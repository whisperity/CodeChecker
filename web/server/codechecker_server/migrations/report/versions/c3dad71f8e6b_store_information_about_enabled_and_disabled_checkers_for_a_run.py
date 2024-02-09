"""Store information about enabled and disabled checkers for a run

Revision ID: c3dad71f8e6b
Revises: 9d956a0fae8d
Create Date: 2023-10-20 14:11:48.371981

"""

# revision identifiers, used by Alembic.
revision = 'c3dad71f8e6b'
down_revision = '9d956a0fae8d'
branch_labels = None
depends_on = None


from logging import getLogger
from typing import Dict, Tuple

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy.ext.automap import automap_base

from codechecker_common.util import progress
from codechecker_server.migrations.common import \
    recompress_zlib_as_untagged, recompress_zlib_as_tagged_exact_ratio


REPORT_UPDATE_CHUNK_SIZE = 100_000


def upgrade():
    # Note: The instantiation of the LOG variable *MUST* stay here so that it
    # uses the facilities that are sourced from the Alembic env.py.
    # Symbols created on the module-level are created *before* Alembic's env.py
    # had loaded.
    LOG = getLogger("migration")
    dialect = op.get_context().dialect.name
    conn = op.get_bind()

    def upgrade_analysis_info():
        # Upgrade the contents of the existing columns in AnalysisInfo to the
        # new ZLibCompressed format.
        #
        # Note: The underlying type of ZLibCompressedString is still
        # LargeBinary in this revision, so the Column type itself needs not be
        # modified, only the content values need migration.
        Base = automap_base()
        Base.prepare(conn, reflect=True)
        # 'analysis_info' is the table!
        AnalysisInfo = Base.classes.analysis_info

        db = Session(bind=conn)
        count = db.query(AnalysisInfo.id).count()
        if not count:
            return

        def _print_progress(index: int, percent: float):
            LOG.info("[%d/%d] Upgrading 'analysis_info'... %.0f%% done.",
                     index, count, percent)

        LOG.info("Preparing to upgrade %d 'analysis_info'...", count)
        for analysis_info in progress(db.query(AnalysisInfo).all(), count,
                                      100 // 5,
                                      callback=_print_progress):
            if analysis_info.analyzer_command is None:
                continue
            _, new_analyzer_command = \
                recompress_zlib_as_tagged_exact_ratio(
                    analysis_info.analyzer_command)
            db.query(AnalysisInfo) \
                .filter(AnalysisInfo.id == analysis_info.id) \
                .update({"analyzer_command": new_analyzer_command},
                        synchronize_session=False)
        db.commit()
        LOG.info("Done upgrading 'analysis_info'.")

    def create_new_tables():
        op.create_table(
            "checkers",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("analyzer_name", sa.String(), nullable=True),
            sa.Column("checker_name", sa.String(), nullable=True),
            sa.Column("severity", sa.Integer()),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_checkers")),
            sa.UniqueConstraint("analyzer_name", "checker_name",
                                name=op.f("uq_checkers_analyzer_name"))
        )
        op.create_index(
            op.f("ix_checkers_severity"),
            "checkers",
            ["severity"],
            unique=False
        )

        fk_analysisinfo_checkers_name = \
            "fk_analysis_info_checkers_analysis_info_id_analysis_info"
        op.create_table(
            "analysis_info_checkers",
            sa.Column("analysis_info_id", sa.Integer(), nullable=False),
            sa.Column("checker_id", sa.Integer(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=True),
            sa.ForeignKeyConstraint(
                ["analysis_info_id"], ["analysis_info.id"],
                name=op.f(fk_analysisinfo_checkers_name),
                ondelete="CASCADE", initially="DEFERRED",
                deferrable=True),
            sa.ForeignKeyConstraint(
                ["checker_id"], ["checkers.id"],
                name=op.f("fk_analysis_info_checkers_checker_id_checkers"),
                ondelete="RESTRICT", initially="DEFERRED", deferrable=True),
            sa.PrimaryKeyConstraint("analysis_info_id", "checker_id",
                                    name=op.f("pk_analysis_info_checkers"))
        )

    def add_new_checker_id_column():
        # Upgrade the 'reports' table to use the 'checkers' foreign look-up
        # instead of containing the strings allocated locally with the record.
        col_reports_checker_id = sa.Column("checker_id", sa.Integer(),
                                           nullable=False, server_default="0")

        if dialect == "sqlite":
            with op.batch_alter_table("reports", recreate="never") as ba:
                ba.alter_column("checker_id", new_column_name="checker_name")
            # Due to the rename reusing the previous name, these can't merge.
            with op.batch_alter_table("reports", recreate="never") as ba:
                ba.add_column(col_reports_checker_id)
        else:
            op.alter_column("reports", "checker_id",
                            new_column_name="checker_name")
            op.add_column("reports", col_reports_checker_id)

    def add_checkers():
        # Pre-allocate IDs in the look-up table for all checkers that were
        # encountered according to the currently present reports in the DB.
        Base = automap_base()
        Base.prepare(conn, reflect=True)
        Report = Base.classes.reports  # 'reports' is the table name!
        Checker = Base.classes.checkers

        db = Session(bind=conn)
        db.add(Checker(analyzer_name="__FAKE__",
                       checker_name="__FAKE__",
                       severity=0))
        db.add(Checker(analyzer_name="UNKNOWN",
                       checker_name="NOT FOUND",
                       severity=0))

        count = db.query(Report.id).count()
        if not count:
            return

        LOG.info("Preparing to fill 'checkers' from %d 'reports'...", count)
        checker_count = 0
        for chk in db.query(Report.analyzer_name,
                            Report.checker_name,
                            Report.severity) \
                .group_by(Report.analyzer_name,
                          Report.checker_name,
                          Report.severity) \
                .all():
            db.add(Checker(analyzer_name=chk.analyzer_name,
                           checker_name=chk.checker_name,
                           severity=chk.severity))
            checker_count += 1

        db.commit()
        LOG.info("Done filling 'checkers', %d unique entries.", checker_count)

    def upgrade_reports():
        report_count = conn.execute("SELECT COUNT(id) FROM reports;").scalar()
        if not report_count:
            return

        LOG.info("Upgrading %d 'reports' to refer 'checkers',"
                 " in batches of %d...",
                 report_count, REPORT_UPDATE_CHUNK_SIZE)
        num_batches = report_count // REPORT_UPDATE_CHUNK_SIZE + 1

        def _print_progress(batch: int):
            LOG.info("[%d/%d] Upgrading 'reports'... (%d–%d) %.0f%% done.",
                     batch, num_batches,
                     (REPORT_UPDATE_CHUNK_SIZE * i) + 1,
                     (REPORT_UPDATE_CHUNK_SIZE * (i + 1))
                     if batch < num_batches else report_count,
                     float(batch) / num_batches * 100)

        for i in range(0, num_batches):
            # FIXME: "UPDATE ... SET ... FROM ..." is only supported starting
            # with SQLite version 3.33.0 (2020-08-14). Until this version
            # reaches LTS maturity (Ubuntu 20.04 LTS comes with 3.31.0, raising
            # a syntax error on the "FROM" in the "UPDATE" query), this
            # branching here needs to stay.
            if dialect == "sqlite":
                conn.execute(f"""
                    UPDATE reports
                    SET
                        checker_id = (
                            SELECT checkers.id
                            FROM checkers
                            WHERE checkers.analyzer_name = reports.analyzer_name
                                AND checkers.checker_name = reports.checker_name
                        )
                    WHERE reports.id IN (
                            SELECT reports.id
                            FROM reports
                            WHERE reports.checker_id = 0
                            LIMIT {REPORT_UPDATE_CHUNK_SIZE}
                        )
                    ;
                """)
            else:
                conn.execute(f"""
                    UPDATE reports
                    SET
                        checker_id = checkers.id
                    FROM checkers
                    WHERE checkers.analyzer_name = reports.analyzer_name
                        AND checkers.checker_name = reports.checker_name
                        AND reports.id IN (
                            SELECT reports.id
                            FROM reports
                            WHERE reports.checker_id = 0
                            LIMIT {REPORT_UPDATE_CHUNK_SIZE}
                        )
                    ;
                """)
            _print_progress(i + 1)

        LOG.info("Done upgrading 'reports'.")

    def drop_reports_table_columns():
        if dialect == "sqlite":
            op.execute("PRAGMA foreign_keys=OFF")

            with op.batch_alter_table("reports", recreate="never") as ba:
                # FIXME: Allowing recreate="auto" (the default) here would
                # result in SQLAlchemy creating a new 'reports' table, which
                # will break the database as the incoming constraints
                # FOREIGN KEYing against 'reports' will essentially TRUNCATE
                # due to the ON DELETE CASCADE markers, e.g., in
                # 'bug_path_events'. This manifests as the Python-based
                # database cleanup routine essentially wiping all reports off
                # the database, following this migration.
                #
                # Until SQLite 3.35.0 is widely available (Ubuntu 22.04, see
                # also dabc6998b8f0_analysis_info_table.py), we side-step the
                # current problem with a simple rename. However, in general,
                # this is always bound to get bad, and a real solution is only
                # expectable from a **significant**, ground-up redesign of both
                # the database and the migration logic, and our processes.
                # (E.g., if we always assumed migrations can trash the database
                # because there are always back-ups, the whole problem with
                # "SQLite + transaction + pragma = no-op" would not be here.)
                #
                # It generally appears that the big issue here is the fact that
                # migration scripts execute as part of a TRANSACTION! As such,
                # the "PRAGMA foreign_keys=OFF" is useless. See the docs at
                #     http://sqlite.org/foreignkeys.html (quoted Jan 16, 2024)
                #
                # > It is not possible to enable or disable foreign key
                # > constraints in the middle of a multi-statement transaction
                # > (when SQLite is not in autocommit mode). Attempting to do
                # > so does not return an error; it simply has no effect.
                #
                # This means that the foreign keys are still enabled, and when
                # the migration commits, 'bug_path_events' and
                # 'bug_report_points' **WILL** TRUNCATE themselves as the batch
                # operation executed a "DROP TABLE reports;". These claims can
                # be re-verified later by executing the following steps:
                #   1. Change the database manually and set the incoming
                #      foreign keys to "ON DELETE RESTRICT" instead of
                #      "CASCADE".
                #   2. Run the migration. An exception will come from this
                #      context but will refer to an internal "DROP TABLE" stmt.
                #   3. Add an op.execute("COMMIT") before the PRAGMA call
                #      above.
                #   4. Re-run the migration and observe everything is good and
                #      there was no data loss whatsoever!

                # ba.drop_column("checker_name")
                ba.alter_column(
                    "checker_name",
                    new_column_name="checker_name_MOVED_TO_checkers")

                # These columns are deleted as this data is now available
                # through the 'checkers' lookup-table.
                # ba.drop_column("analyzer_name")
                # ba.drop_column("severity")
                ba.alter_column(
                    "analyzer_name",
                    new_column_name="analyzer_name_MOVED_TO_checkers")
                ba.alter_column(
                    "severity",
                    new_column_name="severity_MOVED_TO_checkers")

                # These columns are dropped because they rarely contained any
                # meaningful data with new informational value, and their
                # contents were never actually exposed on the API.
                # ba.drop_column("checker_cat")
                # ba.drop_column("bug_type")
                ba.alter_column("checker_cat",
                                new_column_name="checker_cat_UNUSED")
                ba.alter_column("bug_type",
                                new_column_name="bug_type_UNUSED")

            op.execute("PRAGMA foreign_keys=ON")
        else:
            op.drop_column("reports", "checker_name")
            op.drop_column("reports", "analyzer_name")
            op.drop_column("reports", "severity")
            op.drop_column("reports", "checker_cat")
            op.drop_column("reports", "bug_type")

    def upgrade_reports_table_constraints():
        ix_reports_checker_id = {
            "index_name": op.f("ix_reports_checker_id"),
            "columns": ["checker_id"],
            "unique": False
        }
        fk_reports_checker_id = {
            "constraint_name": op.f("fk_reports_checker_id_checkers"),
            "referent_table": "checkers",
            "local_cols": ["checker_id"],
            "remote_cols": ["id"],
            "deferrable": False,
            "ondelete": "RESTRICT"
        }
        if dialect == "sqlite":
            op.execute("PRAGMA foreign_keys=OFF")

            with op.batch_alter_table("reports", recreate="never") as ba:
                # Now that the values are filled, ensure that the constriants
                # are appropriately enforced.
                ba.create_index(**ix_reports_checker_id)
                # This should really be a FOREIGN KEY, but it is not possible
                # without recreating the entire 'reports' table, which breaks
                # other FOREIGN KEYs.
                # ba.create_foreign_key(**fk_reports_checker_id)

            op.execute("PRAGMA foreign_keys=ON")
        else:
            op.create_index(table_name="reports", **ix_reports_checker_id)
            op.create_foreign_key(source_table="reports",
                                  **fk_reports_checker_id)
            op.alter_column("reports", "checker_id", nullable=False,
                            server_default=None)

    upgrade_analysis_info()
    create_new_tables()
    add_new_checker_id_column()
    add_checkers()
    upgrade_reports()
    drop_reports_table_columns()
    upgrade_reports_table_constraints()


def downgrade():
    LOG = getLogger("migration")
    dialect = op.get_context().dialect.name
    conn = op.get_bind()

    def downgrade_analysis_info():
        # Downgrade AnalysisInfo to use raw BLOBs instead of the typed and
        # tagged ZLibCompressedString feature. The actual type of the Column
        # needs no modification, only the values.
        Base = automap_base()
        Base.prepare(conn, reflect=True)
        # 'analysis_info' is the table!
        AnalysisInfo = Base.classes.analysis_info

        db = Session(bind=conn)
        count = db.query(AnalysisInfo.id).count()
        if not count:
            return

        def _print_progress(index: int, percent: float):
            LOG.info("[%d/%d] Downgrading 'analysis_info'... %.0f%% done.",
                     index, count, percent)

        LOG.info("Preparing to downgrade %d 'analysis_info'...", count)
        for analysis_info in progress(db.query(AnalysisInfo).all(), count,
                                      100 // 5,
                                      callback=_print_progress):
            if analysis_info.analyzer_command is None:
                continue
            old_analyzer_command = recompress_zlib_as_untagged(
                analysis_info.analyzer_command)
            db.query(AnalysisInfo) \
                .filter(AnalysisInfo.id == analysis_info.id) \
                .update({"analyzer_command": old_analyzer_command},
                        synchronize_session=False)
        LOG.info("Done downgrading 'analysis_info'.")
        db.commit()

    def restore_report_columns():
        col_reports_analyzer_name = sa.Column("analyzer_name",
                                              sa.String(), nullable=False,
                                              server_default="unknown")
        col_reports_checker_id = sa.Column("checker_id", sa.String())
        col_reports_checker_cat = sa.Column("checker_cat", sa.String())
        col_reports_bug_type = sa.Column("bug_type", sa.String())
        col_reports_severity = sa.Column("severity", sa.Integer())

        if dialect == "sqlite":
            op.execute("PRAGMA foreign_keys=OFF")

            with op.batch_alter_table("reports", recreate="never") as ba:
                # Recreation of FOREIGN KEYs is not possible without recreating
                # the entire 'reports' table.
                # ba.drop_constraint(op.f("fk_reports_checker_id_checkers"))
                ba.drop_index(op.f("ix_reports_checker_id"))
                ba.alter_column("checker_id",
                                new_column_name="checker_id_lookup")

            with op.batch_alter_table("reports", recreate="never") as ba:
                # Restore the columns that were deleted in this revision.
                # ba.add_column(col_reports_analyzer_name)
                # ba.add_column(col_reports_checker_id)
                # ba.add_column(col_reports_checker_cat)
                # ba.add_column(col_reports_bug_type)
                # ba.add_column(col_reports_severity)

                # FIXME: Until SQLite 3.35 is available and we can actually
                # delete columns without a table recreation, we can instead
                # just restore the existing partial data!
                ba.alter_column("analyzer_name_MOVED_TO_checkers",
                                new_column_name="analyzer_name")
                ba.alter_column("checker_name_MOVED_TO_checkers",
                                new_column_name="checker_id")
                ba.alter_column("severity_moved_to_checkers",
                                new_column_name="severity")
                ba.alter_column("checker_cat_UNUSED",
                                new_column_name="checker_cat")
                ba.alter_column("bug_type_UNUSED",
                                new_column_name="bug_type")

                op.execute("PRAGMA foreign_keys=ON")
        else:
            op.drop_constraint(op.f("fk_reports_checker_id_checkers"),
                               "reports")
            op.drop_index(op.f("ix_reports_checker_id"), "reports")
            op.alter_column("reports", "checker_id",
                            new_column_name="checker_id_lookup")

            op.add_column("reports", col_reports_analyzer_name)
            op.add_column("reports", col_reports_checker_id)
            op.add_column("reports", col_reports_checker_cat)
            op.add_column("reports", col_reports_bug_type)
            op.add_column("reports", col_reports_severity)

        LOG.info("Restored type of columns 'reports.bug_type', "
                 "'reports.checker_cat'. However, their contents can NOT "
                 "be restored to the original values, as those were "
                 "irrevocably lost during a previous schema upgrade. "
                 "Note, that these columns NEVER contained any actual "
                 "value that was accessible by users of the API, so "
                 "this is a technical note.")

    def downgrade_reports():
        report_count = conn.execute("SELECT COUNT(id) FROM reports;").scalar()
        if not report_count:
            return

        LOG.info("Downgrading %d 'reports' from 'checkers',"
                 " in batches of %d...",
                 report_count, REPORT_UPDATE_CHUNK_SIZE)
        num_batches = report_count // REPORT_UPDATE_CHUNK_SIZE + 1

        def _print_progress(batch: int):
            LOG.info("[%d/%d] Downgrading 'reports'... (%d–%d) %.0f%% done.",
                     batch, num_batches,
                     (REPORT_UPDATE_CHUNK_SIZE * i) + 1,
                     (REPORT_UPDATE_CHUNK_SIZE * (i + 1))
                     if batch < num_batches else report_count,
                     float(batch) / num_batches * 100)

        for i in range(0, num_batches):
            # FIXME: "UPDATE ... SET ... FROM ..." is only supported starting
            # with SQLite version 3.33.0 (2020-08-14). Until this version
            # reaches LTS maturity (Ubuntu 20.04 LTS comes with 3.31.0, raising
            # a syntax error on the "FROM" in the "UPDATE" query), this
            # branching here needs to stay.
            if dialect == "sqlite":
                conn.execute(f"""
                    UPDATE reports
                    SET
                        (analyzer_name, checker_id, severity, checker_id_lookup) =
                        (SELECT analyzer_name, checker_name, severity, '0'
                            FROM checkers
                            WHERE checkers.id = reports.checker_id_lookup)
                    WHERE reports.id IN (
                            SELECT reports.id
                            FROM reports
                            WHERE reports.checker_id_lookup != 0
                            LIMIT {REPORT_UPDATE_CHUNK_SIZE}
                        )
                    ;
                """)
            else:
                conn.execute(f"""
                    UPDATE reports
                    SET
                        analyzer_name = checkers.analyzer_name,
                        checker_id = checkers.checker_name,
                        severity = checkers.severity,
                        checker_id_lookup = 0
                    FROM checkers
                    WHERE checkers.id = reports.checker_id_lookup
                        AND reports.id IN (
                            SELECT reports.id
                            FROM reports
                            WHERE reports.checker_id_lookup != 0
                            LIMIT {REPORT_UPDATE_CHUNK_SIZE}
                        )
                    ;
                """)
            _print_progress(i + 1)

        LOG.info("Done downgrading 'reports'.")

    def drop_checker_id_numeric_column():
        if dialect == "sqlite":
            with op.batch_alter_table("reports", recreate="never") as ba:
                # FIXME: SQLite >= 3.35 will allow DROP COLUMN...
                # ba.drop_column("checker_id_lookup")
                ba.alter_column("checker_id_lookup",
                                new_column_name="checker_id_lookup_UNUSED")
        else:
            op.drop_column("reports", "checker_id_lookup")

    def drop_new_tables():
        # Drop all tables and columns that were created in this revision.
        # This data is not needed anymore.
        op.drop_index(op.f("ix_checkers_severity"), "checkers")
        op.drop_table("analysis_info_checkers")
        op.drop_table("checkers")

    downgrade_analysis_info()
    restore_report_columns()
    downgrade_reports()
    drop_checker_id_numeric_column()
    drop_new_tables()
