# -------------------------------------------------------------------------
#                     The CodeChecker Infrastructure
#   This file is distributed under the University of Illinois Open Source
#   License. See LICENSE.TXT for details.
# -------------------------------------------------------------------------
"""
Instance manager handles the state keeping of running CodeChecker instances
for a particular user on the local machine.
"""

import argparse
import getpass
import json
import os
import portalocker
import psutil
import socket
import stat
import tempfile


def __getInstanceDescriptorPath():
    return os.path.join(tempfile.gettempdir(), ".codechecker_" +
                        getpass.getuser() + ".instances.json")


def __makeInstanceDescriptorFile():
    descriptor = __getInstanceDescriptorPath()
    if not os.path.exists(descriptor):
        with open(descriptor, 'w') as f:
            json.dump([], f)
        os.chmod(descriptor, stat.S_IRUSR | stat.S_IWUSR)


def __checkInstance(hostname, pid):
    """Check if the given process on the system is a valid, running CodeChecker
    for the current user."""

    # Instances running on a remote host with a filesystem shared with us can
    # not usually be checked (/proc is rarely shared across computers...),
    # so we consider them "alive" servers.
    if hostname != socket.gethostname():
        return True

    try:
        proc = psutil.Process(pid)

        return "CodeChecker.py" in proc.cmdline()[1] and \
               proc.username() == getpass.getuser()
    except psutil.NoSuchProcess:
        # If the process does not exist, it cannot be valid.
        return False


def __rewriteInstanceFile(append, remove):
    """This helper method reads the user's instance descriptor and manages it
    eliminating dead records, appending new ones and reserialising the file."""

    __makeInstanceDescriptorFile()

    with open(__getInstanceDescriptorPath(), 'r+') as f:
        portalocker.lock(f, portalocker.LOCK_EX)

        # After reading, check every instance if they are still valid and
        # make sure PID does not collide accidentally with the
        # to-be-registered instances, if any exists in the append list as it
        # would cause duplication.
        #
        # Also, we remove the records to the given PIDs, if any exists.
        append_pids = [i['pid'] for i in append]
        instances = [i for i in json.load(f)
                     if i['pid'] not in append_pids and
                     (i['hostname'] + ":" + str(i['pid'])) not in remove and
                     __checkInstance(i['hostname'], i['pid'])]

        instances = instances + append

        f.seek(0)
        f.truncate()
        json.dump(instances, f, indent=2)
        portalocker.unlock(f)


def register(kind, pid, workspace, port):
    """
    Adds the specified CodeChecker server instance to the user's instance
    descriptor.
    """

    __rewriteInstanceFile([{"kind": kind,
                            "pid": pid,
                            "hostname": socket.gethostname(),
                            "workspace": workspace,
                            "port": port}],
                          [])


def unregister(pid):
    """
    Removes the specified CodeChecker server instance from the user's instance
    descriptor.
    """

    __rewriteInstanceFile([], [socket.gethostname() + ":" + str(pid)])


def list(kind=None):
    """Returns the list of running servers for the current user."""

    # This method does NOT write the descriptor file.

    descriptor = __getInstanceDescriptorPath()
    instances = []
    if os.path.exists(descriptor):
        with open(descriptor, 'r') as f:
            portalocker.lock(f, portalocker.LOCK_SH)
            instances = [i for i in json.load(f) if __checkInstance(
                i['hostname'], i['pid']) and (
                (kind is not None and i['kind'] == kind)
                or kind is None)]
            portalocker.unlock(f)

    return instances


def add_instance_arguments(parser):
    """Add instance manager arguments to the given argparser."""

    parser.add_argument('-l', '--list',
                        action='store_true',
                        dest="list",
                        required=False,
                        default=argparse.SUPPRESS,
                        help='List servers started by your user.')

    parser.add_argument('-s', '--stop',
                        action='store_true',
                        dest="stop",
                        required=False,
                        default=argparse.SUPPRESS,
                        help='Stops the server associated with '
                             'the given view-port and workspace.')

    parser.add_argument('--stop-all',
                        action='store_true',
                        dest="stop_all",
                        required=False,
                        default=argparse.SUPPRESS,
                        help='Stops all of your running '
                             'CodeChecker instances.')
