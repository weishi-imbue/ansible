# Copyright (c) 2021 Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""
SELinux compatibility shim

This module provides a compatibility layer for SELinux operations that can work
without requiring python selinux bindings (libselinux-python) by directly calling
the libselinux.so shared library when needed.
"""

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import ctypes
import ctypes.util
import os

# First, try to import the native selinux module
try:
    import selinux as _selinux_native
    _HAVE_SELINUX_NATIVE = True
except ImportError:
    _selinux_native = None
    _HAVE_SELINUX_NATIVE = False


# If native module is not available, try to load libselinux.so directly
_libselinux = None
if not _HAVE_SELINUX_NATIVE:
    try:
        # Try to find and load libselinux.so
        libselinux_path = ctypes.util.find_library('selinux')
        if libselinux_path:
            _libselinux = ctypes.CDLL(libselinux_path)
        else:
            # Try common paths
            for path in ['/lib64/libselinux.so.1', '/lib/libselinux.so.1',
                        '/usr/lib64/libselinux.so.1', '/usr/lib/libselinux.so.1',
                        '/lib/x86_64-linux-gnu/libselinux.so.1',
                        '/usr/lib/x86_64-linux-gnu/libselinux.so.1']:
                try:
                    if os.path.exists(path):
                        _libselinux = ctypes.CDLL(path)
                        break
                except OSError:
                    continue

        if _libselinux is None:
            raise ImportError("unable to load libselinux.so")

        # Set up function signatures for the libselinux functions we need
        _libselinux.is_selinux_enabled.restype = ctypes.c_int

        _libselinux.is_selinux_mls_enabled.restype = ctypes.c_int

        _libselinux.lgetfilecon_raw.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_char_p)]
        _libselinux.lgetfilecon_raw.restype = ctypes.c_int

        _libselinux.matchpathcon.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
        _libselinux.matchpathcon.restype = ctypes.c_int

        _libselinux.lsetfilecon.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        _libselinux.lsetfilecon.restype = ctypes.c_int

        _libselinux.security_getenforcemode.argtypes = [ctypes.POINTER(ctypes.c_int)]
        _libselinux.security_getenforcemode.restype = ctypes.c_int

        _libselinux.security_policyvers.argtypes = []
        _libselinux.security_policyvers.restype = ctypes.c_int

        _libselinux.security_getenforce.argtypes = []
        _libselinux.security_getenforce.restype = ctypes.c_int

        _libselinux.selinux_getpolicytype.argtypes = [ctypes.POINTER(ctypes.c_char_p)]
        _libselinux.selinux_getpolicytype.restype = ctypes.c_int

        # Function to free strings allocated by libselinux
        _libselinux.freecon.argtypes = [ctypes.c_char_p]
        _libselinux.freecon.restype = None

    except (ImportError, OSError, AttributeError):
        raise ImportError("unable to load libselinux.so")


def is_selinux_enabled():
    """
    Returns 1 if SELinux is enabled, 0 if disabled
    """
    if _HAVE_SELINUX_NATIVE:
        return _selinux_native.is_selinux_enabled()
    else:
        return _libselinux.is_selinux_enabled()


def is_selinux_mls_enabled():
    """
    Returns 1 if SELinux MLS is enabled, 0 if disabled
    """
    if _HAVE_SELINUX_NATIVE:
        return _selinux_native.is_selinux_mls_enabled()
    else:
        return _libselinux.is_selinux_mls_enabled()


def lgetfilecon_raw(path):
    """
    Returns the raw SELinux security context of the specified file path.
    Returns a list containing [rc, context] where rc is the return code
    and context is the SELinux context as a string.
    """
    if isinstance(path, str):
        path = path.encode('utf-8')

    if _HAVE_SELINUX_NATIVE:
        return _selinux_native.lgetfilecon_raw(path)
    else:
        context_ptr = ctypes.c_char_p()
        rc = _libselinux.lgetfilecon_raw(path, ctypes.byref(context_ptr))
        if rc >= 0 and context_ptr.value:
            context = context_ptr.value.decode('utf-8')
            _libselinux.freecon(context_ptr)
            return [rc, context]
        else:
            return [rc, None]


def matchpathcon(path, mode):
    """
    Returns the default SELinux security context that would be applied to the
    specified file path and mode. Returns a list containing [rc, context] where
    rc is the return code and context is the matched SELinux context as a string.
    """
    if isinstance(path, str):
        path = path.encode('utf-8')

    if _HAVE_SELINUX_NATIVE:
        return _selinux_native.matchpathcon(path, mode)
    else:
        context_ptr = ctypes.c_char_p()
        rc = _libselinux.matchpathcon(path, mode, ctypes.byref(context_ptr))
        if rc == 0 and context_ptr.value:
            context = context_ptr.value.decode('utf-8')
            _libselinux.freecon(context_ptr)
            return [rc, context]
        else:
            return [rc, None]


def lsetfilecon(path, context):
    """
    Sets the SELinux security context of a file.
    Returns 0 on success, -1 on error.
    """
    if isinstance(path, str):
        path = path.encode('utf-8')
    if isinstance(context, str):
        context = context.encode('utf-8')

    if _HAVE_SELINUX_NATIVE:
        return _selinux_native.lsetfilecon(path, context)
    else:
        return _libselinux.lsetfilecon(path, context)


def selinux_getenforcemode():
    """
    Returns the SELinux enforcement mode by invoking `selinux_getenforcemode`.
    Returns a list containing [rc, enforcemode] where rc is the return code
    and enforcemode is the enforcement mode value.
    """
    if _HAVE_SELINUX_NATIVE:
        # The native selinux module has security_getenforcemode
        if hasattr(_selinux_native, 'security_getenforcemode'):
            enforcemode = ctypes.c_int()
            rc = _selinux_native.security_getenforcemode(ctypes.byref(enforcemode))
            return [rc, enforcemode.value]
        else:
            # Fallback to reading /etc/selinux/config or using is_selinux_enabled
            if _selinux_native.is_selinux_enabled():
                # Try to determine enforcement mode
                try:
                    with open('/sys/fs/selinux/enforce', 'r') as f:
                        enforce = int(f.read().strip())
                        return [0, enforce]
                except (IOError, OSError):
                    return [0, 1]  # Assume enforcing if we can't determine
            else:
                return [0, 0]  # Disabled
    else:
        enforcemode = ctypes.c_int()
        rc = _libselinux.security_getenforcemode(ctypes.byref(enforcemode))
        return [rc, enforcemode.value]


def security_policyvers():
    """
    Returns the current SELinux policy version.
    """
    if _HAVE_SELINUX_NATIVE:
        return _selinux_native.security_policyvers()
    else:
        return _libselinux.security_policyvers()


def security_getenforce():
    """
    Returns the current SELinux enforcement mode.
    """
    if _HAVE_SELINUX_NATIVE:
        return _selinux_native.security_getenforce()
    else:
        return _libselinux.security_getenforce()


def selinux_getpolicytype():
    """
    Returns the SELinux policy type.
    Returns a tuple containing (rc, policytype) where rc is the return code
    and policytype is the policy type string.
    """
    if _HAVE_SELINUX_NATIVE:
        return _selinux_native.selinux_getpolicytype()
    else:
        policytype_ptr = ctypes.c_char_p()
        rc = _libselinux.selinux_getpolicytype(ctypes.byref(policytype_ptr))
        if rc == 0 and policytype_ptr.value:
            policytype = policytype_ptr.value.decode('utf-8')
            _libselinux.freecon(policytype_ptr)
            return [rc, policytype]
        else:
            return [rc, None]


# Export the same interface as the native selinux module
__all__ = [
    'is_selinux_enabled',
    'is_selinux_mls_enabled',
    'lgetfilecon_raw',
    'matchpathcon',
    'lsetfilecon',
    'selinux_getenforcemode',
    'security_policyvers',
    'security_getenforce',
    'selinux_getpolicytype'
]