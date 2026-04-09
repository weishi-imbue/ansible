from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import ctypes
import ctypes.util

try:
    _lib_path = ctypes.util.find_library('selinux')
    if _lib_path is None:
        raise OSError('unable to load libselinux.so')
    _selinux = ctypes.cdll.LoadLibrary(_lib_path)
except OSError:
    raise ImportError('unable to load libselinux.so')


def is_selinux_enabled():
    return _selinux.is_selinux_enabled()


def is_selinux_mls_enabled():
    return _selinux.is_selinux_mls_enabled()


def selinux_getenforcemode():
    enforcemode = ctypes.c_int()
    rc = _selinux.selinux_getenforcemode(ctypes.byref(enforcemode))
    return [rc, enforcemode.value]


def lgetfilecon_raw(path):
    if isinstance(path, bytes):
        path = path.decode('utf-8', 'surrogateescape')
    b_path = path.encode('utf-8', 'surrogateescape')
    context = ctypes.c_char_p()
    rc = _selinux.lgetfilecon_raw(b_path, ctypes.byref(context))
    if rc >= 0 and context.value is not None:
        result = [rc, context.value.decode('utf-8', 'surrogateescape')]
        _selinux.freecon(context)
        return result
    return [rc, '']


def matchpathcon(path, mode):
    if isinstance(path, bytes):
        path = path.decode('utf-8', 'surrogateescape')
    b_path = path.encode('utf-8', 'surrogateescape')
    context = ctypes.c_char_p()
    rc = _selinux.matchpathcon(b_path, ctypes.c_int(mode), ctypes.byref(context))
    if rc >= 0 and context.value is not None:
        result = [rc, context.value.decode('utf-8', 'surrogateescape')]
        _selinux.freecon(context)
        return result
    return [rc, '']


def lsetfilecon(path, context):
    if isinstance(path, bytes):
        path = path.decode('utf-8', 'surrogateescape')
    if isinstance(context, bytes):
        context = context.decode('utf-8', 'surrogateescape')
    b_path = path.encode('utf-8', 'surrogateescape')
    b_context = context.encode('utf-8', 'surrogateescape')
    return _selinux.lsetfilecon(b_path, b_context)


def security_policyvers():
    return _selinux.security_policyvers()


def security_getenforce():
    return _selinux.security_getenforce()


def selinux_getpolicytype():
    policytype = ctypes.c_char_p()
    rc = _selinux.selinux_getpolicytype(ctypes.byref(policytype))
    if rc == 0 and policytype.value is not None:
        result = [rc, policytype.value.decode('utf-8', 'surrogateescape')]
        _selinux.freecon(policytype)
        return result
    return [rc, '']
