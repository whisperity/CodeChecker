# -------------------------------------------------------------------------
#
#  Part of the CodeChecker project, under the Apache License v2.0 with
#  LLVM Exceptions. See LICENSE for license information.
#  SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
# -------------------------------------------------------------------------
"""
Implements the logic for analyser-specific generation of documentation URLs.
"""
from .analyser_selection import select_generator


__all__ = [
    "select_generator",
]
