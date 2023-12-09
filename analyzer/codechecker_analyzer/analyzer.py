# -------------------------------------------------------------------------
#
#  Part of the CodeChecker project, under the Apache License v2.0 with
#  LLVM Exceptions. See LICENSE for license information.
#  SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
# -------------------------------------------------------------------------
"""
Prepare and start different analysis types
"""


from collections import defaultdict
import os
import shutil
import signal
import sys
import time

from multiprocess.managers import SyncManager

from codechecker_common.logger import get_logger
from codechecker_common.review_status_handler import ReviewStatusHandler

from . import analyzer_context, analysis_manager, pre_analysis_manager, \
    checkers
from .analyzers import analyzer_types
from .analyzers.config_handler import AnalyzerConfigHandler, CheckerState
from .analyzers.clangsa.analyzer import ClangSA

from .makefile import MakeFileCreator

LOG = get_logger('analyzer')


def prepare_actions(actions, enabled_analyzers):
    """
    Set the analyzer type for each buildaction.
    Multiple actions if multiple source analyzers are set.
    """
    res = []

    for ea in enabled_analyzers:
        for action in actions:
            res.append(action.with_attr('analyzer_type', ea))
    return res


def create_actions_map(actions, manager):
    """
    Create a dict for the build actions which is shareable
    safely between processes.
    Key: (source_file, target)
    Value: BuildAction
    """

    result = manager.dict()

    for act in actions:
        key = act.source, act.target
        if key in result:
            LOG.debug("Multiple entires in compile database "
                      "with the same (source, target) pair: (%s, %s)",
                      act.source, act.target)
        result[key] = act
    return result


def __mgr_init():
    """
    This function is set for the SyncManager object which handles shared data
    structures among the processes of the pool. Ignoring the SIGINT signal is
    necessary in the manager object so it doesn't terminate before the
    termination of the process pool.
    """
    signal.signal(signal.SIGINT, signal.SIG_IGN)


def __get_statistics_data(args):
    """ Get statistics data. """
    statistics_data = None

    if 'stats_enabled' in args and args.stats_enabled:
        statistics_data = {
            'stats_out_dir': os.path.join(args.output_path, "stats")}

    if 'stats_output' in args and args.stats_output:
        statistics_data = {'stats_out_dir': args.stats_output}

    if statistics_data:
        statistics_data['stat_tmp_dir'] = \
            os.path.join(statistics_data.get('stats_out_dir'), 'tmp')

    if 'stats_min_sample_count' in args and statistics_data:
        if args.stats_min_sample_count > 1:
            statistics_data['stats_min_sample_count'] =\
                args.stats_min_sample_count
        else:
            LOG.error("stats_min_sample_count"
                      "must be greater than 1.")
            return None

    if 'stats_relevance_threshold' in args and statistics_data:
        if 1 > args.stats_relevance_threshold > 0:
            statistics_data['stats_relevance_threshold'] =\
                args.stats_relevance_threshold
        else:
            LOG.error("stats-relevance-threshold must be"
                      " greater than 0 and smaller than 1.")
            return None

    return statistics_data


def __get_ctu_data(ctu_dir):
    """ Get CTU data. """
    ctu_capability = ClangSA.ctu_capability()
    return {'ctu_dir': ctu_dir,
            'ctu_func_map_cmd': ctu_capability.mapping_tool_path,
            'ctu_func_map_file': ctu_capability.mapping_file_name,
            'ctu_temp_fnmap_folder': 'tmpExternalFnMaps'}


def __has_enabled_checker(ch: AnalyzerConfigHandler):
    """
    Returns True if at least one checker is enabled in the given config
    handler.
    """
    return any(state == CheckerState.enabled
               for _, (state, _) in ch.checks().items())


