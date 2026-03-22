# Copyright (c) 2021 Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import os
import sys
import subprocess
import tempfile
import json


def has_respawned():
    """
    Returns True if the current Ansible module process is a respawned instance
    (previously invoked via `respawn_module`), otherwise returns False.

    :returns: Boolean indicating if this is a respawned module instance
    """
    return os.environ.get('ANSIBLE_MODULE_RESPAWNED') == '1'


def respawn_module(interpreter_path):
    """
    Respawns the currently-running Ansible module under the specified Python
    interpreter, re-executing the module with its current arguments. Only one
    respawn is allowed; calling it again will raise an exception.

    :param interpreter_path: Path to the Python interpreter to use for respawn
    :raises: RuntimeError if module has already been respawned
    """
    if has_respawned():
        raise RuntimeError("Module has already been respawned and cannot be respawned again")

    # Get the current module's command line arguments
    # We need to reconstruct the module execution environment
    current_args = sys.argv[:]

    # Set environment variable to indicate this is a respawn
    env = os.environ.copy()
    env['ANSIBLE_MODULE_RESPAWNED'] = '1'

    # Get the module's globals to access _module_fqn and _modlib_path
    import __main__

    # These globals should be provided by the module execution harness
    module_fqn = getattr(__main__, '_module_fqn', None)
    modlib_path = getattr(__main__, '_modlib_path', None)

    if module_fqn and modlib_path:
        # If we have the proper globals, we can respawn using runpy
        # Create a script that sets up the environment and runs the module
        respawn_script = '''
import sys
import os
import runpy
import json

# Add the module library path to sys.path
modlib_path = {modlib_path!r}
if modlib_path not in sys.path:
    sys.path.insert(0, modlib_path)

# Import and set up the module arguments
from ansible.module_utils import basic
basic._ANSIBLE_ARGS = {ansible_args!r}

# Set the globals that modules expect
import __main__
__main__._module_fqn = {module_fqn!r}
__main__._modlib_path = {modlib_path!r}

# Run the module
runpy.run_module(mod_name={module_fqn!r}, init_globals={{
    '_module_fqn': {module_fqn!r},
    '_modlib_path': {modlib_path!r}
}}, run_name='__main__', alter_sys=True)
'''.format(
            module_fqn=module_fqn,
            modlib_path=modlib_path,
            ansible_args=getattr(basic, '_ANSIBLE_ARGS', '{}') if 'basic' in sys.modules else '{}'
        )

        # Write the respawn script to a temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(respawn_script)
            script_path = f.name

        try:
            # Execute the script with the new interpreter
            subprocess.check_call([interpreter_path, script_path], env=env)
        finally:
            # Clean up the temporary script
            try:
                os.unlink(script_path)
            except OSError:
                pass
    else:
        # Fallback: try to respawn using current arguments
        # This might not work in all cases but is better than nothing
        subprocess.check_call([interpreter_path] + current_args, env=env)

    # Exit the current process since the respawned process will handle execution
    sys.exit(0)


def probe_interpreters_for_module(interpreter_paths, module_name):
    """
    Returns the first Python interpreter path from `interpreter_paths` that can
    successfully import the specified `module_name`. Returns None if no compatible
    interpreter is found.

    :param interpreter_paths: List of Python interpreter paths to test
    :param module_name: Name of the module to test for import capability
    :returns: String path to compatible interpreter, or None if not found
    """
    import subprocess

    for interpreter_path in interpreter_paths:
        if not os.path.exists(interpreter_path) or not os.access(interpreter_path, os.X_OK):
            continue

        try:
            # Test if the interpreter can import the module
            test_script = '''
import sys
try:
    import {module_name}
    sys.exit(0)
except ImportError:
    sys.exit(1)
'''.format(module_name=module_name)

            result = subprocess.call(
                [interpreter_path, '-c', test_script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            if result == 0:
                return interpreter_path

        except (OSError, subprocess.CalledProcessError):
            # If we can't execute this interpreter, skip it
            continue

    return None