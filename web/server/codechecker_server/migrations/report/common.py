# -------------------------------------------------------------------------
#
#  Part of the CodeChecker project, under the Apache License v2.0 with
#  LLVM Exceptions. See LICENSE for license information.
#  SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
# -------------------------------------------------------------------------
import zlib

from codechecker_server.database.common import encode_zlib


def raw_zlib_decode_buf(value: bytes) -> bytes:
    """
    Decodes the given ZLib-compressed 'value' into a binary buffer.
    """
    return zlib.decompress(value)


def raw_zlib_decode_str(value: bytes) -> str:
    """
    Decodes the given ZLib-compressed 'value' into a string.
    """
    return raw_zlib_decode_buf(value).decode("utf-8", errors="ignore")


def recompress_zlib_as_tagged(value: bytes, kind: str = "str") -> bytes:
    """
    Recompresses the given raw ZLib-compressed 'value' by tagging it with the
    'kind' to be usable with the 'ZLibCompressed*' BLOB column adaptors.

    This method always encodes using Z_BEST_COMPRESSION as the compression
    strategy.
    """
    try:
        raw = raw_zlib_decode_str(value).encode()
        kind = "str"
    except UnicodeDecodeError:
        raw = raw_zlib_decode_buf(value)
        kind = "blob"

    return encode_zlib(raw, kind)


def recompress_zlib_as_tagged_exact_ratio(value: bytes,
                                          kind: str = "str") -> bytes:
    """
    Recompresses the given raw ZLib-compressed 'value' by tagging it with the
    'kind' to be usable with the 'ZLibCompressed*' BLOB column adaptors.

    This method is more costly as it searches for the exact compression ratio
    that was originally used by performing up to 11 rounds of re-encoding
    internally until the compression ratio is figured out. Unfortunately, there
    are no good and deterministic ways to recover this information in a single
    go.

    The exact compression ratio might not be found, e.g., if the zlib version
    used to encode the original 'value' no longer matches what is available
    on the current machine, and all possible compression ratios produce a
    different result than originally present. In this case, Z_BEST_COMPRESSION
    will be used for the re-compressed buffer.
    """
    data = raw_zlib_decode(value)
