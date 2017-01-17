# -------------------------------------------------------------------------
#                     The CodeChecker Infrastructure
#   This file is distributed under the University of Illinois Open Source
#   License. See LICENSE.TXT for details.
# -------------------------------------------------------------------------

import ntpath
import os
import zlib
from abc import ABCMeta

import shared

from codechecker_lib import client
from codechecker_lib import plist_parser
from codechecker_lib import suppress_handler
from codechecker_lib import logger
from codechecker_lib.logger import LoggerFactory
from codechecker_lib.analyzers.result_handler_base import ResultHandler

LOG = LoggerFactory.get_new_logger('PLIST TO DB')


class PlistToDB(ResultHandler):
    """
    Result handler for processing a plist file with the
    analysis results and stores them to the database.
    """

    __metaclass__ = ABCMeta

    def __init__(self, buildaction, workspace, run_id):
        super(PlistToDB, self).__init__(buildaction, workspace)
        self.__run_id = run_id

    def __store_bugs(self, files, bugs, connection, analisys_id):
        file_ids = {}
        # Send content of file to the server if needed.
        for file_name in files:
            file_descriptor = connection.need_file_content(self.__run_id,
                                                           file_name)
            file_ids[file_name] = file_descriptor.fileId

            # Sometimes the file doesn't exist, e.g. when the input of the
            # analysis is pure plist files.
            if not os.path.isfile(file_name):
                LOG.debug(file_name + ' not found, and will not be stored.')
                continue

            if file_descriptor.needed:
                with open(file_name, 'r') as source_file:
                    file_content = source_file.read()
                compressed_file = zlib.compress(file_content,
                                                zlib.Z_BEST_COMPRESSION)
                # TODO: we may not use the file content in the end
                # depending on skippaths.
                LOG.debug('storing file content to the database')
                connection.add_file_content(file_descriptor.fileId,
                                            compressed_file)

        # Skipping bugs in header files handled here.
        report_ids = []
        for bug in bugs:
            events = bug.events()

            # Skip list handler can be None if no config file is set.
            if self.skiplist_handler:
                if events and self.skiplist_handler.should_skip(
                        events[-1].start_pos.file_path):
                    # Issue #20: this bug is in a file which should be skipped
                    LOG.debug(bug.hash_value + ' is skipped (in ' +
                              events[-1].start_pos.file_path + ")")
                    continue

            # Create remaining data for bugs and send them to the server.
            bug_paths = []
            for path in bug.paths():
                bug_paths.append(
                    shared.ttypes.BugPathPos(path.start_pos.line,
                                             path.start_pos.col,
                                             path.end_pos.line,
                                             path.end_pos.col,
                                             file_ids[
                                                 path.start_pos.file_path]))

            bug_events = []
            for event in bug.events():
                bug_events.append(shared.ttypes.BugPathEvent(
                    event.start_pos.line,
                    event.start_pos.col,
                    event.end_pos.line,
                    event.end_pos.col,
                    event.msg,
                    file_ids[event.start_pos.file_path]))

            bug_hash = bug.hash_value

            severity_name = self.severity_map.get(bug.checker_name,
                                                  'UNSPECIFIED')
            severity = shared.ttypes.Severity._NAMES_TO_VALUES[severity_name]

            sp_handler = suppress_handler.SourceSuppressHandler(bug)

            # Check for suppress comment.
            supp = sp_handler.get_suppressed()
            if supp:
                connection.add_suppress_bug(self.__run_id, [supp])

            LOG.debug('Storing check results to the database.')

            report_id = connection.add_report(analisys_id,
                                              file_ids[bug.file_path],
                                              bug_hash,
                                              bug.msg,
                                              bug_paths,
                                              bug_events,
                                              bug.checker_name,
                                              bug.category,
                                              bug.type,
                                              severity,
                                              supp is not None)

            report_ids.append(report_id)

    def handle_results(self, remove_root=None):
        """
        Send the plist content to the database.
        Server API calls should be used in one connection.
         - addBuildAction
         - addReport
         - needFileContent
         - addFileContent
         - finishBuildAction
        """

        with client.get_connection() as connection:

            LOG.debug('Storing original build and analyzer command '
                      'to the database.')

            _, source_file_name = ntpath.split(self.analyzed_source_file)

            if LoggerFactory.get_log_level() == logger.DEBUG:
                analyzer_cmd = ' '.join(self.analyzer_cmd)
            else:
                analyzer_cmd = ''

            build_cmd_hash = self.buildaction.original_command_hash
            analysis_id = \
                connection.add_build_action(self.__run_id,
                                            build_cmd_hash,
                                            analyzer_cmd,
                                            self.buildaction.analyzer_type,
                                            source_file_name)

            assert self.analyzer_returncode == 0

            plist_file = self.analyzer_result_file

            try:
                files, bugs = plist_parser.parse_plist(plist_file, remove_root)
            except Exception as ex:
                LOG.debug(str(ex))
                msg = 'Parsing the generated result file failed.'
                LOG.error(msg + ' ' + plist_file)
                connection.finish_build_action(analysis_id, msg)
                return 1

            self.__store_bugs(files, bugs, connection, analysis_id)

            connection.finish_build_action(analysis_id, self.analyzer_stderr)

    def postprocess_result(self):
        """
        No postprocessing required for plists.
        """
        pass
