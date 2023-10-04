# -------------------------------------------------------------------------
#
#  Part of the CodeChecker project, under the Apache License v2.0 with
#  LLVM Exceptions. See LICENSE for license information.
#  SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
# -------------------------------------------------------------------------
"""
Handles the retrieval and access to a configuration structure loaded from
a file.
"""
from pathlib import Path, PurePosixPath
from typing import cast, Any, Callable, Dict, List, Optional, Union

from .logger import get_logger
from .util import load_json


LOG = get_logger("system")

_K_CONFIGURATION = "__configuration"
_K_OPTION_STORE = "__options"


class Option:
    """
    Encapsulates a configuration option which can be accessed by client
    code, optionally assigned, or even explicitly reloaded from the
    backing storage, should that change.
    """

    class CheckFailedError(Exception):
        def __init__(self, name: str):
            super().__init__("%s:@check() failed!" % name)

    class ReadOnlyError(Exception):
        def __init__(self, name: str):
            super().__init__("'%s' is read-only" % name)

    def __init__(self, name: str,
                 path: str,
                 default: Optional[Union[Any, Callable[[], Any]]] = None,
                 check: Optional[Callable[[Any], bool]] = None,
                 check_fail_msg: Optional[Union[Callable[[], str],
                                                str]] = None,
                 settable: bool = False,
                 updateable: bool = False,
                 description: Optional[str] = None):
        """
        Instantiates a new Option which designates, under a user-facing
        'name', an element accessible in a configuration dictionary, as
        specified by 'path'. The path to the variable is specified akin to
        an XPath expression. '/' is the root of the configuration
        dictionary, and each "directory" is a named key in a
        sub-dictionary. If the accessed element is a list, numeric indices
        must be used to address individual elements, after which dictionary
        dereferencing can continue.

        For example, "/max_run_count" denotes the child of the top level
        dict, whereas "/keepalive/enabled" is a child of a sub-tree.


        If the accessing fails to get the elements of the configuration
        dictionary and a 'KeyError' or 'IndexError' is hit, the 'default'
        value, or the result of the 'default' function, if any, is
        returned. If 'default' is unset, the error is raised unconditionally.

        'check' is an optional callback that is executed every time a
        non-default configuration option is read or a 'settable' option is set.
        During reading, if 'check' returns False or throws, the configured
        value will be considered bogus, and will be replaced by the 'default'.
        If 'default' is unset and 'check' fails, a ValueError is raised
        unconditionally. Setting a value that makes 'check' fail is not
        allowed, and results in a ValueError.

        In any case, if 'check' fails and 'check_fail_msg' is set, it is
        printed to the output LOG as a warning. If 'check_fail_msg' is a
        function, the function is called and its return value is printed to
        the output LOG.


        If the Option is 'settable', clients will be allowed to change the
        Option's value, and that change is kept **IN MEMORY** for
        subsequent reads.

        If the Option is 'updateable', the external Configuration Manager
        will respect the change to the Option's value when the
        configuration is reloaded, see 'reload()'. A change observed
        through a reload will be logged for auditing purposes!

        Writing to the source of the configuration in a persistent fashion
        is **NOT SUPPORTED**!
        """
        self._name = name
        self._description = description
        self._path = PurePosixPath(path)
        self._allow_set = settable
        self._allow_update = updateable
        self._default = default
        self._check = check
        self._check_fail_msg = check_fail_msg

    @property
    def name(self):
        return self._name

    @property
    def description(self):
        return self._description

    @property
    def path(self):
        return self._path

    @property
    def has_default(self):
        return self._default is not None

    @property
    def default(self):
        if not self.has_default:
            raise KeyError("@default")
        if callable(self._default):
            return self._default()
        return self._default

    def _descend_to_closest_parent(self, configuration: Dict) \
            -> Union[Dict, List]:
        """
        Descends the 'configuration' data structure based on the path
        leading to the Option, and returns the innermost parent data
        structure that contains the requested key.

        Examples:
            "/max_run_count" -> "/" (dict)
            "/keepalive/enabled" -> "/keepalive" (dict)
            "/authentication/method_pam/users/2" ->
                "/authentication/method_pam/users" (list)
        """
        tree: Union[Dict, List] = configuration
        for key in self._path.parts[1:-1]:
            if type(tree) is dict:
                tree = tree[key]
            elif type(tree) is list:
                try:
                    key_as_int = int(key)
                    tree = tree[key_as_int]
                except ValueError:
                    raise ValueError("Attempted to index a list "
                                     "with a non-integer!")
            else:
                raise TypeError("Attempted to member-access a "
                                "non-subscriptable configuration entry.")
        return tree

    @classmethod
    def __get_leaf(cls, parent: Union[Dict, List], name: str) -> Any:
        """
        Returns the leaf node, as identified by 'name', contained within
        the 'parent'.
        """
        if type(parent) is dict:
            return parent[name]
        if type(parent) is list:
            try:
                idx = int(name)
                try:
                    return parent[idx]
                except IndexError:
                    raise KeyError(str(idx))
            except ValueError:
                raise
        raise TypeError("Non-subscriptable parent object!")

    @classmethod
    def __set_leaf(cls, parent: Union[Dict, List],
                   name: str, value: Any) -> Any:
        """
        Assigns 'value' to the leaf node, as identified by 'name',
        contained within the 'parent'.
        """
        if type(parent) is dict:
            parent[name] = value
        if type(parent) is list:
            try:
                idx = int(name)
                try:
                    parent[idx] = value
                except IndexError:
                    raise KeyError(str(idx))
            except ValueError:
                raise
        raise TypeError("Non-subscriptable parent object!")

    def _run_check(self, value: Any) -> bool:
        if not self._check:
            return True
        if not self._check(value):
            if self._check_fail_msg:
                msg = self._check_fail_msg
                if callable(msg):
                    msg = msg()
                LOG.warning("Configuration invariant check() failed: %s", msg)
            raise self.CheckFailedError(self._name)
        return True

    def __call__(self, configuration: Dict) -> Any:
        """Reads and returns the value of the Option."""
        try:
            parent = self._descend_to_closest_parent(configuration)
            value = self.__get_leaf(parent, self._path.name)

            try:
                self._run_check(value)
            except Exception:
                if not self.has_default:
                    raise ValueError("check() failed for %s" % self.name)
                return self.default

            return value
        except KeyError:
            if not self.has_default:
                raise
            return self.default

    def set(self, configuration: Dict, value: Any):
        """
        Sets the value of the current Option in the given configuration data
        structure to 'value'. Calling this method is only valid if the Option
        is 'settable'.
        """
        if not self._allow_set:
            raise self.ReadOnlyError(self._name)
        try:
            self._run_check(value)
        except Exception:
            raise ValueError("Assigning value '%s' to '%s' would break "
                             "it's check() invariant!"
                             % (str(value), self._name))

        try:
            parent = self._descend_to_closest_parent(configuration)
            self.__set_leaf(parent, self._path.name, value)
        except KeyError:
            raise KeyError("Descent failed, invalid path: '%s'"
                           % str(self._path))


