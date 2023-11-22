# -------------------------------------------------------------------------
#
#  Part of the CodeChecker project, under the Apache License v2.0 with
#  LLVM Exceptions. See LICENSE for license information.
#  SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
# -------------------------------------------------------------------------

"""
Test the parsing of the plist generated by multiple clang versions.

With the newer clang releases more information is available in the plist files.

* Before Clang v3.7:
  - Not supported

* Clang v3.7:
  - Checker name is available in the plist
  - Report hash is not avilable (generated based on the report path elements
    see report handling and plist parsing modules for more details

* After Clang v3.8:
  - Checker name is available
  - Report hash is available

"""


import os
import unittest

from copy import deepcopy

from codechecker_report_converter.report import BugPathEvent, \
    BugPathPosition, File, Range, Report, report_file
from codechecker_report_converter.report.reports import \
    get_mentioned_original_files


gen_plist_dir_path = os.path.join(
    os.path.dirname(__file__), 'plist_test_files', 'gen_plist')

SRC_FILES = [
    File(os.path.join(gen_plist_dir_path, 'test.cpp')),
    File(os.path.join(gen_plist_dir_path, 'test.h'))]


# Base skeletons for reports where the checker name is already available.
div_zero_skel = Report(
    SRC_FILES[1], 7, 14, 'Division by zero', 'core.DivideZero',
    report_hash='79e31a6ba028f0b7d9779faf4a6cb9cf',
    bug_path_events=[
        BugPathEvent(
            "'base' initialized to 0",
            SRC_FILES[0], 20, 5,
            Range(20, 5, 20, 12)),
        BugPathEvent(
            "Passing the value 0 via 1st parameter 'base'",
            SRC_FILES[0], 21, 15,
            Range(21, 15, 21, 18)),
        BugPathEvent(
            "Calling 'test_func'",
            SRC_FILES[0], 21, 5,
            Range(21, 5, 21, 19)),
        BugPathEvent(
            "Entered call from 'main'",
            SRC_FILES[0], 6, 1,
            Range(6, 1, 6, 1)),
        BugPathEvent(
            "Passing the value 0 via 1st parameter 'num'",
            SRC_FILES[0], 8, 22,
            Range(8, 22, 8, 25)),
        BugPathEvent(
            "Calling 'generate_id'",
            SRC_FILES[0], 8, 10,
            Range(8, 10, 8, 26)),
        BugPathEvent(
            "Entered call from 'test_func'",
            SRC_FILES[1], 6, 1,
            Range(6, 1, 6, 1)),
        BugPathEvent(
            "Division by zero",
            SRC_FILES[1], 7, 14,
            Range(7, 12, 7, 17))
    ],
    bug_path_positions=[
        BugPathPosition(SRC_FILES[0], Range(19, 5, 19, 7)),
        BugPathPosition(SRC_FILES[0], Range(20, 5, 20, 7)),
        BugPathPosition(SRC_FILES[0], Range(21, 5, 21, 13)),
        BugPathPosition(SRC_FILES[0], Range(6, 1, 6, 4)),
        BugPathPosition(SRC_FILES[0], Range(7, 5, 7, 7)),
        BugPathPosition(SRC_FILES[0], Range(8, 5, 8, 6)),
        BugPathPosition(SRC_FILES[0], Range(8, 22, 8, 25)),
        BugPathPosition(SRC_FILES[0], Range(8, 10, 8, 20)),
        BugPathPosition(SRC_FILES[1], Range(6, 1, 6, 3)),
        BugPathPosition(SRC_FILES[1], Range(7, 14, 7, 14))
    ],
    notes=[],
    macro_expansions=[])


stack_addr_skel_msg = \
    "Address of stack memory associated with local variable " \
    "'str' is still referred to by the global variable 'p' " \
    "upon returning to the caller.  " \
    "This will be a dangling reference"

stack_addr_skel = Report(
    SRC_FILES[0], 16, 1,
    stack_addr_skel_msg,
    'core.StackAddressEscape',
    report_hash='f7b5072d428e890f2d309217f3ead16f',
    bug_path_events=[
        BugPathEvent(
            stack_addr_skel_msg, SRC_FILES[0], 16, 1, Range(14, 3, 14, 29))
    ],
    bug_path_positions=[
        BugPathPosition(SRC_FILES[0], Range(14, 3, 14, 6)),
        BugPathPosition(SRC_FILES[0], Range(15, 3, 15, 3)),
        BugPathPosition(SRC_FILES[0], Range(16, 1, 16, 1))
    ],
    notes=[],
    macro_expansions=[])


