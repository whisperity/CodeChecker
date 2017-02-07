# -------------------------------------------------------------------------
#                     The CodeChecker Infrastructure
#   This file is distributed under the University of Illinois Open Source
#   License. See LICENSE.TXT for details.
# -------------------------------------------------------------------------
"""
Handle command line arguments.
"""
import atexit
import errno
import json
import multiprocessing
import os
import psutil
import socket
import shutil
import subprocess
import sys
import tempfile
import time

from codechecker_lib import analyzer
from codechecker_lib import analyzer_env
from codechecker_lib import build_action
from codechecker_lib import build_manager
from codechecker_lib import client
from codechecker_lib import debug_reporter
from codechecker_lib import generic_package_context
from codechecker_lib import generic_package_suppress_handler
from codechecker_lib import host_check
from codechecker_lib import instance_manager
from codechecker_lib import log_parser
from codechecker_lib import session_manager
from codechecker_lib import util
from codechecker_lib.logger import LoggerFactory
from codechecker_lib.analyzers import analyzer_types
from codechecker_lib.database_handler import SQLServer
from daemon import client as daemon_client
from daemon import server as daemon_server
from daemon import lib as daemon_lib
from viewer_server import client_db_access_server

LOG = LoggerFactory.get_new_logger('ARG_HANDLER')


def log_startserver_hint(args):
    db_data = ""
    if args.postgresql:
        db_data += " --postgresql" \
                   + " --dbname " + args.dbname \
                   + " --dbport " + str(args.dbport) \
                   + " --dbusername " + args.dbusername

    LOG.info("To view results run:\nCodeChecker server -w " +
             args.workspace + db_data)


def handle_list_checkers(args):
    """
    List the supported checkers by the analyzers.
    List the default enabled and disabled checkers in the config.
    """
    context = generic_package_context.get_context()
    # If nothing is set, list checkers for all supported analyzers.
    enabled_analyzers = args.analyzers or analyzer_types.supported_analyzers
    analyzer_environment = analyzer_env.get_check_env(
        context.path_env_extra,
        context.ld_lib_path_extra)

    remote = 'remote_host' in args or \
             'remote_port' in args
    if remote:
        # Set the default values here if the user did specify that we go
        # remote, but didn't specify EVERY variable.

        if not getattr(args, 'remote_host', None):
            setattr(args, 'remote_host', 'localhost')
        if not getattr(args, 'remote_port', None):
            setattr(args, 'remote_port', 8002)

    if not remote:
        # ---- Local query ----

        checkers = analyzer_types.get_checkers(
            generic_package_context.get_context(), args)
    else:
        # ---- Remote query ----

        rclient = daemon_client.RemoteClient(args.remote_host,
                                             args.remote_port)
        checkers = rclient.getCheckerList(
            json.dumps({'analyzers': args.analyzers
                        }))
        checkers = map(lambda chk: (chk.checker_name, chk.enabled,
                                    chk.description),
                       checkers)

    for checker_name, enabled, description in checkers:
        if enabled:
            print(' + {0:50} {1}'.format(checker_name, description))
        else:
            print(' - {0:50} {1}'.format(checker_name, description))


def _handle_instancemgr_args(subcommand, args, workspace, port_title='Port'):
    """Handle CodeChecker server/daemon --list/--stop/--stop-all"""

    # Set up some defaults suppressed by the argparser.
    if 'list' not in args:
        args.list = False
    if 'stop' not in args:
        args.stop = False
    if 'stop_all' not in args:
        args.stop_all = False

    if not (args.list or args.stop or args.stop_all):
        # If neither is specified, don't do anything in this method.
        return

    if not (args.list ^ args.stop ^ args.stop_all):
        print("CodeChecker {0}: error: argument -l/--list and -s/--stop"
              "and --stop-all are mutually exclusive.".format(subcommand))
        sys.exit(2)

    if args.list:
        instances = instance_manager.list(subcommand)

        instances_on_multiple_hosts = any(True for inst in instances
                                          if inst['hostname'] !=
                                          socket.gethostname())
        if not instances_on_multiple_hosts:
            rows = [('Workspace', port_title)]
        else:
            rows = [('Workspace', 'Computer host', port_title)]

        for instance in instances:
            if not instances_on_multiple_hosts:
                rows.append((instance['workspace'], str(instance['port'])))
            else:
                rows.append((instance['workspace'],
                             instance['hostname']
                             if instance['hostname'] != socket.gethostname()
                             else '',
                             str(instance['port'])))

        print("Your running CodeChecker servers:")
        util.print_table(rows)
        sys.exit(0)
    elif args.stop or args.stop_all:
        for i in instance_manager.list(subcommand):
            # A STOP only stops the server associated with the given workspace
            # and view-port.
            if i['hostname'] != socket.gethostname() or (
                        args.stop and not (i['port'] == args.view_port and
                                           os.path.abspath(i['workspace']) ==
                                           os.path.abspath(workspace))):
                continue

            try:
                util.kill_process_tree(i['pid'])
                LOG.info("Stopped CodeChecker {3} running on port {0} "
                         "in workspace {1} (PID: {2})".
                         format(i['port'], i['workspace'], i['pid'],
                                subcommand))
            except:
                # Let the exception come out if the commands fail
                LOG.error("Couldn't stop process PID #" + str(i['pid']))
                raise
        sys.exit(0)


