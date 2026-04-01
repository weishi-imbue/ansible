#
# (c) 2019 Red Hat Inc.
#
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
#
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

DOCUMENTATION = """
---
cliconf: eric_eccli
short_description: Use eric_eccli cliconf to run command on Ericsson ECCLI platform
description:
  - This eric_eccli plugin provides low level abstraction apis for
    sending and receiving CLI commands from Ericsson ECCLI network devices.
version_added: "2.9"
"""

import json

from ansible.errors import AnsibleConnectionFailure
from ansible.module_utils._text import to_text
from ansible.module_utils.network.common.utils import to_list
from ansible.module_utils.connection import ConnectionError
from ansible.module_utils.common._collections_compat import Mapping
from ansible.plugins.cliconf import CliconfBase


class Cliconf(CliconfBase):

    def get_device_info(self):
        device_info = {}
        device_info['network_os'] = 'eric_eccli'

        reply = self.get('show version')
        data = to_text(reply, errors='surrogate_or_strict').strip()

        device_info['network_os_version'] = data

        return device_info

    def get_config(self, source='running', format='text', flags=None):
        return ''

    def edit_config(self, candidate=None, commit=True, replace=None, diff=False, comment=None):
        return {}

    def get(self, command, prompt=None, answer=None, sendonly=False, output=None, check_all=False):
        return self.send_command(command=command, prompt=prompt, answer=answer, sendonly=sendonly, check_all=check_all)

    def run_commands(self, commands=None, check_rc=True):
        if commands is None:
            raise ValueError("'commands' value is required")

        responses = list()
        for cmd in to_list(commands):
            if not isinstance(cmd, Mapping):
                cmd = {'command': cmd}

            output = cmd.pop('output', None)

            try:
                out = self.send_command(**cmd)
            except AnsibleConnectionFailure as e:
                if check_rc is True:
                    raise
                out = getattr(e, 'err', e)

            if out is not None:
                try:
                    out = to_text(out, errors='surrogate_or_strict').strip()
                except UnicodeError:
                    raise ConnectionError(message=u'Failed to decode output from %s: %s' % (cmd, to_text(out)))

                responses.append(out)

        return responses

    def get_device_operations(self):
        return {
            'supports_diff_replace': False,
            'supports_commit': False,
            'supports_rollback': False,
            'supports_defaults': False,
            'supports_commit_comment': False,
            'supports_onbox_diff': False,
            'supports_generate_diff': False,
            'supports_multiline_delimiter': False,
            'supports_diff_match': False,
            'supports_diff_ignore_lines': False,
            'supports_config_replace': False,
            'supports_admin': False,
            'supports_commit_label': False,
            'supports_replace': False
        }

    def get_option_values(self):
        return {
            'format': ['text'],
            'diff_match': [],
            'diff_replace': [],
            'output': ['text']
        }

    def get_capabilities(self):
        result = super(Cliconf, self).get_capabilities()
        result['device_operations'] = self.get_device_operations()
        result['device_info'] = self.get_device_info()
        result.update(self.get_option_values())
        return json.dumps(result)
