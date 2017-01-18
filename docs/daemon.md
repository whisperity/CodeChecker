CodeChecker daemon mode
=======================

CodeChecker supports a daemon mode in which analysis is not run on the
developer computer which runs the build, but rather on a remote (team server,
corporate cloud) host.

# Setting up the daemon
~~~~~~~~~~~~~~~~~~~~~~
usage: CodeChecker daemon [-h] [-w WORKSPACE] [--port PORT] [--host HOST]
                          [-r RUNS] [-j JOBS] [--sqlite [DEPRECATED]]
                          [--postgresql] [--dbport DBPORT]
                          [--dbaddress DBADDRESS] [--dbname DBNAME]
                          [--dbusername DBUSERNAME]
                          [--verbose {info,debug,debug_analyzer}]

optional arguments:
  -h, --help            show this help message and exit
  -w WORKSPACE, --workspace WORKSPACE
                        Directory where the CodeChecker can store analysis
                        related data. (default: /home/username/.codechecker)
  --port PORT           Port used for daemon connection. (default: 8002)
  --host HOST           Server address. (default: localhost)
  -r RUNS, --runs RUNS  The maximum number of runs that can be executed
                        simultaneously. (default: 10)
  -j JOBS, --jobs JOBS  The maximum number of parallel analyzer jobs PER RUN
                        that can be executing. (default: 1)
  -l, --list            List daemons started by your user. (default: False)
  -s, --stop            Stops the daemon associated with the given view-port
                        and workspace. (default: False)
  --stop-all            Stops all of your running CodeChecker daemons.
                        (default: False)
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
~~~~~~~~~~~~~~~~~~~~~~

Starting a CodeChecker _daemon_ server requires executing the command:

    CodeChecker daemon

This command creates a CodeChecker workspace under `~/.codechecker`, which can
be overridden by the `--workspace` flag. The daemon also takes the optional
PostgreSQL database connection arguments, working in the same manner as
CodeChecker check](docs/user_guide.md) and [CodeChecker server]
(docs/user_guide.md).

The `--host` and `--port` argument specifies on which internet address and
port the daemon listens on.

----

A daemon alone is only capable of running analysis. To be able to view
results, you also need to start `CodeChecker server` with the **same**
workspace you started the daemon with.

## Limiting the number of actions
~~~~~~~~~~~~~~~~~
  -r RUNS, --runs RUNS  The maximum number of runs that can be executed
                        simultaneously. (default: 10)
  -j JOBS, --jobs JOBS  The maximum number of parallel analyzer jobs PER RUN
                        that can be executing. (default: 1)
~~~~~~~~~~~~~~~~~

# Running remote analysis

To execute an analysis on the remote server, the `CodeChecker check` command
takes some extra arguments.

~~~~~~~~~~~~~~~~~
  --remote-host REMOTE_HOST, --host REMOTE_HOST, -r REMOTE_HOST
                        Use a remote daemon available at this host to check
                        the project instead of the local computer
  --remote-port REMOTE_PORT, -p REMOTE_PORT
                        Use a remote daemon available on this port to check
                        the project, instead of a local instance.
  --remote-keep-alive   If set, the local command will not exit until the
                        server reports that checking has finished.
~~~~~~~~~~~~~~~~~


Append these arguments to your usual invocation and the analysis will take
place on the remote computer. For example:

    CodeChecker check --name my_project --build "make" --remote-host 192.168.1.100

CodeChecker will build the project as usual (or use an already existing
`build.json` file with the `--logfile` argument) and then upload the
neccessary data to the remote server and execute analysis.

If `--remote-keep-alive` is specified, your local CodeChecker will wait until
the server has finished analysing.

## View results after running remote analysis

Using the above example, the results can be viewed on the daemon host's
server [192.168.1.100:8001](http://192.168.1.100:8001).
