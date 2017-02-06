// -------------------------------------------------------------------------
//                     The CodeChecker Infrastructure
//   This file is distributed under the University of Illinois Open Source
//   License. See LICENSE.TXT for details.
// -------------------------------------------------------------------------

include "shared.thrift"

namespace py daemonServer

typedef list<string> PathList

//-----------------------------------------------------------------------------
struct Acknowledgement {
    1: string token,                // the remote check connection's unique token
    2: bool   is_initial            // true if the initated connection is initial - the server has no data
                                    // stored for run the check has been initiated for
}

//-----------------------------------------------------------------------------
struct FileData {
    1: string path,                 // the full path of the file
    2: string sha,                  // the digest of the file's contents
    3: optional string content      // the file verbatim
}
typedef list<FileData> FileList

//-----------------------------------------------------------------------------
struct Checker {
    1: string checker_name,
    2: bool   enabled,
    3: string description
}
typedef list<Checker> CheckerList


//-----------------------------------------------------------------------------
// The order of the functions indicates the order that must be maintained when
// calling into the server.
service RemoteChecking {

    // queries the server whether it is able to create a remote checking instance for the given run_name
    // (this is False if, e.g. the server is already loaded with runs or the given run_name is locked)
    bool pollCheckAvailability(
                               1: string run_name),

    // call the remote server and notify that we wish to execute remote checking
    Acknowledgement initConnection(
                                   1: string run_name,
                                   2: string local_invocation,
                                   3: string check_args)
                                   throws (1: shared.RequestFailed requestError),

    // sends a list of files to the server to notify the server about the state of files on the client machine
    // the return value indicates a list of files that the server reported as non-matching the local hash
    PathList sendFileData(
                          1: string   token
                          2: FileList files)
                          throws (1: shared.RequestFailed requestError),

    // after the client is sure that it fulfilled the server's request on every needed file,
    // this method begins to run the check on the server
    void beginChecking(
                       1: string token)
                       throws (1: shared.RequestFailed requestError),

    // retrieve the analysis results for the run with the given token
    FileList fetchPlists(
                         1: string token)
                         throws (1: shared.RequestFailed requestError),

    // removes the given run from the list of running checks on the server
    void expire(
                1: string token)
                throws (1: shared.RequestFailed requestError),

    // get the list of checkers available on the daemon server
    CheckerList getCheckerList(
                               1: string args_json)

}
