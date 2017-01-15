# -------------------------------------------------------------------------
#                     The CodeChecker Infrastructure
#   This file is distributed under the University of Illinois Open Source
#   License. See LICENSE.TXT for details.
# -------------------------------------------------------------------------

import os
import socket
import sys

from thrift import Thrift
from thrift.server import TServer
from thrift.transport import TSocket, TTransport, THttpClient
from thrift.Thrift import TException, TApplicationException
from thrift.protocol import TBinaryProtocol, TJSONProtocol
from thrift.protocol.TProtocol import TProtocolException


from codechecker_lib import session_manager

from codechecker_gen.daemonServer import RemoteChecking
from codechecker_gen.daemonServer.ttypes import *
import shared


class RemoteClient(object):

    def __init__(self, host, port):
        self.__host = host
        self.__port = int(port)
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
    def initConnection(self, run_name, check_args):
        pass

    # ------------------------------------------------------------
    @ThriftClientCall
    def sendFileData(self, run_name, files):
        pass

    # ------------------------------------------------------------
    @ThriftClientCall
    def beginChecking(self):
        pass