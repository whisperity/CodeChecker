# -------------------------------------------------------------------------
#                     The CodeChecker Infrastructure
#   This file is distributed under the University of Illinois Open Source
#   License. See LICENSE.TXT for details.
# -------------------------------------------------------------------------
"""
Override entry point under CodeChecker to execute analysis on a single project.
"""

from __future__ import print_function
from __future__ import unicode_literals

import argparse
import json
import os
import subprocess
import sys

from codechecker_lib import generic_package_context
from codechecker_lib import host_check
from codechecker_lib.logger import LoggerFactory
from codechecker_lib import util
from daemon import lib as daemon_lib
from daemon.server import RemoteHandler

LOG = LoggerFactory.get_new_logger('SINGLE RUN ANALYSIS')


if __name__ == "__main__":
    print("ERROR: Please use 'CodeChecker override' to call this within env!")
    sys.exit(1)


def __main__(argv):
    if len(argv) == 1 and argv[0] == "docker-status":
        print("CODECHECKER_DAEMON_ANALYZER_READY")
        sys.exit(0)

    parser = argparse.ArgumentParser(
        prog='CodeChecker override daemon-run-analysis',
        description='''Run analysis on single CodeChecker project.'''
    )

    parser.add_argument('-w', '--workspace',
                        type=str,
                        dest='workspace',
                        required=True,
                        help='The CodeChecker workspace where the required '
                             'files are found.')

    parser.add_argument('-n', '--name',
                        type=str,
                        dest='run_name',
                        required=True,
                        help='The name of the run.')

    parser.add_argument('-c', '--config', '--args-json',
                        type=str,
                        dest='config',
                        required=True,
                        help='The analysis invocation data created by the '
                             'daemon server in JSON format.')

    parser.add_argument('--status',
                        action='store_true',
                        default=argparse.SUPPRESS,
                        help='Report if analyzer runner is okay or not.')

    args = parser.parse_args(argv)

    if not host_check.check_zlib():
        LOG.error("zlib error")
        sys.exit(1)

    try:
        workspace = args.workspace
    except AttributeError:
        # If no workspace value was set for some reason
        # in args set the default value.
        workspace = util.get_default_workspace()

    # WARNING
    # In case of SQLite args.dbaddress default value is used
    # for which the is_localhost should return true.
    if not os.path.exists(workspace):
        os.makedirs(workspace)

    context = generic_package_context.get_context()
    context.codechecker_workspace = workspace

    # Unpack analysis args
    with open(args.config, 'r') as cfgfile:
        args_json_str = cfgfile.read()
        args_json = json.loads(args_json_str)

    lock_object = RemoteHandler.RunLock(args.workspace,
                                        args.run_name,
                                        None,
                                        args_json_str)

    # Override args to those got from the daemon deploy server
    lock_object.args.__dict__ = args_json

    LOG.info("Analysis starting...")
    daemon_lib.handle_checking(lock_object,
                               context,
                               None,
                               LOG)
    LOG.info("Analysis over.")

    LOG.info("Entering shell...")
    subprocess.call(['/bin/bash'])
