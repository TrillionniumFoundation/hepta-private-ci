"""Fixed Linux Joint provider entry. Authority belongs to the admitted host owner."""

import argparse
import hashlib
import os
from pathlib import Path
import signal
import stat
import sys
import time
import types

MODULES = ("joint_protocol", "joint_store", "joint_process", "joint_sources", "joint_outputs",
           "joint_lifecycle", "joint_runner", "joint_worker_adapter")
PREFIX = "qualification/hcsn_training/"
FILES = (PREFIX + "__init__.py",) + tuple(PREFIX + name + ".py" for name in (*MODULES, "joint_supervisor"))


def _capture(path):
    if path.resolve(strict=True) != path:
        raise ValueError("physical HC source required")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or not 0 <= before.st_size <= 262144:
        raise ValueError("bounded HC source required")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        def same(value):
            return all(getattr(value, key) == getattr(before, key) for key in
                       ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns"))
        if not same(os.fstat(fd)):
            raise ValueError("HC source open race")
        raw = bytearray()
        while len(raw) <= 262144:
            part = os.read(fd, min(65536, 262145 - len(raw)))
            if not part:
                break
            raw.extend(part)
        if len(raw) != before.st_size or not same(os.fstat(fd)) or not same(path.lstat()):
            raise ValueError("HC source read race")
        return bytes(raw)
    finally:
        os.close(fd)


def _bootstrap():
    repo = Path(__file__).absolute().parents[2]
    captured = {name: _capture(repo / name) for name in FILES}
    if os.path.lexists(repo / "qualification/__init__.py"):
        raise ValueError("unexpected top-level qualification initializer")
    for name in ("qualification", "qualification.hcsn_training"):
        if name in sys.modules:
            raise ValueError("preloaded HC package")
        module = types.ModuleType(name)
        module.__package__ = name
        module.__path__ = [str(repo.joinpath(*name.split(".")))]
        sys.modules[name] = module
    package = sys.modules["qualification.hcsn_training"]
    package.__file__ = str(repo / FILES[0])
    exec(compile(captured[FILES[0]], package.__file__, "exec"), package.__dict__)
    for short in MODULES:
        name = "qualification.hcsn_training." + short
        if name in sys.modules:
            raise ValueError("preloaded HC source")
        module = types.ModuleType(name)
        module.__package__ = "qualification.hcsn_training"
        module.__file__ = str(repo / (PREFIX + short + ".py"))
        module.__pinned_source_sha256__ = hashlib.sha256(captured[PREFIX + short + ".py"]).hexdigest()
        sys.modules[name] = module
        exec(compile(captured[PREFIX + short + ".py"], module.__file__, "exec"), module.__dict__)
    from qualification.hcsn_training.joint_sources import Sources
    return Sources(repo, captured)


def _uint_argument(raw):
    if not raw.isascii() or not raw.isdecimal() or (len(raw) > 1 and raw.startswith("0")):
        raise argparse.ArgumentTypeError("canonical unsigned decimal required")
    value = int(raw)
    if value >= 1 << 64:
        raise argparse.ArgumentTypeError("unsigned integer overflow")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--root-device", type=_uint_argument, required=True)
    parser.add_argument("--root-inode", type=_uint_argument, required=True)
    parser.add_argument("--root-uid", type=_uint_argument, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run")
    mode.add_argument("--worker")
    parser.add_argument("--nonce")
    parser.add_argument("--deadline-ns", type=_uint_argument)
    parser.add_argument("--boot-id")
    args = parser.parse_args()
    if args.worker:
        # Do this before captured HC/H imports. The same deadline is checked
        # against the durable claim after private-root admission, never reset.
        boot_raw = Path("/proc/sys/kernel/random/boot_id").read_bytes()
        if args.deadline_ns is None or hashlib.sha256(boot_raw).hexdigest() != args.boot_id:
            raise ValueError("internal absolute deadline missing")
        remaining = args.deadline_ns - time.clock_gettime_ns(time.CLOCK_BOOTTIME)
        if remaining <= 0:
            raise ValueError("internal absolute deadline expired")
        signal.signal(signal.SIGALRM, signal.SIG_DFL)
        signal.setitimer(signal.ITIMER_REAL, remaining / 1000000000)
    elif args.deadline_ns is not None or args.boot_id is not None:
        raise ValueError("deadline flags belong only to the fixed internal worker")
    sources = _bootstrap()
    from qualification.hcsn_training.joint_protocol import COMMAND_CAP, encoded, require, validate_command
    from qualification.hcsn_training.joint_store import Root
    from qualification.hcsn_training.joint_lifecycle import dispatch
    from qualification.hcsn_training.joint_runner import run_job
    from qualification.hcsn_training.joint_worker_adapter import run_worker
    expected = dict(device=args.root_device, inode=args.root_inode, uid=args.root_uid)
    with Root(args.root, expected) as root:
        if args.run:
            run_job(root, args.run, args.nonce, sources)
            return 0
        if args.worker:
            return run_worker(root, args.worker, args.nonce, sources, args.deadline_ns, args.boot_id)
        require(args.nonce is None, "nonce is internal only")
        raw = sys.stdin.buffer.read(COMMAND_CAP + 1)
        command = validate_command(raw)
        answer = dispatch(root, command, sources)
        root.check()
        sources.check()
        result = encoded(answer)
        require(len(result) <= 65536, "observation byte bound")
        sys.stdout.buffer.write(result + b"\n")
        sys.stdout.buffer.flush()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
