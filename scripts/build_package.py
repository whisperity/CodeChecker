#!/usr/bin/env python
"""
CodeChecker packager script creates a package based on the given layout config.
"""
from __future__ import print_function

import argparse
import errno
import json
import logging
import ntpath
import os
import shutil
import sys

try:
    import urlparse
except ImportError:
    import urllib.parse as urlparse
import tarfile
import subprocess
import time
import shlex
import platform

from distutils.spawn import find_executable

LOG = logging.getLogger('Packager')

msg_formatter = logging.Formatter('[%(levelname)s] - %(message)s')
log_handler = logging.StreamHandler()
log_handler.setFormatter(msg_formatter)
LOG.setLevel(logging.INFO)
LOG.addHandler(log_handler)


# -------------------------------------------------------------------
def run_cmd(cmd, cwd=None, env=None, silent=False):
    """ Run a command. """

    LOG.debug(' '.join(cmd))
    LOG.debug(cwd)
    try:
        stdout = subprocess.PIPE
        stderr = subprocess.PIPE
        if silent:
            stdout = None
            stderr = None
        proc = subprocess.Popen(cmd, cwd=cwd, stdout=stdout, stderr=stderr,
                                env=env)
        proc.wait()
        ret = proc.returncode
        LOG.debug(ret)
        return ret

    except TypeError as type_error:
        LOG.error('Failed to run ' + ' '.join(cmd))
        LOG.error(type_error)
        sys.exit(1)

    except OSError as os_error:
        LOG.error('Failed to run ' + ' '.join(cmd))
        LOG.error(os_error)
        sys.exit(1)


# -------------------------------------------------------------------
def build_ld_logger(ld_logger_path, env, arch=None, clean=True, silent=True):
    """ Build ld logger. """

    LOG.info('Building ld logger ...')
    LOG.debug(ld_logger_path)

    if clean:
        make_cmd = ['make', '-f', 'Makefile.manual', 'clean']
        ret = run_cmd(make_cmd, ld_logger_path, env, silent=silent)
        if ret:
            LOG.error('Failed to run: ' + ' '.join(make_cmd))
            return ret

    if arch is None:
        make_cmd = ['make', '-f', 'Makefile.manual']
    elif arch == '32':
        make_cmd = ['make', '-f', 'Makefile.manual', 'pack32bit']
    elif arch == '64':
        make_cmd = ['make', '-f', 'Makefile.manual', 'pack64bit']

    ret = run_cmd(make_cmd, ld_logger_path, env, silent=silent)
    if ret:
        LOG.error('Failed to run: ' + ' '.join(make_cmd))
        return ret


# -------------------------------------------------------------------
def __thrift_maker(thrift_file, generators, config = None):
    """ Generate files from the Thrift IDL. """

    cmd = ['thrift', '-r', '-I', '.']
    for generator in generators:
        cmd += ['--gen', generator]
    cmd += [thrift_file]

    return run_cmd(cmd, config['thrift_files_dir'],
                   config['env'], config['silent'])


def generate_thrift_files(thrift_files_dir, env, silent=True):
    """ Generate python and javascript files from thrift IDL. """

    LOG.info('Generating thrift files ...')
    config = {'thrift_files_dir': thrift_files_dir,
              'env': env,
              'silent': silent}

    ret = __thrift_maker('report_storage_server.thrift', ['py'], config)
    if ret:
        LOG.error('Failed to generate storage server files')
        return ret

    ret = __thrift_maker('report_viewer_server.thrift',
                         ['py', 'js:jquery'], config)
    if ret:
        LOG.error('Failed to generate viewer server files')
        return ret

    ret = __thrift_maker('daemon_server.thrift', ['py'], config)
    if ret:
        LOG.error('Failed to generate daemon server files')
        return ret

    ret = __thrift_maker('authentication.thrift', ['py'], config)
    if ret:
        LOG.error('Failed to generate authentication interface files')
        return ret

# -------------------------------------------------------------------
def create_folder_layout(path, layout):
    """ Create package directory layout. """

    package_root = layout['root']
    if os.path.exists(path):
        LOG.info('Removing previous package')
        if os.path.exists(package_root):
            shutil.rmtree(package_root)
    else:
        os.makedirs(path)

    LOG.info('Creating package layout')
    LOG.debug(layout)

    os.makedirs(package_root)
    for key, folder in layout.items():
        if key != 'root':
            try:
                directory = os.path.join(package_root, folder)
                os.makedirs(directory)
            except OSError as os_err:
                if os_err.errno != errno.EEXIST:
                    LOG.warning(directory)
                    LOG.warning(os_err.strerror)
                    sys.exit()