class Configuration:
    """
    Allows checked access to a configuration data structure.
    """

    def __init__(self, configuration_file: Path):
        """
        Initialise a new Configuration collection.

        :param configuration_file: The configuration file to be read and
            parsed. This file *MUST* exist to initialise this instance.
            The file *MUST* be in JSON format, currently this is the only one
            supported.
        """
        LOG.debug("%s reading '%s'...",
                  type(self).__name__, configuration_file)

        config_dict = load_json(str(configuration_file), None)
        if not config_dict:
            raise ValueError("Configuration file '%s' was invalid JSON. "
                             "The log output contains more information."
                             % str(configuration_file))

        # This code is frightening at first, but, unfortunately, the usual
        # 'self.member' syntax must be side-stepped so that __getattr__ and
        # __setattr__ can be implemented in a user-friendly way.
        object.__setattr__(self, _K_CONFIGURATION, config_dict)
        object.__setattr__(self, _K_OPTION_STORE, dict())

    def add_option(self, name: str, *args, **kwargs):
        """
        Helper method to ensure an option with the given 'name' is
        appropriately added to the Configuration instance.
        Additional arguments are forwarded to Options's constructor.
        """
        opt = Option(name, *args, **kwargs)
        self.__dict__[_K_OPTION_STORE][name] = opt
        return opt

    def __getattr__(self, name: str):
        """
        Helper method that makes configuration options available with the
        object member access . (dot) syntax.
        """
        options = self.__dict__[_K_OPTION_STORE]
        option: Optional[Option] = None
        try:
            option = options[name]
        except KeyError:
            # If the options dict did not contain the requested key, consider
            # it as if it did not exist at all.
            raise AttributeError(name)

        # The inability to actually read the value of the option is a different
        # type of error.
        configuration = self.__dict__[_K_CONFIGURATION]
        return cast(Option, option)(configuration)

    def __setattr__(self, name: str, value):
        """
        Helper method that makes configuration options settable through
        assigning a member accessed via the . (dot) operator.
        """
        options = self.__dict__[_K_OPTION_STORE]
        option: Optional[Option] = None
        try:
            option = options[name]
        except KeyError:
            # If the options dict did not contain the requested key, consider
            # it as if it did not exist at all.
            raise AttributeError(name)

        # The inability to actually write the value of the option is a
        # different type of error.
        configuration = self.__dict__[_K_CONFIGURATION]
        cast(Option, option).set(configuration, value)

    # def reload():
