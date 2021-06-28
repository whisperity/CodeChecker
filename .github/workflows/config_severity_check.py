#!/usr/bin/env python3
# -------------------------------------------------------------------------
#
#  Part of the CodeChecker project, under the Apache License v2.0 with
#  LLVM Exceptions. See LICENSE for license information.
#  SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
# -------------------------------------------------------------------------
"""
Checks the config/checker_severity_map.json against the list of checkers
reported from the analyzers, and reports if there is a checker for which
severity isn't configured.
"""
import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(
        description="""
Check a list of checkers (usually the output of "CodeChecker checkers") and the
checker severity map for missing or stale entries.
""",
        epilog="""
The tool exits with 0 if the list of checkers is fully covered.
An exit status of 2 indicates bad invocation (via argparse).
An exit status of 4 indicates that checkers were removed from upstream but
still have a severity, and 8 indicates that there are checkers missing
severity settings.
An exit status of 12 (4 + 8) indicates both.
""",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("checker_name_list",
                        type=argparse.FileType('rt'),
                        help="The file that list of checkers available in the "
                             "analyzer. The file must exist!")
    parser.add_argument("checker_severity_map",
                        type=argparse.FileType('rt'),
                        help="The path of the "
                             "\"checker_severity_map.json\" file. The file "
                             "must exist!")

    existing = parser.add_argument_group(
        "filtering options for existing checks")
    existing.add_argument("--existing-ignore",
                          nargs='*',
                          default=list(),
                          help="The checker prefixes (such as \"alpha.\" or "
                               "\"debug.\") to ignore from the coverage check "
                               "when searching for removed checkers.")
    existing.add_argument("--existing-ignore-suffix",
                          nargs='*',
                          default=list(),
                          help="The checker suffixes (such as \"Sanitizer\""
                               "or \"-name\") to ignore from the coverage "
                               "check when searching for removed checkers.")

    new = parser.add_argument_group(
        "filtering options for new checks")
    new.add_argument("--new-ignore",
                     nargs='*',
                     default=list(),
                     help="The checker prefixes (such as \"alpha.\" or "
                          "\"debug.\") to ignore from the coverage check "
                          "when searching for unconfigured checkers.")
    new.add_argument("--new-ignore-suffix",
                     nargs='*',
                     default=list(),
                     help="The checker suffixes (such as \"Sanitizer\" or "
                          "\"-name\") to ignore from the coverage check "
                          "when searching for unconfigured checkers.")

    args = parser.parse_args()

    checkers = set(line.strip() for line in args.checker_name_list)
    ignored_checkers = set(entry for entry in checkers
                           if entry.startswith(tuple(args.new_ignore)) or
                           entry.endswith(tuple(args.new_ignore_suffix)))
    available_checkers = checkers - ignored_checkers

    severity_map = json.load(args.checker_severity_map)
    severity_map_ignored = set(entry for entry in severity_map.keys()
                               if entry.startswith(tuple(args.existing_ignore))
                               or entry.endswith(tuple(
                                   args.existing_ignore_suffix)))
    known_checkers = set(filter(lambda k: k not in severity_map_ignored,
                                severity_map.keys()))

    print("Checkers REMOVED from upstream, but configured with a severity:")
    any_removed = False
    for removed_checker in sorted(known_checkers - available_checkers):
        print(" - {0: <64} {1}".format(removed_checker,
                                       severity_map[removed_checker]))
        any_removed = True
    if not any_removed:
        print("    No results.")

    print()

    print("Checkers ADDED to upstream, without a severity setting:")
    any_new = False
    for missing_checker in sorted(available_checkers - known_checkers):
        print(" + {}".format(missing_checker))
        any_new = True
    if not any_new:
        print("    No results.")

    return_code = 0
    if any_removed:
        return_code += 4
    if any_new:
        return_code += 8
    return return_code


if __name__ == '__main__':
    sys.exit(main())