# -------------------------------------------------------------------
def copy_tree(src, dst):
    """ Copy file tree. """

    if not os.path.exists(dst):
        os.makedirs(dst)
    for item in os.listdir(src):
        source = os.path.join(src, item)
        destination = os.path.join(dst, item)
        if os.path.isdir(source):
            copy_tree(source, destination)
        else:
            delta = os.stat(src).st_mtime - os.stat(dst).st_mtime
            if not os.path.exists(destination) or delta > 0:
                shutil.copy2(source, destination)


# -------------------------------------------------------------------
def handle_external_file(dep, clean, env, verbose):
    """
    Download (and if needed, extract) files from the given url.
    Currently supports handling of files with the following extensions:
      .tar.gz, .js, .css
    """
    supported_exts = {
        'compressed': ['.tar.gz'],
        'uncompressed': ['.js', '.css']
    }

    source_package = dep['source_package']
    directory = dep['directory']
    if clean and os.path.exists(directory):
        LOG.debug('Removing directory ' + directory)
        shutil.rmtree(directory)
    else:
        if os.path.exists(directory):
            return

    os.makedirs(directory)
    download_cmd = []
    download_cmd.extend(shlex.split(source_package['download_cmd']))
    file_url = source_package['url']
    download_cmd.append(file_url)

    option = source_package['option']
    download_cmd.append(option)

    file_name = source_package['name']
    download_cmd.append(file_name)

    LOG.info('Downloading ...')
    if run_cmd(download_cmd, directory, env, verbose):
        LOG.error('Failed to get dependency')
        sys.exit(1)

    url_data = urlparse.urlparse(file_url)
    head, file_name = ntpath.split(url_data.path)

    head, file_ext = os.path.splitext(file_name)
    if file_ext == '.gz' and head.endswith('.tar'):
        file_ext = '.tar.gz'

    if file_ext in supported_exts['compressed']:
        if file_ext == '.tar.gz':
            file_name = os.path.join(directory, file_name)
            with tarfile.open(file_name) as tar:
                tar.extractall(directory)
            os.remove(file_name)
        else:
            LOG.error('Unsupported file type')
    elif file_ext in supported_exts['uncompressed']:
        pass
    else:
        LOG.error('Unsupported file type')


# -------------------------------------------------------------------
def handle_external_repository(dep, clean, env, verbose):
    """ Download external repository. """
    repository = dep['repository']
    if repository['type'] == 'git':
        directory = dep['directory']
        if clean and os.path.exists(directory):
            LOG.debug('Removing directory ' + directory)
            shutil.rmtree(directory)
        else:
            if os.path.exists(directory):
                return

        git_cmd = ['git', 'clone', '--depth', '1', '--single-branch']

        git_tag = repository.get('git_tag')
        if git_tag:
            git_cmd.append('-b')
            git_cmd.append(git_tag)
        git_cmd.append(repository.get('url'))
        git_cmd.append(directory)

        dir_name, tail = ntpath.split(directory)
        LOG.info('Downloading ...')
        if run_cmd(git_cmd, dir_name, env=env, silent=verbose):
            LOG.error('Failed to get dependency')
            sys.exit(1)
    else:
        LOG.error('Unsupported repository type')


# -------------------------------------------------------------------
def handle_ext_source_dep(dep, clean, env, verbose):
    """ Handle external project dependencies."""

    LOG.info('Checking source: ' + dep['name'])

    if dep.get('source_package') is None and dep.get('repository') is None:
        LOG.error('Missing download for source dependency: ' + dep['name'])
        sys.exit(1)

    if dep.get('source_package'):
        handle_external_file(dep, clean, env, verbose)

    if dep.get('repository'):
        handle_external_repository(dep, clean, env, verbose)

    LOG.info('Done.')


# -------------------------------------------------------------------
def compress_to_tar(source_folder, target_folder, compress):
    """ Compress folder to tar.gz file. """

    source = source_folder.rstrip('//')
    target = target_folder.rstrip('//')
    if source == target:
        # the folder which should be compressed is
        # the same as the target folder
        return False

    target = os.path.join(target_folder, compress)

    t = tarfile.open(target, mode='w:gz')

    head, tail = os.path.split(source)

    for root, dirs, files in os.walk(source_folder):
        for f in files:
            cfile = os.path.join(root, f)
            rename = cfile.replace(head, '')
            LOG.debug('Compressing: %s' % rename)
            t.add(cfile, arcname=rename)
    t.close()
    return True


