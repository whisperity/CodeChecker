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
                        1: string run_name,
                        2: string check_args)
                        throws (1: shared.RequestFailed requestError),

    // sends a list of files to the server to notify the server about the state of files on the client machine
    // the return value indicates a list of files that the server reported as non-matching the local hash
    PathList sendFileData(
                          1: string   run_name
                          2: FileList files)

    // after the client is sure that it fulfilled the server's request on every needed file,
    // this method begins to run the check on the server
    void beginChecking(
                       1: string run_name,
                       2: bool   disconnect_immediately)
}
