# CodeChecker Userguide

## CodeChecker usage

First of all, you have to setup the environment for CodeChecker.
Codechecker server uses SQLite database (by default) to store the results which is also packed into the package.

The next step is to start the CodeChecker main script.
The main script can be started with different options.

~~~~~~~~~~~~~~~~~~~~~
usage: CodeChecker [-h]

                   {check,quickcheck,log,checkers,server,cmd,debug,plist,version}
                   ...

Run the CodeChecker source analyzer framework.
See the subcommands for specific features.

positional arguments:
  {check,quickcheck,log,checkers,server,cmd,debug,plist,version}
                        commands
    check               Run the supported source code analyzers on a project.
    quickcheck          Run CodeChecker for aproject without database.
    log                 Runs the given build command. During the build the
                        compilation commands are collected and stored into a
                        compilation command json file (no analysis is done
                        during the build).
    checkers            List the available checkers for the supported
                        analyzers and show their default status (+ for being
                        enabled, - for being disabled by default).
    server              Start the CodeChecker web server.
    daemon              Start the CodeChecker remote checker server.
    cmd                 Command line client
    debug               Generate gdb debug dump files for all the failed
                        compilation commands in the last analyzer run.
                        Requires a database with the failed compilation
                        commands.
    plist               Parse plist files in the given directory.
    version             Print package version information.

optional arguments:
  -h, --help            show this help message and exit

Example usage:
--------------
Analyzing a project with default settings:
CodeChecker check -w ~/workspace -b "cd ~/myproject && make" -n myproject

Start the viewer to see the results:
CodeChecker server -w ~/workspace

~~~~~~~~~~~~~~~~~~~~~


## Default configuration:

Used ports:
* 5432 - PostgreSQL
* 8001 - CodeChecker result viewer
* 8002 - CodeChecker daemon

## 1. log mode:

Just build your project and create a log file but do not invoke the source code analysis.

~~~~~~~~~~~~~~~~~~~~~
$CodeChecker log --help
usage: CodeChecker log [-h] -o LOGFILE -b COMMAND

optional arguments:
  -h, --help            show this help message and exit
  -o LOGFILE, --output LOGFILE
                        Path to the log file.
  -b COMMAND, --build COMMAND
                        Build command.
~~~~~~~~~~~~~~~~~~~~~

You can change the compilers that should be logged.
Set CC_LOGGER_GCC_LIKE environment variable to a colon separated list.
For example (default):

~~~~~~~~~~~~~~~~~~~~~
export CC_LOGGER_GCC_LIKE="gcc:g++:clang"
~~~~~~~~~~~~~~~~~~~~~

Example:

~~~~~~~~~~~~~~~~~~~~~
CodeChecker log -o ../codechecker_myProject_build.log -b "make -j2"
~~~~~~~~~~~~~~~~~~~~~

Note:
In case you want to analyze your whole project, do not forget to clean your build tree before logging.

## 2. check mode:

### Basic Usage

Database and connections will be automatically configured.
The main script starts and setups everything what is required for analyzing a project (database server, tables ...).

~~~~~~~~~~~~~~~~~~~~~
CodeChecker check -w codechecker_workspace -n myTestProject -b "make"
~~~~~~~~~~~~~~~~~~~~~

Static analysis can be started also by using an already generated buildlog (see log mode).
If log is not available the analyzer will automatically create it.
An already created CMake json compilation database can be used as well.

~~~~~~~~~~~~~~~~~~~~~
CodeChecker check -w ~/codechecker_wp -n myProject -l ~/codechecker_wp/build_log.json
~~~~~~~~~~~~~~~~~~~~~

### Advanced Usage

