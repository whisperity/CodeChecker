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
import json
import ntpath
import os
import time
import threading
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

from codechecker_lib.analyzers import analyzer_types
from codechecker_lib import database_handler
from codechecker_lib import generic_package_context
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

        class RunStates:
            INITIALISED = 1,
            ANALYZERS_RUNNING = 2,
            DONE = 3

        def __init__(self, workspace, run_name, local_invocation, args_json):
            self.workspace = workspace
            self.run_name = run_name
            self.lock_created = datetime.now()
            self.__persistent_hash = util.get_hash([workspace,
                                                    run_name,
                                                    self.lock_created])[0:8]

            file_root = os.path.join(self.workspace, run_name)
            self.args = Namespace(
                # Mandatory field for indicating that the checking does
                # NOT take place on a local machine!
                is_remote_checking=True,
                local_invocation=local_invocation,
                daemon_root=file_root,

                # Field overrides due to remote context.
                name=run_name,
                logfile=os.path.join(file_root,
                                     daemon_lib.
                                     FILES_TO_ALWAYS_UPLOAD['logfile']),

                # TODO: Review these overrides!
                add_compiler_defaults=False,
                force=False,
                keep_tmp=False
            )
            daemon_lib.unpack_check_args(self.args, args_json)

            self.__state = RemoteHandler.RunLock.RunStates.INITIALISED

        def get_persistent_token(self):
            return self.__persistent_hash

        def mark_running(self):
            self.__state = RemoteHandler.RunLock.RunStates.ANALYZERS_RUNNING

        def is_running(self):
            return self.__state == RemoteHandler.RunLock.\
                RunStates.ANALYZERS_RUNNING

        def mark_finished(self):
            if self.is_running():
                self.__state = RemoteHandler.RunLock.RunStates.DONE

    def pollCheckAvailability(self, run_name):
        """
        Tells the client whether the server is able to create a remote
        checking execution for the given run_name.
        """

        if len(self._running_checks) >= self.max_runs:
            LOG.debug('Refused because {0} >= {1}, server is loaded.'
                      .format(len(self._running_checks), self.max_runs))
            return False

        if run_name in self._running_checks:
            if self._running_checks[run_name].is_running():
                LOG.debug('Refused because the analysis is already running.')
                return False
            elif (datetime.now() - self._running_checks[run_name]
                    .lock_created).total_seconds() <= 300:
                LOG.debug('Refused because check inited in the past 5 min')
                return False

        return True

    def initConnection(self, run_name, local_invocation, check_args):
        """
        Sets up a remote checking's environment on the server based on a
        client's request.
        """

        # Check whether the given run is locked.
        if not self.pollCheckAvailability(run_name):
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

        if lock_object.args.jobs > self.max_jobs:
            LOG.info("{0}: client requested {1} job threads, but server "
                     "allows only {2}".format(run_name,
                                              lock_object.args.jobs,
                                              self.max_jobs))
            lock_object.args.jobs = self.max_jobs

        first_connection_for_run = not os.path.exists(
            lock_object.args.daemon_root)
        if first_connection_for_run:
            LOG.debug("Creating run folder at " + lock_object.args.daemon_root)
            os.mkdir(lock_object.args.daemon_root)

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
            local_path = os.path.join(run.args.daemon_root, client_path)

            # We also need to check if the proper directory structure exists
            if not os.path.exists(os.path.dirname(local_path)):
                os.makedirs(os.path.dirname(local_path))

            if fd.sha == "#REMOVE#":
                # Some left-over files from a previous check (such as suppress
                # or saargs) could be left over and the new client can command
                # the server to force remove these files.
                if os.path.exists(local_path):
                    os.remove(local_path)
            elif fd.content is not None:
                # For files that have content, we extract them
                # to the run-folder
                with open(local_path, 'w') as f:
                    f.write(fd.content)
            elif fd.content is None:
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
            run_object.mark_finished()
            del self._running_checks[run_object.run_name]

        run = self._get_run(token)
        if not run:
            LOG.error("Client commanded to start run #" + token + " but such"
                      " run does not exist!")
            raise shared.ttypes.RequestFailed(
                shared.ttypes.ErrorCode.GENERAL,
                str("No run with the given token."))

        daemon_lib.unpack_check_fileargs(run.args, run.args.daemon_root)
        run.mark_running()

        check_process = threading.Thread(
            target=daemon_lib.handle_checking,
            args=(
                run,
                self.context,
                lambda: _end_check_callback(self, run),
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

    def getCheckerList(self, args_json):
        """Retrieve the list of checkers available on the server."""
        args = json.loads(args_json)
        args = Namespace(
            analyzers=args['analyzers']
        )

        checkers = analyzer_types.get_checkers(
            generic_package_context.get_context(), args)

        checker_records = []
        for checker_name, enabled, description in checkers:
            checker_records.append(Checker(checker_name, enabled,
                                           description))

        return checker_records

    def __init__(self, context, session, max_runs, max_jobs_per_run):
        self._running_checks = {}
        self.context = context
        self.workspace = context.codechecker_workspace
        self.session = session
        self.max_runs = max_runs
        self.max_jobs = max_jobs_per_run


def run_server(args, db_uri, context, callback_event=None):
    host = args.host
    port = args.port
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
        handler = RemoteHandler(context, session, args.runs, args.jobs)

        processor = RemoteChecking.Processor(handler)
        transport = TSocket.TServerSocket(host=host, port=port)
        tfactory = TTransport.TBufferedTransportFactory()
        pfactory = TBinaryProtocol.TBinaryProtocolFactory()

        server = TServer.TThreadPoolServer(processor,
                                           transport,
                                           tfactory,
                                           pfactory,
                                           daemon=True)

        server.setNumThreads(args.runs)

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
