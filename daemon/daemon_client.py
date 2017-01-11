# -------------------------------------------------------------------------
#                     The CodeChecker Infrastructure
#   This file is distributed under the University of Illinois Open Source
#   License. See LICENSE.TXT for details.
# -------------------------------------------------------------------------

import hashlib
import os
import socket
import sys
import subprocess

from thrift import Thrift
from thrift.server import TServer
from thrift.transport import TSocket, TTransport, THttpClient
from thrift.Thrift import TException, TApplicationException
from thrift.protocol import TBinaryProtocol, TJSONProtocol
from thrift.protocol.TProtocol import TProtocolException

from codechecker_lib import build_action
from codechecker_lib import session_manager

from codechecker_gen.daemonServer import RemoteChecking
from codechecker_gen.daemonServer.ttypes import *
import shared

class RemoteClient(object):

    def __init__(self, host, port):
        print("DAEMON CLIENT INITIALISED")
        #jsonFile.seek(0)

        #print('\n'.join(jsonFile.readlines()))
        #jsonFile.seek(0)

        print("\n\n\n")
        print host, port

        self.socket = TSocket.TSocket(host, port)
        self.transport = TTransport.TBufferedTransport(self.socket)
        self.protocol = TBinaryProtocol.TBinaryProtocol(self.transport)
        self.client = RemoteChecking.Client(self.protocol)

    # ------------------------------------------------------------
    def ThriftClientCall(function):
        # print type(function)
        funcName = function.__name__

        def wrapper(self, *args, **kwargs):
            # print('['+host+':'+str(port)+'] >>>>> ['+funcName+']')
            # before = datetime.datetime.now()
            self.transport.open()
            func = getattr(self.client, funcName)
            try:
                res = func(*args, **kwargs)

            except shared.ttypes.RequestFailed as reqfailure:
                if reqfailure.error_code == shared.ttypes.ErrorCode.DATABASE:
                    print('Database error on server')
                    print(str(reqfailure.message))
                if reqfailure.error_code == shared.ttypes.ErrorCode.PRIVILEGE:
                    print('Unauthorized access')
                    print(str(reqfailure.message))
                else:
                    print('Other error')
                    print(str(reqfailure))

                sys.exit(1)
            except TProtocolException:
                print("Connection failed to {0}:{1}"
                      .format(self.__host, self.__port))
                sys.exit(1)
            except socket.error as serr:
                errCause = os.strerror(serr.errno)
                print(errCause)
                print(str(serr))
                sys.exit(1)

            self.transport.close()
            return res

        return wrapper

    # ------------------------------------------------------------
    @ThriftClientCall
    def initConnection(self, run_name):
        pass

    # ------------------------------------------------------------
    @ThriftClientCall
    def sendFileData(self, run_name, files):
        pass

    # ============================================================
    def createInitialFileData(self, log_file, actions):
        """
        Transforms the given BuildAction list to generate a list
        of FileData that needs to be sent to the remote server.
        """

        # -----------------------------------
        # The log_file must ALWAYS be sent
        with open(log_file, 'r') as f:
            logStr = f.read()
            logSha = hashlib.sha1(logStr).hexdigest()

        logFD = FileData('compilation_commands.json', logSha, logStr)

        # -----------------------------------
        # We need to send ALL source files (if they are in the build.json,
        # the source files have been modified)

        sourceFiles = set()
        headerFiles = set()
        for action in actions:
            sourceFiles = sourceFiles.union(action.sources)

            dependencyCommand = action.original_command.split(' ')
            dependencyCommand[0] = dependencyCommand[0] \
                + ' -M -MQ"__dummy"'
            dependencyCommand = ' '.join(dependencyCommand)

            p = subprocess.Popen(dependencyCommand,
                                 stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 shell=True)
            output, err = p.communicate()
            rc = p.returncode

            if rc == 0:
                # Parse 'Makefile' syntax dependency file
                dependencies = output.replace('__dummy: ', '')\
                    .replace('\\', '')\
                    .replace('  ', '')\
                    .replace(' ', '\n')

                headerFiles = headerFiles.union(dependencies.split('\n'))

        sourceFDs = []
        for f in sourceFiles:
            with open(f, 'r') as sf:
                sourceStr = sf.read()
                sourceSha = hashlib.sha1(sourceStr).hexdigest()
                sourceFDs.append(FileData(f, sourceSha, sourceStr))

        # -----------------------------------
        # We also need to send the metadata (path, sha) for every included
        # header file. Headers don't get their content sent.
        headerFDs = []
        for f in headerFiles.difference(sourceFiles):
            if f == '':
                continue

            # (Ensure no source file dependency is marked as a header!)
            with open(f, 'r') as df:
                headSha = hashlib.sha1(df.read()).hexdigest()
                headerFDs.append(FileData(f, headSha, None))

        return [logFD] + sourceFDs + headerFDs

    # ============================================================
    def createFileDataFromPaths(self, path_list):
        """
        Reads the files specified by path_list and creates a FileData list
        by reading and hashing these files to send them to the server.
        """
        fds = []
        for f in path_list:
            with open(f, 'r') as sf:
                sourceStr = sf.read()
                sourceSha = hashlib.sha1(sourceStr).hexdigest()
                fds.append(FileData(f, sourceSha, sourceStr))

        return fds