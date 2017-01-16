# -------------------------------------------------------------------------
#                     The CodeChecker Infrastructure
#   This file is distributed under the University of Illinois Open Source
#   License. See LICENSE.TXT for details.
# -------------------------------------------------------------------------

from __future__ import print_function
from __future__ import unicode_literals

from argparse import Namespace
import datetime
import errno
import hashlib
import multiprocessing
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
from codechecker_lib.logger import LoggerFactory
from codechecker_lib import util
from db_model.orm_model import *

from . import lib as daemon_lib

LOG = LoggerFactory.get_new_logger('CC DAEMON')


class RemoteHandler(object):
    """
    Class to handle requests from the CodeChecker script to
    perform checking on this remote, daemon machine.
    """

    class RunLock(object):
        """A lock object that contains transient data associated with one
        particular remote checking execution."""

        def __init__(self, workspace, run_name, local_invocation, args_json):
            self.workspace = workspace
            self.run_name = run_name
            self.file_root = os.path.join(self.workspace, run_name)
            self.lock_created = datetime.now()
            self.__persistent_hash = util.get_hash([workspace,
                                                    run_name,
                                                    self.lock_created])[0:8]

            self.args = Namespace(
                # Mandatory field for indicating that the checking does
                # NOT take place on a local machine!
                is_remote_checking=True,
                local_invocation=local_invocation,

                # Field overrides due to remote context,
                name=run_name,
                logfile=os.path.join(self.file_root,
                                     "compilation_commands.json"),

                # TODO: Review these overrides!
                add_compiler_defaults=False,
                jobs=1,  # TODO: Let local invoker alter the number of jobs!
                force=False,
                keep_tmp=False
            )
            daemon_lib.unpack_check_args(self.args, args_json)

        def get_persistent_token(self):
            return self.__persistent_hash

    def initConnection(self, run_name, local_invocation, check_args):
        """
        Sets up a remote checking's environment on the server based on a
        client's request.
        """

        # Check whether the given run is locked.
        if run_name in self._running_checks:
            if (datetime.now() - self._running_checks[run_name]
                    .lock_created).total_seconds() <= 5:
                LOG.info("Refusing to do '" + run_name +
                         "' as a run named like so is already being done!")
                raise shared.ttypes.RequestFailed(
                    shared.ttypes.ErrorCode.GENERAL,
                    str("A run named '" + run_name +
                        "' is already in progress."))

        LOG.info("Beginning to handle new remote check request for '" +
                 run_name + "'")

        lock_object = RemoteHandler.RunLock(self.workspace,
                                            run_name,
                                            local_invocation,
                                            check_args)

        first_connection_for_run = not os.path.exists(lock_object.file_root)
        if first_connection_for_run:
            LOG.debug("Creating run folder at " + lock_object.file_root)
            os.mkdir(lock_object.file_root)

        self._running_checks[run_name] = lock_object

        return Acknowledgement(lock_object.get_persistent_token(),
                               first_connection_for_run)

    def _get_run(self, token):
        """Returns if a current run for the given unique token."""
        return next((lobj for lobj in self._running_checks.values()
                     if lobj.get_persistent_token() == token), None)

    def sendFileData(self, token, files):
        """
        Receives a list of files and metadata from
        the client for a given connection.
        """

        run = self._get_run(token)
        if not run:
            LOG.error("Received file data for run #" + token + " but such"
                      " run does not exist!")
            raise shared.ttypes.RequestFailed(
                shared.ttypes.ErrorCode.GENERAL,
                str("No run with the given token."))

        LOG.info("Received " + str(len(files)) +
                 " file data for run '" + run.run_name + "'")

        files_need_send = []
        for fd in files:
            # Twist the path so it refers to a place under the
            # workspace/runname folder.
            client_path = fd.path
            if os.path.isabs(client_path):
                # TODO: This won't work under Windows!
                client_path = client_path.lstrip('/')
            local_path = os.path.join(run.file_root, client_path)

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

    def beginChecking(self, token, disconnect_immediately):
        """Starts the checking on the daemon host."""

        def _end_check_callback(self, run_object):
            LOG.debug('Check runner subprocess exited for run #{0} ({1}).'.
                      format(run_object.get_persistent_token(),
                             run_object.run_name))
            del self._running_checks[run_object.run_name]

        run = self._get_run(token)
        if not run:
            LOG.error("Client commanded to start run #" + token + " but such"
                      " run does not exist!")
            raise shared.ttypes.RequestFailed(
                shared.ttypes.ErrorCode.GENERAL,
                str("No run with the given token."))

        check_process = multiprocessing.Process(
            target=daemon_lib.handle_checking,
            args=(
                run,
                self.context,
                _end_check_callback(self, run),
                LOG))

        check_process.start()

        if not disconnect_immediately:
            # If the user wants to wait for the checking to finish,
            # then we shall wait
            LOG.debug('Check running. Keeping connection alive '
                      'until check is over...')
            check_process.join()
        else:
            LOG.debug('User did not request keep-alive. Goodbye!')

    def __init__(self, context, session):
        self._running_checks = {}
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
        # TODO: Cmdline argument to limit threads and jobs per thread
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
