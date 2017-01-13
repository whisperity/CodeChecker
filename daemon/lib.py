# -------------------------------------------------------------------------
#                     The CodeChecker Infrastructure
#   This file is distributed under the University of Illinois Open Source
#   License. See LICENSE.TXT for details.
# -------------------------------------------------------------------------

import hashlib
import json
import os
import sys

from codechecker_lib import build_action
from codechecker_lib import build_manager
from codechecker_lib import log_parser
from codechecker_lib import util

from codechecker_gen.daemonServer import RemoteChecking
from codechecker_gen.daemonServer.ttypes import *
import shared

def __createDependencies(command):
    """
    Transforms the given original build 'command' to a command that, when
    executed, is able to generate a dependency list.
    """
    if 'CC_LOGGER_GCC_LIKE' not in os.environ:
        os.environ['CC_LOGGER_GCC_LIKE'] = 'gcc:g++:clang:clang++:cc:c++'
    command = command.split(' ')

    if command[0] in os.environ['CC_LOGGER_GCC_LIKE'].split(':'):
        # gcc and clang can generate makefile-style dependency list
        command[0] = command[0] + ' -M -MQ"__dummy"'

        output, rc = util.call_command(' '.join(command),
                                       env=os.environ, shell=True)
        if rc == 0:
            # Parse 'Makefile' syntax dependency file
            dependencies = output.replace('__dummy: ', '') \
                .replace('\\', '') \
                .replace('  ', '') \
                .replace(' ', '\n')

            return dependencies.split('\n')
        else:
            raise Exception(
                "Failed to generate dependency list for " +
                command + "\n\nThe original output was: " + output)
    else:
        raise Exception("Cannot generate dependency list for build command " +
                        command)


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
        header_files = header_files.union(
            __createDependencies(action.original_command))



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


class __DummyArgs(object):
    """
    Mock to simulate a dot-accessible args object.
    (via http://stackoverflow.com/a/652417/1428773)
    """
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def __fix_compile_json(json, file_root):
    if 'CC_LOGGER_GCC_LIKE' not in os.environ:
        os.environ['CC_LOGGER_GCC_LIKE'] = 'gcc:g++:clang:clang++:cc:c++'

    for command in json:
        command['file'] = os.path.join(file_root,
                                       command['file'].lstrip('/'))
        command['directory'] = os.path.join(file_root,
                                            command['directory'].lstrip('/'))

        if command['command'].split(' ')[0]\
                in os.environ['CC_LOGGER_GCC_LIKE']:
            command['command'] = command['command'].replace(
                " -I", " -nostdinc --nostdinc++ -I", 1)
            command['command'] = command['command'].replace(
                " -I", " -I" + file_root)
        else:
            raise Exception(
                "Cannot fix compilation action for build command " +
                command + " --- used executable unknown")

    return json


# ============================================================
def handleChecking(run_name, file_root, context, LOG):
    args = __DummyArgs(
        logfile=os.path.join(file_root, "compilation_commands.json"),

        # TODO: This is an advanced option, support for this later!
        add_compiler_defaults=False
    )

    # Before the log-file parsing can continue, we must first "hackfix" the log
    # file so that it uses the paths under file_root, not the paths on the
    # client's computer.
    #
    # TODO: HACK: This is a HACKFIX.
    # TODO:       Later please implement a much more useful support for this!
    fixed_file = os.path.join(os.path.dirname(args.logfile),
                              os.path.basename(args.logfile).
                                replace('.json', '.fixed.json'))

    LOG.debug("Saving fixed log file to " + fixed_file)
    with open(fixed_file, 'w') as outf:
        with open(args.logfile, 'r') as inf:
            commands = json.load(inf)
            commands = __fix_compile_json(commands, file_root)
            json.dump(commands, outf)

    args.logfile = fixed_file

    log_file = build_manager.check_log_file(args, context)
    if not log_file:
        LOG.error("Failed to generate compilation command file: " +
                  log_file)
        sys.exit(1)

    actions = log_parser.parse_log(log_file,
                                   args.add_compiler_defaults)

    for action in actions:
        print(action.__str__())

    #analyzer.run_check(args, actions, context)