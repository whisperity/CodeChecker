# -------------------------------------------------------------------------
#                     The CodeChecker Infrastructure
#   This file is distributed under the University of Illinois Open Source
#   License. See LICENSE.TXT for details.
# -------------------------------------------------------------------------

class RemoteClient(object):

    def __init__(self, jsonFile):
        print("DAEMON CLIENT INITIALISED")
        jsonFile.seek(0)

        print('\n'.join(jsonFile.readlines()))
        jsonFile.seek(0)

        pass
