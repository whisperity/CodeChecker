#
# -------------------------------------------------------------------------
#
#  Part of the CodeChecker project, under the Apache License v2.0 with
#  LLVM Exceptions. See LICENSE for license information.
#  SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
# -------------------------------------------------------------------------
"""
Analysis run related tests.
"""


from datetime import datetime
import os
import unittest

from libtest import env

from codechecker_api.codeCheckerDBAccess_v6.ttypes import \
    AnalysisInfoFilter, \
    DetectionStatus, \
    Order, \
    ReportFilter, RunFilter, RunSortMode, RunSortType

from . import setup_class_common, teardown_class_common


class TestRunData(unittest.TestCase):

    _ccClient = None

    def setup_class(self):
        setup_class_common("run_data")

    def teardown_class(self):
        teardown_class_common()

    def setup_method(self, method):
        test_workspace = os.environ['TEST_WORKSPACE']

        test_class = self.__class__.__name__
        print('Running ' + test_class + ' tests in ' + test_workspace)

        self._testproject_data = env.setup_test_proj_cfg(test_workspace)
        self.assertIsNotNone(self._testproject_data)

        self._cc_client = env.setup_viewer_client(test_workspace)
        self.assertIsNotNone(self._cc_client)

        self._run_names = env.get_run_names(test_workspace)

    def __get_runs(self, run_name_filter=None):
        """ Helper function to get all run names which belong to this test"""
        run_filter = RunFilter()
        if run_name_filter is not None:
            run_filter.names = [run_name_filter]

        runs = self._cc_client.getRunData(run_filter, None, 0, None)
        return [run for run in runs if run.name in self._run_names]

    def test_filter_run_names(self):
        # Filter all runs.
        test_runs = self.__get_runs()
        self.assertEqual(len(test_runs), 2,
                         "There should be two runs for this test.")

        # Filter runs which name starts with `test_files_`.
        test_runs = self.__get_runs('test_files_*')
        self.assertEqual(len(test_runs), 1,
                         "There should be one run for this test.")

        # Run name filter is case insensitive.
        test_runs = self.__get_runs('Test_Files_*')
        self.assertEqual(len(test_runs), 1,
                         "There should be one run for this test.")

        # Filter runs which name contains `files_`.
        test_runs = self.__get_runs('*files_*')
        self.assertEqual(len(test_runs), 1,
                         "There should be one run for this test.")

        # Filter runs which name contains `test_files*`.
        test_runs = self.__get_runs('test_files*')
        self.assertEqual(len(test_runs), 2,
                         "There should be two runs for this test.")

        test_runs = self.__get_runs('*_*')
        self.assertEqual(len(test_runs), 2,
                         "There should be two runs for this test.")

        test_runs = self.__get_runs('*')
        self.assertEqual(len(test_runs), 2,
                         "There should be two runs for this test.")

        test_runs = self.__get_runs('%')
        self.assertEqual(len(test_runs), 0,
                         "There should be no run for this test.")

        # Filter non existing run.
        test_runs = self.__get_runs('non_existing_run_name')
        self.assertEqual(len(test_runs), 0,
                         "There should be no run for this test.")

    def test_number_of_unique_reports(self):
        """
        Tests that resultCount field value in runData is equal with the
        number of unfixed reports in the run.
        """
        test_runs = self.__get_runs()

        report_filter = ReportFilter()
        report_filter.detectionStatus = [DetectionStatus.NEW,
                                         DetectionStatus.UNRESOLVED,
                                         DetectionStatus.REOPENED]

        for run in test_runs:
            run_count = self._cc_client.getRunResultCount([run.runId],
                                                          report_filter,
                                                          None)
            self.assertEqual(run.resultCount, run_count)

    def test_sort_run_data_order(self):
        """
        Test sort runs by different order types.
        """
        # Sort runs in ascending order.
        sort_mode = RunSortMode(RunSortType.DURATION, Order.ASC)
        runs = self._cc_client.getRunData(None, None, 0, sort_mode)

        for i in range(len(runs) - 1):
            self.assertTrue(runs[i].duration <= runs[i + 1].duration)

        # Sort runs in descending order.
        sort_mode = RunSortMode(RunSortType.DURATION, Order.DESC)
        runs = self._cc_client.getRunData(None, None, 0, sort_mode)

        for i in range(len(runs) - 1):
            self.assertTrue(runs[i].duration >= runs[i + 1].duration)

    def test_sort_run_data(self):
        """
        Test sort runs by different field types.
        """
        # Sort runs by number of unresolved reports field.
        sort_mode = RunSortMode(RunSortType.UNRESOLVED_REPORTS, Order.ASC)
        runs = self._cc_client.getRunData(None, None, 0, sort_mode)

        for i in range(len(runs) - 1):
            self.assertTrue(runs[i].resultCount <= runs[i + 1].resultCount)

        # Sort runs by date field.
        sort_mode = RunSortMode(RunSortType.DATE, Order.ASC)
        runs = self._cc_client.getRunData(None, None, 0, sort_mode)

        for i in range(len(runs) - 1):
            date1 = datetime.strptime(runs[i].runDate,
                                      '%Y-%m-%d %H:%M:%S.%f')
            date2 = datetime.strptime(runs[i + 1].runDate,
                                      '%Y-%m-%d %H:%M:%S.%f')
            self.assertTrue(date1 <= date2)

        # Sort runs by CodeChecker version field.
        sort_mode = RunSortMode(RunSortType.CC_VERSION, Order.ASC)
        runs = self._cc_client.getRunData(None, None, 0, sort_mode)

        for i in range(len(runs) - 1):
            cc_version1 = runs[i].codeCheckerVersion
            cc_version2 = runs[i + 1].codeCheckerVersion
            self.assertTrue(cc_version1 <= cc_version2)

        # Sort runs by name field. We are not comparing the run names in python
        # code because Python and SQL compare strings differently if it
        # contains special characters.
        sort_mode = RunSortMode(RunSortType.NAME, Order.ASC)
        self._cc_client.getRunData(None, None, 0, sort_mode)

    def test_analysis_info(self):
        """
        Test that storing runs to the server records the executed analyzer
        command and the list of checkers present and executed.
        """
        workspace = os.environ["TEST_WORKSPACE"]
        runs = self.__get_runs("test_files*%")
        self.assertEqual(len(runs), 1,
                         "There should be one run for this test.")
        run = runs[0]
        run_id = run.runId

        analysis_infos = self._cc_client.getAnalysisInfo(
            AnalysisInfoFilter(run_id, None, None), 1, 0)
        self.assertEqual(len(analysis_infos), 1,
                         "An analysis_info must be recorded for the run!")

        info = analysis_infos[0]
        cmd = info.analyzerCommand
        print(run_id, analysis_infos)

        self.assertTrue(workspace in cmd,
                        "The name of the test workspace should be part of "
                        "the report directory, found in the cmdline.")
        # Ensure that the tests here are up-to-date with what's in __init__.py.
        self.assertTrue("-d core.StackAddressEscape" in cmd,
                        "A disabled checker is needed for this test to work!")
        self.assertTrue("-d unix.Malloc" in cmd,
                        "A disabled checker is needed for this test to work!")
        self.assertTrue("-d clang-diagnostic" in cmd,
                        "A disabled checker is needed for this test to work!")
        self.assertTrue("-e clang-diagnostic-division-by-zero" in cmd,
                        "An enabled checker is needed for this test to work!")

        checkers = info.checkers

        def assertChecker(analyzer, checker):
            self.assertTrue(checkers[analyzer][checker].enabled)

        def assertNotChecker(analyzer, checker):
            self.assertFalse(checkers[analyzer][checker].enabled)

        assertNotChecker("clangsa", "alpha.cplusplus.MismatchedIterator")
        assertNotChecker("clangsa", "alpha.webkit.UncountedCallArgsChecker")
        assertNotChecker("clangsa", "core.StackAddressEscape")
        assertChecker("clangsa", "core.CallAndMessage")
        assertChecker("clangsa", "deadcode.DeadStores")
        assertChecker("clangsa", "cplusplus.NewDelete")
        assertNotChecker("clangsa", "osx.cocoa.Loops")
        assertNotChecker("clangsa", "unix.Malloc")

        assertNotChecker("clang-tidy", "bugprone-easily-swappable-parameters")
        assertChecker("clang-tidy", "clang-diagnostic-division-by-zero")
        assertNotChecker("clang-tidy", "clang-diagnostic-return-type")
        assertNotChecker("clang-tidy", "clang-diagnostic-vla")
        assertNotChecker("clang-tidy", "llvmlibc-restrict-system-libc-headers")
        assertChecker("clang-tidy", "misc-definitions-in-headers")
        assertNotChecker("clang-tidy", "objc-super-self")

        self.assertTrue("cppcheck" not in checkers.keys(),
                        "This analysis was run without CppCheck!")
        self.assertTrue("gcc" not in checkers.keys(),
                        "This analysis was run without GCC!")
