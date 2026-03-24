# -*- coding: utf-8 -*-
# (c) 2015, Brian Coca  <briancoca+dev@gmail.com>
# (c) 2018, Matt Martz  <matt@sivel.net>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

# Make coding more python3-ish
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import os

try:
    from collections.abc import Mapping
except ImportError:
    from collections import Mapping

from ansible.errors import AnsibleError, AnsibleAction, _AnsibleActionDone, AnsibleActionFail
from ansible.module_utils._text import to_native
from ansible.module_utils.parsing.convert_bool import boolean
from ansible.plugins.action import ActionBase


class ActionModule(ActionBase):

    TRANSFERS_FILES = True

    def run(self, tmp=None, task_vars=None):
        self._supports_async = True

        if task_vars is None:
            task_vars = dict()

        result = super(ActionModule, self).run(tmp, task_vars)
        del tmp  # tmp no longer has any effect

        src = self._task.args.get('src', None)
        body = self._task.args.get('body', None)
        body_format = self._task.args.get('body_format', 'raw')
        remote_src = boolean(self._task.args.get('remote_src', 'no'), strict=False)

        try:
            new_module_args = self._task.args.copy()

            # Handle src parameter (existing logic)
            if src and not remote_src:
                try:
                    src = self._find_needle('files', src)
                except AnsibleError as e:
                    raise AnsibleActionFail(to_native(e))

                tmp_src = self._connection._shell.join_path(self._connection._shell.tmpdir, os.path.basename(src))
                self._transfer_file(src, tmp_src)
                self._fixup_perms2((self._connection._shell.tmpdir, tmp_src))
                new_module_args.update(dict(src=tmp_src))

            # Handle multipart form data
            if body_format == 'form-multipart':
                if not isinstance(body, Mapping):
                    raise AnsibleActionFail("body must be a mapping when body_format is form-multipart, got %s" % type(body).__name__)

                # Process file fields in the multipart data
                processed_body = {}
                for field_name, field_value in body.items():
                    if isinstance(field_value, Mapping):
                        # This is a file field
                        processed_field = field_value.copy()
                        filename = field_value.get('filename')
                        content = field_value.get('content')

                        # If filename is provided but no content, resolve and transfer the file
                        if filename and not content:
                            try:
                                local_file_path = self._find_needle('files', filename)
                            except AnsibleError as e:
                                raise AnsibleActionFail("Failed to find file '%s': %s" % (filename, to_native(e)))

                            # Transfer the file to the remote system
                            remote_filename = self._connection._shell.join_path(
                                self._connection._shell.tmpdir,
                                os.path.basename(local_file_path)
                            )
                            self._transfer_file(local_file_path, remote_filename)
                            self._fixup_perms2((self._connection._shell.tmpdir, remote_filename))

                            # Update the field to point to the remote file path
                            processed_field['filename'] = remote_filename

                        processed_body[field_name] = processed_field
                    else:
                        # Simple text field
                        processed_body[field_name] = field_value

                new_module_args['body'] = processed_body

            # If everything is remote, or no local files need handling, execute directly
            if ((src and remote_src) or not src) and body_format != 'form-multipart':
                raise _AnsibleActionDone(result=self._execute_module(task_vars=task_vars, wrap_async=self._task.async_val))

            result.update(self._execute_module('uri', module_args=new_module_args, task_vars=task_vars, wrap_async=self._task.async_val))
        except AnsibleAction as e:
            result.update(e.result)
        finally:
            if not self._task.async_val:
                self._remove_tmp_path(self._connection._shell.tmpdir)
        return result
