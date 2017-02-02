# -------------------------------------------------------------------------
#                     The CodeChecker Infrastructure
#   This file is distributed under the University of Illinois Open Source
#   License. See LICENSE.TXT for details.
# -------------------------------------------------------------------------

import linecache
import math
import ntpath
import os
import shutil
import sys
from abc import ABCMeta

from codechecker_lib import plist_parser
from codechecker_lib import suppress_handler
from codechecker_lib.logger import LoggerFactory
from codechecker_lib.analyzers.result_handler_base import ResultHandler

LOG = LoggerFactory.get_new_logger('PLIST TO FILE')


class PlistToFile(ResultHandler):
    """
    Result handler for copying a plist file to a different location.
    """

    __metaclass__ = ABCMeta

    def __init__(self, buildaction, workspace, lock):
        super(PlistToFile, self).__init__(buildaction, workspace)
        self.__lock = lock

    @property
    def print_steps(self):
        """
        Print the multiple steps for a bug if there is any.
        """
        return self.__print_steps

    @print_steps.setter
    def print_steps(self, value):
        """
        Print the multiple steps for a bug if there is any.
        """
        self.__print_steps = value

    def handle_results(self, jailed_root):
        """This handler copies the plist file into the jailed_root."""
        plist = self.analyzer_result_file

        try:
            plist_parser.parse_plist(plist, jailed_root)
        except Exception as ex:
            LOG.error('The generated plist is not valid!')
            LOG.error(ex)
            return 1

        err_code = self.analyzer_returncode

        if err_code == 0:
            try:
                # No lock when consuming plist.
                self.__lock.acquire() if self.__lock else None
                with open(plist, 'r') as pl:
                    with open(os.path.join(jailed_root,
                                           os.path.basename(plist)),
                              'w') as out:
                        for line in pl:
                            out.write(line.replace(jailed_root, ''))
            finally:
                self.__lock.release() if self.__lock else None
        else:
            self.__output.write('Analyzing %s with %s failed.\n' %
                                (ntpath.basename(self.analyzed_source_file),
                                 self.buildaction.analyzer_type))
        return err_code

    def postprocess_result(self):
        """
        No postprocessing required for plists.
        """
        pass
