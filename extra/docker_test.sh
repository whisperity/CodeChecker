#!/bin/bash

#echo "Checking if CodeChecker is installed, if not, installing it..."
#dpkg --install /root/*.deb
#apt-get install -fy

echo "Checking if CodeChecker is installed?"
apt-cache show codechecker 2>/dev/null

if [ $? -ne 0 ]
then
  echo -e "\e[91mFAIL \e[39mto find installed package package."
  echo -e "Entering shell...\n\n"
  echo "export PS1='\[\033[01;31m\](docker!) \[\033[00m\]\A\[\033[00m\] ${debian_chroot:+($debian_chroot)}\[\033[01;31m\]\u@\h:\[\033[01;33m\]\w\[\033[01;31m\]\$\[\033[00m\] '" > ~/.bash_aliases
  /bin/bash

  exit $?
fi

echo "Running a CodeChecker default command"
CodeChecker

if [ $? -ne 2 ]
then
  echo -e "\e[91mFAIL \e[39mto run CC."
  echo -e "Entering shell...\n\n"
  echo "export PS1='\[\033[01;31m\](docker!) \[\033[00m\]\A\[\033[00m\] ${debian_chroot:+($debian_chroot)}\[\033[01;31m\]\u@\h:\[\033[01;33m\]\w\[\033[01;31m\]\$\[\033[00m\] '" > ~/.bash_aliases
  /bin/bash

  exit $?
else
  echo -e "\e[92mSUCCESS \e[39mran CC."
  echo -e "Entering shell...\n\n"

  echo "export PS1='\[\033[01;32m\](docker!) \[\033[00m\]\A\[\033[00m\] ${debian_chroot:+($debian_chroot)}\[\033[01;31m\]\u@\h:\[\033[01;33m\]\w\[\033[01;31m\]\$\[\033[00m\] '" > ~/.bash_aliases
  /bin/bash

  exit $?
fi