# -------------------------------------------------------------------
def get_ext_package_data(deps, dep_name):
    """ Search for a dependency in the list. """
    for dep in deps:
        if dep['name'] == dep_name:
            return dep


# -------------------------------------------------------------------
def build_package(repository_root, build_package_config, env=None):
    """ Package can be integrated easier to build systems if required. """

    verbose = build_package_config.get('verbose_log')
    if verbose:
        LOG.setLevel(logging.DEBUG)

    LOG.debug(env)
    LOG.debug(build_package_config)

    LOG.debug('Using build config')
    for val in build_package_config.items():
        LOG.debug(val)

    with open(build_package_config['package_layout_config'],
              'r') as pckg_layout_cfg:
        package_layout_content = pckg_layout_cfg.read()
    LOG.debug(package_layout_content)
    layout = json.loads(package_layout_content)

    LOG.debug(layout)
    package_layout = layout['static']

    output_dir = build_package_config['output_dir']

    package_root = os.path.join(output_dir, 'CodeChecker')
    package_layout['root'] = package_root

    # Get external dependencies.
    ext_deps_dir = os.path.join(repository_root, 'external-source-deps')
    ext_deps_config = os.path.join(ext_deps_dir, 'ext_source_deps_config.json')
    LOG.debug(ext_deps_config)
    with open(ext_deps_config, 'r') as ext_cfg:
        ext_dep_cfg = ext_cfg.read()
        ext_deps = json.loads(ext_dep_cfg)

    clean = build_package_config['clean']
    for dep in ext_deps:
        dep['directory'] = os.path.join(repository_root, dep['directory'])
        handle_ext_source_dep(dep, clean, env, verbose)

    external_dependencies = {dep['name']: dep for dep in ext_deps}

    LOG.info('Getting external dependencies done.')

    # Create package folder layout.
    create_folder_layout(output_dir, package_layout)

    # Check scan-build-py (intercept).
    LOG.info('Checking source: llvm scan-build-py (intercept)')

    intercept_build_executable = find_executable('intercept-build')

    if intercept_build_executable is not None:
        LOG.info('Available')
    else:
        if platform.system() == 'Darwin':
            LOG.error('Not exists, scan-build-py (intercept) '
                      'is mandatory on OS X!')
            sys.exit(1)
        # Build ld logger because intercept is not available.
        if platform.system() == 'Linux':
            LOG.warning('Not exists, build ld logger')
            ld_logger_path = build_package_config['ld_logger_path']
            if ld_logger_path:
                ld_logger_build = os.path.join(ld_logger_path, 'build')

                ld_logger32 = build_package_config.get('ld_logger_32')
                ld_logger64 = build_package_config.get('ld_logger_64')
                rebuild = build_package_config.get('rebuild_ld_logger') or clean

                arch = None
                if ld_logger32 == ld_logger64:
                    # Build both versions.
                    pass
                elif ld_logger32:
                    arch = '32'
                elif ld_logger64:
                    arch = '64'

                if build_ld_logger(ld_logger_path, env, arch, rebuild, verbose):
                    LOG.error('Failed to build ld logger')
                    sys.exit()

                # Copy ld logger files.
                target = os.path.join(package_root, package_layout['ld_logger'])

                copy_tree(ld_logger_build, target)

                curr_dir = os.getcwd()
                os.chdir(os.path.join(package_root, package_layout['bin']))
                logger_symlink = os.path.join('../',
                                              package_layout['ld_logger'],
                                              'bin', 'ldlogger')
                os.symlink(logger_symlink, 'ldlogger')
                os.chdir(curr_dir)

            else:
                LOG.info('Skipping ld logger from package')

    thrift_files_dir = os.path.join(repository_root,
                                    build_package_config['local_build_folder'])
    generated_py_files = os.path.join(thrift_files_dir, 'gen-py')
    generated_js_files = os.path.join(thrift_files_dir, 'gen-js')

    target = os.path.join(package_root, package_layout['codechecker_gen'])
    copy_tree(generated_py_files, target)

    target = os.path.join(package_root, package_layout['web_client'])
    copy_tree(generated_js_files, target)

    # The cmd_line client.
    cmdline_client_files = os.path.join(repository_root,
                                        'viewer_clients',
                                        'cmdline_client')
    target = os.path.join(package_root, package_layout['cmdline_client'])
    copy_tree(cmdline_client_files, target)

    # Documentation files.
    source = os.path.join(repository_root,
                          build_package_config['local_build_folder'],
                          'gen-docs', 'html')
    target = os.path.join(package_root, package_layout['docs'])
    copy_tree(source, target)

    source = os.path.join(repository_root, 'docs', 'checker_docs')
    target = os.path.join(package_root, package_layout['checker_md_docs'])
    copy_tree(source, target)

    # Thift js.
    thrift_dep = external_dependencies['thrift']
    thrift_root = os.path.join(repository_root, thrift_dep.get('directory'))
    thift_js_files = os.path.join(thrift_root, 'lib', 'js', 'src')
    target = os.path.join(package_root, package_layout['js_thrift'])
    copy_tree(thift_js_files, target)

    # CodeMirror.
    codemirror_dep = external_dependencies['codemirror']
    codemirror_root = os.path.join(repository_root,
                                   codemirror_dep.get('directory'))
    target = os.path.join(package_root,
                          package_layout['web_client_codemirror'])
    copy_tree(codemirror_root, target)

    # HighlightJs.
    highlightjs_dep = external_dependencies['highlightjs']
    highlightjs_root = os.path.join(repository_root,
                                    highlightjs_dep.get('directory'))
    target = os.path.join(package_root,
                          package_layout['web_client_highlightjs'])
    copy_tree(highlightjs_root, target)

    # HighlightJs_css.
    highlightjs_css_dep = external_dependencies['highlightjs_css']
    highlightjs_css_root = os.path.join(repository_root,
                                        highlightjs_css_dep.get('directory'))
    target = os.path.join(package_root,
                          package_layout['web_client_highlightjs'])
    target = os.path.join(target, 'css')
    copy_tree(highlightjs_css_root, target)

    # Dojo.
    dojo_dep = external_dependencies['dojotoolkit']
    file_url = dojo_dep['source_package']['url']
    url_data = urlparse.urlparse(file_url)
    head, file_name = ntpath.split(url_data.path)
    head, tail = file_name.split('.tar.gz')

    dojo_root = os.path.join(repository_root, dojo_dep.get('directory'))
    dojo_root = os.path.join(dojo_root, head)
    target = os.path.join(package_root, package_layout['web_client_dojo'])
    copy_tree(dojo_root, target)

    # Marked.
    marked_dep = external_dependencies['marked']
    marked_root = os.path.join(repository_root, marked_dep.get('directory'))
    target = os.path.join(package_root, package_layout['web_client_marked'])
    shutil.copy(os.path.join(marked_root, 'marked.min.js'), target)

    # JsPlumb.
    jsplumb_dep = external_dependencies['jsplumb']
    jsplumb_root = os.path.join(repository_root, jsplumb_dep.get('directory'))
    target = os.path.join(package_root, package_layout['web_client_jsplumb'])
    jsplumb = os.path.join(jsplumb_root, 'dist', 'js',
                           'jquery.jsPlumb-1.7.6-min.js')
    shutil.copy(jsplumb, target)

    # Add jQuery for JsPlumb.
    target = os.path.join(target, 'external')
    if not os.path.exists(target):
        os.mkdir(target)
    jquery = os.path.join(jsplumb_root, 'external',
                          'jquery-1.9.0-min.js')
    shutil.copy(jquery, target)

    # config files
    LOG.debug('Copy config files')
    source = os.path.join(repository_root, 'config')
    target = os.path.join(package_root, package_layout['config'])
    copy_tree(source, target)

    version_file = os.path.join(target, 'version.json')
    LOG.debug('Extending version file: ' + version_file)

    with open(version_file) as v_file:
        version_json_data = json.load(v_file)

    git_hash = ''
    try:
        git_hash_cmd = ['git', 'rev-parse', 'HEAD']
        git_hash = subprocess.check_output(git_hash_cmd,
                                           cwd=repository_root)
        git_hash = str(git_hash.rstrip())
    except subprocess.CalledProcessError as cperr:
        LOG.error('Failed to get last commit hash.')
        LOG.error(str(cperr))
    except OSError as oerr:
        LOG.error('Failed to run command:' + ' '.join(git_hash_cmd))
        LOG.error(str(oerr))
        sys.exit(1)

    version_json_data['git_hash'] = git_hash

    time_now = time.strftime("%Y-%m-%dT%H:%M")
    version_json_data['package_build_date'] = time_now

    # Rewrite version config file with the extended data.
    with open(version_file, 'w') as v_file:
        v_file.write(json.dumps(version_json_data, sort_keys=True, indent=4))

    # CodeChecker web client.
    LOG.debug('Copy web client files')
    source = os.path.join(repository_root, 'viewer_clients',
                          'web-client')
    target = os.path.join(package_root, package_layout['www'])
    copy_tree(source, target)

    # CodeChecker main scripts.
    LOG.debug('Copy main codechecker files')
    source = os.path.join(repository_root, 'codechecker', 'CodeChecker.py')
    target = os.path.join(package_root, package_layout['cc_bin'])
    shutil.copy2(source, target)

    source = os.path.join(repository_root, 'codechecker', 'CodeChecker')
    target = os.path.join(package_root, package_layout['bin'])
    shutil.copy2(source, target)

    # CodeChecker modules.
    LOG.debug('Copy codechecker modules')
    source = os.path.join(repository_root, 'codechecker_lib')
    target = os.path.join(package_root, package_layout['codechecker_lib'])
    copy_tree(source, target)

    # CodeChecker db model.
    LOG.debug('Copy codechecker database model')
    source = os.path.join(repository_root, 'db_model')
    target = os.path.join(package_root, package_layout['codechecker_db_model'])
    copy_tree(source, target)

    # CodeChecker db migrate.
    LOG.debug('Copy codechecker database migration')
    source = os.path.join(repository_root, 'db_migrate')
    target = os.path.join(package_root,
                          package_layout['codechecker_db_migrate'])
    copy_tree(source, target)

    # CodeChecker storage server.
    LOG.debug('Copy codechecker storage server')
    source = os.path.join(repository_root, 'storage_server')
    target = os.path.join(package_root,
                          package_layout['storage_server_modules'])
    copy_tree(source, target)

    # CodeChecker daemon server.
    LOG.debug('Copy codechecker daemon server')
    source = os.path.join(repository_root, 'daemon')
    target = os.path.join(package_root,
                          package_layout['daemon_modules'])
    copy_tree(source, target)

    # CodeChecker viewer server.
    LOG.debug('Copy codechecker viewer server')
    source = os.path.join(repository_root, 'viewer_server')
    target = os.path.join(package_root,
                          package_layout['viewer_server_modules'])
    copy_tree(source, target)

    # License.
    license_file = os.path.join(repository_root, 'LICENSE.TXT')
    target = os.path.join(package_root)
    shutil.copy(license_file, target)

    compress = build_package_config.get('compress')
    if compress:
        LOG.info('Compressing package ...')
        compress_to_tar(package_root, output_dir, compress)
    LOG.info('Creating package finished successfully.')


