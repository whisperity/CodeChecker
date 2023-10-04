# -------------------------------------------------------------------------
#
#  Part of the CodeChecker project, under the Apache License v2.0 with
#  LLVM Exceptions. See LICENSE for license information.
#  SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
# -------------------------------------------------------------------------
"""
Handles the retrieval and access to the file-based configuration of a server.
"""
import os
from pathlib import Path, PurePosixPath
import shutil

from codechecker_common.configuration_access import Configuration
from codechecker_common.logger import get_logger

from codechecker_web.shared.env import check_file_owner_rw


LOG = get_logger("server")


def register_configuration_options(cfg: Configuration):
    """
    Registers the schema of Options that are accessible in a server
    configuration file.
    """
    cfg.add_option("worker_processes", "/worker_processes",
                   default=lambda: os.cpu_count(),
                   check=lambda v: v > 0,
                   check_fail_msg=lambda: "The number of 'worker_processes' "
                                          "can not be negative, using CPU "
                                          "count (%d) instead."
                                          % os.cpu_count(),
                   # TODO: This should affect the count of the background
                   # workers as well!
                   description="The number of API request handler processes "
                               "to start on the server.")


def get_example_configuration_file_path() -> Path:
    """
    Returns the location of the example configuration that is shipped
    together with the CodeChecker package.
    """
    return Path(os.environ["CC_DATA_FILES_DIR"],
                "config", "server_config.json")


def migrate_session_config_to_server_config(session_config_file: Path,
                                            server_config_file: Path) -> Path:
    """
    Migrates an existing, deprecated 'session_config' file to its new
    'server_config' structure.

    Returns server_config_file path.
    """
    if session_config_file.exists() and not server_config_file.exists():
        LOG.warning("The use of '%s' file is deprecated since "
                    "CodeChecker v6.5!", session_config_file)

        os.rename(session_config_file, server_config_file)
        LOG.info("Automatically renamed '%s' to '%s'...\n\t"
                 "Please check the example configuration configuration file "
                 "('%s') or the User Guide "
                 "(http://codechecker.readthedocs.io) for more information.",
                 session_config_file, server_config_file,
                 get_example_configuration_file_path())
    return server_config_file


def create_server_config_file(server_config_file: Path) -> Path:
    """
    Creates a default server configuration file at the specified location from
    the package's built-in example.

    Returns server_config_file path.
    """
    if not server_config_file.exists():
        shutil.copyfile(get_example_configuration_file_path(),
                        server_config_file)
        LOG.info("CodeChecker server's example configuration file created "
                 "at '%s'", server_config_file)
    return server_config_file


def load_configuration(config_directory: Path) -> Configuration:
    """
    Do everything possible to ensure that a valid server configuration
    exists in the expected file under config_directory. Following that,
    read it, parse it, and returns the contents in the access providing
    Configuration data structure.
    """
    server_config = config_directory / "server_config.json"
    if not server_config.exists():
        server_config = migrate_session_config_to_server_config(
            config_directory / "session_config.json",
            server_config)
    if not server_config.exists():
        server_config = create_server_config_file(server_config)
    if not server_config.exists():
        LOG.fatal("Server configuration factory ran out of options to "
                  "instantiate a viable configuration for this instance!")
        raise FileNotFoundError(str(server_config))

    # This helper function prints a warning to the output if the access
    # to the file is too permissive.
    check_file_owner_rw(server_config)

    cfg = Configuration(server_config)
    register_configuration_options(cfg)
    return cfg
