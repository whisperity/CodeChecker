# -------------------------------------------------------------------------
#
#  Part of the CodeChecker project, under the Apache License v2.0 with
#  LLVM Exceptions. See LICENSE for license information.
#  SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
# -------------------------------------------------------------------------
"""
Multiprocessing compatibility module.
"""
import sys

# pylint: disable=no-name-in-module,unused-import
if sys.platform in ["darwin", "win32"]:
    from multiprocess import Pool  # type: ignore
    from multiprocess import cpu_count
else:
    from concurrent.futures import ProcessPoolExecutor as Pool  # type: ignore
    from multiprocessing import cpu_count
