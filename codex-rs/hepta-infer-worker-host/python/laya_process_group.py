"""Non-reaping process-group signalling for the existing Laya transport.

Darwin killpg skips zombies and may report EPERM for a zombie-only group. Never
interpret EPERM itself as absence. The narrow fallback below requires an owned,
exited direct child and a complete kernel group snapshot containing ONLY it.
This is a trusted exclusive-reaper helper, not a sandbox or descendant attestor.
"""
from __future__ import annotations

import ctypes
import errno
import os
import signal
import subprocess
import sys

from laya_wait import observe_owned_exit

SIGNALLED = "signalled"
ABSENT = "absent"
EXITED_LEADER_ONLY = "exited-leader-only"


def _darwin_group_members(leader: int) -> tuple[int, ...]:
    # Two slots suffice: success requires exactly one member; a full buffer is
    # rejected, never mistaken for the complete group. proc_listpgrppids returns
    # a PID COUNT (unlike proc_listpids, which returns bytes). Its implementation
    # includes allproc AND zombproc; an empty result is not positive evidence.
    library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    function = library.proc_listpgrppids
    function.argtypes = (ctypes.c_int, ctypes.c_void_p, ctypes.c_int)
    function.restype = ctypes.c_int
    pids = (ctypes.c_int * 2)()
    ctypes.set_errno(0)
    count = function(leader, pids, ctypes.sizeof(pids))
    error_number = ctypes.get_errno()
    if error_number:
        raise OSError(error_number, "group observation failed")
    if count != 1 or pids[0] <= 0 or pids[1] != 0:
        raise OSError(errno.EAGAIN, "group snapshot is absent, non-singleton or incomplete")
    return (int(pids[0]),)


def _exit_identity(observed, leader: int):
    if (observed is None or observed.si_pid != leader
            or observed.si_signo != signal.SIGCHLD
            or observed.si_code not in (1, 2, 3)):
        return None
    return (observed.si_pid, observed.si_code, observed.si_status)


def signal_owned_group(child: subprocess.Popen, observed_exit) -> str:
    """Signal while the caller still owns the unreaped session leader.

    The caller must serialize lifecycle access and latch ChildProcessError as a
    permanent ownership loss. A return permits its existing bounded wait, NOT a
    successful request, verified descendants, resource release or retry.
    """
    leader = child.pid
    if type(leader) is not int or leader <= 1 or child.returncode is not None:
        raise ChildProcessError("group leader ownership was lost")
    try:
        os.killpg(leader, signal.SIGKILL)
        return SIGNALLED
    except ProcessLookupError:
        return ABSENT
    except PermissionError as denied:
        if sys.platform != "darwin" or denied.errno != errno.EPERM:
            raise
        # The child can exit BETWEEN the caller's observation and killpg.
        # Re-observe after EPERM without reaping; a still-live child is denied.
        prior = _exit_identity(observed_exit, leader)
        current = observe_owned_exit(leader)
        exited = _exit_identity(current, leader)
        if exited is None:
            raise
        if prior is not None and prior != exited:
            raise ChildProcessError("group leader exit identity changed")
        if _darwin_group_members(leader) != (leader,):
            raise denied
        # The proc snapshot does not consume the child. Check ownership again
        # before permitting wait; no later signal may use a recycled group ID.
        if child.returncode is not None:
            raise ChildProcessError("group leader ownership was lost")
        current = observe_owned_exit(leader)
        if _exit_identity(current, leader) != exited:
            raise ChildProcessError("group leader exit identity changed")
        return EXITED_LEADER_ONLY
