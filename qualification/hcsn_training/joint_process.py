"""Linux process/clock observations and pidfd-bound cancellation, never PID guessing."""

import os
from pathlib import Path
import select
import signal
import time

from qualification.hcsn_training.joint_protocol import process, require, sha, uint


def _small(path, cap=4096):
    with open(path, "rb") as stream:
        raw = stream.read(cap + 1)
    require(0 < len(raw) <= cap, "kernel identity bound")
    return raw


def boot_id():
    return sha(_small("/proc/sys/kernel/random/boot_id", 128))


def host_id():
    return sha(_small("/etc/machine-id", 128))


def clock_ns():
    return time.clock_gettime_ns(time.CLOCK_BOOTTIME)


def process_identity(pid, host):
    uint(pid, positive=True)
    raw = _small(f"/proc/{pid}/stat").decode("utf-8")
    tail = raw[raw.rfind(")") + 2:].split()
    require(len(tail) >= 20, "process stat fields")
    if tail[0] in ("Z", "X"):
        raise ProcessLookupError("process is terminal")
    start = tail[19]
    require(start.isascii() and start.isdecimal(), "process start ticks")
    return dict(host_id=host, process_id=pid,
                incarnation=sha(_small("/proc/sys/kernel/random/boot_id", 128) + b"\0" + start.encode("ascii")))


def liveness(expected):
    process(expected)
    try:
        actual = process_identity(expected["process_id"], host_id())
        return "live" if actual == expected else "different"
    except (FileNotFoundError, ProcessLookupError):
        return "stopped"
    except (OSError, ValueError, IndexError, UnicodeError):
        return "unknown"


def remaining_ns(claim):
    require(claim["clock"] == "CLOCK_BOOTTIME" and claim["boot_id"] == boot_id(), "deadline boot changed")
    return max(0, claim["deadline_nanoseconds"] - clock_ns())


def arm_deadline(deadline_ns, expected_boot):
    """Internal adapter timer; never changes the H request or its CLI."""
    uint(deadline_ns, positive=True)
    require(boot_id() == expected_boot, "worker deadline boot changed")
    remaining = deadline_ns - clock_ns()
    require(remaining > 0, "worker absolute deadline elapsed")
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    signal.setitimer(signal.ITIMER_REAL, remaining / 1000000000)


def verified_pidfd(expected, command, python_resolved):
    require(hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"), "pidfd required")
    process(expected)
    fd = os.pidfd_open(expected["process_id"])
    try:
        require(process_identity(expected["process_id"], host_id()) == expected, "worker incarnation changed")
        raw = b"\0".join(os.fsencode(value) for value in command) + b"\0"
        require(_small(f"/proc/{expected['process_id']}/cmdline", len(raw)) == raw, "worker command changed")
        require(Path(f"/proc/{expected['process_id']}/exe").resolve(strict=True) == python_resolved,
                "worker interpreter changed")
        require(process_identity(expected["process_id"], host_id()) == expected, "worker incarnation changed after contact")
        return fd
    except BaseException:
        os.close(fd)
        raise


def stop_pidfd(fd):
    """One signal to the bound process, never a group or an inferred descendant."""
    signal.pidfd_send_signal(fd, signal.SIGKILL)
    poll = select.poll()
    poll.register(fd, select.POLLIN)
    return any(number == fd and events & (select.POLLIN | select.POLLHUP)
               for number, events in poll.poll(5000))
