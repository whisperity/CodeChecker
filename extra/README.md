`make-docker`
=============

**make-docker** is the CodeChecker [Docker](http://docker.com) image generator
tool.

`make-docker.py` creates a `Dockerfile` based on the invocation and 
compiles this `Dockerfile` into an image on the local computer.


Usage
-----

To build and run a bare minimal executable CodeChecker image, execute
the commands

    ./make-docker.py --install
    docker run --rm codechecker

This will create the `codechecker` docker image, which can be run by `docker
run codechecker`. The arguments to this container instance correspond to the
argument list of `CodeChecker` (see [Usage](/docs/usage.md)).

The script takes some extra arguments. For example, to build an image from the
latest CodeChecker release on GitHub with full support (such as PostgreSQL
database) with a custom name, execute the command: 

    ./make-docker.py --from stable --build full --install --name codechecker-full

### `from`

The `from` argument specifies which release is to be used as a base image.
The image is created from the `ubuntu:16.04` and then a CodeChecker source
is checked out inside.

Only **one** `from` argument can be specified.

  * `local` &ndash; uploads the current CodeChecker code (the developer's
    local working copy) where `make-docker.py` is ran.
  * `basic` &ndash; uses [the `master`
     branch](http://github.com/Ericsson/codechecker) from GitHub (this is
     the _default_)
  * `stable` &ndash; uses the [latest
    release](https://github.com/Ericsson/codechecker/releases/latest)

### `build`

The minimal install of CodeChecker doesn't support _all_ features available,
such as [PostgreSQL backend](/docs/postgresql_setup.md) and [Credential-only
access mode](/docs/authentication.md). Additional _packages_ can be specified in as an
argument to `build`, which causes the script to build further tools into the
resulting image.

  * `authentication` &ndash; enables credential access mode
  * `full` &ndash; enables PostgreSQL support

Use the `--help` command to always get an overview on which `from` and `build`
packages are available.

### `install`

Unless `--install` is specified, the resulting Docker image will **NOT** have
an _executable_ CodeChecker inside, image creation stops before fully setting
up CodeChecker. This is useful for creating an image that is to further be
changed or tooled upon. This way, you can create (and attach to) a container
from the image with

    docker run --rm -t -i codechecker /bin/bash

or use the resulting image as a
[`FROM`](https://docs.docker.com/engine/reference/builder/#/from) in your
own `Dockerfile`.

> In most cases, `--install` is present in the invocation.

If you specify `--install`, the Docker container will behave like it's a
CodeChecker binary:

    docker run codechecker cmd runs --host example.com

To access the filesystem of this container, you need to override the _entry 
point_:

    docker run --entrypoint /bin/bash codechecker

### `name`

Sets the resulting name of the built Docker image. By default, it's
`codechecker`. The [usual Docker image name
rules](https://docs.docker.com/engine/reference/commandline/build/) apply.
