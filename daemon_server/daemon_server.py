# -------------------------------------------------------------------------
#                     The CodeChecker Infrastructure
#   This file is distributed under the University of Illinois Open Source
#   License. See LICENSE.TXT for details.
# -------------------------------------------------------------------------

from __future__ import print_function
from __future__ import unicode_literals

import datetime
import errno
import ntpath
import os
import socket
import sys

import shared
import sqlalchemy
from codechecker_gen.DBThriftAPI import CheckerReport
from codechecker_gen.DBThriftAPI.ttypes import *
from thrift.protocol import TBinaryProtocol
from thrift.server import TServer
from thrift.transport import TSocket
from thrift.transport import TTransport

from codechecker_lib import database_handler
from codechecker_lib import decorators
from codechecker_lib import logger
from db_model.orm_model import *

from codechecker_lib.profiler import timeit
from codechecker_lib.profiler import profileit

from storage_server import report_server

LOG = logger.get_new_logger('CC DAEMON')

def run_server(port, db_uri, db_version_info, callback_event=None):
    LOG.debug('Starting CodeChecker daemon ...')

    try:
        engine = database_handler.SQLServer.create_engine(db_uri)

        LOG.debug('Creating new database session.')
        session = CreateSession(engine)

    except sqlalchemy.exc.SQLAlchemyError as alch_err:
        LOG.error(str(alch_err))
        sys.exit(1)

    session.autoflush = False  # Autoflush is enabled by default.

    LOG.debug('Starting thrift server.')
    try:
        # Start thrift server.
        handler = report_server.CheckerReportHandler(session, True)

        processor = CheckerReport.Processor(handler)
        transport = TSocket.TServerSocket(port=port)
        tfactory = TTransport.TBufferedTransportFactory()
        pfactory = TBinaryProtocol.TBinaryProtocolFactory()

        server = TServer.TThreadPoolServer(processor,
                                           transport,
                                           tfactory,
                                           pfactory,
                                           daemon=True)

        LOG.info('Waiting for check results on [' + str(port) + ']')
        if callback_event:
            callback_event.set()
        LOG.debug('Starting to serve.')
        server.serve()
        LOG.debug('Stopped serving.')
        session.commit()
    except socket.error as sockerr:
        LOG.error(str(sockerr))
        if sockerr.errno == errno.EADDRINUSE:
            LOG.error('Checker port ' + str(port) + ' is already used!')
        sys.exit(1)
    except Exception as err:
        LOG.error(str(err))
        session.commit()
        sys.exit(1)