~~~~~~~~~~~~~~~~~~~~~
usage: CodeChecker check [-h] [-w WORKSPACE] -n NAME (-b COMMAND | -l LOGFILE)
                         [-j JOBS] [-u SUPPRESS] [-c [DEPRECATED]]
                         [--update [DEPRECATED]] [--force] [-s SKIPFILE]
                         [--quiet-build] [--add-compiler-defaults]
                         [--remote-host REMOTE_HOST]
                         [--remote-port REMOTE_PORT] [--remote-keep-alive]
                         [-e ENABLE] [-d DISABLE] [--keep-tmp]
                         [--analyzers ANALYZERS [ANALYZERS ...]]
                         [--saargs CLANGSA_ARGS_CFG_FILE]
                         [--tidyargs TIDY_ARGS_CFG_FILE]
                         [--sqlite [DEPRECATED]] [--postgresql]
                         [--dbport DBPORT] [--dbaddress DBADDRESS]
                         [--dbname DBNAME] [--dbusername DBUSERNAME]
                         [--verbose {info,debug,debug_analyzer}]

optional arguments:
  -h, --help            show this help message and exit
  -w WORKSPACE, --workspace WORKSPACE
                        Directory where the CodeChecker can store analysis
                        related data. (default: /home/username/.codechecker)
  -n NAME, --name NAME  Name of the analysis.
  -b COMMAND, --build COMMAND
                        Build command which is used to build the project.
  -l LOGFILE, --log LOGFILE
                        Path to the log file which is created during the
                        build. If there is an already generated log file with
                        the compilation commands generated by 'CodeChecker
                        log' or 'cmake -DCMAKE_EXPORT_COMPILE_COMMANDS'
                        CodeChecker check can use it for the analysis in that
                        case running the original build will be left out from
                        the analysis process (no log is needed).
  -j JOBS, --jobs JOBS  Number of jobs.Start multiple processes for faster
                        analysis. (default: 1)
  -u SUPPRESS, --suppress SUPPRESS
                        Path to suppress file. Suppress file can be used to
                        suppress analysis results during the analysis. It is
                        based on the bug identifier generated by the compiler
                        which is experimental. Do not depend too much on this
                        file because identifier or file format can be changed.
                        For other in source suppress features see the user
                        guide.
  -c [DEPRECATED], --clean [DEPRECATED]
                        DEPRECATED argument! (default: None)
  --update [DEPRECATED]
                        DEPRECATED argument! (default: None)
  --force               Delete analysis results form the database if a run
                        with the given name already exists. (default: False)
  -s SKIPFILE, --skip SKIPFILE
                        Path to skip file.
  --quiet-build         Do not print out the output of the original build.
                        (default: False)
  --add-compiler-defaults
                        Fetch built in compiler includepaths and defines and
                        pass them to Clang. This isuseful when you do cross-
                        compilation. (default: False)
  --remote-host REMOTE_HOST, --host REMOTE_HOST, -r REMOTE_HOST
                        Use a remote daemon available at this host to check
                        the project instead of the local computer
  --remote-port REMOTE_PORT, -p REMOTE_PORT
                        Use a remote daemon available on this port to check
                        the project, instead of a local instance.
  --remote-keep-alive   If set, the local command will not exit until the
                        server reports that checking has finished.
  -e ENABLE, --enable ENABLE
                        Enable checker.
  -d DISABLE, --disable DISABLE
                        Disable checker.
  --keep-tmp            Keep temporary report files generated during the
                        analysis. (default: False)
  --analyzers ANALYZERS [ANALYZERS ...]
                        Select which analyzer should be enabled. Currently
                        supported analyzers are: clangsa clang-tidy e.g. '--
                        analyzers clangsa clang-tidy' (default: ['clangsa',
                        'clang-tidy'])
  --saargs CLANGSA_ARGS_CFG_FILE
                        File with arguments which will be forwarded directly
                        to the Clang static analyzer without modification.
  --tidyargs TIDY_ARGS_CFG_FILE
                        File with arguments which will be forwarded directly
                        to the Clang tidy analyzer without modification.
  --sqlite [DEPRECATED]
                        DEPRECATED argument! (default: None)
  --postgresql          Use PostgreSQL database. (default: False)
  --dbport DBPORT       Postgres server port. (default: 5432)
  --dbaddress DBADDRESS
                        Postgres database server address. (default: localhost)
  --dbname DBNAME       Name of the database. (default: codechecker)
  --dbusername DBUSERNAME
                        Database user name. (default: codechecker)
  --verbose {info,debug,debug_analyzer}
                        Set verbosity level. (default: info)
