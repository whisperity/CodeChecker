#####################
# This script sets up the BASIC operating system required for CodeChecker:
#  - Bare minimum required system libs
#  - Bare minimum Python modules
#
# This code does NOT install a runnable CodeChecker package.
#####################

# Use latest Ubuntu LTS
FROM ubuntu:16.04

RUN apt-get update && \
     apt-get install --no-install-recommends -y \
       clang-3.8 \
       clang-tidy-3.8 \
       build-essential \
       curl \
       doxygen \
       gcc-multilib \
       git \
       python-dev \
       python-setuptools \
       python-virtualenv \
       thrift-compiler && \
     update-alternatives --install /usr/bin/clang clang /usr/bin/clang-3.8 0 && \
     update-alternatives --install /usr/bin/clang-tidy clang-tidy /usr/bin/clang-tidy-3.8 0

RUN easy_install pip && \
     pip install nose pg8000
