// -------------------------------------------------------------------------
//                     The CodeChecker Infrastructure
//   This file is distributed under the University of Illinois Open Source
//   License. See LICENSE.TXT for details.
// -------------------------------------------------------------------------

include "shared.thrift"

namespace py daemonServer

//-----------------------------------------------------------------------------
struct FileData {
    1: string path,                 // the full path of the file
    2: string sha,                  // the digest of the file's contents
    3: optional string content      // the file verbatim
}
typedef list<FileData> FileList

typedef list<string> PathList

//-----------------------------------------------------------------------------
// The order of the functions indicates the order that must be maintained when
// calling into the server.
service RemoteChecking {

    // call the remote server and notify that we wish to execute remote checking
    bool initConnection(
                        1: string run_name)
                        throws (1: shared.RequestFailed requestError)

    i64 sendFileData(
                     1: FileList files)
                     throws (1: shared.RequestFailed requestError)

    PathList getNeededFiles()
                            throws (1: shared.RequestFailed requestError)

    bool doneCheck()
                   throws (1: shared.RequestFailed requestError)

    bool stopServer()
                    throws (1: shared.RequestFailed requestError)
}