~~~~~~~~~~~~~~~~~~~~~

CodeChecker is able to handle several analyzer tools. Currently CodeChecker
supports Clang Static Analyzer and Clang Tidy. `CodeChecker checkers`
command lists all checkers from each analyzers. These can be switched on and off
by `-e` and `-d` flags. Furthermore `--analyzers` specifies which
analyzer tool should be used (both by default). The tools are completely
independent, so either can be omitted if not present as these are provided by
different binaries.

#### Forward compiler options

These options can modify the compilation actions logged by the build logger or
created by cmake (exporting compile commands). The extra compiler options can be
given in config files which are provided by the flags described below.

The config files can contain placeholders in `$(ENV_VAR)` format. If the
`ENV_VAR` environment variable is set then the placeholder is replaced to its
value. Otherwise an error message is logged saying that the variable is not set,
and in this case an empty string is inserted in the place of the placeholder.

##### Clang Static Analyzer

Use the `--saargs` argument to a file which contains compilation options.


    CodeChecker check --saargs extra_compile_flags -n myProject -b "make -j4"


Where the extra_compile_flags file contains additional compilation options.

Config file example:

~~~~
-I~/include/for/analysis -I$(MY_LIB)/include -DDEBUG
~~~~

where `MY_LIB` is the path of a library code.

##### Clang-tidy

Use the `--tidyargs` argument to a file which contains compilation options.

    CodeChecker check --tidyargs extra_tidy_compile_flags -n myProject -b "make -j4"

Where the extra_compile_flags file contains additional compilation flags.
Clang tidy requires a different format to add compilation options.
Compilation options can be added before ( `-extra-arg-before=<string>` ) and
after (`-extra-arg=<string>`) the original compilation options.

Config file example:

    -extra-arg-before='-I~/include/for/analysis' -extra-arg-before='-I~/other/include/for/analysis/' -extra-arg-before='-I$(MY_LIB)/include' -extra-arg='-DDEBUG'

where `MY_LIB` is the path of a library code.

### Using SQLite for database:

CodeChecker can also use SQLite for storing the results. In this case the
SQLite database will be created in the workspace directory.

In order to use PostgreSQL instead of SQLite, use the `--postgresql` command
line argument for `CodeChecker server` and `CodeChecker check`
commands. If `--postgresql` is not given then SQLite is used by default in
which case `--dbport`, `--dbaddress`, `--dbname`, and
`--dbusername` command line arguments are ignored.

#### Note:
Schema migration is not supported with SQLite. This means if you upgrade your
CodeChecker to a newer version, you might need to re-check your project.

### Suppression in the source:

Suppress comments can be used in the source to suppress specific or all checker results found in a source line.
Suppress comment should be above the line where the bug was found no empty lines are allowed between the line with the bug and the suppress comment.
Only comment lines staring with "//" are supported

Supported comment formats:

~~~~~~~~~~~~~~~~~~~~~
void test() {
  int x;
  // codechecker_suppress [deadcode.DeadStores] suppress deadcode
  x = 1; // warn
}
~~~~~~~~~~~~~~~~~~~~~

~~~~~~~~~~~~~~~~~~~~~
void test() {
  int x;
  // codechecker_suppress [all] suppress all checker results
  x = 1; // warn
}
~~~~~~~~~~~~~~~~~~~~~

~~~~~~~~~~~~~~~~~~~~~
void test() {
  int x;

  // codechecker_suppress [all] suppress all
  // checker resuls
  // with a long
  // comment
  x = 1; // warn
}
~~~~~~~~~~~~~~~~~~~~~

### Suppress file:

~~~~~~~~~~~~~~~~~~~~~
-u SUPPRESS
~~~~~~~~~~~~~~~~~~~~~

