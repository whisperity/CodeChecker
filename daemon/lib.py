# -------------------------------------------------------------------------
#                     The CodeChecker Infrastructure
#   This file is distributed under the University of Illinois Open Source
#   License. See LICENSE.TXT for details.
# -------------------------------------------------------------------------

import hashlib
import json
import logging
import os
import sys

from codechecker_lib import analyzer
from codechecker_lib import build_manager
from codechecker_lib import log_parser
from codechecker_lib import skiplist_handler
from codechecker_lib import util

from codechecker_gen.daemonServer.ttypes import *
import shared


def _create_dependencies(action):
    """
    Transforms the given original build 'command' to a command that, when
    executed, is able to generate a dependency list.
    """
    if 'CC_LOGGER_GCC_LIKE' not in os.environ:
        os.environ['CC_LOGGER_GCC_LIKE'] = 'gcc:g++:clang:clang++:cc:c++'
    command = action.original_command.split(' ')

    if command[0] in os.environ['CC_LOGGER_GCC_LIKE'].split(':'):
        # gcc and clang can generate makefile-style dependency list
        command[0] += ' -E -M -MQ"__dummy"'

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


def create_initial_file_data(args, actions, include_contents_for_all):
    """
    Transforms the given BuildAction list to generate a list
    of FileData that needs to be sent to the remote server.
    """

    # -----------------------------------
    # There are some files that must always be sent.
    always_fds = []
    for key in FILES_TO_ALWAYS_UPLOAD:
        if key in args.__dict__:
            with open(getattr(args, key), 'r') as f:
                always_str = f.read()
                always_sha = hashlib.sha1(always_str).hexdigest()

                always_fds.append(FileData(FILES_TO_ALWAYS_UPLOAD[key],
                                           always_sha, always_str))
        else:
            # If the file is not given or does not exist
            always_fds.append(FileData(FILES_TO_ALWAYS_UPLOAD[key],
                                       "#REMOVE#", None))

    # -----------------------------------
    # We need to send ALL source files (if they are in the build.json,
    # the source files have been modified)

    source_files = set()
    header_files = set()
    for action in actions:
        source_files = source_files.union(action.sources)
        header_files = header_files.union(_create_dependencies(action))

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
            head_str = df.read()
            head_sha = hashlib.sha1(head_str).hexdigest()
            header_fds.append(FileData(f,
                                       head_sha,
                                       head_str if include_contents_for_all
                                       else None))

    return always_fds + source_fds + header_fds


def create_file_data_from_paths(path_list):
    """
    Reads the files specified by path_list and creates a FileData list
    by reading and hashing these files to send them to the server.
    """

    fds = []
    for f in path_list:
        with open(f, 'r') as sf:
            file_str = sf.read()
            file_sha = hashlib.sha1(file_str).hexdigest()
            fds.append(FileData(f, file_sha, file_str))

    return fds


def _fix_compile_json(json, file_root):
    """
    Fixup the compile_commands.json file to ensure that source and include
    files are loaded from the "virtual root" of the remote run.
    """

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


# The argument keys of 'CodeChecker check' which points to files existing
# on the client's computer and must be transferred over the wire for remote
# checking to properly take place.
#
# This dict associates configuration keys with remote filenames.
FILES_TO_ALWAYS_UPLOAD = {'logfile': 'compilation_commands.json',
                          'clangsa_args_cfg_file': 'sa-args',
                          'tidy_args_cfg_file': 'tidy-args',
                          'suppress': 'suppress',
                          'skipfile': 'skipfile'
                          }

# The argument keys of 'CodeChecker check' which must be transferred over
# the wire for remote checking to properly take place.
#
# Keys specified in FILES_TO_ALWAYS_UPLOAD MUST NOT be specified here.
CHECK_ARGS_TO_COMMUNICATE = ['analyzers',
                             'ordered_checkers',
                             'jobs'
                             ]


def pack_check_args(args):
    """
    Filters the original (clientside) check invocation arguments and packs
    them into a json string to send to the daemon.
    """

    data = {}
    for key in CHECK_ARGS_TO_COMMUNICATE:
        if key in args.__dict__:
            data[key] = getattr(args, key)

    return json.dumps(data)


def unpack_check_args(args, args_json):
    """
    Unpack the received client args json into a Namespace object
    usable by the rest of CodeChecker.
    """

    data = json.loads(args_json)
    if type(data) is not dict:
        raise ValueError("The checking configuration sent over the wire "
                         "must be a JSON-encoded dictionary.")

    for key in data.keys():
        if key in CHECK_ARGS_TO_COMMUNICATE and key not in args.__dict__:
            setattr(args, key, data[key])


def unpack_check_fileargs(args, file_root):
    """
    Unpacks the FILES_TO_ALWAYS_UPLOAD keys into the given args Namespace
    if the specified files exists in the file_root.
    """

    for argvar, filename in FILES_TO_ALWAYS_UPLOAD.iteritems():
        if os.path.exists(os.path.join(file_root, filename)) and \
                argvar not in args.__dict__:
            setattr(args, argvar, os.path.join(file_root, filename))


def handle_checking(run, context, callback=None, LOG=None):
    """"
    Actually execute the analysis on a project.
    """

    # Before the log-file parsing can continue, we must first "hackfix" the
    # log file so that it uses the paths under daemon_root, not the paths on
    # the client's computer.
    fixed_file = os.path.join(os.path.dirname(run.args.logfile),
                              os.path.basename(run.args.logfile).
                              replace('.json', '.fixed.json'))

    LOG.debug("Saving fixed LOG file to " + fixed_file)
    with open(fixed_file, 'w') as outf:
        with open(run.args.logfile, 'r+') as inf:
            commands = json.load(inf)
            commands = _fix_compile_json(commands, run.args.daemon_root)
            json.dump(commands, outf,
                      indent=(4 if LOG.level == logging.DEBUG
                              or LOG.level == logging.DEBUG_ANALYZER
                              else None))

    run.args.logfile = fixed_file

    # We need to do the same with the skip-file as the paths in that file
    # are also non-applicable to the daemon's folder layout.
    if 'skipfile' in run.args:
        fixed_skip = os.path.join(os.path.dirname(run.args.skipfile),
                                  os.path.basename(run.args.skipfile) +
                                  '.fixed')
        LOG.debug("Saving fixed SKIP file to " + fixed_file)

        skiplist_handler.preface_skip_file(run.args.skipfile,
                                           run.args.daemon_root,
                                           fixed_skip)

        run.args.skipfile = fixed_skip

    log_file, _ = build_manager.check_log_file(run.args, context)
    if not log_file:
        LOG.error("Failed to generate compilation command file: " +
                  log_file)
        sys.exit(1)

    actions = log_parser.parse_log(log_file,
                                   run.args.add_compiler_defaults)

    try:
        plist_path = os.path.join(run.args.daemon_root, '..', 'results')
        if not os.path.exists(plist_path):
            os.mkdir(plist_path)

        analyzer.run_quick_check(run.args, context, actions,
                                 export_plist_path=plist_path)
    finally:
        run.mark_finished()

    LOG.info("Analysis done!")

    if callback:
        callback()
