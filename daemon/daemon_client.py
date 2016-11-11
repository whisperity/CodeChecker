# -------------------------------------------------------------------------
#                     The CodeChecker Infrastructure
#   This file is distributed under the University of Illinois Open Source
#   License. See LICENSE.TXT for details.
# -------------------------------------------------------------------------

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

    @timeit
    def handshake(self):
        self.transport.open()
        result = self.client.Hello(20)
        result2 = self.client.Hello(25)
        self.transport.close()

        print("Result is", result, result2)

