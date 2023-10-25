"""Add 'enabled_checkers' to 'analysis_info'

Revision ID: c3dad71f8e6b
Revises: 9d956a0fae8d
Create Date: 2023-10-20 14:11:48.371981

"""

# revision identifiers, used by Alembic.
revision = 'c3dad71f8e6b'
down_revision = '9d956a0fae8d'
branch_labels = None
depends_on = None

from alembic import op
from logging import getLogger
import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy.ext.automap import automap_base

from codechecker_common.util import progress
from codechecker_server.database.common import ZLibCompressedJSON
from codechecker_server.migrations.report.common import \
    recompress_zlib_as_untagged, recompress_zlib_as_tagged_exact_ratio


def AnalysisInfo_in_DB(conn):
    """
    Obtain a database conncetion and the in-migration AnalysisInfo object's
    definition.
    """
    Base = automap_base()
    Base.prepare(conn, reflect=True)

    AnalysisInfo = Base.classes.analysis_info  # "analysis_info" table name.

    return Session(bind=conn), AnalysisInfo


def upgrade():
    # Note: The instantiation of the LOG variable *MUST* stay here so that it
    # uses the facilities that are sourced from the Alembic env.py.
    # Symbols created on the module-level are created *before* Alembic's env.py
    # had loaded.
    LOG = getLogger("migration")

    # Upgrade the contents of the existing columns to the new ZLibCompressed
    # format.
    #
    # Note: The underlying type of ZLibCompressedString is still LargeBinary,
    # so the Column itself need not be modified, only the contents.
    conn = op.get_bind()
    db, AnalysisInfo = AnalysisInfo_in_DB(conn)
    count = db.query(AnalysisInfo).count()
    if count:
        def _print_progress(index: int, percent: float):
            LOG.info("[%d/%d] Migrating 'analysis_info'... %.0f%% done.",
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
        LOG.info("Done upgrading 'analysis_info'.")
        db.commit()

    # Add the new columns created in this revision.
    op.add_column("analysis_info",
                  sa.Column("enabled_checkers",
                            # ZLibCompressedJSON(),
                            sa.String(),
                            nullable=True))


def downgrade():
    LOG = getLogger("migration")

    # Drop all columns that were created in this revision.
    if op.get_context().dialect.name == "sqlite":
        op.execute("PRAGMA foreign_keys=off")
        with op.batch_alter_table("analysis_info") as batch:
            batch.drop_column("enabled_checkers")
        op.execute("PRAGMA foreign_keys=on")
    else:
        op.drop_column("analysis_info", "enabled_checkers")

    # Revert the changes of the columns that remain.
    conn = op.get_bind()
    db, AnalysisInfo = AnalysisInfo_in_DB(conn)
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
