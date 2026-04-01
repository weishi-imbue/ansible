# Copyright: (c) 2019, Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import os
import tarfile
import tempfile

import ansible.constants as C
from ansible.errors import AnsibleError
from ansible.module_utils._text import to_native, to_text
from ansible.module_utils.common.process import get_bin_path
from ansible.utils.display import Display

try:
    from subprocess import Popen, PIPE
except ImportError:
    from subprocess import Popen, PIPE

display = Display()


def scm_archive_collection(src, name=None, version='HEAD'):
    """
    Archive a collection from a git repository.

    :param src: The git repository source URL.
    :param name: The name of the collection/repo.
    :param version: The git tree-ish to archive (default 'HEAD').
    :return: The file path of the tar archive containing the collection.
    """
    return scm_archive_resource(src, scm='git', name=name, version=version)


def scm_archive_resource(src, scm='git', name=None, version='HEAD', keep_scm_meta=False):
    """
    Archive a resource from an SCM repository.

    :param src: The repository source URL.
    :param scm: The SCM type, 'git' or 'hg' (default 'git').
    :param name: The name for the archived resource.
    :param version: The git tree-ish to archive (default 'HEAD').
    :param keep_scm_meta: Whether to keep SCM metadata in the archive.
    :return: The file path of the tar archive.
    """

    def run_scm_cmd(cmd, tempdir):
        try:
            stdout = ''
            stderr = ''
            popen = Popen(cmd, cwd=tempdir, stdout=PIPE, stderr=PIPE)
            stdout, stderr = popen.communicate()
        except Exception as e:
            ran = " ".join(cmd)
            display.debug("ran %s:" % ran)
            display.debug("\tstdout: " + to_text(stdout))
            display.debug("\tstderr: " + to_text(stderr))
            raise AnsibleError("when executing %s: %s" % (ran, to_native(e)))
        if popen.returncode != 0:
            raise AnsibleError("- command %s failed in directory %s (rc=%s) - %s"
                               % (' '.join(cmd), tempdir, popen.returncode, to_native(stderr)))

    if scm not in ['hg', 'git']:
        raise AnsibleError("- scm %s is not currently supported" % scm)

    try:
        scm_path = get_bin_path(scm)
    except (ValueError, OSError, IOError):
        raise AnsibleError("could not find/use %s, it is required to continue with installing %s" % (scm, src))

    tempdir = tempfile.mkdtemp(dir=C.DEFAULT_LOCAL_TMP)
    clone_cmd = [scm_path, 'clone', src, name]
    run_scm_cmd(clone_cmd, tempdir)

    if scm == 'git' and version:
        checkout_cmd = [scm_path, 'checkout', to_text(version)]
        run_scm_cmd(checkout_cmd, os.path.join(tempdir, name))

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.tar', dir=C.DEFAULT_LOCAL_TMP)
    archive_cmd = None
    if keep_scm_meta:
        display.vvv('tarring %s from %s to %s' % (name, tempdir, temp_file.name))
        with tarfile.open(temp_file.name, "w") as tar:
            tar.add(os.path.join(tempdir, name), arcname=name)
    elif scm == 'hg':
        archive_cmd = [scm_path, 'archive', '--prefix', "%s/" % name]
        if version:
            archive_cmd.extend(['-r', version])
        archive_cmd.append(temp_file.name)
    elif scm == 'git':
        archive_cmd = [scm_path, 'archive', '--prefix=%s/' % name, '--output=%s' % temp_file.name]
        if version:
            archive_cmd.append(version)
        else:
            archive_cmd.append('HEAD')

    if archive_cmd is not None:
        display.vvv('archiving %s' % archive_cmd)
        run_scm_cmd(archive_cmd, os.path.join(tempdir, name))

    return temp_file.name


def get_galaxy_metadata_path(b_path):
    """
    Determine the location of the galaxy metadata file in a collection directory.

    :param b_path: Path to the collection directory.
    :return: Path to galaxy.yml or galaxy.yaml if found, otherwise default galaxy.yml path.
    """
    b_galaxy_yml = os.path.join(b_path, b'galaxy.yml')
    b_galaxy_yaml = os.path.join(b_path, b'galaxy.yaml')

    if os.path.exists(b_galaxy_yml):
        return b_galaxy_yml
    elif os.path.exists(b_galaxy_yaml):
        return b_galaxy_yaml

    return b_galaxy_yml
