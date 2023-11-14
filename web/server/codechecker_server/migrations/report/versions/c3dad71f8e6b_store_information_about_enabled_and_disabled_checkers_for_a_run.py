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
from typing import Dict, List, Set, Tuple

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy.ext.automap import automap_base

from codechecker_common.util import progress
from codechecker_server.migrations.report.common import \
    recompress_zlib_as_untagged, recompress_zlib_as_tagged_exact_ratio


def upgrade():
    # Note: The instantiation of the LOG variable *MUST* stay here so that it
    # uses the facilities that are sourced from the Alembic env.py.
    # Symbols created on the module-level are created *before* Alembic's env.py
    # had loaded.
    LOG = getLogger("migration")
    dialect = op.get_context().dialect.name
    conn = op.get_bind()
    db = Session(bind=conn)

    def upgrade_analysis_info():
        # Upgrade the contents of the existing columns in AnalysisInfo to the
        # new ZLibCompressed format.
        #
        # Note: The underlying type of ZLibCompressedString is still
        # LargeBinary, so the Column itself need not be modified, only the
        # contents.
        Base = automap_base()
        Base.prepare(conn, reflect=True)
        # 'analysis_info' is the table!
        AnalysisInfo = Base.classes.analysis_info

        count = db.query(AnalysisInfo).count()
        if count:
            def _print_progress(index: int, percent: float):
                LOG.info("[%d/%d] Upgrading 'analysis_info'... %.0f%% done.",
                         index, count, percent)

            LOG.info("Preparing to upgrade %d 'analysis_info'...", count)
            for analysis_info in progress(db.query(AnalysisInfo).all(), count,
                                          100 // 5,
                                          callback=_print_progress):
                _, new_analyzer_command = recompress_zlib_as_tagged_exact_ratio(
                    analysis_info.analyzer_command)
                db.query(AnalysisInfo) \
                    .filter(AnalysisInfo.id == analysis_info.id) \
                    .update({"analyzer_command": new_analyzer_command},
                            synchronize_session=False)
            db.commit()
            LOG.info("Done upgrading 'analysis_info'.")

    def create_new_tables():
        op.create_table(
            "checker_names",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("analyzer_name", sa.String(), nullable=True),
            sa.Column("checker_name", sa.String(), nullable=True),
            sa.Column("severity", sa.Integer()),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_checker_names")),
            sa.UniqueConstraint("analyzer_name", "checker_name",
                                name=op.f("uq_checker_names_analyzer_name"))
        )
        op.create_index(op.f("ix_checker_names_severity"),
                        "checker_names",
                        ["severity"],
                        unique=False)

        op.create_table(
            "analysis_info_checkers",
            sa.Column("analysis_info_id", sa.Integer(), nullable=False),
            sa.Column("checker_name_id", sa.Integer(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=True),
            sa.ForeignKeyConstraint(
                ["analysis_info_id"], ["analysis_info.id"],
                name=op.f("fk_analysis_info_checkers_analysis_info_id_analysis_info"),
                ondelete="CASCADE", initially="DEFERRED",
                deferrable=True),
            sa.ForeignKeyConstraint(
                ["checker_name_id"], ["checker_names.id"],
                name=op.f("fk_analysis_info_checkers_checker_name_id_checker_names"),
                ondelete="RESTRICT", initially="DEFERRED", deferrable=True),
            sa.PrimaryKeyConstraint("analysis_info_id", "checker_name_id",
                                    name=op.f("pk_analysis_info_checkers"))
        )

    def get_and_add_checker_names_from_reports():
        # Pre-allocate IDs in the look-up table for all checkers that were
        # encountered according to the currently present reports in the DB.
        Base = automap_base()
        Base.prepare(conn, reflect=True)
        Report = Base.classes.reports  # 'reports' is the table name!
        CheckerName = Base.classes.checker_names

        db.add(CheckerName(analyzer_name="UNKNOWN",
                           checker_name="NOT FOUND",
                           severity=0))
        db.commit()

        count = db.query(Report).count()
        checkers_to_reports: Dict[Tuple[str, str], List[int]] = dict()
        checkers_to_ids: Dict[Tuple[str, str], int] = dict()
        checkers_to_severity: Dict[Tuple[str, str], int] = dict()
        if count:
            def _print_progress(index: int, percent: float):
                LOG.info("[%d/%d] Gathering checkers from 'reports'... "
                         "%.0f%% done. %d checkers found.",
                         index, count, percent, len(checkers_to_reports))

            LOG.info("Preparing to pre-fill 'checker_names'...")
            LOG.info("Preparing to gather checkers from %d 'reports'...",
                     count)
            for report in progress(db.query(Report).all(), count,
                                   100 // 5,
                                   callback=_print_progress):
                chk = (report.analyzer_name, report.checker_id)
                reps = checkers_to_reports.get(chk, list())
                reps.append(report.id)
                checkers_to_reports[chk] = reps
                checkers_to_severity[chk] = report.severity

            for chk in sorted(checkers_to_reports.keys()):
                obj = CheckerName(analyzer_name=chk[0], checker_name=chk[1],
                                  severity=checkers_to_severity[chk])
                db.add(obj)
                db.flush()
                db.refresh(obj, ["id"])
                checkers_to_ids[chk] = obj.id

            db.commit()
            LOG.info("Done pre-filling 'checker_names'.")

        return count, checkers_to_reports, checkers_to_ids

    def upgrade_reports(count, checkers_to_reports, checkers_to_ids):
        if count:
            LOG.info("Preparing to upgrade %d 'reports'...", count)
            done_report_count = 0
            for chk in sorted(checkers_to_reports.keys()):
                report_id_list = checkers_to_reports[chk]
                chk_id = checkers_to_ids[chk]

                conn.execute(f"""
                    UPDATE reports
                    SET
                        checker_id = {chk_id}
                    WHERE id IN ({','.join(map(str, report_id_list))});
                """)

                done_report_count += len(report_id_list)
                LOG.info("[%d/%d] Upgrading 'reports'... "
                         "'%s/%s' (%d), %.2f%% done.",
                         done_report_count, count, chk[0], chk[1],
                         len(report_id_list),
                         (done_report_count * 100.0 / count))

    def upgrade_reports_table_columns():
        # Upgrade the 'reports' table to use the 'checker_names' foreign look-up
        # instead of containing the strings allocated locally with the record.
        col_reports_checker_name_id = sa.Column("checker_id", sa.Integer(),
                                                nullable=True)

        LOG.info("Upgrading 'reports' table structure...")
        if dialect == "sqlite":
            LOG.warning("On SQLite databases, column changes require the "
                        "creation of a new temporary table. If you have many "
                        "reports, this might take a while...")
            op.execute("PRAGMA foreign_keys=OFF;")

        with op.batch_alter_table("reports",
                                  recreate="always" if dialect == "sqlite"
                                           else "auto") as ba:
            ba.drop_column("checker_id")
            # These columns are deleted as this data is now available through
            # the 'checker_names' lookup-table.
            ba.drop_column("analyzer_name")
            ba.drop_column("severity")

            ba.add_column(col_reports_checker_name_id, insert_after="bug_id")

        if dialect == "sqlite":
            op.execute("PRAGMA foreign_keys=ON;")

    def upgrade_reports_table_constraints():
        ix_reports_checker_id = {
            "index_name": op.f("ix_reports_checker_id"),
            "columns": ["checker_id"],
            "unique": False
        }
        fk_reports_checker_id = {
            "constraint_name": op.f("fk_reports_checker_id_checker_names"),
            "referent_table": "checker_names",
            "local_cols": ["checker_id"],
            "remote_cols": ["id"],
            "deferrable": False,
            "ondelete": "RESTRICT"
        }
        if dialect == "sqlite":
            op.execute("PRAGMA foreign_keys=OFF;")

        with op.batch_alter_table("reports") as ba:
            # Now that the values are filled, ensure that the constriants are
            # appropriately enforced.
            ba.create_index(**ix_reports_checker_id)
            ba.create_foreign_key(**fk_reports_checker_id)

            ba.alter_column("checker_id", nullable=False)

        if dialect == "sqlite":
            op.execute("PRAGMA foreign_keys=ON;")

    upgrade_analysis_info()
    create_new_tables()
    report_count, checkers_to_reports, checkers_to_ids = \
        get_and_add_checker_names_from_reports()
    upgrade_reports_table_columns()
    upgrade_reports(report_count, checkers_to_reports, checkers_to_ids)
    upgrade_reports_table_constraints()


def downgrade():
    LOG = getLogger("migration")
    dialect = op.get_context().dialect.name
    conn = op.get_bind()
    db = Session(bind=conn)

    def downgrade_analysis_info():
        # Downgrade AnalysisInfo to use raw BLOBs instead of the typed
        # ZLibCompressedString feature.
        Base = automap_base()
        Base.prepare(conn, reflect=True)

        # 'analysis_info' is the table!
        AnalysisInfo = Base.classes.analysis_info
        count = db.query(AnalysisInfo).count()
        if count:
            def _print_progress(index: int, percent: float):
                LOG.info("[%d/%d] Downgrading 'analysis_info'... %.0f%% done.",
                         index, count, percent)

            LOG.info("Preparing to downgrade %d 'analysis_info'...", count)
            for analysis_info in progress(db.query(AnalysisInfo).all(), count,
                                          100 // 5,
                                          callback=_print_progress):
                old_analyzer_command = recompress_zlib_as_untagged(
                    analysis_info.analyzer_command)
                db.query(AnalysisInfo) \
                    .filter(AnalysisInfo.id == analysis_info.id) \
                    .update({"analyzer_command": old_analyzer_command},
                            synchronize_session=False)
            LOG.info("Done downgrading 'analysis_info'.")
            db.commit()

    def get_checker_names_and_associated_reports():
        Base = automap_base()
        Base.prepare(conn, reflect=True)

        # Revert the introduction of a lookup table to identify checkers,
        # back-inserting the relevant information to the 'reports' table.
        Report = Base.classes.reports  # 'reports' is the table name!
        CheckerName = Base.classes.checker_names

        count = db.query(Report).count()
        checker_count = db.query(CheckerName).count()
        ids_to_checkers: Dict[int, Tuple[str, str]] = dict()
        checkers_to_reports: Dict[Tuple[str, str], List[int]] = dict()
        checkers_to_severity: Dict[Tuple[str, str], int] = dict()
        if count and checker_count:
            def _print_progress(index: int, percent: float):
                LOG.info("[%d/%d] Collecting checker names from 'reports'... "
                         "%.0f%% done.",
                         index, count, percent)

            LOG.info("Preparing to backfill %d 'checker_names' into %d "
                     "'reports'...", checker_count, count)
            for chk in db.query(CheckerName).all():
                chk_name = (chk.analyzer_name, chk.checker_name)
                ids_to_checkers[chk.id] = chk_name
                checkers_to_severity[chk_name] = chk.severity

            for report in progress(db.query(Report).all(), count,
                                   100 // 5,
                                   callback=_print_progress):
                chk = ids_to_checkers[report.checker_id]
                reps = checkers_to_reports.get(chk, list())
                reps.append(report.id)
                checkers_to_reports[chk] = reps

        return count, checkers_to_reports, checkers_to_severity

    def downgrade_report_table_columns():
        col_reports_checker_id = sa.Column("checker_id", sa.String())
        col_reports_analyzer_name = sa.Column("analyzer_name",
                                              sa.String(), nullable=False,
                                              server_default="unknown")
        col_reports_severity = sa.Column("severity", sa.Integer())

        LOG.info("Downgrading 'reports' table structure...")
        if dialect == "sqlite":
            LOG.warning("On SQLite databases, column changes require the "
                        "creation of a new temporary table. If you have many "
                        "reports, this might take a while...")
            op.execute("PRAGMA foreign_keys=OFF;")

        with op.batch_alter_table("reports",
                                  recreate="always" if dialect == "sqlite"
                                           else "auto") as ba:
            # Drop the column that was introduced in this revision.
            ba.drop_constraint(
                op.f("fk_reports_checker_id_checker_names"))
            ba.drop_index(op.f("ix_reports_checker_id"))
            ba.drop_column("checker_id")

            # Restore the columns that were deleted in this revision.
            ba.add_column(col_reports_analyzer_name, insert_after="bug_id")
            ba.add_column(col_reports_checker_id, insert_after="analyzer_name")
            ba.add_column(col_reports_severity, insert_after="checker_id")

        if dialect == "sqlite":
            op.execute("PRAGMA foreign_keys=ON;")

    def downgrade_reports(count, checkers_to_reports, checkers_to_severity):
        if count:
            LOG.info("Preparing to downgrade %d 'reports'...", count)
            done_report_count = 0
            for chk in sorted(checkers_to_reports.keys()):
                report_id_list = checkers_to_reports[chk]

                conn.execute(f"""
                    UPDATE reports
                    SET
                        analyzer_name = "{chk[0]}",
                        checker_id = "{chk[1]}",
                        severity = "{checkers_to_severity[chk]}"
                    WHERE id IN ({','.join(map(str, report_id_list))});
                """)

                done_report_count += len(report_id_list)
                LOG.info("[%d/%d] Downgrading 'reports'... "
                         "'%s/%s' (%d), %.2f%% done.",
                         done_report_count, count, chk[0], chk[1],
                         len(report_id_list),
                         (done_report_count * 100.0 / count))
            db.commit()
            LOG.info("Done inserting 'checker_names' back into 'reports'.")
        pass

    def drop_new_tables():
        # Drop all tables and columns that were created in this revision.
        # This data is not needed anymore.
        op.drop_index(op.f("ix_checker_names_severity"))
        op.drop_table("analysis_info_checkers")
        op.drop_table("checker_names")

    downgrade_analysis_info()
    report_count, checkers_to_reports, checkers_to_severity = \
        get_checker_names_and_associated_reports()
    downgrade_report_table_columns()
    downgrade_reports(report_count, checkers_to_reports, checkers_to_severity)
    drop_new_tables()
