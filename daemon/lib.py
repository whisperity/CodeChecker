# -------------------------------------------------------------------------
#                     The CodeChecker Infrastructure
#   This file is distributed under the University of Illinois Open Source
#   License. See LICENSE.TXT for details.
# -------------------------------------------------------------------------

import hashlib
import json
import os
import sys

from codechecker_lib import analyzer
from codechecker_lib import build_action
from codechecker_lib import build_manager
from codechecker_lib import log_parser
from codechecker_lib import util

from codechecker_gen.daemonServer import RemoteChecking
from codechecker_gen.daemonServer.ttypes import *
import shared


def __create_dependencies(action):
    """
    Transforms the given original build 'command' to a command that, when
    executed, is able to generate a dependency list.
    """
    if 'CC_LOGGER_GCC_LIKE' not in os.environ:
        os.environ['CC_LOGGER_GCC_LIKE'] = 'gcc:g++:clang:clang++:cc:c++'
    command = action.original_command.split(' ')

    if command[0] in os.environ['CC_LOGGER_GCC_LIKE'].split(':'):
        # gcc and clang can generate makefile-style dependency list
        command[0] = command[0] + ' -E -M -MQ"__dummy"'

        try:
            option_index = command.index('-o')
        except ValueError:
            # Indicates that '-o' is not in the command list

            try:
                option_index = command.index('--output')
            except ValueError:
                # Indicates that '--output' isn't either..
                option_index = None

        if option_index:
            # If an output file is set, the dependency is not written to the
            # standard output but rather into the given file.
            # We need to first eliminate the output from the command
            command = command[0:option_index] + command[option_index+2:]

        output, rc = util.call_command(' '.join(command),
                                       env=os.environ, shell=True)
        if rc == 0:
            # Parse 'Makefile' syntax dependency output
            dependencies = output.replace('__dummy: ', '') \
                .replace('\\', '') \
                .replace('  ', '') \
                .replace(' ', '\n')

            return [dep for dep in dependencies.split('\n') if dep != ""]
        else:
            raise Exception(
                "Failed to generate dependency list for " +
                command + "\n\nThe original output was: " + output)
    else:
        raise Exception("Cannot generate dependency list for build command " +
                        command)


def create_initial_file_data(log_file, actions):
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
        header_files = header_files.union(__create_dependencies(action))

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


def create_file_data_from_paths(path_list):
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


def __fix_compile_json(json, file_root):
    if 'CC_LOGGER_GCC_LIKE' not in os.environ:
        os.environ['CC_LOGGER_GCC_LIKE'] = 'gcc:g++:clang:clang++:cc:c++'

    for command in json:
        new_directory = os.path.join(file_root,
                                    command['directory'].lstrip('/'))

        # Fix source and target file paths in the command itself
        command['command'] = command['command'].replace(command['directory'],
                                                        new_directory)

        command['file'] = os.path.join(file_root,
                                       command['file'].lstrip('/'))
        command['directory'] = new_directory

        # Fix include paths
        if command['command'].split(' ')[0]\
                in os.environ['CC_LOGGER_GCC_LIKE']:

            command['command'] = command['command'].replace(
                " -Isystem/", " -Isystem" + file_root + "/")
            command['command'] = command['command'].replace(
                " -I/", " -I" + file_root + "/")
        else:
            raise Exception(
                "Cannot fix compilation action for build command " +
                command + " --- used executable unknown")

    return json


class __DummyArgs(object):
    """
    Mock to simulate a dot-accessible args object.
    (via http://stackoverflow.com/a/652417/1428773)
    """

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


CHECK_ARGS_TO_COMMUNICATE = ['local_invocation',
                             'analyzers',
                             'saargs',
                             'tidyargs',
                             'ordered_checkers'
                             ]


def pack_check_args(args):
    """
    Filters the original (clientside) check invocation arguments and packs them into a json string to send to
    the daemon.
    """

    data = {}
    for key in CHECK_ARGS_TO_COMMUNICATE:
        if key in args.__dict__:
            data[key] = getattr(args, key)

    return json.dumps(data)


def unpack_check_args(args, args_json):
    """
    Unpack the received client args json into a 'Namespace'-like dummy object usable by the rest of CodeChecker.
    """

    data = json.loads(args_json)
    if type(data) is not dict:
        raise ValueError("The checking configuration sent over the wire must be a JSON-encoded dictionary.")

    for key in data.keys():
        if key in CHECK_ARGS_TO_COMMUNICATE and key not in args.__dict__:
            args.__dict__[key] = data[key]



def handle_checking(run_name, file_root, session_data, context, callback=None, LOG=None):
    args = __DummyArgs(
        # Mandatory field for indicating that the checking does NOT take place on a local machine!
        is_remote_checking=True,

        # Field overrides due to remote context,
        name=run_name,
        logfile=os.path.join(file_root, "compilation_commands.json"),

        # TODO: Review these overrides!
        add_compiler_defaults=False,
        jobs=1,
        force=False,
        keep_tmp=False
    )

    unpack_check_args(args, session_data['argsjson'])

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
            json.dump(commands, outf, indent=4)

    args.logfile = fixed_file

    log_file = build_manager.check_log_file(args, context)
    if not log_file:
        LOG.error("Failed to generate compilation command file: " +
                  log_file)
        sys.exit(1)

    actions = log_parser.parse_log(log_file,
                                   args.add_compiler_defaults)

    #for action in actions:
    #    LOG.info("--------------------------------------------------------")
    #    LOG.info(action.__str__())

    analyzer.run_check(args, actions, context)

    LOG.info("Analysis done!")

    if callback:
        callback()