def handle_server(args):
    """
    Starts the report viewer server.
    """
    if not host_check.check_zlib():
        sys.exit(1)

    workspace = args.workspace
    _handle_instancemgr_args('server', args, workspace, 'View port')

    # WARNING
    # In case of SQLite args.dbaddress default value is used
    # for which the is_localhost should return true.
    if util.is_localhost(args.dbaddress) and not os.path.exists(workspace):
        os.makedirs(workspace)

    suppress_handler = generic_package_suppress_handler.\
        GenericSuppressHandler()
    if args.suppress is None:
        LOG.warning('No suppress file was given, suppressed results will '
                    'be only stored in the database.')
    else:
        if not os.path.exists(args.suppress):
            LOG.error('Suppress file ' + args.suppress + ' not found!')
            sys.exit(1)

    context = generic_package_context.get_context()
    context.codechecker_workspace = workspace
    session_manager.SessionManager.CodeChecker_Workspace = workspace
    context.db_username = args.dbusername

    check_env = analyzer_env.get_check_env(context.path_env_extra,
                                           context.ld_lib_path_extra)

    sql_server = SQLServer.from_cmdline_args(args,
                                             context.codechecker_workspace,
                                             context.migration_root,
                                             check_env)
    conn_mgr = client.ConnectionManager(sql_server, args.check_address,
                                        args.check_port)
    if args.check_port:
        LOG.debug('Starting CodeChecker server and database server.')
        sql_server.start(context.db_version_info, wait_for_start=True,
                         init=True)
        conn_mgr.start_report_server()
    else:
        LOG.debug('Starting database.')
        sql_server.start(context.db_version_info, wait_for_start=True,
                         init=True)

    # Start database viewer.
    db_connection_string = sql_server.get_connection_string()

    suppress_handler.suppress_file = args.suppress
    LOG.debug('Using suppress file: ' + str(suppress_handler.suppress_file))

    checker_md_docs = os.path.join(context.doc_root, 'checker_md_docs')
    checker_md_docs_map = os.path.join(checker_md_docs,
                                       'checker_doc_map.json')
    with open(checker_md_docs_map, 'r') as dFile:
        checker_md_docs_map = json.load(dFile)

    package_data = {'www_root': context.www_root, 'doc_root': context.doc_root,
                    'checker_md_docs': checker_md_docs,
                    'checker_md_docs_map': checker_md_docs_map}

    try:
        client_db_access_server.start_server(package_data,
                                             args.view_port,
                                             db_connection_string,
                                             suppress_handler,
                                             args.not_host_only,
                                             context)
    except socket.error as err:
        if err.errno == errno.EADDRINUSE:
            LOG.error("Server can't be started, maybe the given port number "
                      "({}) is already used. Check the connection "
                      "parameters.".format(args.view_port))
            sys.exit(1)
        else:
            raise


