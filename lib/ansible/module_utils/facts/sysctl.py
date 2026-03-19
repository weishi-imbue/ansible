# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import re


def get_sysctl(module, prefixes):
    sysctl_cmd = module.get_bin_path('sysctl')
    if sysctl_cmd is None:
        raise ValueError("sysctl command not found")

    cmd = [sysctl_cmd]
    cmd.extend(prefixes)

    try:
        rc, out, err = module.run_command(cmd)
    except (IOError, OSError) as e:
        module.warn("Unable to read sysctl: %s" % str(e))
        return dict()

    if rc != 0:
        error_msg = err.strip() if err else "command failed with exit code %d" % rc
        module.warn("Unable to read sysctl: %s" % error_msg)
        return dict()

    sysctl = dict()
    current_key = None
    current_value = ""

    for line in out.splitlines():
        if not line:
            continue

        # Handle multiline values - lines starting with whitespace are continuations
        if line.startswith((' ', '\t')):
            if current_key is not None:
                # Preserve line breaks in multiline values
                current_value += '\n' + line
            continue

        # Save previous key-value pair if we have one
        if current_key is not None:
            sysctl[current_key] = current_value.strip()

        # Parse new key-value pair
        try:
            (key, value) = re.split(r'\s?=\s?|: ', line, maxsplit=1)
            current_key = key.strip()
            current_value = value.strip()
        except (ValueError, AttributeError) as e:
            module.warn("Unable to split sysctl line (%s): %s" % (line, str(e)))
            current_key = None
            current_value = ""
            continue

    # Save the last key-value pair
    if current_key is not None:
        sysctl[current_key] = current_value.strip()

    return sysctl


def get_sysctl_boottime(module):
    """
    Get boot time using sysctl -n kern.boottime.
    Returns the boot time as an integer if successful, None otherwise.
    """
    sysctl_cmd = module.get_bin_path('sysctl')
    if sysctl_cmd is None:
        raise ValueError("sysctl command not found")

    cmd = [sysctl_cmd, '-n', 'kern.boottime']

    try:
        rc, out, err = module.run_command(cmd)
        if rc != 0:
            # Command failed, but don't raise exception - just return None
            return None

        boottime_str = out.strip()
        if not boottime_str:
            # Empty output
            return None

        # Validate that output is numeric
        try:
            boottime = int(boottime_str)
            return boottime
        except ValueError:
            # Output is not a valid numeric string
            return None
    except (IOError, OSError):
        # Command execution failed, but don't raise exception - just return None
        return None