# -------------------------------------------------------------------
def main():
    """ Main script. """

    description = '''CodeChecker packager script'''

    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=description)

    parser.add_argument("-l", action="store",
                        dest="package_layout_config",
                        help="Package layout configuration file.")
    parser.add_argument("-o", "--output", required=True, action="store",
                        dest="output_dir")
    parser.add_argument("-b", "--build-folder",
                        dest="local_build_folder",
                        default="build",
                        help="The local dependency folder under which Thrift "
                             "and documentation files have been generated.")
    parser.add_argument("--clean",
                        action="store_true",
                        dest='clean',
                        help='Clean external dependencies')


    logger_group = parser.add_argument_group('ld-logger')
    logger_group.add_argument("--ld-logger", action="store",
                              dest="ld_logger_path",
                              help="Ld logger source path.")
    logger_group.add_argument('--32', action='store_true',
                              dest="ld_logger_32",
                              help='Build for 32bit architecture.')
    logger_group.add_argument('--64', action='store_true',
                              dest="ld_logger_64",
                              help='Build for 64bit architecture.')
    logger_group.add_argument('--rebuild', action='store_true',
                              dest='rebuild_ld_logger',
                              help='Clean and rebuild logger.')

    parser.add_argument("--compress", action="store",
                        dest="compress", default=False,
                        help="Compress package to tar.gz")

    parser.add_argument("-v", action="store_true", dest="verbose_log",
                        help='Set log level to higher verbosity.')

    args = vars(parser.parse_args())


    build_package_config = {k: args[k] for k in args if args[k] is not None}

    repository_root = os.environ['REPO_ROOT']
    default_package_layout = os.path.join(repository_root,
                                          "config",
                                          "package_layout.json")
    build_package_config['package_layout_config'] = default_package_layout

    default_logger_dir = os.path.join(repository_root,
                                      'external-source-deps',
                                      'build-logger')

    build_package_config['ld_logger_path'] = default_logger_dir

    build_package(repository_root, build_package_config)


if __name__ == "__main__":
    main()