def handle_daemon(args):
    """
    Starts the CodeChecker-as-a-Service daemon.
    This mode opens a server and listens to remote connections to support
    checking a project not on the developer computer but on a team server.
    """
    if not host_check.check_zlib():
        LOG.error("zlib error")
        sys.exit(1)

    try:
        workspace = args.workspace
    except AttributeError:
        # If no workspace value was set for some reason
        # in args set the default value.
        workspace = util.get_default_workspace()

    _handle_instancemgr_args('daemon', args, workspace, 'Daemon port')

    # WARNING
    # In case of SQLite args.dbaddress default value is used
    # for which the is_localhost should return true.

    if args.docker:
        LOG.info("Starting daemon with analyses running in a Docker instance.")

        # Check if a proper Docker image exists
        try:
            res = subprocess.check_output(['docker', 'run',
                                           '--rm', 'codechecker'])

            if res != "CODECHECKER_DAEMON_ANALYZER_READY":
                LOG.error("The Docker container didn't respond properly.\n"
                          "Make sure you created az --install image and "
                          "that it is named 'codechecker'!")
                LOG.info("The output was: \n" + res)
                sys.exit(1)
        except OSError:
            LOG.error("Docker does not seem to be installed on the system!")
            sys.exit(1)
        except subprocess.CalledProcessError:
            LOG.error("The initial test for the Docker image didn't conclude.")
            sys.exit(1)

    local_db = util.is_localhost(args.dbaddress)
    if local_db and not os.path.exists(workspace):
        os.makedirs(workspace)

    context = generic_package_context.get_context()
    context.codechecker_workspace = workspace
    session_manager.SessionManager.CodeChecker_Workspace = workspace
    context.db_username = args.dbusername

    is_server_started = multiprocessing.Event()
    server = multiprocessing.Process(target=daemon_server.run_server,
                                     args=(
                                         args,
                                         context,
                                         is_server_started,
                                         args.docker))

    server.start()

    # Wait a bit.
    counter = 0
    while not is_server_started.is_set() and counter < 4:
        LOG.debug('Waiting for daemon server to start.')
        time.sleep(3)
        counter += 1

    if counter >= 4 or not server.is_alive():
        # Last chance to start.
        if server.exitcode is None:
            # It is possible that the database starts really slow.
            time.sleep(5)
            if not is_server_started.is_set():
                LOG.error('Failed to start checker server.')
                sys.exit(1)
        else:
            LOG.error('Failed to start checker server.')
            LOG.error('Checker server exit code: ' +
                      str(server.exitcode))
            sys.exit(1)

    atexit.register(server.terminate)
    LOG.debug('Daemon start sequence done.')

    # The main thread will wait FOREVER for the server to shut down
    server.join()
    LOG.debug("Daemon server quit.")


def handle_log(args):
    """
    Generates a build log by running the original build command.
    No analysis is done.
    """
    args.logfile = os.path.realpath(args.logfile)
    if os.path.exists(args.logfile):
        os.remove(args.logfile)

    context = generic_package_context.get_context()
    build_manager.perform_build_command(args.logfile,
                                        args.command,
                                        context)


def handle_debug(args):
    """
    Runs a debug command on the buildactions where the analysis
    failed for some reason.
    """
    context = generic_package_context.get_context()

    context.codechecker_workspace = args.workspace
    context.db_username = args.dbusername

    check_env = analyzer_env.get_check_env(context.path_env_extra,
                                           context.ld_lib_path_extra)

    sql_server = SQLServer.from_cmdline_args(args,
                                             context.codechecker_workspace,
                                             context.migration_root,
                                             check_env)
    sql_server.start(context.db_version_info, wait_for_start=True, init=False)

    debug_reporter.debug(context, sql_server.get_connection_string(),
                         args.force)


def handle_check(args):
    """
    Runs the original build and logs the buildactions.
    Based on the log runs the analysis.
    """

    try:
        if not host_check.check_zlib():
            sys.exit(1)

        args.workspace = os.path.abspath(args.workspace)

        context = generic_package_context.get_context()
        context.codechecker_workspace = args.workspace
        context.db_username = args.dbusername

        log_file, set_in_cmdline = build_manager.check_log_file(args, context)

        if not log_file:
            LOG.error("Failed to generate compilation command file: " +
                      log_file)
            sys.exit(1)

        actions = log_parser.parse_log(log_file,
                                       args.add_compiler_defaults)

        check_env = analyzer_env.get_check_env(context.path_env_extra,
                                               context.ld_lib_path_extra)

        sql_server = SQLServer.from_cmdline_args(args,
                                                 context.
                                                 codechecker_workspace,
                                                 context.migration_root,
                                                 check_env)

        conn_mgr = client.ConnectionManager(sql_server, 'localhost',
                                            util.get_free_port())

        sql_server.start(context.db_version_info, wait_for_start=True,
                         init=True)

        conn_mgr.start_report_server()

        LOG.debug("Checker server started.")

        analyzer.run_check(args, actions, context)

        LOG.info("Analysis has finished.")

        log_startserver_hint(args)
    except Exception as ex:
        LOG.error(ex)
        import traceback
        print(traceback.format_exc())
    finally:
        if not args.keep_tmp:
            if log_file and not set_in_cmdline:
                LOG.debug('Removing temporary log file: ' + log_file)
                os.remove(log_file)