def perform_analysis(args, skip_handlers, rs_handler: ReviewStatusHandler,
                     actions, metadata_tool, compile_cmd_count):
    """
    Perform static analysis via the given (or if not, all) analyzers,
    in the given analysis context for the supplied build actions.
    Additionally, insert statistical information into the metadata dict.
    """
    # pylint: disable=no-member multiprocess module members.

    context = analyzer_context.get_context()

    ctu_reanalyze_on_failure = 'ctu_reanalyze_on_failure' in args and \
        args.ctu_reanalyze_on_failure

    analyzers = args.analyzers if 'analyzers' in args \
        else analyzer_types.supported_analyzers
    analyzers, errored = analyzer_types.check_supported_analyzers(analyzers)
    analyzer_types.check_available_analyzers(analyzers, errored)

    ctu_collect = False
    ctu_analyze = False
    ctu_dir = ''
    if 'ctu_phases' in args:
        ctu_dir = os.path.join(args.output_path, 'ctu-dir')
        args.ctu_dir = ctu_dir
        if ClangSA.ANALYZER_NAME not in analyzers:
            LOG.error("CTU can only be used with the clang static analyzer.")
            return
        ctu_collect = args.ctu_phases[0]
        ctu_analyze = args.ctu_phases[1]

    if 'stats_enabled' in args and args.stats_enabled:
        if ClangSA.ANALYZER_NAME not in analyzers:
            LOG.debug("Statistics can only be used with "
                      "the Clang Static Analyzer.")
            return

    config_map = analyzer_types.build_config_handlers(args, analyzers)

    no_checker_analyzers = \
        [a for a in analyzers if not __has_enabled_checker(config_map[a])]
    for analyzer in no_checker_analyzers:
        LOG.info("No checkers enabled for %s", analyzer)
        analyzers.remove(analyzer)

    actions = prepare_actions(actions, analyzers)

    available_checkers = set()
    # Add profile names to the checkers list so we will not warn
    # if a profile is enabled but there is no checker with that name.

    available_checkers.update(
        context.checker_labels.get_description('profile'))

    # Collect all the available checkers from the enabled analyzers.
    for analyzer in config_map.items():
        _, analyzer_cfg = analyzer
        for analyzer_checker in analyzer_cfg.checks().items():
            checker_name, _ = analyzer_checker
            available_checkers.add(checker_name)

    if 'ordered_checkers' in args:
        missing_checkers = checkers.available(args.ordered_checkers,
                                              available_checkers)
        if missing_checkers:
            diag_msg = "No checker(s) with these names was found:\n{}".format(
                '\n'.join(missing_checkers))
            if 'no_missing_checker_error' in args:
                LOG.warning(diag_msg)
            else:
                LOG.error(diag_msg)
                LOG.info("Although it is not reccomended, if you want to "
                         "suppress errors relating to unknown "
                         "checker names, consider using the option "
                         "'--no-missing-checker-error'")
                sys.exit(1)

    enabled_checkers = defaultdict(list)

    # Save some metadata information.
    for analyzer in analyzers:
        metadata_info = {
            'checkers': {},
            'analyzer_statistics': {
                "failed": 0,
                "failed_sources": [],
                "successful": 0,
                "successful_sources": [],
                "version": None}}

        for check, data in config_map[analyzer].checks().items():
            state, _ = data
            metadata_info['checkers'].update({
                check: state == CheckerState.enabled})
            if state == CheckerState.enabled:
                enabled_checkers[analyzer].append(check)

        # TODO: cppcheck may require a different environment than clang.
        version = analyzer_types.supported_analyzers[analyzer] \
            .get_binary_version(context.analyzer_env)
        metadata_info['analyzer_statistics']['version'] = version

        metadata_tool['analyzers'][analyzer] = metadata_info

    LOG.info("Enabled checkers:\n%s", '\n'.join(
        k + ': ' + ', '.join(v) for k, v in enabled_checkers.items()))

    if 'makefile' in args and args.makefile:
        statistics_data = __get_statistics_data(args)

        ctu_data = None
        if ctu_collect or statistics_data:
            ctu_data = __get_ctu_data(ctu_dir)

        makefile_creator = MakeFileCreator(analyzers, args.output_path,
                                           config_map, skip_handlers,
                                           ctu_collect, statistics_data,
                                           ctu_data)
        makefile_creator.create(actions)
        return

    if ctu_collect:
        shutil.rmtree(ctu_dir, ignore_errors=True)
    elif ctu_analyze and not os.path.exists(ctu_dir):
        LOG.error("CTU directory: '%s' does not exist.", ctu_dir)
        return

    start_time = time.time()

    # Use Manager to create data objects which can be
    # safely shared between processes.
    manager = SyncManager()
    manager.start(__mgr_init)

    config_map = manager.dict(config_map)
    actions_map = create_actions_map(actions, manager)

    # Setting to not None value will enable statistical analysis features.
    statistics_data = __get_statistics_data(args)
    if statistics_data:
        statistics_data = manager.dict(statistics_data)

    if ctu_collect or statistics_data:
        ctu_data = None
        if ctu_collect or ctu_analyze:
            ctu_data = manager.dict(__get_ctu_data(ctu_dir))

        pre_analyze = [a for a in actions
                       if a.analyzer_type == ClangSA.ANALYZER_NAME]
        pre_anal_skip_handlers = None

        # Skip list is applied only in pre-analysis
        # if --ctu-collect or --stats-collect  was called explicitly
        if ((ctu_collect and not ctu_analyze)
                or ("stats_output" in args and args.stats_output)):
            pre_anal_skip_handlers = skip_handlers

        clangsa_config = config_map.get(ClangSA.ANALYZER_NAME)

        if clangsa_config is not None:
            pre_analysis_manager.run_pre_analysis(pre_analyze,
                                                  clangsa_config,
                                                  args.jobs,
                                                  pre_anal_skip_handlers,
                                                  ctu_data,
                                                  statistics_data,
                                                  manager)
        else:
            LOG.error("Can not run pre analysis without clang "
                      "static analyzer configuration.")

    if 'stats_output' in args and args.stats_output:
        return

    if 'stats_dir' in args and args.stats_dir:
        statistics_data = manager.dict({'stats_out_dir': args.stats_dir})

    if ctu_analyze or statistics_data or (not ctu_analyze and not ctu_collect):

        LOG.info("Starting static analysis ...")
        analysis_manager.start_workers(actions_map, actions,
                                       config_map, args.jobs,
                                       args.output_path,
                                       skip_handlers,
                                       rs_handler,
                                       metadata_tool,
                                       'quiet' in args,
                                       'capture_analysis_output' in args,
                                       'generate_reproducer' in args,
                                       args.timeout if 'timeout' in args
                                       else None,
                                       ctu_reanalyze_on_failure,
                                       statistics_data,
                                       manager,
                                       compile_cmd_count)
        LOG.info("Analysis finished.")
        LOG.info("To view results in the terminal use the "
                 "\"CodeChecker parse\" command.")
        LOG.info("To store results use the \"CodeChecker store\" command.")
        LOG.info("See --help and the user guide for further options about"
                 " parsing and storing the reports.")
        LOG.info("----=================----")

    end_time = time.time()
    LOG.info("Analysis length: %s sec.", end_time - start_time)

    analyzer_types.print_unsupported_analyzers(errored)

    metadata_tool['timestamps'] = {'begin': start_time,
                                   'end': end_time}

    if ctu_collect and ctu_analyze:
        shutil.rmtree(ctu_dir, ignore_errors=True)

    manager.shutdown()
