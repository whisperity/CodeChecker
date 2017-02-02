#!/usr/bin/env python
# -------------------------------------------------------------------------
#                     The CodeChecker Infrastructure
#   This file is distributed under the University of Illinois Open Source
#   License. See LICENSE.TXT for details.
# -------------------------------------------------------------------------
"""Make-Docker creates a Docker image from a CodeChecker repository."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib2

if __name__ != "__main__":
    raise ImportError("make-docker is not meant to be imported.")


def strip_comments(str):
    """Strips lines starting with # from the string."""
    result = []

    for line in str.split('\n'):
        if not line.startswith('#'):
            result.append(line)

    return '\n'.join(result)


def __handler_local(outfile):
    """Handles the template instantiation for the 'local' package."""

    # The local package is set up from the current CodeChecker
    # working directory.

    # Docker can NOT copy relative paths outside its build folder...
    # So we must package the current WD...
    docker_folder = os.path.abspath(os.getcwd())
    local_path = "codechecker.tar.gz"
    tar_path = os.path.join(docker_folder, local_path)

    os.chdir(os.path.abspath('..'))
    subprocess.call(['tar', 'cvfz',
                     tar_path,
                     '.'])
    os.chdir(docker_folder)

    with open('resources/from-local.Dockercommands.template') as template:
        str = template.read()
        str = strip_comments(str)
        str = str.replace("{LOCAL_PATH}", local_path)

        outfile.write(str)


def __handler_basic(outfile):
    """Handles the template instantiation for the 'basic' package."""

    with open('resources/from-basic.Dockercommands.template') as template:
        str = template.read()
        str = strip_comments(str)
        str = str.replace("{REPO_URL}",
                          "http://github.com/Ericsson/codechecker.git")

        outfile.write(str)


def __handle_stable(outfile):
    """Handles template instantiation for the 'stable' package."""

    api = "https://api.github.com/repos/Ericsson/codechecker/releases/latest"
    api_result = urllib2.urlopen(api)
    data = json.loads(api_result.read())

    if 'tarball_url' in data:
        remote_url = data['tarball_url']
        local_filename = "codechecker.tar.gz"
        extract_cmd = "tar xvfz codechecker.tar.gz"
    else:
        print("ERROR! Couldn't download release information from GitHub!")
        sys.exit(1)

    with open('resources/from-stable.Dockercommands.template') as template:
        str = template.read()
        str = strip_comments(str)
        str = str.replace("{CURL_COMMAND}",
                          "curl -L " + remote_url) \
                 .replace("{LOCAL_FILENAME}", local_filename) \
                 .replace("{EXTRACT_COMMAND}", extract_cmd) \
                 .replace("{EXPORTED_GLOB}", "Ericsson-codechecker-*")

        outfile.write(str)


def handle_package(pkg, outfile):
    if not pkg or not outfile:
        return

    # Special handlers for template files
    handlers = {
        'local': lambda of: __handler_local(of),
        'basic': lambda of: __handler_basic(of),
        'stable': lambda of: __handle_stable(of)
    }

    if pkg not in handlers:
        # If no special handler is present, it might be meant
        # to be bare-handled.

        if not os.path.exists("resources/" + pkg + ".Dockercommands"):
            print("ERROR! Requested to handle package '" + pkg + "' but no "
                  "handler assigned!")
            sys.exit(1)
        else:
            with open("resources/" + pkg + ".Dockercommands") as template:
                str = template.read()
                str = strip_comments(str)
                outfile.write(str)
    else:
        handlers[pkg](outfile)

# ----------------------------------------------------------------------------