def handle_remote(args):
    """
    Runs the original build and logs the buildactions.
    Based on the log runs the analysis on a remote server.
    """

    LOG.info(''.join(['Using remote check at [',
                      args.remote_host or '',
                      ':', str(args.remote_port), ']']))

    log_file = None  # Referenced before assignment...
    try:
        if not host_check.check_zlib():
            sys.exit(1)

        args.workspace = os.path.abspath(args.workspace)

        if not os.path.exists(args.export_plist):
            os.makedirs(args.export_plist)
        args.export_plist = os.path.abspath(args.export_plist)

        # In remote mode, connect to the remote daemon
        # and use a temporary workspace
        args.workspace = os.path.realpath(util.get_temporary_workspace())

        rclient = daemon_client.RemoteClient(args.remote_host,
                                             args.remote_port)
        try:
            can_run = rclient.pollCheckAvailability(args.name)
        except Exception as e:
            LOG.error(e.message)
            LOG.error("Couldn't initiate remote checking on [{0}:{1}]"
                      .format(args.remote_host or 'localhost',
                              args.remote_port))
            sys.exit(1)

        if not can_run:
            LOG.error("Server did not accept the request to run '" +
                      args.name + "'. It is either overloaded or a run " +
                      "with the given name is already being executed.")
            sys.exit(1)

        if not os.path.isdir(args.workspace):
            os.mkdir(args.workspace)

        context = generic_package_context.get_context()
        context.codechecker_workspace = args.workspace

        log_file, set_in_cmdline = build_manager.check_log_file(args, context)

        if not log_file:
            LOG.error("Failed to generate compilation command file: " +
                      log_file)
            sys.exit(1)

        actions = log_parser.parse_log(log_file,
                                       args.add_compiler_defaults)

        LOG.debug("Logfile generation was successful in " + log_file)

        try:
            ack = rclient.initConnection(args.name,
                                         ' '.join(sys.argv),
                                         daemon_lib.pack_check_args(args))
        except Exception as e:
            LOG.error("Couldn't start uploading data to server: " +
                      e.message)
            sys.exit(1)

        if not ack.is_initial:
            LOG.debug("Generating file transport for modified files "
                      "and metadata")
        else:
            LOG.debug("Generating file transport for all files.")

        # Send the build.json, and other mandatory configuration files,
        # the source codes and the dependency metadata to the server.
        args.logfile = log_file
        initialfiles = daemon_lib.create_initial_file_data(args,
                                                           actions,
                                                           ack.is_initial)

        LOG.debug("Sending files to server...")
        wrongfiles = rclient.sendFileData(ack.token, initialfiles)

        while len(wrongfiles) != 0:
            LOG.debug(str(len(wrongfiles)) +
                      " more files reported by server as required.")
            fds = daemon_lib.create_file_data_from_paths(wrongfiles)
            wrongfiles = rclient.sendFileData(ack.token, fds)

        LOG.info('All files successfully uploaded to remote server.')

        # Tell the server that we have sent everything
        rclient.beginChecking(ack.token)

        LOG.info('Server reported analysis to be over...')

        plists = rclient.fetchPlists(ack.token)
        for plist in plists:
            with open(os.path.join(args.export_plist, plist.path), 'w') as f:
                f.write(plist.content)

        rclient.expire(ack.token)
        LOG.info("Done -- downloaded {0} plists.".format(len(plists)))
    except Exception as ex:
        LOG.error(ex)
        import traceback
        print(traceback.format_exc())
    finally:
        if not args.keep_tmp:
            if log_file and not set_in_cmdline:
                LOG.debug('Removing temporary log file: ' + log_file)
                os.remove(log_file)

            if os.path.exists(args.workspace):
                shutil.rmtree(args.workspace)


