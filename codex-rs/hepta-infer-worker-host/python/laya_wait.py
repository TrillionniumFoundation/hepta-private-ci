"""Bounded, non-reaping direct-child observation for the existing transport.

CPython does not expose os.waitid on every macOS build. Darwin's 64-bit public
siginfo_t/waitid ABI is used only there; other POSIX builds use os.waitid.
This helper never waits, reaps, signals, retries EINTR or proves group shutdown.
ABI sources: apple-oss-distributions/xnu, bsd/sys/{signal,wait}.h.
"""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
import errno
import os
import signal
import sys


@dataclass(frozen=True)
class ExitObservation:
    si_pid: int
    si_signo: int
    si_code: int
    si_status: int


class _Sigval(ctypes.Union):
    _fields_ = [("integer", ctypes.c_int), ("pointer", ctypes.c_void_p)]


class _DarwinSiginfo(ctypes.Structure):
    _fields_ = [("si_signo", ctypes.c_int), ("si_errno", ctypes.c_int),
                ("si_code", ctypes.c_int), ("si_pid", ctypes.c_int),
                ("si_uid", ctypes.c_uint), ("si_status", ctypes.c_int),
                ("si_addr", ctypes.c_void_p), ("si_value", _Sigval),
                ("si_band", ctypes.c_long), ("reserved", ctypes.c_ulong * 7)]


def _native_available() -> bool:
    return callable(getattr(os, "waitid", None)) and all(
        hasattr(os, name) for name in ("P_PID", "WEXITED", "WNOHANG", "WNOWAIT"))


def observation_supported() -> bool:
    """Capability of this interpreter, not evidence that a child terminated."""
    return os.name == "posix" and (_native_available() or
                                  (sys.platform == "darwin" and ctypes.sizeof(ctypes.c_void_p) == 8))


def _darwin_observe(pid: int):
    # Reject unknown layouts BEFORE passing a writable pointer to the C ABI.
    if (sys.platform != "darwin" or ctypes.sizeof(ctypes.c_void_p) != 8
            or ctypes.sizeof(ctypes.c_long) != 8 or ctypes.sizeof(_DarwinSiginfo) != 104
            or _DarwinSiginfo.si_pid.offset != 12 or _DarwinSiginfo.si_status.offset != 20):
        raise OSError(errno.ENOTSUP, "unsupported child-observation ABI")
    library = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    function = library.waitid
    function.argtypes = (ctypes.c_int, ctypes.c_uint, ctypes.POINTER(_DarwinSiginfo), ctypes.c_int)
    function.restype = ctypes.c_int
    information = _DarwinSiginfo()  # zeroed: WNOHANG/no result must not expose stale storage
    ctypes.set_errno(0)
    result = function(1, pid, ctypes.byref(information), 0x04 | 0x01 | 0x20)
    error_number = ctypes.get_errno()
    if result != 0 or error_number:
        # ECHILD maps to ChildProcessError, preserving the owner's permanent latch.
        raise OSError(error_number or errno.EIO, "child observation failed")
    return information if information.si_pid else None


def observe_owned_exit(pid: int) -> ExitObservation | None:
    """Observe one exact child without consuming its identity, or propagate failure.

    None is a still-unresolved observation, never proof of non-execution. All
    calls use WEXITED|WNOHANG|WNOWAIT; a signal interruption is not retried here.
    The caller must retain exclusive reaper ownership and bound its polling loop.
    """
    if type(pid) is not int or not 1 < pid <= 0x7fff_ffff:
        raise ValueError("invalid owned child identity")
    if _native_available():
        observed = os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
    else:
        observed = _darwin_observe(pid)
    if observed is None:
        return None
    if (observed.si_pid != pid or observed.si_signo != signal.SIGCHLD
            or observed.si_code not in (1, 2, 3)):
        raise ChildProcessError(errno.ECHILD, "child observation identity changed")
    return ExitObservation(observed.si_pid, observed.si_signo, observed.si_code, observed.si_status)
