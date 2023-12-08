# -------------------------------------------------------------------------
#
#  Part of the CodeChecker project, under the Apache License v2.0 with
#  LLVM Exceptions. See LICENSE for license information.
#  SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
# -------------------------------------------------------------------------
from functools import wraps
from typing import Tuple, Union, cast
import zlib

from codechecker_server.database.common import decode_zlib, encode_zlib


def raw_zlib_encode_buf(value: bytes) -> bytes:
    """
    Encodes the given 'value' binary buffer with ZLib's Z_BEST_COMPRESSION.
    """
    return zlib.compress(value, zlib.Z_BEST_COMPRESSION)


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


def recompress_zlib_as_untagged(value: bytes) -> bytes:
    """
    Recompresses the given tagged and ZLib-compressed 'value' as a raw
    ZLib-compressed binary buffer without any additional tags.

    This method always encodes using Z_BEST_COMPRESSION as the compression
    strategy.
    """
    kind, payload = decode_zlib(value)
    payload = cast(bytes,
                   cast(str, payload).encode() if kind == "str" else payload)

    return raw_zlib_encode_buf(payload)


def recompress_zlib_as_tagged_exact_ratio(
    value: bytes,
    kind: str = "str"
) -> Tuple[int, bytes]:
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
    data = raw_zlib_decode_buf(value)

    def _attempt(level: int) -> bool:
        return zlib.compress(data, level) == value

    level_to_use = zlib.Z_BEST_COMPRESSION
    for compression_level in reversed(range(-1, 10)):
        if _attempt(compression_level):
            # Found a matching compression ratio, use this one.
            level_to_use = compression_level
            break

    return level_to_use, encode_zlib(data, kind, level_to_use)


class AlterContext:
    """
    Executes ALTER TABLE operations in an appropriate context, by batching
    operations when neccessary.
    """

    def __init__(self, op, table_name: str, recreate: str = "auto",
                 force_batch = False,
                 disable_foreign_keys_during_operation = False):
        self.op = op
        self.table_name = table_name
        self.recreate = recreate
        self.force_batch = force_batch
        self.disable_foreign_keys = disable_foreign_keys_during_operation

        self.dialect = op.get_context().dialect.name
        self.batcher_context = None
        self.batcher = None

    def _foreign_keys_off(self):
        if self.dialect == "sqlite":
            self.op.execute("PRAGMA foreign_keys=OFF;")

    def _foreign_keys_on(self):
        if self.dialect == "sqlite":
            self.op.execute("PRAGMA foreign_keys=ON;")

    def __enter__(self):
        if self.disable_foreign_keys:
            self._foreign_keys_off()

        if self.force_batch or self.dialect == "sqlite":
            # Simulate the behaviour of
            #     with op.batch_alter_table("foo") as ba:
            # through its context. Clients using AlterContext can use the
            # object to pass function calls to either the batch context or the
            # raw Alembic library, depending on the dialect.
            self.batcher_context = self.op.batch_alter_table(
                self.table_name, recreate=self.recreate)
            self.batcher = self.batcher_context.__enter__()
        elif self.dialect == "postgresql":
            # Usually, there is no need for batch operations for PostgreSQL.
            pass

        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.disable_foreign_keys:
            self._foreign_keys_on()

        if self.batcher_context and self.batcher:
            self.batcher = None
            self.batcher_context.__exit__(exc_type, exc_value, traceback)

    @staticmethod
    def __wraps_alembic(needs_table_name = True,
                        needs_table_name_in_batch_mode = False,
                        table_name_as_kwarg: Union[bool, str] = False):
        """
        Decorates a member function to forward operation onto an Alembic
        table alteration function, in batch mode or normal mode, depending on
        the context's state.
        """
        def _do_wrap(function):
            function_name = function.__name__

            @wraps(function)
            def _wrapper(self, *args, **kwargs):
                if self.batcher:
                    actual_function = getattr(self.batcher, function_name)
                    pass_table_name = needs_table_name and \
                        needs_table_name_in_batch_mode
                else:
                    actual_function = getattr(self.op, function_name)
                    pass_table_name = needs_table_name

                actual_args = list(args)
                actual_kwargs = dict(kwargs)
                if pass_table_name:
                    if not table_name_as_kwarg:
                        actual_args = [self.table_name] + actual_args
                    else:
                        actual_kwargs[
                            "table_name" if table_name_as_kwarg is True
                            else table_name_as_kwarg] = self.table_name

                return actual_function(*actual_args, **actual_kwargs)
            return _wrapper
        return _do_wrap

    @staticmethod
    def __unsupported_nonbatch_kwargs(*arg_names):
        """
        Removes the named arguments in 'arg_names' from the kwargs of the call
        if the function is called in batch mode.
        """
        def _do_wrap(function):
            @wraps(function)
            def _wrapper(self, *args, **kwargs):
                actual_kwargs = {k: v for k, v in dict(kwargs).items()
                                 if k not in arg_names}
                return function(self, *args, **actual_kwargs)
            return _wrapper
        return _do_wrap

    @__unsupported_nonbatch_kwargs("insert_after", "insert_before")
    @__wraps_alembic()
    def add_column(self, *args, **kwargs):
        pass

    @__unsupported_nonbatch_kwargs("insert_after", "insert_before")
    @__wraps_alembic()
    def alter_column(self, *args, **kwargs):
        pass

    @__wraps_alembic()
    def drop_column(self, *args, **kwargs):
        pass

    @__wraps_alembic(table_name_as_kwarg=True)
    def create_index(self, *args, **kwargs):
        pass

    @__wraps_alembic(table_name_as_kwarg=True)
    def drop_index(self, *args, **kwargs):
        pass

    @__wraps_alembic(table_name_as_kwarg="source_table")
    def create_foreign_key(self, *args, **kwargs):
        pass

    @__wraps_alembic(table_name_as_kwarg=True)
    def drop_constraint(self, *args, **kwargs):
        pass