class PlistParserTestCase(unittest.TestCase):
    """Test the parsing of the plist generated by multiple clang versions."""

    @classmethod
    def setup_class(cls):
        """Initialize test source file."""
        # Bugs found by these checkers in the test source files.
        cls.__found_checker_names = [
            'core.DivideZero',
            'core.StackAddressEscape',
            'deadcode.DeadStores']

        # Already generated plist files for the tests.
        cls.__this_dir = os.path.dirname(__file__)
        cls.__plist_test_files = os.path.join(
            cls.__this_dir, 'plist_test_files')

    def test_empty_file(self):
        """Plist file is empty."""
        empty_plist = os.path.join(self.__plist_test_files, 'empty_file')
        reports = report_file.get_reports(empty_plist)
        self.assertEqual(reports, [])

    def test_no_bug_file(self):
        """There was no bug in the checked file."""
        no_bug_plist = os.path.join(
            self.__plist_test_files, 'clang-3.7-noerror.plist')
        reports = report_file.get_reports(no_bug_plist)
        self.assertEqual(reports, [])

    def test_clang37_plist(self):
        """
        Check plist generated by clang 3.7 checker name should be in the plist
        file generating a report hash is still needed.
        """
        clang37_plist = os.path.join(
            self.__plist_test_files, 'clang-3.7.plist')
        reports = report_file.get_reports(clang37_plist)
        self.assertEqual(len(reports), 3)

        files = get_mentioned_original_files(reports)
        self.assertEqual(files, set(SRC_FILES))

        for report in reports:
            # Checker name should be available for all the reports.
            self.assertNotEqual(report.checker_name, 'NOT FOUND')

            if report.checker_name == 'core.DivideZero':
                skel = deepcopy(div_zero_skel)
                skel.report_hash = '51bd152830c2599e98c89cfc78890d0b'

                self.assertEqual(report, skel)

            if report.checker_name == 'core.StackAddressEscape':
                # core.StackAddressEscape hash is changed because the checker
                # name is available and it is included in the hash.
                skel = deepcopy(stack_addr_skel)
                skel.report_hash = '3439d5e09aeb5b69a835a6f0a307dfb6'

                self.assertEqual(report, skel)

    def test_clang38_trunk_plist(self):
        """
        Check plist generated by clang 3.8 trunk checker name and report hash
        should be in the plist file.
        """
        clang38_plist = os.path.join(
            self.__plist_test_files, 'clang-3.8-trunk.plist')
        reports = report_file.get_reports(clang38_plist)
        self.assertEqual(len(reports), 3)

        files = get_mentioned_original_files(reports)
        self.assertEqual(files, set(SRC_FILES))

        for report in reports:
            self.assertIn(report.checker_name, self.__found_checker_names)

            if report.checker_name == 'core.DivideZero':
                # Test data is still valid for this version.
                self.assertEqual(report, div_zero_skel)

            if report.checker_name == 'core.StackAddressEscape':
                self.assertEqual(report, stack_addr_skel)

    def test_clang40_plist(self):
        """
        Check plist generated by clang 4.0 checker name and report hash
        should be in the plist file.
        """
        clang40_plist = os.path.join(
            self.__plist_test_files, 'clang-4.0.plist')
        reports = report_file.get_reports(clang40_plist)
        self.assertEqual(len(reports), 3)

        files = get_mentioned_original_files(reports)
        self.assertEqual(files, set(SRC_FILES))

        for report in reports:
            # Checker name should be in the plist file.
            self.assertNotEqual(report.checker_name, 'NOT FOUND')
            self.assertIn(report.checker_name, self.__found_checker_names)

            if report.checker_name == 'core.DivideZero':
                # Test data is still valid for this version.
                self.assertEqual(report, div_zero_skel)

            if report.checker_name == 'core.StackAddressEscape':
                skel = deepcopy(stack_addr_skel)
                skel.report_hash = 'a6d3464f8aab9eb31a8ea7e167e84322'

                self.assertEqual(report, skel)

    def test_clang50_trunk_plist(self):
        """
        Check plist generated by clang 5.0 trunk checker name and report hash
        should be in the plist file.
        """
        clang50_trunk_plist = os.path.join(
            self.__plist_test_files, 'clang-5.0-trunk.plist')
        reports = report_file.get_reports(clang50_trunk_plist)
        self.assertEqual(len(reports), 3)

        files = get_mentioned_original_files(reports)
        self.assertEqual(files, set(SRC_FILES))

        for report in reports:
            # Checker name should be in the plist file.
            self.assertNotEqual(report.checker_name, 'NOT FOUND')
            self.assertIn(report.checker_name, self.__found_checker_names)

            if report.checker_name == 'core.DivideZero':
                # Test data is still valid for this version.
                self.assertEqual(report, div_zero_skel)

                self.assertEqual(
                    report.bug_path_events, div_zero_skel.bug_path_events)
                self.assertEqual(
                    report.bug_path_positions,
                    div_zero_skel.bug_path_positions)

            if report.checker_name == 'core.StackAddressEscape':
                skel = deepcopy(stack_addr_skel)
                skel.report_hash = 'a6d3464f8aab9eb31a8ea7e167e84322'

                self.assertEqual(report, skel)
                self.assertEqual(
                    report.bug_path_events, skel.bug_path_events)
                self.assertEqual(
                    report.bug_path_positions, skel.bug_path_positions)
