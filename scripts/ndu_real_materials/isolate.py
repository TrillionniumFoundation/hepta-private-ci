"""Linux actor boundary: mandatory Landlock, seccomp, closed descriptors, and clean env.

This protects registered private inputs from the executed actor. It is not a
native Cell receipt, a trusted evaluator identity declaration, or a kernel audit.
There is no fallback to an unrestricted subprocess.
"""

import argparse
import ctypes
import ctypes.util
import errno
import hashlib
import json
import os
from pathlib import Path
import platform
import queue
import resource
import selectors
import signal
import subprocess
import sys
import threading
import time

FS_READ = (1 << 0) | (1 << 2) | (1 << 3)
FS_WRITE = (1 << 1) | sum(1 << bit for bit in range(4, 15))
BLOCKED_SYSCALLS = (
    "socket", "socketpair", "connect", "bind", "listen", "accept", "accept4",
    "sendto", "sendmsg", "sendmmsg", "recvfrom", "recvmsg", "recvmmsg",
    "ptrace", "process_vm_readv", "process_vm_writev", "process_madvise", "process_mrelease",
    "pidfd_getfd", "pidfd_open", "kcmp", "bpf", "perf_event_open", "userfaultfd",
    "open_by_handle_at", "name_to_handle_at", "io_uring_setup", "io_uring_enter", "io_uring_register",
    "mount", "umount2", "pivot_root", "chroot", "setns", "unshare",
    "setsid", "setpgid",
    "fsopen", "fsconfig", "fsmount", "fspick", "move_mount", "open_tree", "mount_setattr",
    "chmod", "fchmod", "fchmodat", "fchmodat2", "chown", "fchown", "lchown", "fchownat",
    "setxattr", "lsetxattr", "fsetxattr", "removexattr", "lremovexattr", "fremovexattr",
    "utime", "utimes", "futimesat", "utimensat", "keyctl", "add_key", "request_key",
    "reboot", "kexec_load", "kexec_file_load", "init_module", "finit_module", "delete_module",
)


class Ruleset(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64),
                ("handled_access_net", ctypes.c_uint64), ("scoped", ctypes.c_uint64)]


class PathRule(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


def enforce(read_roots, write_root):
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "aarch64"}:
        raise RuntimeError("This isolation profile requires supported native Linux")
    if os.geteuid() == 0:
        raise RuntimeError("Run actors under an unprivileged host account")
    libc = ctypes.CDLL(None, use_errno=True)
    seccomp = ctypes.CDLL(ctypes.util.find_library("seccomp"), use_errno=True)
    seccomp.seccomp_init.argtypes = [ctypes.c_uint32]
    seccomp.seccomp_init.restype = ctypes.c_void_p
    seccomp.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    seccomp.seccomp_syscall_resolve_name.restype = ctypes.c_int
    seccomp.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    seccomp.seccomp_load.argtypes = [ctypes.c_void_p]
    seccomp.seccomp_release.argtypes = [ctypes.c_void_p]
    abi = libc.syscall(444, 0, 0, 1)
    if abi < 3:
        raise RuntimeError(f"Mandatory Landlock ABI >=3 is unavailable: abi={abi}, errno={ctypes.get_errno()}")
    handled = (1 << (16 if abi >= 5 else 15)) - 1
    attrs = Ruleset(handled, 0, 3 if abi >= 6 else 0)
    ruleset = libc.syscall(444, ctypes.byref(attrs), ctypes.sizeof(attrs), 0)
    if ruleset < 0:
        raise OSError(ctypes.get_errno(), "landlock_create_ruleset")
    try:
        for path, writable in [(value, False) for value in read_roots] + [(write_root, True)]:
            descriptor = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                rights = FS_READ | (FS_WRITE if writable else 0)
                if not Path(path).is_dir():
                    rights &= ~(1 << 3)
                rule = PathRule(rights & handled, descriptor)
                if libc.syscall(445, ruleset, 1, ctypes.byref(rule), 0) != 0:
                    raise OSError(ctypes.get_errno(), "landlock_add_rule")
            finally:
                os.close(descriptor)
        if libc.prctl(38, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "PR_SET_NO_NEW_PRIVS")
        if libc.syscall(446, ruleset, 0) != 0:
            raise OSError(ctypes.get_errno(), "landlock_restrict_self")
    finally:
        os.close(ruleset)
    context = seccomp.seccomp_init(0x7FFF0000)
    if not context:
        raise RuntimeError("seccomp_init failed")
    blocked = []
    try:
        for name in BLOCKED_SYSCALLS:
            number = seccomp.seccomp_syscall_resolve_name(name.encode())
            if number >= 0:
                if seccomp.seccomp_rule_add(context, 0x00050000 | errno.EPERM, number, 0) != 0:
                    raise RuntimeError("seccomp rule failed: " + name)
                blocked.append(name)
        if seccomp.seccomp_load(context) != 0:
            raise RuntimeError("Mandatory seccomp filter could not be loaded")
    finally:
        seccomp.seccomp_release(context)
    return {"landlock_abi": abi, "uid": os.geteuid(), "seccomp_blocked_syscalls": blocked,
            "no_new_privileges": True, "filesystem_default": "DENY",
            "network": "DENY", "kernel": platform.release()}