Suppress file can contain bug hashes and comments.
Suppressed bugs will not be showed in the viewer by default.
Usually a reason to suppress a bug is a false positive result (reporting a non-existent bug). Such false positives should be reported, so we can fix the checkers.
A comment can be added to suppressed reports that describes why that report is false positive. You should not edit suppress file by hand. The server should handle it.
The suppress file can be checked into the source code repository.
Bugs can be suppressed on the viewer even when suppress file was not set by command line arguments. This case the suppress will not be permanent. For this reason it is
advised to always provide (the same) suppress file for the checks.

### Skip file:

~~~~~~~~~~~~~~~~~~~~~
-s SKIPFILE, --skip SKIPFILE
~~~~~~~~~~~~~~~~~~~~~
With a skip file you can filter which files should or shouldn't be checked.
Each line in a skip file should start with a '-' or '+' character followed by a path glob pattern. A minus character means that if a checked file path - including the headers - matches with the pattern, the file will not be checked. The plus character means the opposite: if a file path matches with the pattern, it will be checked.
CodeChecker reads the file from top to bottom and stops at the first matching pattern.

For example:

~~~~~~~~~~~~~~~~~~~~~
-/skip/all/source/in/directory*
-/do/not/check/this.file
+/dir/check.this.file
-/dir/*
~~~~~~~~~~~~~~~~~~~~~

### Enable/Disable checkers

~~~~~~~~~~~~~~~~~~~~~
-e ENABLE, --enable ENABLE
-d DISABLE, --disable DISABLE
~~~~~~~~~~~~~~~~~~~~~
You can enable or disable checkers or checker groups. If you want to enable more checker groups use -e multiple times. To get the actual list of checkers run ```CodeChecer checkers``` command.
For example if you want to enable core and security checkers, but want to disable alpha checkers use

~~~~~~~~~~~~~~~~~~~~~
CodeChecker check -e core -e security -d alpha ...
~~~~~~~~~~~~~~~~~~~~~

### Multithreaded Checking

~~~~~~~~~~~~~~~~~~~~~
-j JOBS, --jobs JOBS  Number of jobs.
~~~~~~~~~~~~~~~~~~~~~
CodeChecker will execute analysis on as many threads as specified after -j argument.

### Remote checking
~~~~~~~~~~~~~~~~~~~~~
  --remote-host REMOTE_HOST, --host REMOTE_HOST, -r REMOTE_HOST
                        Use a remote daemon available at this host to check
                        the project instead of the local computer
  --remote-port REMOTE_PORT, -p REMOTE_PORT
                        Use a remote daemon available on this port to check
                        the project, instead of a local instance.
  --remote-keep-alive   If set, the local command will not exit until the
                        server reports that checking has finished.
~~~~~~~~~~~~~~~~~~~~~
Specify the daemon server to use as analysis host. Read more about [daemon
mode](docs/daemon.md).

### Various deployment possibilities

The CodeChecker server can be started separately when desired.
In that case multiple clients can use the same database to store new results or view old ones.


#### Codechecker server and database on the same machine

Codechecker server and the database are running on the same machine but the database server is started manually.
In this case the database handler and the database can be started manually by running the server command.
The workspace needs to be provided for both the server and the check commands.

~~~~~~~~~~~~~~~~~~~~~
CodeChecker server -w ~/codechecker_wp --dbname myProjectdb --dbport 5432 --dbaddress localhost --view-port 8001
~~~~~~~~~~~~~~~~~~~~~

The checking process can be started separately on the same machine

~~~~~~~~~~~~~~~~~~~~~
CodeChecker check  -w ~/codechecker_wp -n myProject -b "make -j 4" --dbname myProjectdb --dbaddress localhost --dbport 5432
~~~~~~~~~~~~~~~~~~~~~

or on a different machine

~~~~~~~~~~~~~~~~~~~~~
CodeChecker check  -w ~/codechecker_wp -n myProject -b "make -j 4" --dbname myProjectdb --dbaddress 192.168.1.1 --dbport 5432
~~~~~~~~~~~~~~~~~~~~~


#### Codechecker server and database are on different machines

It is possible that the CodeChecker server and the PostgreSQL database that contains the analysis results are on different machines. To setup PostgreSQL see later section.

In this case the CodeChecker server can be started using the following command:

~~~~~~~~~~~~~~~~~~~~~
CodeChecker server --dbname myProjectdb --dbport 5432 --dbaddress 192.168.1.2 --view-port 8001
~~~~~~~~~~~~~~~~~~~~~

Start CodeChecker server locally which connects to a remote database (which is started separately). Workspace is not required in this case.


Start the checking as explained previously.

~~~~~~~~~~~~~~~~~~~~~
CodeChecker check -w ~/codechecker_wp -n myProject -b "make -j 4" --dbname myProjectdb --dbaddress 192.168.1.2 --dbport 5432
~~~~~~~~~~~~~~~~~~~~~

## 3. Quick check mode:

It's possible to quickly check a small project (set of files) for bugs without
storing the results into a database. In this case only the build command is
required and the defect list appears on the console. The defect list doesn't
shows the bug paths by default but you can turn it on using the --steps command
line parameter.

Basic usage:

~~~~~~~~~~~~~~~~~~~~~
CodeChecker quickcheck -b 'make'
~~~~~~~~~~~~~~~~~~~~~

Enabling bug path:

~~~~~~~~~~~~~~~~~~~~~
CodeChecker quickcheck -b 'make' --steps
~~~~~~~~~~~~~~~~~~~~~

Usage:

~~~~~~~~~~~~~~~~~~~~~
usage: CodeChecker quickcheck [-h] (-b COMMAND | -l LOGFILE) [-e ENABLE]
                                 [-d DISABLE] [-s]

optional arguments:
  -h, --help            show this help message and exit
  -b COMMAND, --build COMMAND
                        Build command.
  -l LOGFILE, --log LOGFILE
                        Path to the log file which is created during the
                        build.
  -e ENABLE, --enable ENABLE
                        Enable checker.
  -d DISABLE, --disable DISABLE
                        Disable checker.
  -s, --steps           Print steps.
~~~~~~~~~~~~~~~~~~~~~

## 4. checkers mode:

List all available checkers.

The ```+``` (or ```-```) sign before a name of a checker shows whether the checker is enabled (or disabled) by default.

~~~~~~~~~~~~~~~~~~~~~
CodeChecker checkers
~~~~~~~~~~~~~~~~~~~~~


## 5. cmd mode:

A lightweigh command line interface to query the results of an analysis.
It is a suitable client to integrate with continuous integration, schedule maintenance tasks and verifying correct analysis process.
The commands always need a viewer port of an already running CodeChecker server instance (which can be started using CodeChecker server command).

~~~~~~~~~~~~~~~~~~~~~
usage: CodeChecker cmd [-h] {runs,results,sum,del} ...

positional arguments:
  {runs,results,diff,sum,del}
    runs                Get the run data.
    results             List results.
    diff                Diff two runs.
    sum                 Summarize the results of the run.
    del                 Remove run results.

optional arguments:
  -h, --help            show this help message and exit
~~~~~~~~~~~~~~~~~~~~~
## 6. plist mode:
Clang Static Analyzer's scan-build script can generate analyis output into plist xml files. 
In this You can import these files into the database.
You will need to specify containing the plist files afther the -d option.

Example:
~~~~~~~~~~~~~~~~~~~~~
CodeChecker plist -d ./results_plist -n myresults
~~~~~~~~~~~~~~~~~~~~~


## 7. debug mode:

In debug mode CodeChecker can generate logs for failed build actions. The logs can be helpful debugging the checkers.

## Example Usage

### Checking files

Checking with some extra checkers disabled and enabled

~~~~~~~~~~~~~~~~~~~~~
CodeChecker check -w ~/Develop/workspace -j 4 -b "cd ~/Libraries/myproject && make clean && make -j4" -s ~/Develop/skip.list -u ~/Develop/suppress.txt -e unix.Malloc -d core.uninitialized.Branch  -n MyLittleProject -c --dbport 5432 --dbname cctestdb
~~~~~~~~~~~~~~~~~~~~~

### View results

To view the results CodeChecker sever needs to be started.

~~~~~~~~~~~~~~~~~~~~~
CodeChecker server -w ~/codes/package/checker_ws/ --dbport 5432 --dbaddress localhost
~~~~~~~~~~~~~~~~~~~~~

After the server has started open the outputed link to the browser (localhost:8001 in this example).

~~~~~~~~~~~~~~~~~~~~~
[11318] - WARNING! No suppress file was given, suppressed results will be only stored in the database.
[11318] - Checking for database
[11318] - Database is not running yet
[11318] - Starting database
[11318] - Waiting for client requests on [localhost:8001]
~~~~~~~~~~~~~~~~~~~~~

### Run CodeChecker distributed in a cluster

You may want to configure CodeChecker to do the analysis on separate machines in a distributed way.
Start the postgres database on a central machine (in this example it is called codechecker.central) on a remotely accessible address and port and then run
```CodeChecker check``` on multiple machines (called host1 and host2), specify the remote dbaddress and dbport and use the same run name.

Create and start an empty database to which the CodeChecker server can connect.

#### Setup PostgreSQL (one time only)

Before the first use, you have to setup PostgreSQL.
PostgreSQL stores its data files in a data directory, so before you start the PostgreSQL server you have to create and init this data directory.
I will call the data directory to pgsql_data.

Do the following steps:

~~~~~~~~~~~~~~~~~~~~~
# on machine codechecker.central

mkdir -p /path/to/pgsql_data
initdb -U codechecker -D /path/to/pgsql_data -E "SQL_ASCII"
# Start PostgreSQL server on port 5432
postgres -U codechecker -D /path/to/pgsql_data -p 5432 &>pgsql_log &
~~~~~~~~~~~~~~~~~~~~~

#### Run CodeChecker on multiple hosts

Then you can run CodeChecker on multiple hosts but using the same run name (in this example this is called "distributed_run".
postgres is listening on codechecker.central port 9999.

~~~~~~~~~~~~~~~~~~~~~
# On host1 we check module1
CodeChecker check -w /tmp/codechecker_ws -b "cd module_1;make" --dbport 5432 --dbaddress codechecker.central -n distributed_run

# On host2 we check module2
CodeChecker check -w /tmp/codechecker_ws -b "cd module_2;make" --dbport 5432 --dbaddress codechecker.central -n disributed_run
~~~~~~~~~~~~~~~~~~~~~


#### PostgreSQL authentication (optional)

If a CodeChecker is run with a user that needs database authentication, the
PGPASSFILE environment variable should be set to a pgpass file
For format and further information see PostgreSQL documentation:
http://www.postgresql.org/docs/current/static/libpq-pgpass.html

## Debugging CodeChecker

Command line flag can be used to turn in CodeChecker debug mode. The different
subcommands can be given a `-v` flag which needs a parameter. Possible values
are `debug`, `debug_analyzer` and `info`. Default is `info`.

`debug_analyzer` switches analyzer related logs on:

~~~~~~~~~~~~~~~~~~~~~
CodeChecker check -n <name> -b <build_command> --verbose debug_analyzer
~~~~~~~~~~~~~~~~~~~~~

Turning on CodeChecker debug level logging is possible for the most subcommands:

~~~~~~~~~~~~~~~~~~~~~
CodeChecker check -n <name> -b <build_command> --verbose debug
CodeChecker server -v <view_port> --verbose debug
~~~~~~~~~~~~~~~~~~~~~

If debug logging is enabled and PostgreSQL database is used, PostgreSQL logs are written to postgresql.log in the workspace directory.

Turn on SQL_ALCHEMY debug level logging

~~~~~~~~~~~~~~~~~~~~~
export CODECHECKER_ALCHEMY_LOG=True
~~~~~~~~~~~~~~~~~~~~~
