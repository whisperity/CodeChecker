# -------------------------------------------------------------------------
#
#  Part of the CodeChecker project, under the Apache License v2.0 with
#  LLVM Exceptions. See LICENSE for license information.
#  SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
# -------------------------------------------------------------------------

import base64
import os
import sqlalchemy
import tempfile
import time
import zipfile
import zlib

from collections import defaultdict
from datetime import datetime
from hashlib import sha256
from tempfile import TemporaryDirectory
from typing import Any, Dict, List, Optional, Set, Tuple

import codechecker_api_shared
from codechecker_api.codeCheckerDBAccess_v6 import ttypes

from codechecker_common import skiplist_handler
from codechecker_common.logger import get_logger
from codechecker_common.review_status_handler import ReviewStatusHandler, \
    SourceReviewStatus
from codechecker_common.util import load_json, path_for_fake_root

from codechecker_report_converter.util import trim_path_prefixes
from codechecker_report_converter.report import report_file, Report
from codechecker_report_converter.report.hash import get_report_path_hash

from ..database import db_cleanup
from ..database.config_db_model import Product
from ..database.database import DBSession
from ..database.run_db_model import AnalysisInfo, AnalyzerStatistic, \
    BugPathEvent, BugReportPoint, ReportAnnotations, ExtendedReportData, \
    File, FileContent, Report as DBReport, ReviewStatus as ReviewStatusRule, \
    Run, RunHistory, RunLock
from ..metadata import checker_is_unavailable, MetadataInfoParser

from .report_server import ThriftRequestHandler
from .thrift_enum_helper import report_extended_data_type_str


LOG = get_logger('server')
STORE_TIME_LOG = get_logger('store_time')


class LogTask:
    def __init__(self, run_name: str, message: str):
        self.__run_name = run_name
        self.__msg = message
        self.__start_time = time.time()

    def __enter__(self, *args):
        LOG.info("[%s] %s...", self.__run_name, self.__msg)

    def __exit__(self, *args):
        LOG.info("[%s] %s done... (duration: %s sec)", self.__run_name,
                 self.__msg, round(time.time() - self.__start_time, 2))


def unzip(b64zip: str, output_dir: str) -> int:
    """
    This function unzips the base64 encoded zip file. This zip is extracted
    to a temporary directory and the ZIP is then deleted. The function returns
    the size of the extracted decompressed zip file.
    """
    if len(b64zip) == 0:
        return 0

    with tempfile.NamedTemporaryFile(suffix='.zip') as zip_file:
        LOG.debug("Unzipping mass storage ZIP '%s' to '%s'...",
                  zip_file.name, output_dir)

        zip_file.write(zlib.decompress(base64.b64decode(b64zip)))
        with zipfile.ZipFile(zip_file, 'r', allowZip64=True) as zipf:
            try:
                zipf.extractall(output_dir)
                return os.stat(zip_file.name).st_size
            except Exception:
                LOG.error("Failed to extract received ZIP.")
                import traceback
                traceback.print_exc()
                raise
    return 0


def get_file_content(file_path: str) -> bytes:
    """Return the file content for the given filepath. """
    with open(file_path, 'rb') as f:
        return f.read()


def add_file_record(
    session: DBSession,
    file_path: str,
    content_hash: str
) -> Optional[int]:
    """
    Add the necessary file record pointing to an already existing content.
    Returns the added file record id or None, if the content_hash is not
    found.

    This function must not be called between add_checker_run() and
    finish_checker_run() functions when SQLite database is used!
    add_checker_run() function opens a transaction which is closed by
    finish_checker_run() and since SQLite doesn't support parallel
    transactions, this API call will wait until the other transactions
    finish. In the meantime the run adding transaction times out.

    This function doesn't insert blame info in the File objects because those
    are added by __add_blame_info(). In previous CodeChecker versions git info
    was not stored at all, so upgrading to a new CodeChecker results the
    storage of git blame info even for files that are already stored. For this
    reason we can't avoid an update on File and FileContent tables, but we can
    avoid double reading of blame info json files.
    """
    file_record = session.query(File) \
        .filter(File.content_hash == content_hash,
                File.filepath == file_path) \
        .one_or_none()

    if file_record:
        return file_record.id

    try:
        # Parallel storage of runs containing common file paths results a
        # "duplicate key violation" error. This is handled by CodeChecker, so
        # practically it causes no problem. The INSERT command of the second
        # transaction will be thrown away. However, some DB systems are
        # supporting "ON CONFLICT DO NOTHING" clause in INSERT statement which
        # solves the same issue gracefully.
        # TODO: "ON CONFLICT DO NOTHING" feature is available for SQLite engine
        # too in SQLAlchemy 1.4.
        if session.bind.dialect.name == 'postgresql':
            insert_stmt = sqlalchemy.dialects.postgresql.insert(File).values(
                filepath=file_path,
                filename=os.path.basename(file_path),
                content_hash=content_hash).on_conflict_do_nothing(
                    index_elements=['filepath', 'content_hash'])
            file_id = session.execute(insert_stmt).inserted_primary_key[0]
            session.commit()
            return file_id
        else:
            file_record = File(file_path, content_hash, None, None)
            session.add(file_record)
        session.commit()
    except sqlalchemy.exc.IntegrityError as ex:
        LOG.error(ex)
        # Other transaction might have added the same file in the
        # meantime.
        session.rollback()
        file_record = session.query(File) \
            .filter(File.content_hash == content_hash,
                    File.filepath == file_path).one_or_none()

    return file_record.id if file_record else None


