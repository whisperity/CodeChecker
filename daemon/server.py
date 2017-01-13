# -------------------------------------------------------------------------
#                     The CodeChecker Infrastructure
#   This file is distributed under the University of Illinois Open Source
#   License. See LICENSE.TXT for details.
# -------------------------------------------------------------------------

from __future__ import print_function
from __future__ import unicode_literals

import datetime
import errno
import hashlib
import ntpath
import os
import time
import socket
import sys

import shared
import sqlalchemy
from codechecker_gen.daemonServer import RemoteChecking
from codechecker_gen.daemonServer.ttypes import *
from thrift.protocol import TBinaryProtocol
from thrift.server import TServer
from thrift.transport import TSocket
from thrift.transport import TTransport

from codechecker_lib import database_handler
from codechecker_lib import decorators
from codechecker_lib import logger
from codechecker_lib.logger import LoggerFactory
from db_model.orm_model import *

from . import lib as daemon_lib

from codechecker_lib.profiler import profileit

LOG = LoggerFactory.get_new_logger('CC DAEMON')


class RemoteHandler(object):
    """
    Class to handle requests from the CodeChecker script to
    perform checking on this remote, daemon machine.
    """

    def _generate_folder(self, run_name):
        return os.path.join(self.workspace, run_name)

    def initConnection(self, run_name):
        """
        Sets up a remote checking's environment on the server based on a
        client's request.
        """

        if run_name in self._runningChecks:
            if (datetime.now() - self._runningChecks[run_name])\
                    .total_seconds() <= 60:
                return False

        LOG.info("Beginning to handle new remote check request for '" +
                 run_name + "'")
        self._runningChecks[run_name] = datetime.now()

        # Check if the workspace folder for this run exists
        folder = self._generate_folder(run_name)
        if not os.path.exists(folder):
            LOG.debug("Creating run folder at " + folder)
            os.mkdir(folder)

        return True

    def sendFileData(self, run_name, files):
        """
        Receives a list of files and metadata from
        the client for a given connection.
        """
        if run_name not in self._runningChecks:
            return
        folder = self._generate_folder(run_name)

        LOG.info("Received " + str(len(files)) + " file data for run '" + run_name + "'")

        files_need_send = []
        for fd in files:
            # Twist the path so it refers to a place under the
            # workspace/runname folder.
            client_path = fd.path
            if os.path.isabs(client_path):
                # TODO: This won't work under Windows!
                client_path = client_path.lstrip('/')
            local_path = os.path.join(folder, client_path)

            # We also need to check if the proper directory structure exists
            if not os.path.exists(os.path.dirname(local_path)):
                os.makedirs(os.path.dirname(local_path))

            if fd.content is not None:
                # For files that have content, we extract them to the run-folder
                with open(local_path, 'w') as f:
                    f.write(fd.content)
            else:
                # For files that don't have their content set, we check if the
                # local version's hash (if exists) matches the client's hash
                if not os.path.exists(local_path):
                    files_need_send.append(fd.path)
                else:
                    with open(local_path, 'r') as f:
                        sha = hashlib.sha1(f.read()).hexdigest()
                        if sha != fd.sha:
                            LOG.debug("File '" + fd.path + "' SHA mismatch.\n"
                                "\tClient: " + fd.sha +
                                "\tServer: " + sha)

                            files_need_send.append(fd.path)

        return files_need_send

    def beginChecking(self, run_name):
        daemon_lib.handleChecking(run_name,
                                  self._generate_folder(run_name),
                                  self.context,
                                  LOG)

    def __init__(self, context, session):
        self._runningChecks = {}
        self.context = context
        self.workspace = context.codechecker_workspace
        self.session = session


def run_server(host, port, db_uri, context, callback_event=None):
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
        handler = RemoteHandler(context, session)

        processor = RemoteChecking.Processor(handler)
        transport = TSocket.TServerSocket(host=host, port=port)
        tfactory = TTransport.TBufferedTransportFactory()
        pfactory = TBinaryProtocol.TBinaryProtocolFactory()

        server = TServer.TThreadPoolServer(processor,
                                           transport,
                                           tfactory,
                                           pfactory,
                                           daemon=True)
        server.setNumThreads(15)  # TODO: Dev config --- please remove

        LOG.info('Waiting for remote connections on [' +
                 (host if host else '') + ':' + str(port) + ']')

        if callback_event:
            callback_event.set()
        LOG.debug('Starting to serve.')
        server.serve()
        session.commit()
    except socket.error as sockerr:
        LOG.error(str(sockerr))
        if sockerr.errno == errno.EADDRINUSE:
            LOG.error('Port ' + str(port) + ' is already used!')
        sys.exit(1)
    except Exception as err:
        LOG.error(str(err))
        session.commit()
        sys.exit(1)