arguments = argparse.ArgumentParser(
    prog="make-docker",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    description='''
This script builds a CodeChecker docker image on the local computer, using
the package(s) selected by the user.
''',
    epilog='''

Description about the different packages
----------------------------------------

++ Minimal (required for operation)

    local       Use the current CodeChecker code (where you are running this
                script) as source, do not check out anything from the internet.
                (In this case, it's: ''' + os.path.abspath('..') + ''')

    basic       The LATEST bare minimum CodeChecker infrastructure, checked
                out from GitHub

    stable      The stable package is a bare minimum CodeChecker infrastructure,
                downloaded from GitHub releases


++ Full (required for using every "stock" capability of CodeChecker)

    full        The bare minimum infrastructure does not support certain
                operations (such as PostgreSQL database usage). Selecting
                this package will create the Docker image with such support.


++ Extra (not required for normal operation but contain extra functionality)

    authentication        Enables privileged access (credentials mode) support.
'''
)

arguments.add_argument('-f', '--base', '--from',
                       type=str,
                       dest='base',
                       metavar='pkg',
                       default='basic',
                       choices=['local', 'basic', 'stable'],
                       required=False,
                       help='The base package (see below in Section "Minimal"'
                            ' for available choices) from which CodeChecker '
                            'source code must be retrieved.')

arguments.add_argument('-b', '--build',
                       type=str,
                       dest='packages',
                       metavar='pkg',
                       nargs='*',
                       default=[],
                       required=False,
                       help='The list of packages to compile into the build.'
                            ' See below for the available choices.')

arguments.add_argument('-i', '--install',
                       dest='install',
                       action='store_true',
                       required=False,
                       help='Create a Docker image that has a runnable '
                            'CodeChecker installed within. If not specified '
                            'the image will only contain the checked-out '
                            'source code and the built environment, but no '
                            'actual CodeChecker executable will be present.')

arguments.add_argument('-n', '--name',
                       type=str,
                       dest='name',
                       required=False,
                       default="codechecker",
                       help='The name of the built Docker image.')

args = arguments.parse_args()
print(args)

# --------------
# Step one: Build the selected packages.

with open('Dockerfile', 'w') as dockerfile:
    def handle(pkg):
        handle_package(pkg, dockerfile)

    if 'local' in args.packages or \
            'basic' in args.packages or \
            'stable' in args.packages:
        print("ERROR! Base image choice 'local' or 'basic' or 'stable' was "
              "specified as extra package.")
        print("       Disregarding...")

        args.packages = [pkg for pkg in args.packages
                         if pkg != 'local' and
                         pkg != 'basic' and
                         pkg != 'stable']

    # Initial OS
    print("Setting up 'base_OS'...")
    with open('resources/initial.Dockerfile') as initial:
        initial_docker = initial.read()
        dockerfile.write(strip_comments(initial_docker))

    # CodeChecker package source
    print("Setting up '" + args.base + "'...")
    handle(args.base)

    # Put minimal install script into the Dockerfile
    handle('basic-requirements')

    # Extra packages and related code
    for pkg in args.packages:
        print("Setting up '" + pkg + "'...")
        handle(pkg)

    # Install actions
    if args.install:
        print("Setting up 'install'...")
        handle('install')
    else:
        with open('resources/false-start.sh.template', 'r') as template:
            with open('false-start.sh', 'w') as output:
                str = template.read()
                str = str.replace('{INSTALL_NAME}', args.name)

                output.write(str)

        print("Setting up 'false-start'...")
        handle('false-start')

print("\nDone setting up Dockerfile.")
print("---------------- BEGIN DOCKERFILE ----------------")
with open('Dockerfile', 'r') as dockerfile:
    print(dockerfile.read())
print("----------------  END DOCKERFILE ----------------")

# --------------
# Step two: Call Docker.

print("\n\nBuilding package...")
subprocess.call(['docker', 'build', '--tag', args.name, '.'])

# --------------
# Step three: Run the built image.
print("\n\nRunning a dummy of the installed package...")
subprocess.call(['docker', 'run', '--rm', args.name])

# --------------
# Step four: Cleanup.
print("\n")
os.remove("Dockerfile")

if args.base == 'local' and os.path.exists("codechecker.tar.gz"):
    os.remove("codechecker.tar.gz")

if not args.install and os.path.exists("false-start.sh"):
    os.remove("false-start.sh")