def _do_quickcheck(args):
    """
    Handles the "quickcheck" command.

    For arguments see main function in CodeChecker.py.
    It also requires an extra property in args object, namely workspace which
    is a directory path as a string.
    This function is called from handle_quickcheck.
    """

    try:
        context = generic_package_context.get_context()

        context.codechecker_workspace = args.workspace
        args.name = "quickcheck"

        log_file, set_in_cmdline = build_manager.check_log_file(args, context)
        actions = log_parser.parse_log(log_file,
                                       args.add_compiler_defaults)
        analyzer.run_quick_check(args, context, actions,
                                 args.export_plist)

    except Exception as ex:
        LOG.error("Running quickcheck failed.")
    finally:
        if not args.keep_tmp:
            if log_file and not set_in_cmdline:
                LOG.debug('Removing temporary log file: ' + log_file)
                os.remove(log_file)


def handle_quickcheck(args):
    """
    Handles the "quickcheck" command using _do_quickcheck function.

    It creates a new temporary directory and sets it as workspace directory.
    After _do_quickcheck call it deletes the temporary directory and its
    content.
    """

    args.workspace = tempfile.mkdtemp(prefix='codechecker-qc')

    if args.export_plist:
        if not os.path.exists(args.export_plist):
            os.mkdir(args.export_plist)
        args.export_plist = os.path.abspath(args.export_plist)

    try:
        _do_quickcheck(args)
    finally:
        if not args.keep_tmp:
            shutil.rmtree(args.workspace)


def consume_plist(item):
    plist, args, context = item
    LOG.info('Consuming ' + plist)

    action = build_action.BuildAction()
    action.analyzer_type = analyzer_types.CLANG_SA
    action.original_command = 'Imported from PList directly'

    rh = analyzer_types.construct_result_handler(args,
                                                 action,
                                                 context.run_id,
                                                 args.directory,
                                                 context.severity_map,
                                                 None,
                                                 None,
                                                 not args.stdout)

    rh.analyzer_returncode = 0
    rh.buildaction.analyzer_type = 'Build action from plist'
    rh.buildaction.original_command = plist
    rh.analyzer_cmd = ''
    rh.analyzed_source_file = ''  # TODO: fill from plist.
    rh.result_file = os.path.join(args.directory, plist)
    rh.handle_results()


def handle_plist(args):
    context = generic_package_context.get_context()
    context.codechecker_workspace = args.workspace
    context.db_username = args.dbusername

    if not args.stdout:
        args.workspace = os.path.realpath(args.workspace)
        if not os.path.isdir(args.workspace):
            os.mkdir(args.workspace)

        check_env = analyzer_env.get_check_env(context.path_env_extra,
                                               context.ld_lib_path_extra)

        sql_server = SQLServer.from_cmdline_args(args,
                                                 context.codechecker_workspace,
                                                 context.migration_root,
                                                 check_env)

        conn_mgr = client.ConnectionManager(sql_server,
                                            'localhost',
                                            util.get_free_port())

        sql_server.start(context.db_version_info, wait_for_start=True,
                         init=True)

        conn_mgr.start_report_server()

        with client.get_connection() as connection:
            context.run_id = connection.add_checker_run(' '.join(sys.argv),
                                                        args.name,
                                                        context.version,
                                                        args.force)

    pool = multiprocessing.Pool(args.jobs)

    try:
        items = [(plist, args, context)
                 for plist in os.listdir(args.directory)]
        pool.map_async(consume_plist, items, 1).get(float('inf'))
        pool.close()
    except Exception:
        pool.terminate()
        raise
    finally:
        pool.join()

    if not args.stdout:
        log_startserver_hint(args)


def handle_version_info(args):
    """
    Get and print the version information from the
    version config file and thrift API versions.
    """

    context = generic_package_context.get_context()

    print('Base package version: \t' + context.version).expandtabs(30)
    print('Package build date: \t' +
          context.package_build_date).expandtabs(30)
    print('Git hash: \t' + context.package_git_hash).expandtabs(30)
    print('DB schema version: \t' +
          str(context.db_version_info)).expandtabs(30)

    # Thift api version for the clients.
    from codeCheckerDBAccess import constants
    print(('Thrift client api version: \t' + constants.API_VERSION).
          expandtabs(30))