def get_blame_file_data(
    blame_file: str
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Get blame information from the given file.

    It will return a tuple of 'blame information', 'remote url' and
    'tracking branch'.
    """
    blame_info = None
    remote_url = None
    tracking_branch = None

    if os.path.isfile(blame_file):
        data = load_json(blame_file)
        if data:
            remote_url = data.get("remote_url")
            tracking_branch = data.get("tracking_branch")

            blame_info = data

            # Remove fields which are not needed anymore from the blame info.
            del blame_info["remote_url"]
            del blame_info["tracking_branch"]

    return blame_info, remote_url, tracking_branch


class MassStoreRun:
    def __init__(
        self,
        report_server: ThriftRequestHandler,
        name: str,
        tag: Optional[str],
        version: Optional[str],
        b64zip: str,
        force: bool,
        trim_path_prefixes: Optional[List[str]],
        description: Optional[str]
    ):
        """ Initialize object. """
        self.__report_server = report_server

        self.__name = name
        self.__tag = tag
        self.__version = version
        self.__b64zip = b64zip
        self.__force = force
        self.__trim_path_prefixes = trim_path_prefixes
        self.__description = description

        self.__mips: Dict[str, MetadataInfoParser] = {}
        self.__analysis_info: Dict[str, AnalysisInfo] = {}
        self.__duration: int = 0
        self.__report_count: int = 0
        self.__report_limit: int = 0
        self.__wrong_src_code_comments: List[str] = []
        self.__already_added_report_hashes: Set[str] = set()
        self.__severity_map: Dict[str, int] = {}
        self.__new_report_hashes: Dict[str, Tuple] = {}
        self.__all_report_checkers: Set[str] = set()
        self.__added_reports: List[Tuple[DBReport, Report]] = list()

        self.__get_report_limit_for_product()

    @property
    def __manager(self):
        return self.__report_server._manager

    @property
    def __Session(self):
        return self.__report_server._Session

    @property
    def __config_database(self):
        return self.__report_server._config_database

    @property
    def __product(self):
        return self.__report_server._product

    @property
    def __context(self):
        return self.__report_server._context

    @property
    def user_name(self):
        return self.__report_server._get_username()

    def __check_run_limit(self):
        """
        Checks the maximum allowed of uploadable runs for the current product.
        """
        max_run_count = self.__manager.get_max_run_count()

        with DBSession(self.__config_database) as session:
            product = session.query(Product).get(self.__product.id)
            if product.run_limit:
                max_run_count = product.run_limit

        # Session that handles constraints on the run.
        with DBSession(self.__Session) as session:
            if not max_run_count:
                return

            LOG.debug("Check the maximum number of allowed runs which is %d",
                      max_run_count)

            run = session.query(Run) \
                .filter(Run.name == self.__name) \
                .one_or_none()

            # If max_run_count is not set in the config file, it will allow
            # the user to upload unlimited runs.

            run_count = session.query(Run.id).count()

            # If we are not updating a run or the run count is reached the
            # limit it will throw an exception.
            if not run and run_count >= max_run_count:
                remove_run_count = run_count - max_run_count + 1
                raise codechecker_api_shared.ttypes.RequestFailed(
                    codechecker_api_shared.ttypes.ErrorCode.GENERAL,
                    f"You reached the maximum number of allowed runs "
                    f"({run_count}/{max_run_count})! Please remove at least "
                    f"{remove_run_count} run(s) before you try it again.")

    def __store_run_lock(self, session: DBSession):
        """
        Store a RunLock record for the given run name into the database.
        """
        try:
            # If the run can be stored, we need to lock it first. If there is
            # already a lock in the database for the given run name which is
            # expired and multiple processes are trying to get this entry from
            # the database for update we may get the following exception:
            # could not obtain lock on row in relation "run_locks"
            # This is the reason why we have to wrap this query to a try/except
            # block.
            run_lock = session.query(RunLock) \
                .filter(RunLock.name == self.__name) \
                .with_for_update(nowait=True).one_or_none()
        except (sqlalchemy.exc.OperationalError,
                sqlalchemy.exc.ProgrammingError) as ex:
            LOG.error("Failed to get run lock for '%s': %s", self.__name, ex)
            raise codechecker_api_shared.ttypes.RequestFailed(
                codechecker_api_shared.ttypes.ErrorCode.DATABASE,
                "Someone is already storing to the same run. Please wait "
                "while the other storage is finished and try it again.")

        if not run_lock:
            # If there is no lock record for the given run name, the run
            # is not locked -- create a new lock.
            run_lock = RunLock(self.__name, self.user_name)
            session.add(run_lock)
        elif run_lock.has_expired(
                db_cleanup.RUN_LOCK_TIMEOUT_IN_DATABASE):
            # There can be a lock in the database, which has already
            # expired. In this case, we assume that the previous operation
            # has failed, and thus, we can re-use the already present lock.
            run_lock.touch()
            run_lock.username = self.user_name
        else:
            # In case the lock exists and it has not expired, we must
            # consider the run a locked one.
            when = run_lock.when_expires(
                db_cleanup.RUN_LOCK_TIMEOUT_IN_DATABASE)

            username = run_lock.username if run_lock.username is not None \
                else "another user"

            LOG.info("Refusing to store into run '%s' as it is locked by "
                     "%s. Lock will expire at '%s'.", self.__name, username,
                     when)
            raise codechecker_api_shared.ttypes.RequestFailed(
                codechecker_api_shared.ttypes.ErrorCode.DATABASE,
                "The run named '{0}' is being stored into by {1}. If the "
                "other store operation has failed, this lock will expire "
                "at '{2}'.".format(self.__name, username, when))

        # At any rate, if the lock has been created or updated, commit it
        # into the database.
        try:
            session.commit()
        except (sqlalchemy.exc.IntegrityError,
                sqlalchemy.orm.exc.StaleDataError):
            # The commit of this lock can fail.
            #
            # In case two store ops attempt to lock the same run name at the
            # same time, committing the lock in the transaction that commits
            # later will result in an IntegrityError due to the primary key
            # constraint.
            #
            # In case two store ops attempt to lock the same run name with
            # reuse and one of the operation hangs long enough before COMMIT
            # so that the other operation commits and thus removes the lock
            # record, StaleDataError is raised. In this case, also consider
            # the run locked, as the data changed while the transaction was
            # waiting, as another run wholly completed.

            LOG.info("Run '%s' got locked while current transaction "
                     "tried to acquire a lock. Considering run as locked.",
                     self.__name)
            raise codechecker_api_shared.ttypes.RequestFailed(
                codechecker_api_shared.ttypes.ErrorCode.DATABASE,
                "The run named '{0}' is being stored into by another "
                "user.".format(self.__name))

    def __free_run_lock(self, session: DBSession):
        """ Remove the lock from the database for the given run name. """
        # Using with_for_update() here so the database (in case it supports
        # this operation) locks the lock record's row from any other access.
        run_lock = session.query(RunLock) \
            .filter(RunLock.name == self.__name) \
            .with_for_update(nowait=True).one()
        session.delete(run_lock)
        session.commit()

    def __store_source_files(
        self,
        source_root: str,
        filename_to_hash: Dict[str, str]
    ) -> Dict[str, int]:
        """ Storing file contents from plist. """

        file_path_to_id = {}

        for file_name, file_hash in filename_to_hash.items():
            source_file_path = path_for_fake_root(file_name, source_root)
            LOG.debug("Storing source file: %s", source_file_path)
            trimmed_file_path = trim_path_prefixes(
                file_name, self.__trim_path_prefixes)

            if not os.path.isfile(source_file_path):
                # The file was not in the ZIP file, because we already
                # have the content. Let's check if we already have a file
                # record in the database or we need to add one.

                LOG.debug('%s not found or already stored.', trimmed_file_path)
                with DBSession(self.__Session) as session:
                    fid = add_file_record(
                        session, trimmed_file_path, file_hash)

                if fid:
                    file_path_to_id[trimmed_file_path] = fid
                    LOG.debug("%d fileid found", fid)
                else:
                    LOG.error("File ID for %s is not found in the DB with "
                              "content hash %s. Missing from ZIP?",
                              source_file_path, file_hash)
                continue

            with DBSession(self.__Session) as session:
                self.__add_file_content(session, source_file_path, file_hash)

                file_path_to_id[trimmed_file_path] = add_file_record(
                    session, trimmed_file_path, file_hash)

        return file_path_to_id

    def __add_blame_info(
        self,
        blame_root: str,
        filename_to_hash: Dict[str, str]
    ):
        """
        This function updates blame info in File and FileContent tables if
        these were NULL. This function exists only because in earlier
        CodeChecker versions blame info was not stored in these tables and
        in a subsequent storage we can't update the tables for an unchanged
        file since __store_source_files() updates only the ones that are in the
        .zip file. This function stores blame info even if the corresponding
        source file is not in the .zip file.
        """
        with DBSession(self.__Session) as session:
            for subdir, _, files in os.walk(blame_root):
                for f in files:
                    blame_file = os.path.join(subdir, f)
                    file_path = blame_file[len(blame_root.rstrip("/")):]
                    blame_info, remote_url, tracking_branch = \
                        get_blame_file_data(blame_file)

                    if blame_info:
                        session \
                            .query(FileContent) \
                            .filter(FileContent.blame_info.is_(None)) \
                            .filter(FileContent.content_hash ==
                                    filename_to_hash.get(file_path)) \
                            .update({"blame_info": blame_info})

                    session \
                        .query(File) \
                        .filter(File.remote_url.is_(None)) \
                        .filter(File.filepath == file_path) \
                        .update({
                            "remote_url": remote_url,
                            "tracking_branch": tracking_branch})

            session.commit()

    def __add_file_content(
        self,
        session: DBSession,
        source_file_name: str,
        content_hash: Optional[str]
    ):
        """
        Add the necessary file contents. If content_hash in None then this
        function calculates the content hash. Or if it's available at the
        caller and it's provided then it will not be calculated again.

        This function must not be called between add_checker_run() and
        finish_checker_run() functions when SQLite database is used!
        add_checker_run() function opens a transaction which is closed by
        finish_checker_run() and since SQLite doesn't support parallel
        transactions, this API call will wait until the other transactions
        finish. In the meantime the run adding transaction times out.

        This function doesn't insert blame info in the FileContent objects
        because those are added by __add_blame_info(). In previous CodeChecker
        versions git info was not stored at all, so upgrading to a new
        CodeChecker results the storage of git blame info even for files that
        are already stored. For this reason we can't avoid an update on File
        and FileContent tables, but we can avoid double reading of blame info
        json files.
        """
        source_file_content = None
        if not content_hash:
            source_file_content = get_file_content(source_file_name)

            hasher = sha256()
            hasher.update(source_file_content)
            content_hash = hasher.hexdigest()

        file_content = session.query(FileContent).get(content_hash)
        if not file_content:
            if not source_file_content:
                source_file_content = get_file_content(source_file_name)
            try:
                if session.bind.dialect.name == 'postgresql':
                    insert_stmt = sqlalchemy.dialects.postgresql \
                        .insert(FileContent).values(
                            content_hash=content_hash,
                            content=source_file_content,
                            blame_info=None).on_conflict_do_nothing(
                                index_elements=['content_hash'])

                    session.execute(insert_stmt)
                else:
                    fc = FileContent(content_hash, source_file_content, None)
                    session.add(fc)

                session.commit()
            except sqlalchemy.exc.IntegrityError:
                # Other transaction moght have added the same content in
                # the meantime.
                session.rollback()

    def __store_analysis_statistics(
        self,
        session: DBSession,
        run_history_id: int
    ):
        """
        Store analysis statistics for the given run history.

        It will unique the statistics for each analyzer type based on the
        metadata information.
        """
        stats = defaultdict(lambda: {
            "versions": set(),
            "failed_sources": set(),
            "successful_sources": set(),
            "successful": 0
        })

        for mip in self.__mips.values():
            self.__duration += int(sum(mip.check_durations))

            for analyzer_type, res in mip.analyzer_statistics.items():
                if "version" in res:
                    stats[analyzer_type]["versions"].add(res["version"])

                if "failed_sources" in res:
                    if self.__version == '6.9.0':
                        stats[analyzer_type]["failed_sources"].add(
                            'Unavailable in CodeChecker 6.9.0!')
                    else:
                        stats[analyzer_type]["failed_sources"].update(
                            res["failed_sources"])

                if "successful_sources" in res:
                    stats[analyzer_type]["successful_sources"].update(
                        res["successful_sources"])

                if "successful" in res:
                    stats[analyzer_type]["successful"] += res["successful"]

        for analyzer_type, stat in stats.items():
            analyzer_version = None
            if stat["versions"]:
                analyzer_version = "; ".join(stat["versions"])

            failed = 0
            failed_files = None
            if stat["failed_sources"]:
                failed_files = '\n'.join(stat["failed_sources"])

                failed = len(stat["failed_sources"])

            successful = len(stat["successful_sources"]) \
                if stat["successful_sources"] else stat["successful"]

            analyzer_statistics = AnalyzerStatistic(
                run_history_id, analyzer_type, analyzer_version,
                successful, failed, failed_files)

            session.add(analyzer_statistics)

    def __store_analysis_info(
        self,
        session: DBSession,
        run_history: RunHistory
    ):
        """ Store analysis info for the given run history. """
        for src_dir_path, mip in self.__mips.items():
            for analyzer_command in mip.check_commands:
                analysis_info_rows = session \
                    .query(AnalysisInfo) \
                    .filter(AnalysisInfo.analyzer_command ==
                            analyzer_command) \
                    .all()

                if analysis_info_rows:
                    # It is possible when multiple runs are stored
                    # simultaneously to the server with the same analysis
                    # command that multiple entries are stored into the
                    # database. In this case we will select the first one.
                    analysis_info = analysis_info_rows[0]
                else:
                    analysis_info = AnalysisInfo(
                        analyzer_command=analyzer_command)

                    session.add(analysis_info)

                run_history.analysis_info.append(analysis_info)
                self.__analysis_info[src_dir_path] = analysis_info

    def __add_or_update_run(
        self,
        session: DBSession,
        run_history_time: datetime
    ) -> Tuple[int, bool]:
        """
        Store run related data to the database.
        By default updates the results if name already exists.
        Using the force flag removes existing analysis results for a run.
        """
        try:
            LOG.debug("Adding run '%s'...", self.__name)

            run = session.query(Run) \
                .filter(Run.name == self.__name) \
                .one_or_none()

            update_run = True
            if run and self.__force:
                # Clean already collected results.
                if not run.can_delete:
                    # Deletion is already in progress.
                    msg = f"Can't delete {run.id}"
                    LOG.debug(msg)
                    raise codechecker_api_shared.ttypes.RequestFailed(
                        codechecker_api_shared.ttypes.ErrorCode.DATABASE,
                        msg)

                LOG.info('Removing previous analysis results...')
                session.delete(run)
                # Not flushing after delete leads to a constraint violation
                # error later, when adding run entity with the same name as
                # the old one.
                session.flush()

                checker_run = Run(self.__name, self.__version)
                session.add(checker_run)
                session.flush()
                run_id = checker_run.id

            elif run:
                # There is already a run, update the results.
                run.date = datetime.now()
                run.duration = -1
                session.flush()
                run_id = run.id
            else:
                # There is no run create new.
                checker_run = Run(self.__name, self.__version)
                session.add(checker_run)
                session.flush()
                run_id = checker_run.id
                update_run = False

            # Add run to the history.
            LOG.debug("Adding run history.")

            if self.__tag is not None:
                run_history = session.query(RunHistory) \
                    .filter(RunHistory.run_id == run_id,
                            RunHistory.version_tag == self.__tag) \
                    .one_or_none()

                if run_history:
                    run_history.version_tag = None
                    session.add(run_history)

            cc_versions = set()
            for mip in self.__mips.values():
                if mip.cc_version:
                    cc_versions.add(mip.cc_version)

            cc_version = '; '.join(cc_versions) if cc_versions else None
            run_history = RunHistory(
                run_id, self.__tag, self.user_name, run_history_time,
                cc_version, self.__description)

            session.add(run_history)
            session.flush()

            LOG.debug("Adding run done.")

            self.__store_analysis_statistics(session, run_history.id)
            self.__store_analysis_info(session, run_history)

            session.flush()
            LOG.debug("Storing analysis statistics done.")

            return run_id, update_run
        except Exception as ex:
            raise codechecker_api_shared.ttypes.RequestFailed(
                codechecker_api_shared.ttypes.ErrorCode.GENERAL,
                str(ex))

    def __add_report(
        self,
        session: DBSession,
        run_id: int,
        report: Report,
        file_path_to_id: Dict[str, int],
        review_status: SourceReviewStatus,
        detection_status: str,
        detection_time: datetime,
        run_history_time: datetime,
        analysis_info: AnalysisInfo,
        analyzer_name: Optional[str] = None,
        fixed_at: Optional[datetime] = None
    ) -> int:
        """ Add report to the database. """
        try:
            checker_name = report.checker_name

            # Cache the severity of the checkers
            try:
                severity = self.__severity_map[checker_name]
            except KeyError:
                severity_name = \
                    self.__context.checker_labels.severity(checker_name)
                severity = ttypes.Severity._NAMES_TO_VALUES[severity_name]
                self.__severity_map[checker_name] = severity

            db_report = DBReport(
                run_id, report.report_hash, file_path_to_id[report.file.path],
                report.message, checker_name or 'NOT FOUND',
                report.category, report.type, report.line, report.column,
                severity, review_status.status, review_status.author,
                review_status.message, run_history_time,
                review_status.in_source,
                detection_status, detection_time,
                len(report.bug_path_events), analyzer_name)

            db_report.fixed_at = fixed_at

            if analysis_info:
                db_report.analysis_info.append(analysis_info)

            session.add(db_report)
            self.__added_reports.append((db_report, report))

            # THE id is none at this point of time
            # wondering if not returning anything is good?
            # The report is already handled at the above lines
            return db_report.id

        except Exception as ex:
            raise codechecker_api_shared.ttypes.RequestFailed(
                codechecker_api_shared.ttypes.ErrorCode.GENERAL,
                str(ex))

    def __add_report_context(self, session, file_path_to_id):
        try:
            for db_report, report in self.__added_reports:
                LOG.debug("Storing bug path positions.")
                for i, p in enumerate(report.bug_path_positions):
                    session.add(BugReportPoint(
                        p.range.start_line, p.range.start_col,
                        p.range.end_line, p.range.end_col,
                        i, file_path_to_id[p.file.path], db_report.id))

                LOG.debug("Storing bug path events.")
                for i, event in enumerate(report.bug_path_events):
                    session.add(BugPathEvent(
                        event.range.start_line, event.range.start_col,
                        event.range.end_line, event.range.end_col,
                        i, event.message, file_path_to_id[event.file.path],
                        db_report.id))

                LOG.debug("Storing notes.")
                for note in report.notes:
                    data_type = report_extended_data_type_str(
                        ttypes.ExtendedReportDataType.NOTE)

                    session.add(ExtendedReportData(
                        note.range.start_line, note.range.start_col,
                        note.range.end_line, note.range.end_col,
                        note.message, file_path_to_id[note.file.path],
                        db_report.id, data_type))

                LOG.debug("Storing macro expansions.")
                for macro in report.macro_expansions:
                    data_type = report_extended_data_type_str(
                        ttypes.ExtendedReportDataType.MACRO)

                    session.add(ExtendedReportData(
                        macro.range.start_line, macro.range.start_col,
                        macro.range.end_line, macro.range.end_col,
                        macro.message, file_path_to_id[macro.file.path],
                        db_report.id, data_type))

                if report.annotations:
                    self.__validate_and_add_report_annotations(
                        session, db_report.id, report.annotations)

            session.flush()

        except Exception as ex:
            raise codechecker_api_shared.ttypes.RequestFailed(
                codechecker_api_shared.ttypes.ErrorCode.GENERAL,
                str(ex))

    def __process_report_file(
        self,
        report_file_path: str,
        session: DBSession,
        run_id: int,
        file_path_to_id: Dict[str, int],
        run_history_time: datetime,
        skip_handler: skiplist_handler.SkipListHandler,
        review_status_handler: ReviewStatusHandler,
        hash_map_reports: Dict[str, List[Any]]
    ) -> bool:
        """
        Process and save reports from the given report file to the database.
        """
        reports = report_file.get_reports(report_file_path)

        if not reports:
            return True

        def get_missing_file_ids(report: Report) -> List[str]:
            """ Returns file paths which database file id is missing. """
            missing_ids_for_files = []
            for file_path in report.trimmed_files:
                file_id = file_path_to_id.get(file_path, -1)
                if file_id == -1:
                    missing_ids_for_files.append(file_path)

            return missing_ids_for_files

        root_dir_path = os.path.dirname(report_file_path)
        mip = self.__mips[root_dir_path]
        analysis_info = self.__analysis_info.get(root_dir_path)

        for report in reports:
            self.__report_count += 1
            report.trim_path_prefixes(self.__trim_path_prefixes)

            missing_ids_for_files = get_missing_file_ids(report)
            if missing_ids_for_files:
                LOG.warning("Failed to get database id for file path '%s'! "
                            "Skip adding report: %s:%d:%d [%s]",
                            ' '.join(missing_ids_for_files), report.file.path,
                            report.line, report.column, report.checker_name)
                continue

            self.__all_report_checkers.add(report.checker_name)

            if skip_handler.should_skip(report.file.original_path):
                continue

            report_path_hash = get_report_path_hash(report)
            if report_path_hash in self.__already_added_report_hashes:
                LOG.debug('Not storing report. Already added: %s', report)
                continue

            LOG.debug("Storing report to the database...")

            detection_status = 'new'
            detected_at = run_history_time

            old_report = None
            if report.report_hash in hash_map_reports:
                old_report = hash_map_reports[report.report_hash][0]
                old_status = old_report.detection_status
                detection_status = 'reopened' \
                    if old_status == 'resolved' else 'unresolved'
                detected_at = old_report.detected_at

            analyzer_name = mip.checker_to_analyzer.get(
                report.checker_name, report.analyzer_name)

            review_status = SourceReviewStatus()

            try:
                review_status = review_status_handler.get_review_status(report)
            except ValueError as err:
                self.__wrong_src_code_comments.append(str(err))

            review_status.author = self.user_name
            review_status.date = run_history_time

            # False positive and intentional reports are considered as closed
            # reports which is indicated with non-null "fixed_at" date.
            fixed_at = None
            if review_status.status in ['false_positive', 'intentional']:
                # Keep in mind that now this is not handling review status
                # rules, only review status source code comments
                if old_report and old_report.review_status in \
                        ['false_positive', 'intentional']:
                    fixed_at = old_report.review_status_date
                else:
                    fixed_at = run_history_time

            self.__check_report_count()
            self.__add_report(
                session, run_id, report, file_path_to_id,
                review_status, detection_status, detected_at,
                run_history_time, analysis_info, analyzer_name, fixed_at)

            self.__new_report_hashes[report.report_hash] = \
                review_status.status
            self.__already_added_report_hashes.add(report_path_hash)

            LOG.debug(f"Storing report done. bug_hash:{report.report_hash}, " +
                      f"source_file:{report_file_path}")

        return True

    def __validate_and_add_report_annotations(
        self,
        session: DBSession,
        report_id: int,
        report_annotation: Dict
    ):
        """
        This function checks the format of the annotations. For example a
        "timestamp" annotation must be in datetime format. If the format
        doesn't match then an exception is thrown. In case of proper format the
        annotation is added to the database.
        """
        ALLOWED_TYPES = {
            "datetime": {
                "func": datetime.fromisoformat,
                "display": "date-time in ISO format"
            },
            "string": {
                "func": str,
                "display": "string"
            }
        }

        ALLOWED_ANNOTATIONS = {
            "timestamp": ALLOWED_TYPES["datetime"],
            "testsuite": ALLOWED_TYPES["string"],
            "testcase": ALLOWED_TYPES["string"]
        }

        for key, value in report_annotation.items():
            try:
                ALLOWED_ANNOTATIONS[key]["func"](value)
                session.add(ReportAnnotations(report_id, key, value))
            except KeyError:
                raise codechecker_api_shared.ttypes.RequestFailed(
                    codechecker_api_shared.ttypes.ErrorCode.REPORT_FORMAT,
                    f"'{key}' is not an allowed report annotation.",
                    ALLOWED_ANNOTATIONS.keys())
            except ValueError:
                raise codechecker_api_shared.ttypes.RequestFailed(
                    codechecker_api_shared.ttypes.ErrorCode.REPORT_FORMAT,
                    f"'{value}' has wrong format. '{key}' annotations must be "
                    f"'{ALLOWED_ANNOTATIONS[key]['display']}'."
                )

    def __get_report_limit_for_product(self):
        with DBSession(self.__config_database) as session:
            product = session.query(Product).get(self.__product.id)
            if product.report_limit:
                self.__report_limit = product.report_limit

    def __check_report_count(self):
        """
        This method comparest the already added report count to the report
        limit, Raises exception if the number of reports is more than the
        that is configured for the product.
        """
        if len(self.__added_reports) >= self.__report_limit:
            LOG.error("The number of reports in the given report folder is " +
                      "larger than the allowed." +
                      f"The limit: {self.__report_limit}!")
            extra_info = [
                "report_limit",
                f"limit:{self.__report_limit}"
            ]
            raise codechecker_api_shared.ttypes.RequestFailed(
                codechecker_api_shared.ttypes.
                ErrorCode.GENERAL,
                "**Report Limit Exceeded** " +
                "This report folder cannot be stored because the number of " +
                "reports in the result folder is too high. Usually noisy " +
                "checkers, generating a lot of reports are not useful and " +
                "it is better to disable them. Run `CodeChecker parse " +
                "<report_folder>` to gain a better understanding on report " +
                "counts. Disable checkers that have generated an excessive " +
                "number of reports and then rerun the analysis to be able " +
                "to store the results on the server. " +
                f"Limit: {self.__report_limit}",
                extra_info)

    def __store_reports(
        self,
        session: DBSession,
        report_dir: str,
        source_root: str,
        run_id: int,
        file_path_to_id: Dict[str, int],
        run_history_time: datetime
    ):
        """ Parse up and store the plist report files. """

        def get_skip_handler(
            report_dir: str
        ) -> skiplist_handler.SkipListHandler:
            """ Get a skip list handler based on the given report directory."""
            skip_file_path = os.path.join(report_dir, 'skip_file')
            if not os.path.exists(skip_file_path):
                return skiplist_handler.SkipListHandler()

            LOG.debug("Pocessing skip file %s", skip_file_path)
            try:
                with open(skip_file_path,
                          encoding="utf-8", errors="ignore") as f:
                    skip_content = f.read()
                    LOG.debug(skip_content)

                    return skiplist_handler.SkipListHandler(skip_content)
            except (IOError, OSError) as err:
                LOG.error("Failed to open skip file: %s", err)
                raise

        # Reset internal data.
        self.__already_added_report_hashes = set()
        self.__new_report_hashes = dict()
        self.__all_report_checkers = set()
        self.__severity_map = dict()

        all_reports = session.query(DBReport) \
            .filter(DBReport.run_id == run_id) \
            .all()

        report_to_report_id = defaultdict(list)
        for db_report in all_reports:
            report_to_report_id[db_report.bug_id].append(db_report)

        enabled_checkers: Set[str] = set()
        disabled_checkers: Set[str] = set()

        # Processing analyzer result files.
        processed_result_file_count = 0

        for root_dir_path, _, report_file_paths in os.walk(report_dir):
            LOG.debug("Get reports from '%s' directory", root_dir_path)

            skip_handler = get_skip_handler(root_dir_path)

            review_status_handler = ReviewStatusHandler(source_root)

            review_status_cfg = \
                os.path.join(root_dir_path, 'review_status.yaml')
            if os.path.isfile(review_status_cfg):
                review_status_handler.set_review_status_config(
                    review_status_cfg)

            mip = self.__mips[root_dir_path]
            enabled_checkers.update(mip.enabled_checkers)
            disabled_checkers.update(mip.disabled_checkers)

            for f in report_file_paths:
                if not report_file.is_supported(f):
                    continue

                LOG.debug("Parsing input file '%s'", f)

                report_file_path = os.path.join(root_dir_path, f)
                self.__process_report_file(
                    report_file_path, session, run_id,
                    file_path_to_id, run_history_time,
                    skip_handler, review_status_handler, report_to_report_id)
                processed_result_file_count += 1

        session.flush()

        self.__add_report_context(session, file_path_to_id)
        # Get all relevant review_statuses for the newly stored reports
        # CHHECK: Call self.getReviewStatusRules instead of the below query
        # but before first check the performance
        reports_to_rs_rules = session.query(ReviewStatusRule, DBReport) \
            .join(DBReport, DBReport.bug_id == ReviewStatusRule.bug_hash) \
            .filter(sqlalchemy.and_(
                DBReport.run_id == run_id,
                DBReport.review_status_is_in_source.is_(False),
                ReviewStatusRule.bug_hash.in_(self.__new_report_hashes)))

        # Set the newly stored reports
        for review_status, db_report in reports_to_rs_rules:
            old_report = None
            if db_report.bug_id in report_to_report_id:
                old_report = report_to_report_id[db_report.bug_id][0]
            fixed_at = None
            if review_status.status in ['false_positive', 'intentional']:
                # Keep in mind that now this is not handling review status
                # rules, only review status source code comments
                if old_report and old_report.review_status in \
                        ['false_positive', 'intentional']:
                    fixed_at = old_report.review_status_date
                else:
                    fixed_at = run_history_time

            db_report.review_status = review_status.status
            db_report.review_statuses_author = review_status.author
            db_report.review_status_message = review_status.message
            db_report.review_statuses_date = review_status.date
            db_report.fixed_at = fixed_at
            db_report.review_status_is_in_source = False

        session.flush()

        LOG.info("[%s] Processed %d analyzer result file(s).", self.__name,
                 processed_result_file_count)

        # If a checker was found in a plist file it can not be disabled so we
        # will add this to the enabled checkers list and remove this checker
        # from the disabled checkers list.
        # Also if multiple report directories are stored and a checker was
        # enabled in one report directory but it was disabled in another
        # directory we will mark this checker as enabled.
        enabled_checkers |= self.__all_report_checkers
        disabled_checkers -= self.__all_report_checkers

        reports_to_delete = set()
        for bug_hash, reports in report_to_report_id.items():
            if bug_hash in self.__new_report_hashes:
                reports_to_delete.update([x.id for x in reports])
            else:
                for report in reports:
                    checker = report.checker_id
                    if checker in disabled_checkers:
                        report.detection_status = 'off'
                    elif checker_is_unavailable(checker, enabled_checkers):
                        report.detection_status = 'unavailable'
                    else:
                        report.detection_status = 'resolved'

                    if report.fixed_at is None:
                        report.fixed_at = run_history_time

        if reports_to_delete:
            self.__report_server._removeReports(
                session, list(reports_to_delete))

    def finish_checker_run(
        self,
        session: DBSession,
        run_id: int
    ) -> bool:
        """ Finish the storage of the given run. """
        try:
            LOG.debug("Finishing checker run")
            run = session.query(Run).get(run_id)
            if not run:
                return False

            run.mark_finished()
            run.duration = self.__duration

            return True
        except Exception as ex:
            LOG.error(ex)

        return False

    def store(self) -> int:
        """ Store run results to the server. """
        start_time = time.time()

        # Check constraints of the run.
        self.__check_run_limit()

        with DBSession(self.__Session) as session:
            self.__store_run_lock(session)

        try:
            with TemporaryDirectory(
                dir=self.__context.codechecker_workspace
            ) as zip_dir:
                with LogTask(run_name=self.__name,
                             message="Unzip storage file"):
                    zip_size = unzip(self.__b64zip, zip_dir)

                if zip_size == 0:
                    raise codechecker_api_shared.ttypes.RequestFailed(
                        codechecker_api_shared.ttypes.
                        ErrorCode.GENERAL,
                        "The received zip file content is empty!")

                LOG.debug("Using unzipped folder '%s'", zip_dir)

                source_root = os.path.join(zip_dir, 'root')
                blame_root = os.path.join(zip_dir, 'blame')
                report_dir = os.path.join(zip_dir, 'reports')
                content_hash_file = os.path.join(
                    zip_dir, 'content_hashes.json')

                filename_to_hash = load_json(content_hash_file, {})

                with LogTask(run_name=self.__name,
                             message="Store source files"):
                    LOG.info("[%s] Storing %d source file(s).", self.__name,
                             len(filename_to_hash.keys()))
                    file_path_to_id = self.__store_source_files(
                        source_root, filename_to_hash)
                    self.__add_blame_info(blame_root, filename_to_hash)

                run_history_time = datetime.now()

                # Parse all metadata information from the report directory.
                for root_dir_path, _, _ in os.walk(report_dir):
                    metadata_file_path = os.path.join(
                        root_dir_path, 'metadata.json')

                    self.__mips[root_dir_path] = \
                        MetadataInfoParser(metadata_file_path)

                # When we use multiple server instances and we try to run
                # multiple storage to each server which contain at least two
                # reports which have the same report hash and have source code
                # comments it is possible that the following exception will be
                # thrown: (psycopg2.extensions.TransactionRollbackError)
                # deadlock detected.
                # The problem is that the report hash is the key for the
                # review_statuses table and both of the store actions try to
                # update the same review_statuses data row.
                # Neither of the two processes can continue, and they will wait
                # for each other indefinitely. PostgreSQL in this case will
                # terminate one transaction with the above exception.
                # For this reason in case of failure we will wait some seconds
                # and try to run the storage again.
                # For more information see #2655 and #2653 issues on github.
                # TODO: Since review status is stored in "reports" table and
                # "review_statuses" table is not written during storage, this
                # multiple trials should be unnecessary.
                max_num_of_tries = 3
                num_of_tries = 0
                sec_to_wait_after_failure = 60
                while True:
                    try:
                        # This session's transaction buffer stores the actual
                        # run data into the database.
                        with DBSession(self.__Session) as session:
                            # Load the lock record for "FOR UPDATE" so that the
                            # transaction that handles the run's store
                            # operations has a lock on the database row itself.
                            run_lock = session.query(RunLock) \
                                .filter(RunLock.name == self.__name) \
                                .with_for_update(nowait=True).one()

                            # Do not remove this seemingly dummy print, we need
                            # to make sure that the execution of the SQL
                            # statement is not optimised away and the fetched
                            # row is not garbage collected.
                            LOG.debug("Storing into run '%s' locked at '%s'.",
                                      self.__name, run_lock.locked_at)

                            # Actual store operation begins here.
                            run_id, update_run = self.__add_or_update_run(
                                session, run_history_time)

                            with LogTask(run_name=self.__name,
                                         message="Store reports"):
                                self.__store_reports(
                                    session, report_dir, source_root, run_id,
                                    file_path_to_id, run_history_time)

                            self.finish_checker_run(session, run_id)

                            session.commit()

                        inc_num_of_runs = 1

                        # If it's a run update, do not increment the number
                        # of runs of the current product.
                        if update_run:
                            inc_num_of_runs = None

                        self.__report_server._set_run_data_for_curr_product(
                            inc_num_of_runs, run_history_time)

                        runtime = round(time.time() - start_time, 2)
                        zip_size_kb = round(zip_size / 1024)

                        tag_desc = ""
                        if self.__tag:
                            tag_desc = f", under tag '{self.__tag}'"

                        LOG.info("'%s' stored results (%s KB "
                                 "/decompressed/) to run '%s' (id: %d) %s in "
                                 "%s seconds.", self.user_name,
                                 zip_size_kb, self.__name, run_id, tag_desc,
                                 runtime)

                        iso_start_time = datetime.fromtimestamp(
                            start_time).isoformat()

                        log_msg = f"{iso_start_time}, " +\
                                  f"{runtime}s, " +\
                                  f'"{self.__product.name}", ' +\
                                  f'"{self.__name}", ' +\
                                  f"{zip_size_kb}KB, " +\
                                  f"{self.__report_count}, " +\
                                  f"{run_id}"

                        STORE_TIME_LOG.info(log_msg)

                        return run_id
                    except (sqlalchemy.exc.OperationalError,
                            sqlalchemy.exc.ProgrammingError) as ex:
                        num_of_tries += 1

                        if num_of_tries == max_num_of_tries:
                            raise codechecker_api_shared.ttypes.RequestFailed(
                                codechecker_api_shared.ttypes.
                                ErrorCode.DATABASE,
                                "Storing reports to the database failed: "
                                "{0}".format(ex))

                        LOG.error("Storing reports of '%s' run failed: "
                                  "%s.\nWaiting %d sec before trying to store "
                                  "it again!", self.__name, ex,
                                  sec_to_wait_after_failure)
                        time.sleep(sec_to_wait_after_failure)
                        sec_to_wait_after_failure *= 2
        except Exception as ex:
            LOG.error("Failed to store results: %s", ex)
            import traceback
            traceback.print_exc()
            raise
        finally:
            # In any case if the "try" block's execution began, a run lock must
            # exist, which can now be removed, as storage either completed
            # successfully, or failed in a detectable manner.
            # (If the failure is undetectable, the coded grace period expiry
            # of the lock will allow further store operations to the given
            # run name.)
            with DBSession(self.__Session) as session:
                self.__free_run_lock(session)

            if self.__wrong_src_code_comments:
                raise codechecker_api_shared.ttypes.RequestFailed(
                    codechecker_api_shared.ttypes.ErrorCode.SOURCE_FILE,
                    self.__wrong_src_code_comments)
