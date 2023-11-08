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

    # Upgrade the contents of the existing columns to the new ZLibCompressed
    # format.
    #
    # Note: The underlying type of ZLibCompressedString is still LargeBinary,
    # so the Column itself need not be modified, only the contents.
    conn = op.get_bind()
    db = Session(bind=conn)
    Base = automap_base()
    Base.prepare(conn, reflect=True)
    AnalysisInfo = Base.classes.analysis_info  # 'analysis_info' is the table!

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

    # Add the new tables and columns created in this revision.
    op.create_table(
        "checker_names",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("analyzer_name", sa.String(), nullable=True),
        sa.Column("checker_name", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_checker_names")),
        sa.UniqueConstraint("analyzer_name", "checker_name",
                            name=op.f("uq_checker_names_analyzer_name"))
    )

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
            ondelete="CASCADE", initially="DEFERRED", deferrable=True),
        sa.PrimaryKeyConstraint("analysis_info_id", "checker_name_id",
                                name=op.f("pk_analysis_info_checkers"))
    )

    # Pre-allocate IDs in the look-up table for all checkers that were
    # encountered according to the currently present reports in the DB.
    Base = automap_base()
    Base.prepare(conn, reflect=True)
    Report = Base.classes.reports  # 'reports' is the table name!
    CheckerName = Base.classes.checker_names  # 'checker_names' is the table!
    count = db.query(Report).count()
    if count:
        checkers_to_reports: Dict[Tuple[str, str], List[int]] = dict()

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

        checkers_to_objs: Dict[Tuple[str, str], int] = dict()
        for chk in sorted(checkers_to_reports.keys()):
            obj = CheckerName(analyzer_name=chk[0], checker_name=chk[1])
            db.add(obj)
            db.flush()
            db.refresh(obj, ["id"])

            checkers_to_objs[chk] = obj.id
        db.commit()
        LOG.info("Done pre-filling 'checker_names'.")

    # Upgrade the 'reports' table to use the 'checker_names' foreign look-up
    # instead of containing the strings allocated locally with the record.
    col_reports_checker_name_id = sa.Column("checker_id", sa.Integer(),
                                            nullable=True)
    ix_reports_checker_id = {
        "index_name": op.f("ix_reports_checker_id"),
        "columns": ["checker_id"],
        "unique": False
    }
    fk_reports_checker_id = {
        "constraint_name": op.f("fk_reports_checker_id_checker_names"),
        "referent_table": "checker_names",
        "local_cols": ["checker_id"],
        "remote_cols": ["id"]
    }

    if dialect == "sqlite":
        op.execute("PRAGMA foreign_keys=OFF;")

    with op.batch_alter_table("reports") as ba:
        ba.alter_column("checker_id", new_column_name="checker_id_old")

    with op.batch_alter_table("reports",
                              recreate="always" if dialect == "sqlite"
                                       else "auto") as ba:
        ba.add_column(col_reports_checker_name_id, insert_after="bug_id")
        ba.create_index(**ix_reports_checker_id)
        ba.create_foreign_key(**fk_reports_checker_id)

    # TODO: Fill all the reports with the information about their checker_ids.

    # with op.batch_alter_table("reports") as ba:
        # ba.drop_column("checker_id_old")
        # ba.alter_column("checker_id", nullable=False)

    if dialect == "sqlite":
        op.execute("PRAGMA foreign_keys=ON;")


def downgrade():
    LOG = getLogger("migration")

    # Drop all tables and columns that were created in this revision.
    op.drop_table("analysis_info_checkers")
    op.drop_table("checker_names")

    # Revert the changes of the columns that remain.
    conn = op.get_bind()
    db = Session(bind=conn)
    Base = automap_base()
    Base.prepare(conn, reflect=True)
    AnalysisInfo = Base.classes.analysis_info  # 'analysis_info' is the table!

    count = db.query(AnalysisInfo).count()
    if count:
        def _print_progress(index: int, percent: float):
            LOG.info("[%d/%d] Migrating 'analysis_info'... %.0f%% done.",
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
