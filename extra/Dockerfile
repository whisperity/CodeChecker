FROM ubuntu:16.04

RUN apt-get update

# These are commented out so that the Debian package is forced to
# download and install the dependencies, just as how it would on a live system.
#RUN apt-get install -fy \
#     aptitude \
#     clang \
#     clang-tidy \
#     python \
#     python-pip

ADD docker_test.sh /usr/bin/docker-test
ADD *.deb /root

# dpkg install here fails as there are unmet dependencies...
RUN dpkg --install /root/*.deb || \
     echo "CodeChecker install begins"

RUN echo "Fixing unmet dependencies..."; \
     apt-get install -f -y

ENTRYPOINT ["/bin/bash", "-c", "force_color_prompt=yes /bin/bash docker-test"]