def _child(config, receipt_fd):
    os.chdir(config["write_root"])
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024 * 1024, 32 * 1024 * 1024))
    cpu_bound = int(config["timeout_seconds"]) + 2
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_bound, cpu_bound))
    receipt = enforce(config["read_roots"], config["write_root"])
    receipt.update(launcher_pid=os.getpid(), command_sha256=hashlib.sha256(
        json.dumps(config["command"], separators=(",", ":")).encode()).hexdigest())
    os.write(receipt_fd, (json.dumps(receipt, sort_keys=True) + "\n").encode())
    os.close(receipt_fd)
    os.execve(config["command"][0], config["command"], config["environment"])


def run_actor(command, *, public_root, output_root, runtime_roots, private_roots,
              input_bytes=b"", timeout_seconds=30, max_output_bytes=1024 * 1024,
              host_callback=None):
    """Run an actor with only its current public directory and named runtime inputs.

    The caller must supply all material-private roots; every overlapping
    allowlisted ancestor or descendant is rejected. The actor cannot select its own allowlist.
    The unforgeable-in-process launch receipt is written before exec to an fd
    closed before the actor starts; it is not an actor-supplied JSON claim.
    With host_callback, complete stdout JSONL objects are given to the trusted
    host. It may return the next public stdin bytes, or None to close stdin.
    Never return hidden references, evaluator scores, or future observations.
    """
    public = Path(public_root).resolve(strict=True)
    output = Path(output_root).resolve(strict=True)
    private = [Path(path).resolve(strict=True) for path in private_roots]
    if (not private or public == output or output.is_relative_to(public)
            or public.is_relative_to(output)):
        raise ValueError("Disjoint public/output roots and explicit private exclusions are required")
    if not isinstance(input_bytes, bytes) or len(input_bytes) > 1024 * 1024:
        raise ValueError("Actor input must be bounded public bytes")
    roots = [public, *[Path(path).resolve(strict=True) for path in runtime_roots]]
    for allowed in roots + [output]:
        if allowed == Path("/") or any(
                value == allowed or value.is_relative_to(allowed) or allowed.is_relative_to(value)
                for value in private):
            raise ValueError("Read/write allowlist would expose a private source root")
    for path in public.rglob("*"):
        if path.is_symlink() or (path.is_file() and path.stat().st_nlink != 1):
            raise ValueError("Public projection cannot contain aliases to private files")
    if not command or not Path(command[0]).is_absolute():
        raise ValueError("Actor executable must be an explicit absolute path")
    environment = {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
                   "PYTHONUNBUFFERED": "1", "OMP_NUM_THREADS": "1",
                   "TMPDIR": str(output), "PATH": "/usr/bin:/bin"}
    config = {"command": command, "read_roots": [str(path) for path in roots],
              "write_root": str(output), "timeout_seconds": timeout_seconds, "environment": environment}
    read_fd, write_fd = os.pipe()
    started = time.perf_counter()
    process = subprocess.Popen(
        [sys.executable, "-I", str(Path(__file__).resolve()), "--child", json.dumps(config), str(write_fd)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=environment, pass_fds=(write_fd,), close_fds=True, start_new_session=True)
    os.close(write_fd)
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    # A bounded writer queue prevents a malicious nonreader from blocking the
    # parent's timeout/output checks. There is only one actor process per episode.
    pending = queue.Queue(maxsize=4)
    stdin_closed = False
    if host_callback is None:
        pending.put(input_bytes)
        pending.put(None)
        stdin_closed = True
    elif input_bytes:
        pending.put(input_bytes)

    def feed():
        try:
            while True:
                payload = pending.get()
                if payload is None:
                    break
                process.stdin.write(payload)
                process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass
    writer = threading.Thread(target=feed, daemon=True)
    writer.start()
    streams = {"stdout": bytearray(), "stderr": bytearray(), "launch_receipt": bytearray()}
    selector = selectors.DefaultSelector()
    for stream, label in ((process.stdout, "stdout"), (process.stderr, "stderr"), (read_fd, "launch_receipt")):
        selector.register(stream, selectors.EVENT_READ, label)
    limit_reason = None
    protocol_error = None
    line_buffer = bytearray()
    exchanges = []

    def reject_constant(value):
        raise ValueError("Nonfinite actor event")

    def unique_pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate actor event key")
            result[key] = value
        return result

    try:
        while selector.get_map():
            if time.perf_counter() - started > timeout_seconds:
                limit_reason = "timeout"
            if sum(len(value) for value in streams.values()) > max_output_bytes:
                limit_reason = "output_limit"
            if limit_reason is not None or protocol_error is not None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                break
            for key, _ in selector.select(timeout=0.1):
                block = os.read(key.fd, min(65536, max_output_bytes + 1))
                if block:
                    streams[key.data].extend(block)
                    if host_callback is not None and key.data == "stdout":
                        line_buffer.extend(block)
                        while b"\n" in line_buffer and protocol_error is None:
                            line, _, remainder = line_buffer.partition(b"\n")
                            line_buffer[:] = remainder
                            if not line.strip():
                                continue
                            try:
                                if len(exchanges) >= 1024:
                                    raise ValueError("Actor event count exceeds the bounded episode profile")
                                event = json.loads(line.decode("utf-8"), object_pairs_hook=unique_pairs,
                                                   parse_constant=reject_constant)
                                if not isinstance(event, dict):
                                    raise ValueError("Actor event must be a JSON object")
                                reply = host_callback(event)
                                if reply is not None and (not isinstance(reply, bytes) or len(reply) > 1024 * 1024):
                                    raise ValueError("Host callback must return bounded public bytes or None")
                                if stdin_closed and reply is not None:
                                    raise ValueError("Host callback attempted to reopen closed actor input")
                                if not stdin_closed:
                                    pending.put_nowait(reply)
                                    stdin_closed = reply is None
                                exchanges.append({"event_sha256": hashlib.sha256(line).hexdigest(),
                                    "reply_sha256": None if reply is None else hashlib.sha256(reply).hexdigest(),
                                    "reply_bytes": 0 if reply is None else len(reply)})
                            except Exception as error:
                                protocol_error = f"{type(error).__name__}: {str(error)[:240]}"
                else:
                    selector.unregister(key.fileobj)
                    if host_callback is not None and key.data == "stdout" and line_buffer.strip():
                        protocol_error = "Actor event ended without a complete JSONL line"
        if protocol_error is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        exit_code = process.wait(timeout=5)
    finally:
        selector.close()
        os.close(read_fd)
        process.stdout.close()
        process.stderr.close()
        if not stdin_closed:
            try:
                pending.put_nowait(None)
            except queue.Full:
                pass
        writer.join(timeout=0.2)
    receipt_raw = bytes(streams["launch_receipt"])
    receipt = json.loads(receipt_raw) if receipt_raw else None
    return {"schema": "ndu.real.actor-isolation.v1", "exit_code": exit_code,
            "enforced_before_actor_exec": receipt is not None, "launch_receipt": receipt,
            "limit_reason": limit_reason, "wall_seconds": time.perf_counter() - started,
            "protocol_error": protocol_error, "callback_error": protocol_error,
            "host_exchanges": exchanges,
            "stdout": bytes(streams["stdout"]).decode("utf-8", errors="replace"),
            "stderr": bytes(streams["stderr"]).decode("utf-8", errors="replace"),
            "launcher_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "native_owner_authentication": "SEPARATE_REQUIRED"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", nargs=2, metavar=("CONFIG", "RECEIPT_FD"), required=True)
    args = parser.parse_args()
    _child(json.loads(args.child[0]), int(args.child[1]))
