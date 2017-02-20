#!/usr/bin/env python
"""Retrieve a CodeChecker release and package it into Debian format."""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import urllib2

parser = argparse.ArgumentParser(
    prog="get-release",
    description='''
This script creates a Debian package from a CodeChecker release or local
working directory.
''')

parser.add_argument('-f', '--from', '--base',
                    type=str,
                    dest='base',
                    default="stable",
                    choices=['stable', 'local'],
                    required=False,
                    help='Whether to download a release from GitHub or create'
                         'one from the local parent folder.')

parser.add_argument('-i', '--install',
                    action='store_true',
                    required=False,
                    help='Automatically execute the creation of the Debian '
                         'package.')

args = parser.parse_args()

release_data = {'version': "0.0",
                'name': "codechecker-0.0",
                'filename': "codechecker_0.0.orig.tar.gz"
                }


def github():
    # --- Retrieve the package ---

    api = "https://api.github.com/repos/Ericsson/codechecker/releases/latest"
    api_result = urllib2.urlopen(api)
    data = json.loads(api_result.read())

    if 'tarball_url' in data:
        remote_url = data['tarball_url']

        version = data['tag_name'].replace("v", "")

        release_data['version'] = version
        release_data['name'] = "codechecker-" + version
        release_data['filename'] = "codechecker_" + version + ".orig.tar.gz"
    else:
        print("ERROR! Couldn't download release information from GitHub!")
        sys.exit(1)

    print("Downloading release from GitHub...")
    subprocess.call(["curl", "-L", remote_url, "-o", release_data['filename']])
    print("Downloaded release " + version)
    subprocess.call(["tar", "xfz", release_data['filename']])
    print("Extracting release...")
    subprocess.call(["mv", glob.glob("Ericsson-codechecker-*")[0],
                     release_data['name']])

    print("Created from GitHub.")


def local():
    release_data['filename'] = release_data['name'] + ".orig.tar.gz"

    print("Packing local working directory...")
    subprocess.call(["tar", "cfz", release_data['filename'], "..",
                     "--exclude=../.git", "--exclude=../extra",
                     "--exclude=../build"])
    os.makedirs(release_data['name'])

    print("Extracting to proper folder structure...")
    subprocess.call(["tar", "xfz", release_data['filename'],
                     "-C", release_data['name']])

    print("Created from local.")


# Get a release
if args.base == "stable":
    github()
elif args.base == "local":
    local()

# --- Setup the Debian layout ---

if os.path.exists("debian"):
    shutil.rmtree("debian")

