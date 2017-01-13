# -------------------------------------------------------------------------
#                     The CodeChecker Infrastructure
#   This file is distributed under the University of Illinois Open Source
#   License. See LICENSE.TXT for details.
# -------------------------------------------------------------------------

import hashlib
import subprocess

from codechecker_lib import build_action

from codechecker_gen.daemonServer import RemoteChecking
from codechecker_gen.daemonServer.ttypes import *
import shared

# ============================================================
def createInitialFileData(log_file, actions):
    """
    Transforms the given BuildAction list to generate a list
    of FileData that needs to be sent to the remote server.
    """

    # -----------------------------------
    # The log_file must ALWAYS be sent
    with open(log_file, 'r') as f:
        log_str = f.read()
        log_sha = hashlib.sha1(log_str).hexdigest()

    log_fd = FileData('compilation_commands.json', log_sha, log_str)

    # -----------------------------------
    # We need to send ALL source files (if they are in the build.json,
    # the source files have been modified)

    source_files = set()
    header_files = set()
    for action in actions:
        source_files = source_files.union(action.sources)

        dependency_command = action.original_command.split(' ')
        dependency_command[0] = dependency_command[0] \
                                + ' -M -MQ"__dummy"'
        dependency_command = ' '.join(dependency_command)

        p = subprocess.Popen(dependency_command,
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

            header_files = header_files.union(dependencies.split('\n'))

    source_fds = []
    for f in source_files:
        with open(f, 'r') as sf:
            source_str = sf.read()
            source_sha = hashlib.sha1(source_str).hexdigest()
            source_fds.append(FileData(f, source_sha, source_str))

    # -----------------------------------
    # We also need to send the metadata (path, sha) for every included
    # header file. Headers don't get their content sent.
    header_fds = []
    for f in header_files.difference(source_files):
        if f == '':
            continue

        # (Ensure no source file dependency is marked as a header!)
        with open(f, 'r') as df:
            head_sha = hashlib.sha1(df.read()).hexdigest()
            header_fds.append(FileData(f, head_sha, None))

    return [log_fd] + source_fds + header_fds

# ============================================================
def createFileDataFromPaths(path_list):
    """
    Reads the files specified by path_list and creates a FileData list
    by reading and hashing these files to send them to the server.
    """
    fds = []
    for f in path_list:
        with open(f, 'r') as sf:
            source_str = sf.read()
            source_sha = hashlib.sha1(source_str).hexdigest()
            fds.append(FileData(f, source_sha, source_str))

    return fds
