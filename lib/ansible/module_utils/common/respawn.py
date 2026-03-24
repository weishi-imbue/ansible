from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import os
import subprocess
import sys

RESPAWN_SENTINEL = 'ANSIBLE_MODULE_RESPAWNED'


def has_respawned():
    """Return True if the current module process was respawned via respawn_module."""
    return os.environ.get(RESPAWN_SENTINEL) == '1'


def respawn_module(interpreter_path):
    """
    Re-execute the current Ansible module under the specified Python interpreter.

    This function will not return - it replaces the current process after
    the subprocess completes.

    :arg interpreter_path: Path to the Python interpreter to use for re-execution.
    :raises Exception: If the module has already been respawned.
    """
    if has_respawned():
        raise Exception('module has already been respawned')

    # The payload and arguments are passed via the module's __main__ globals
    # which are set by the AnsiballZ wrapper
    payload = _get_module_payload()

    env = os.environ.copy()
    env[RESPAWN_SENTINEL] = '1'

    rc = subprocess.call([interpreter_path, payload], env=env)
    sys.exit(rc)


def probe_interpreters_for_module(interpreter_paths, module_name):
    """
    Find the first interpreter from interpreter_paths that can import module_name.

    :arg interpreter_paths: List of Python interpreter paths to try.
    :arg module_name: The Python module name to attempt to import.
    :returns: The path to the first working interpreter, or None.
    """
    for interpreter in interpreter_paths:
        if not os.path.isfile(interpreter):
            continue
        try:
            rc = subprocess.call(
                [interpreter, '-c', 'import {0}'.format(module_name)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if rc == 0:
                return interpreter
        except (OSError, IOError):
            continue
    return None


def _get_module_payload():
    """Get the path to the current module payload (the AnsiballZ zipfile)."""
    # When running under AnsiballZ, sys.argv[0] is the path to the payload script
    return sys.argv[0]