if not os.path.exists("debian"):
    # If the 'debian' folder in the current folder (NOT in the release, but in
    # the working folder) doesn't exist, create a dummy layout
    print("[ERROR] - debian/ folder does not exist, cannot restore previous "
          "changelog.")
    print("          The package created this way will NOT be accepted by "
          "the maintainers...")

    os.mkdir("debian")

    # Changelog file
    subprocess.call(["dch", "--create",
                     "--package", 'codechecker',
                     "--newversion", release_data['version'],
                     "--upstream",
                     "Created Debian package from '" + args.base +
                     "' upstream."])

    # We need to create a "non-native" package, ie. a Debian version
    # The policy manual dictates not to build a Debian native package
    # if the product is expected to be ran on non-Debian (or derived) systems.
    subprocess.call(["dch",
                     "--package", 'codechecker',
                     "--increment",
                     "_"])

    with open(os.path.join('debian', 'changelog'), 'r+') as dummy_changelog:
        line = dummy_changelog.readline()
        is_ubuntu = 'ubuntu' in line

        release_data['version'] = re.match(r'codechecker \(([\d\.\w-]+)\)',
                                           line).group(1)
        release_data['filename'] = "codechecker_" + release_data['version'] +\
                                   ".orig.tar.gz"

        # Remove the dummy line
        dummy_changelog.seek(0)
        text = dummy_changelog.read()
        dummy_changelog.seek(0)

        text = text.replace("  * _\n", "")
        dummy_changelog.truncate()
        dummy_changelog.write(text)

    # We also need to rename the release file
    orig = glob.glob("*.orig.tar.gz")[0]
    shutil.move(orig, release_data['filename'])

    # dch expects you to be ABOVE the debian folder, so we only 'cd' here
    os.chdir("debian")

    # Compatibility file must contain the number 9
    with open("compat", 'w') as compat:
        compat.write("9")

    # Control lists the "most" version-agnostic definition for the package
    with open("control", 'w') as control:
        def wr(msg=""):
            print >>control, msg

        wr("Source: codechecker")
        wr("Maintainer: The CodeChecker Team <codechecker@codecheck.er>")
        # The version of the Debian Standard on Ubuntu 16.04 LTS is 3.9.6
        # https://www.debian.org/doc/debian-policy/ (see dh_make)
        wr("Standards-Version: 3.9.6")
        if is_ubuntu:
            wr("Section: universe/devel")
        else:  # Debian
            wr("Section: devel")
        wr("Priority: optional")
        wr("Build-Depends: debhelper (>= 9),")
        wr("               curl (>= 7.35),")
        wr("               doxygen (>= 1.8),")
        wr("               python-dev (>= 2.7.6),")
        wr("               thrift-compiler (>= 0.9.1), "
           "thrift-compiler (<< 0.10)")
        wr()
        wr("Package: codechecker")
        wr("Architecture: any")
        wr("Depends: ${shlibs:Depends}, ${misc:Depends},")
        wr("         clang (>= 3.8),")
        wr("         clang-tidy (>= 3.8),")
        wr("         python (>= 2.7.6), python (<< 3.0),")
        wr("         python-pip (>= 1.5.4),")

        # Because most releases aren't exactly "0.8.2" but
        # rather "0.8.2-3ubuntu1", we need to constrain dependencies in range.
        wr("         python-alembic (>= 0.8.2), python-alembic (<< 0.9),")
        wr("         python-pg8000 (>= 1.10.2), python-pg8000 (<< 1.10.3),")

        # The Debian package for portalocker is versioned at 0.5.
        wr("         python-portalocker (>= 0.5), "
           "python-portalocker (<< 0.6),")
        wr("         python-sqlalchemy (>= 1.0.11), "
           "python-sqlalchemy (<< 1.0.12),")
        wr("         python-thrift (>= 0.9.1), python-thrift (<< 0.10)")
        wr("Suggests: postgresql (>= 9.3.5)")
        wr("Description: Lightweight static analysis executor and result "
           "viewer")
        wr(" CodeChecker is an infrastructure built on Clang Static")
        wr(" Analyzer to aid developers in analysing their code. It replaces")
        wr(" scan-build in a Linux or macOS environment.")
        wr(" .")
        wr(" CodeChecker analyses your C/C++ projects and stores the results")
        wr(" in a database, which is viewable from a command-line and a")
        wr(" web-browser based result viewer, both of which is included in")
        wr(" this package.")
        if is_ubuntu:
            wr("Bugs: http://github.com/Ericsson/codechecker/issues")

    # TODO: Copyright?
    with open("copyright", 'w') as copyright:
        pass

    # Rules state how you want the package to be built from the source
    with open("rules", 'w') as rules:
        def wr(msg=""):
            print >>rules, msg

        wr("#!/usr/bin/make -f")
        wr("%:")
        wr("\tdh $@")
        wr()
        wr("override_dh_auto_test: ;")
        wr()
        wr("override_dh_auto_install:")
        wr("\tcp -R build/CodeChecker $$(pwd)/debian/codechecker/opt")
        wr()
        wr("override_dh_installman:")
        wr("\tinstall -m 0644 $$(pwd)/../CodeChecker.1 "
           "$$(pwd)/debian/codechecker/usr/share/man/man1")
    os.chmod("rules", 0755)

    # The packaging install is to happen at debian/install/opt/CodeChecker,
    # but it does not exist. We need to tell the packager to create it!
    with open("codechecker.dirs", 'w') as dirs:
        def wr(msg=""):
            print >>dirs, msg

        wr("opt/CodeChecker")
        wr("usr/bin")
        wr("usr/share/man/man1")

    # Set up the list of symbolic links we need to create
    with open("codechecker.links", 'w') as links:
        def wr(msg=""):
            print >>links, msg

        wr("/opt/CodeChecker/bin/CodeChecker\t/usr/bin/CodeChecker")

    # The format of the package is magic
    os.mkdir("source")
    with open("source/format", 'w') as formatfile:
        formatfile.write("3.0 (quilt)\n")

    print("debian/ structure set up.")
    os.chdir("..")


sourcefolder_debian = os.path.join(release_data['name'], "debian")
if os.path.exists(sourcefolder_debian):
    print("Clearing left-behind release folder in the sourcedir...")
    shutil.rmtree(sourcefolder_debian)

shutil.copytree("debian", sourcefolder_debian)
print("Debian configuration folder copied.")

if args.install:
    print("Executing Debian package creation...")
    os.chdir(release_data['name'])
    subprocess.call(["debuild", "-us", "-uc"])
