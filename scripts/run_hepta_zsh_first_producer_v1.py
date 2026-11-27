"""One source-bound zsh build-only producer; activation and publication are separate."""

import time

PROCESS_START = time.monotonic()
import datetime
import difflib
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import resource
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import types
import urllib.error
import urllib.request

REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
HEPTA_REPOSITORY = REPOSITORY
PARENT = {
    "head": "5a842a417dc288e22d506fb16bc691b889fa4297",
    "tree": "b8b977b8c6e8970a09f7afd1474c258e7f2142b8",
}
SCOPE = "hepta-zsh-first-producer-v1"
BRANCH = "fix/hepta-zsh-first-producer-20261127-7c9e"
BASE_BRANCH = "fix/hepta-native-fixture-modeling-20261127-7c9e"
WORKFLOW = ".github/workflows/hepta-zsh-first-producer-v1.yml"
JOB_NAME = "First zsh producer (macOS 26 ARM)"
INPUT = "scripts/hepta_zsh_first_producer_inputs_v1.json"
COLLECTOR = "scripts/hepta_zsh_first_producer_collector_v1.py"
BUILD_SCRIPT = ".github/scripts/build-hepta-zsh-first-producer-v1.sh"
PATCH = "codex-rs/shell-escalation/patches/zsh-exec-wrapper.patch"
OWNER = "scripts/run_hepta_zsh_first_producer_v1.py"
SOURCE_PATHS = tuple(sorted((WORKFLOW, INPUT, COLLECTOR, BUILD_SCRIPT, PATCH, OWNER)))
CAPS = {"whole_seconds": 1800, "work_seconds": 1500, "retention_seconds": 300}
UPSTREAM = "77045ef899e53b9598bebc5a41db93a548a40ca6"
UPSTREAM_TREE = "a1f9db593f3177225fb4ee2f7f2b92cbcf0ad883"
BASE_PATH = "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")
BASE = Path("/__unconfigured_hepta_source__")
OUT = Path("/__unconfigured_hepta_output__")
ALLOWED_READ_ROOTS = ()
START = PROCESS_START
STOP, OP_STOP, COMMAND_STOP = START + 1800, START + 1500, START + 1440
READS, BEFORE_METADATA, ORIGINALS = {}, {}, {}
SIGNALS, HANDLERS = [], {}
FINALIZING, OWNED = False, False
COMMAND_ENV = {}
RESULT = {
    "schema": "hepta-zsh-first-producer-result-v1",
    "status": "FAIL_OR_UNKNOWN",
    "scope_id": SCOPE,
    "commands": [],
    "caps": CAPS,
    "compiler_build_attempts": None,
    "new_producer_smokes": None,
    "archive": None,
    "actual_candidate": None,
    "immutable_provider": None,
    "release_tag": None,
    "DotSlash_manifest_updated": False,
    "old_seven_Mac_regressions_executed": False,
    "O_UNIQUE_or_skill_read_qualified": False,
    "E1_E6_added": 0,
    "E6_remaining_seconds": 1.9960488015785813,
    "requires_external_original_job_terminal_and_artifact_readback": True,
}
OWN_CPU = resource.getrusage(resource.RUSAGE_SELF)
CHILD_CPU = resource.getrusage(resource.RUSAGE_CHILDREN)


def require(value, message):
    if not value:
        raise ValueError(message)


def observed_signal(number, _frame):
    # Never throw across Popen -> protected cleanup or during receipt writes.
    if len(SIGNALS) < 16:
        SIGNALS.append(
            {
                "number": number,
                "name": signal.Signals(number).name,
                "monotonic_seconds": time.monotonic(),
                "during_retention": FINALIZING,
            }
        )


def check(deadline=None, cancel=True):
    if cancel and SIGNALS and not FINALIZING:
        raise KeyboardInterrupt("first zsh producer scope cancelled")
    require(
        time.monotonic()
        < (deadline if deadline is not None else STOP if FINALIZING else OP_STOP),
        "fixed shared zsh producer deadline exhausted",
    )


def pin(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": hashlib.sha1(
            b"blob " + str(len(raw)).encode() + b"\0" + raw
        ).hexdigest(),
    }


def encode(value):
    return (
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()


def unique_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "duplicate JSON key")
            value[key] = item
        return value

    return json.loads(raw, object_pairs_hook=pairs)


def metadata(value):
    return {
        key: getattr(value, key)
        for key in (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_uid",
            "st_gid",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
    }


def regular(path, maximum=64 * 1024 * 1024):
    check()
    path = Path(path)
    require(
        path.is_absolute()
        and path.resolve() == path
        and any(path.is_relative_to(root) for root in ALLOWED_READ_ROOTS),
        "unreviewed physical read path",
    )
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        require(
            stat.S_ISREG(before.st_mode)
            and before.st_nlink == 1
            and 0 <= before.st_size <= maximum,
            "unbounded or nonregular source",
        )
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(maximum + 1)
        after, named = os.fstat(fd), path.lstat()
        require(
            len(raw) == before.st_size <= maximum
            and metadata(before) == metadata(after) == metadata(named),
            "source changed during the original descriptor read",
        )
        check()
        return raw, metadata(before)
    finally:
        os.close(fd)


def register(row):
    path = row["path"]
    expected = {
        key: row[key]
        for key in ("path", "bytes", "sha256", "git_blob")
        if row.get(key) is not None
    }
    require(
        isinstance(path, str)
        and type(expected.get("bytes")) is int
        and 0 <= expected["bytes"] <= 64 * 1024 * 1024
        and isinstance(expected.get("sha256"), str)
        and len(expected["sha256"]) == 64
        and all(char in "0123456789abcdef" for char in expected["sha256"]),
        "invalid fixed input/tool pin",
    )
    if path in READS:
        previous = READS[path]
        require(
            all(
                previous[key] == expected[key]
                for key in previous.keys() & expected.keys()
            ),
            "one physical input has conflicting pins",
        )
        expected = {**previous, **expected}
    READS[path] = expected
    return expected


def read(row):
    expected = register(row)
    path = expected["path"]
    raw, observed = regular(path)
    actual = pin(raw)
    require(
        all(actual[key] == expected[key] for key in expected if key != "path"),
        "original input/tool pin differs: " + path,
    )
    BEFORE_METADATA.setdefault(path, observed)
    return raw


def save(relative, raw):
    require(OWNED, "fresh output directory is not owned")
    path = OUT / relative
    require(
        path.is_relative_to(OUT) and path.resolve() == path,
        "output escaped original scope",
    )
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"path": str(path), **pin(raw)}


def census(root):
    root = Path(root)
    require(
        root.resolve() == root and root.is_relative_to(BASE),
        "package/output root changed",
    )
    pending, files, dirs, count = [root], [], [], 0
    while pending:
        check()
        folder = pending.pop()
        require(stat.S_ISDIR(folder.lstat().st_mode), "unexpected census ancestor")
        with os.scandir(folder) as entries:
            for entry in entries:
                count += 1
                require(count <= 1000, "fixed tool/output census bound")
                path = Path(entry.path)
                value = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(value.st_mode):
                    dirs.append(path.relative_to(root).as_posix())
                    pending.append(path)
                else:
                    require(
                        stat.S_ISREG(value.st_mode) and value.st_nlink == 1,
                        "unexpected tool/output link or special entry",
                    )
                    files.append(path.relative_to(root).as_posix())
    return {"files": sorted(files), "directories": sorted(dirs)}


def leader_exited(process):
    while True:
        try:
            value = os.waitid(
                os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT
            )
            break
        except InterruptedError:
            continue
    if value is None:
        return False
    require(
        value.si_pid == process.pid
        and value.si_code in (os.CLD_EXITED, os.CLD_KILLED, os.CLD_DUMPED),
        "owned child wait status changed",
    )
    return True


def darwin_exited_leader_only(process):
    if sys.platform != "darwin":
        return False
    try:
        if not leader_exited(process):
            return False
        import ctypes

        library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        call = library.proc_listpids
        call.argtypes = [
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        call.restype = ctypes.c_int
        members = (ctypes.c_int * 2)()
        ctypes.set_errno(0)
        size = call(2, process.pid, members, ctypes.sizeof(members))
        return (
            size == ctypes.sizeof(ctypes.c_int)
            and members[0] == process.pid
            and ctypes.get_errno() == 0
        )
    except (OSError, AttributeError, ValueError):
        return False


class DarwinOriginalGroup:
    """Read-only libproc identity/PGID observations while Popen's leader is unreaped."""

    def __init__(self):
        import ctypes

        self.ctypes = ctypes
        self.library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)

        class BsdInfo(ctypes.Structure):
            _fields_ = [
                ("flags", ctypes.c_uint32),
                ("status", ctypes.c_uint32),
                ("xstatus", ctypes.c_uint32),
                ("pid", ctypes.c_uint32),
                ("ppid", ctypes.c_uint32),
                ("uid", ctypes.c_uint32),
                ("gid", ctypes.c_uint32),
                ("ruid", ctypes.c_uint32),
                ("rgid", ctypes.c_uint32),
                ("svuid", ctypes.c_uint32),
                ("svgid", ctypes.c_uint32),
                ("reserved", ctypes.c_uint32),
                ("comm", ctypes.c_char * 16),
                ("name", ctypes.c_char * 32),
                ("nfiles", ctypes.c_uint32),
                ("pgid", ctypes.c_uint32),
                ("pjobc", ctypes.c_uint32),
                ("tty", ctypes.c_uint32),
                ("tty_pgid", ctypes.c_uint32),
                ("nice", ctypes.c_int32),
                ("start_seconds", ctypes.c_uint64),
                ("start_microseconds", ctypes.c_uint64),
            ]

        self.BsdInfo = BsdInfo
        require(ctypes.sizeof(BsdInfo) == 136, "Darwin proc_bsdinfo ABI differs")
        self.pidinfo = self.library.proc_pidinfo
        self.pidinfo.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint64,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        self.pidinfo.restype = ctypes.c_int
        self.listpids = self.library.proc_listpids
        self.listpids.argtypes = [
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        self.listpids.restype = ctypes.c_int

    def original_leader(self, process):
        ctypes = self.ctypes
        value = self.BsdInfo()
        ctypes.set_errno(0)
        size = self.pidinfo(
            process.pid, 3, 0, ctypes.byref(value), ctypes.sizeof(value)
        )
        error = ctypes.get_errno()
        raw = ctypes.string_at(ctypes.byref(value), ctypes.sizeof(value))
        row = {
            "api": "proc_pidinfo",
            "flavor": "PROC_PIDTBSDINFO",
            "flavor_value": 3,
            "returned_bytes": size,
            "errno": error,
            "raw_hex": raw.hex(),
            "raw_pin": pin(raw),
            "pid": value.pid,
            "ppid": value.ppid,
            "pgid": value.pgid,
            "birth_seconds": value.start_seconds,
            "birth_microseconds": value.start_microseconds,
            "observed_monotonic_seconds": time.monotonic(),
            "held_unreaped_Popen_pid": process.pid,
        }
        require(
            size == ctypes.sizeof(value)
            and error == 0
            and value.pid == process.pid
            and value.ppid == os.getpid()
            and value.pgid == process.pid
            and value.start_seconds > 0
            and value.start_microseconds < 1000000
            and process.returncode is None,
            "original leader PID/birth/parent/PGID cannot be verified: " + repr(row),
        )
        return row

    def snapshot(self, process, original):
        ctypes = self.ctypes
        require(
            process.returncode is None, "group cannot be observed after leader reap"
        )
        require(
            original is not None
            and original["pid"] == process.pid
            and original["pgid"] == process.pid,
            "original leader identity is absent",
        )
        held_exited = leader_exited(process)
        members = (ctypes.c_int * 4097)()
        ctypes.set_errno(0)
        size = self.listpids(2, process.pid, members, ctypes.sizeof(members))
        error = ctypes.get_errno()
        raw_members = list(
            members[: max(0, min(4097, size // ctypes.sizeof(ctypes.c_int)))]
        )
        row = {
            "api": "proc_listpids",
            "type": "PROC_PGRP_ONLY",
            "type_value": 2,
            "original_pgid": process.pid,
            "original_leader": original,
            "returned_bytes": size,
            "errno": error,
            "members": raw_members,
            "held_leader_exited_WNOWAIT": held_exited,
            "observed_monotonic_seconds": time.monotonic(),
            "scope_is_only_the_original_process_group": True,
            "detached_or_reparented_descendants_proven": False,
        }
        require(
            error == 0
            and 0 <= size < ctypes.sizeof(members)
            and size % ctypes.sizeof(ctypes.c_int) == 0
            and len(raw_members) == len(set(raw_members))
            and all(pid > 0 for pid in raw_members),
            "original PGID snapshot failed or exceeded its bound: " + repr(row),
        )
        row["original_group_terminal_before_reap"] = held_exited and set(
            raw_members
        ).issubset({process.pid})
        return row


def run(name, argv):
    check(COMMAND_STOP - 1)
    row = {
        "name": name,
        "argv": argv,
        "pid": None,
        "returncode": None,
        "started_monotonic_seconds": time.monotonic(),
        "attempts": 1,
        "complete_stdout": False,
        "complete_stderr": False,
        "original_group_cleanup": None,
        "actual_child_reaped": False,
    }
    RESULT["commands"].append(row)
    streams, raw, eof = {}, {"stdout": bytearray(), "stderr": bytearray()}, set()
    process = None
    native_group = None
    cleanup_errors = []
    child_cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
    env = {
        key: value
        for key, value in os.environ.items()
        if key in ("HOME", "TMPDIR", "LANG", "LC_ALL", "USER", "LOGNAME", "TERM")
    }
    env.update(COMMAND_ENV)
    env.update({"CI": "true", "NO_COLOR": "1", "NO_UPDATE_NOTIFIER": "1"})
    try:
        for kind in raw:
            streams[kind] = (OUT / "evidence" / (name + "." + kind)).open("xb")
        require(
            all(
                hasattr(os, name)
                for name in (
                    "waitid",
                    "P_PID",
                    "WEXITED",
                    "WNOHANG",
                    "WNOWAIT",
                    "CLD_EXITED",
                    "CLD_KILLED",
                    "CLD_DUMPED",
                )
            ),
            "original non-reaping wait API is unavailable",
        )
        native_group = DarwinOriginalGroup()
        process = subprocess.Popen(
            argv,
            cwd=OUT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            start_new_session=True,
        )
        # Signal handlers only latch; the cleanup region owns this child before
        # the first explicit cancellation/deadline check can throw.
        try:
            row["pid"] = process.pid
            row["original_leader_identity"] = native_group.original_leader(process)
            with selectors.DefaultSelector() as selector:
                for kind, pipe in (
                    ("stdout", process.stdout),
                    ("stderr", process.stderr),
                ):
                    os.set_blocking(pipe.fileno(), False)
                    selector.register(pipe, selectors.EVENT_READ, kind)
                while True:
                    check(COMMAND_STOP - 1)
                    if len(eof) == 2 and leader_exited(process):
                        break
                    events = (
                        selector.select(
                            min(0.05, max(0, COMMAND_STOP - 1 - time.monotonic()))
                        )
                        if len(eof) < 2
                        else []
                    )
                    check(COMMAND_STOP - 1)
                    if len(eof) == 2:
                        time.sleep(0.005)
                    for key, _ in events:
                        kind = key.data
                        chunk = os.read(key.fileobj.fileno(), 65536)
                        if not chunk:
                            eof.add(kind)
                            selector.unregister(key.fileobj)
                            continue
                        require(
                            len(raw[kind]) + len(chunk) <= 2 * 1024 * 1024,
                            "producer output exceeded its retained bound",
                        )
                        streams[kind].write(chunk)
                        raw[kind].extend(chunk)
        finally:
            reserved = False
            try:
                leader_exited(process)
                reserved = True
                snapshots, observation_errors, kill_error = [], [], None
                original = row.get("original_leader_identity")
                terminal = False
                try:
                    first = native_group.snapshot(process, original)
                    snapshots.append(first)
                    terminal = first["original_group_terminal_before_reap"]
                except BaseException as error:
                    observation_errors.append(repr(error))
                if terminal:
                    row["original_group_cleanup"] = (
                        "observed_terminal_before_reap_no_signal_needed"
                    )
                else:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                        row["original_group_cleanup"] = (
                            "one_original_group_signal_before_reap"
                        )
                    except ProcessLookupError:
                        row["original_group_cleanup"] = (
                            "group_absent_at_original_signal"
                        )
                    except BaseException as error:
                        kill_error = repr(error)
                    group_stop = min(STOP, time.monotonic() + 1)
                    for _ in range(64):
                        if time.monotonic() >= group_stop:
                            break
                        try:
                            item = native_group.snapshot(process, original)
                            snapshots.append(item)
                            terminal = item["original_group_terminal_before_reap"]
                        except BaseException as error:
                            observation_errors.append(repr(error))
                            break
                        if terminal:
                            break
                        time.sleep(min(0.005, max(0, group_stop - time.monotonic())))
                row["original_group_snapshots"] = snapshots
                row["original_group_observation_errors"] = observation_errors
                row["original_group_signal_error"] = kill_error
                row["original_group_terminal_observed"] = bool(
                    terminal
                    and not observation_errors
                    and kill_error is None
                    and time.monotonic() < STOP
                )
                require(
                    row["original_group_terminal_observed"],
                    "original group terminal is not proved before the unique reap",
                )
            finally:
                if reserved:
                    # No poll/wait/reap occurs before the LAST group signal.
                    process.wait(timeout=max(0.001, min(1, STOP - time.monotonic())))
                    row["returncode"] = process.returncode
                    row["actual_child_reaped"] = type(process.returncode) is int
    except BaseException as error:
        row["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        for pipe in (
            None if process is None else process.stdout,
            None if process is None else process.stderr,
        ):
            if pipe is not None:
                try:
                    pipe.close()
                except OSError as error:
                    cleanup_errors.append(str(error))
        for kind, stream in streams.items():
            try:
                stream.flush()
                os.fsync(stream.fileno())
            except OSError as error:
                cleanup_errors.append(str(error))
            finally:
                try:
                    stream.close()
                except OSError as error:
                    cleanup_errors.append(str(error))
            row[kind] = {
                "path": str(OUT / "evidence" / (name + "." + kind)),
                **pin(bytes(raw[kind])),
            }
            row["complete_" + kind] = kind in eof
        row["cleanup_errors"] = cleanup_errors
        row["elapsed_seconds"] = time.monotonic() - row["started_monotonic_seconds"]
        now = resource.getrusage(resource.RUSAGE_CHILDREN)
        row["child_cpu_seconds"] = (
            now.ru_utime + now.ru_stime - child_cpu.ru_utime - child_cpu.ru_stime
        )
    require(
        row["returncode"] == 0
        and row["actual_child_reaped"]
        and row["original_group_cleanup"] is not None
        and row.get("original_group_terminal_observed") is True
        and row["complete_stdout"]
        and row["complete_stderr"]
        and not cleanup_errors,
        "producer original exit, complete streams or owned cleanup failed",
    )
    check()


def diff(before, after, path):
    return "".join(
        difflib.unified_diff(
            before.decode().splitlines(True),
            after.decode().splitlines(True),
            fromfile="a/" + path,
            tofile="b/" + path,
        )
    )


class _NoIdentityRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("identity API redirects are not accepted")


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    value = {}
    for key, item in pairs:
        require(key not in value, f"duplicate JSON field: {key}")
        value[key] = item
    return value


def identity_remaining(deadline):
    check(deadline)
    left = deadline - time.monotonic()
    require(math.isfinite(left) and left > 0, "original identity deadline exhausted")
    return left


def identity_save(path, raw):
    check(STOP, cancel=False)
    return save(Path(path).relative_to(OUT).as_posix(), raw)


def identity_json(path, value):
    return identity_save(path, encode(value))


class IdentityAPI:
    def __init__(self, output, deadline):
        self.output, self.deadline, self.rows = output, deadline, []
        self.token = os.environ.get("GH_TOKEN", "")
        require(bool(self.token), "current workflow read token is absent")
        self.opener = urllib.request.build_opener(_NoIdentityRedirect())

    def get(self, suffix, label):
        require(
            re.fullmatch(r"[a-z0-9-]+", label) is not None, "identity evidence label"
        )
        url = "https://api.github.com/repos/" + HEPTA_REPOSITORY + suffix
        require(
            suffix.startswith("/") and "\\" not in suffix and "#" not in suffix,
            "identity API path",
        )
        row = {"request_url": url, "received_bytes": 0, "retained_bytes": 0}
        self.rows.append(row)
        chunks, original = [], None
        response = None
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "Authorization": "Bearer " + self.token,
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "User-Agent": "hepta-zsh-first-producer-v1",
                },
            )
            try:
                response = self.opener.open(
                    request, timeout=min(10, identity_remaining(self.deadline))
                )
            except urllib.error.HTTPError as error:
                response, original = error, error
            with response:
                row.update(
                    status=response.status,
                    response_url=response.geturl(),
                    headers=dict(response.headers.items()),
                )
                require(
                    row["response_url"] == url, "identity API response origin changed"
                )
                limit = 1024 * 1024 if original is not None else 12 * 1024 * 1024
                while True:
                    identity_remaining(self.deadline)
                    try:
                        block = response.read(
                            min(65536, limit - row["retained_bytes"] + 1)
                        )
                    except BaseException as error:
                        row["body_read_error"] = repr(error)
                        partial = getattr(error, "partial", b"")
                        if isinstance(partial, bytes):
                            row["received_bytes"] += len(partial)
                            kept = partial[: max(0, limit - row["retained_bytes"])]
                            chunks.append(kept)
                            row["retained_bytes"] += len(kept)
                            row["exception_partial_bytes"] = len(partial)
                            row["body_overflow"] = row["received_bytes"] > limit
                        elif partial:
                            row["exception_partial_unavailable"] = repr(type(partial))
                        if original is not None:
                            raise original from error
                        raise
                    if not block:
                        row["body_eof"] = True
                        break
                    row["received_bytes"] += len(block)
                    kept = block[: max(0, limit - row["retained_bytes"])]
                    chunks.append(kept)
                    row["retained_bytes"] += len(kept)
                    require(
                        row["received_bytes"] <= limit,
                        "identity API body exceeds its bound",
                    )
                if original is not None:
                    raise original
                require(row["status"] == 200, "identity API status")
                value = json.loads(
                    b"".join(chunks),
                    object_pairs_hook=_unique_object,
                    parse_constant=lambda value: (_ for _ in ()).throw(
                        ValueError(value)
                    ),
                )
                require(isinstance(value, dict), "identity API object")
                return value
        except BaseException as error:
            if original is None:
                original = error
            row["error"] = repr(original)
            if original is not error:
                raise original from error
            raise
        finally:
            raw = b"".join(chunks)
            row["sha256"] = hashlib.sha256(raw).hexdigest()
            try:
                identity_save(self.output / (label + ".body"), raw)
                identity_json(self.output / (label + ".json"), row)
                identity_remaining(self.deadline)
            except BaseException as retention:
                row["retention_error"] = repr(retention)
                if original is None:
                    raise
                original.add_note(
                    "identity API evidence retention failed: " + repr(retention)
                )


def source_pin(path):
    raw, observed = regular(path, 1024 * 1024)
    row = {"path": str(path), **pin(raw)}
    register(row)
    BEFORE_METADATA[row["path"]] = observed
    return raw, row


def utc_seconds(value):
    require(isinstance(value, str) and value.endswith("Z"), "provider UTC timestamp")
    return datetime.datetime.fromisoformat(value[:-1] + "+00:00").timestamp()


def anchor_clock(bootstrap, job):
    global START, STOP, OP_STOP, COMMAND_STOP
    stamp = utc_seconds(job["started_at"])
    require(
        type(bootstrap["utc_seconds"]) in (int, float)
        and type(bootstrap["monotonic_seconds"]) in (int, float),
        "bootstrap clocks",
    )
    delta = bootstrap["utc_seconds"] - stamp
    require(math.isfinite(delta) and 0 <= delta <= 1800, "job/bootstrap clock order")
    origin = bootstrap["monotonic_seconds"] - delta
    require(origin <= PROCESS_START <= time.monotonic(), "monotonic job origin differs")
    START = origin
    STOP, OP_STOP, COMMAND_STOP = START + 1800, START + 1500, START + 1440
    check()
    RESULT["clock"] = {
        "provider_job_started_at": job["started_at"],
        "bootstrap_monotonic": bootstrap["monotonic_seconds"],
        "bootstrap_utc": bootstrap["utc_seconds"],
        "provider_to_bootstrap_seconds": delta,
        "job_origin_monotonic": START,
        "owner_process_start_monotonic": PROCESS_START,
        "owner_preceding_job_seconds": PROCESS_START - START,
        "work_stop": OP_STOP,
        "command_stop": COMMAND_STOP,
        "whole_stop": STOP,
        "verification_reserve_within_work_seconds": 60,
        "external_provider_completed_at_required": True,
    }


def load_collector(raw):
    name = "_hepta_zsh_first_producer_collector"
    require(name not in sys.modules, "collector module is already present")
    module = types.ModuleType(name)
    module.__file__ = str(BASE / COLLECTOR)
    module.__package__ = ""
    sys.modules[name] = module
    try:
        exec(compile(raw, module.__file__, "exec"), module.__dict__)
    except BaseException:
        del sys.modules[name]
        raise
    return module


def provider_identity(api, inp, event, bootstrap):
    run_id = int(bootstrap["run_id"])
    require(
        bootstrap["run_attempt"] == "1"
        and event.get("action") == "opened"
        and os.environ.get("GITHUB_EVENT_NAME") == "pull_request"
        and os.environ.get("GITHUB_JOB") == "produce",
        "only the first natural opened attempt is admitted",
    )
    pr = event.get("pull_request", {})
    head, number = pr.get("head", {}).get("sha"), event.get("number")
    require(
        HEX40.fullmatch(head or "")
        and type(number) is int
        and number > 0
        and pr.get("draft") is True
        and pr.get("head", {}).get("ref") == BRANCH
        and pr.get("base", {}).get("ref") == BASE_BRANCH
        and pr.get("base", {}).get("sha") == PARENT["head"]
        and pr.get("head", {}).get("repo", {}).get("full_name") == REPOSITORY
        and pr.get("base", {}).get("repo", {}).get("full_name") == REPOSITORY,
        "wrong candidate, base, repository or non-Draft event",
    )
    require(
        bootstrap["source_head"] == head
        and os.environ.get("HEPTA_ZSH_SOURCE_HEAD") == head
        and bootstrap["event_sha"] == os.environ.get("GITHUB_SHA")
        and HEX40.fullmatch(bootstrap["event_sha"]),
        "provider event/source selector differs",
    )
    require(
        event.get("sender", {}).get("login") == inp["approved_actor"]
        and os.environ.get("GITHUB_ACTOR") == inp["approved_actor"],
        "actor differs from the concrete Root admission",
    )
    run = api.get(f"/actions/runs/{run_id}/attempts/1", "original-run")
    require(
        run.get("id") == run_id
        and run.get("run_attempt") == 1
        and run.get("head_sha") == head
        and run.get("head_branch") == BRANCH
        and run.get("event") == "pull_request"
        and run.get("status") == "in_progress"
        and run.get("conclusion") is None
        and run.get("path") == WORKFLOW
        and run.get("repository", {}).get("full_name") == REPOSITORY
        and type(run.get("workflow_id")) is int
        and run["workflow_id"] > 0,
        "actual producer run differs",
    )
    prs = [row for row in run.get("pull_requests", []) if row.get("number") == number]
    require(
        len(prs) == 1
        and prs[0].get("head", {}).get("sha") == head
        and prs[0].get("base", {}).get("sha") == PARENT["head"],
        "original run PR binding differs",
    )
    jobs = api.get(
        f"/actions/runs/{run_id}/attempts/1/jobs?per_page=100", "original-jobs"
    )
    require(
        jobs.get("total_count") == 1 and len(jobs.get("jobs", [])) == 1,
        "producer is not exactly one job",
    )
    job = jobs["jobs"][0]
    require(
        job.get("name") == JOB_NAME
        and job.get("status") == "in_progress"
        and job.get("conclusion") is None
        and job.get("run_id") == run_id
        and job.get("run_attempt") == 1
        and job.get("head_sha") == head
        and job.get("runner_name") == os.environ.get("RUNNER_NAME")
        and type(job.get("id")) is int
        and job["id"] > 0
        and type(job.get("runner_id")) is int
        and job["runner_id"] > 0,
        "actual original job/runner binding differs",
    )
    current = [
        row
        for row in job.get("steps", [])
        if row.get("name") == "Build the one source-bound zsh artifact"
    ]
    require(
        len(current) == 1
        and current[0].get("status") == "in_progress"
        and current[0].get("conclusion") is None,
        "wrong current producer step",
    )
    require("macos-26" in job.get("labels", []), "actual job is not the selected label")
    anchor_clock(bootstrap, job)
    api.deadline = OP_STOP
    history = api.get(
        f"/actions/workflows/{run['workflow_id']}/runs"
        "?event=pull_request&branch=fix%2Fhepta-zsh-first-producer-20261127-7c9e&per_page=100",
        "original-scope-history",
    )
    require(
        history.get("total_count") == 1
        and len(history.get("workflow_runs", [])) == 1
        and history["workflow_runs"][0].get("id") == run_id
        and history["workflow_runs"][0].get("run_attempt") == 1
        and history["workflow_runs"][0].get("head_sha") == head,
        "this fixed producer branch already has another attempt/run",
    )
    actual_pr = api.get(f"/pulls/{number}", "original-pr")
    require(
        actual_pr.get("number") == number
        and actual_pr.get("state") == "open"
        and actual_pr.get("draft") is True
        and actual_pr.get("head", {}).get("sha") == head
        and actual_pr.get("head", {}).get("ref") == BRANCH
        and actual_pr.get("base", {}).get("sha") == PARENT["head"]
        and actual_pr.get("base", {}).get("ref") == BASE_BRANCH,
        "live exact PR identity differs",
    )
    commit = api.get("/git/commits/" + head, "original-source-commit")
    require(
        commit.get("sha") == head
        and [row.get("sha") for row in commit.get("parents", [])] == [PARENT["head"]],
        "source commit does not have the sole fixed real parent",
    )
    tree_sha = commit.get("tree", {}).get("sha")
    require(HEX40.fullmatch(tree_sha or "") is not None, "source tree")
    changes = api.get("/commits/" + head, "original-source-paths")
    files = changes.get("files", [])
    require(
        changes.get("sha") == head
        and [row.get("sha") for row in changes.get("parents", [])] == [PARENT["head"]]
        and len(files) == len(SOURCE_PATHS)
        and sorted(row.get("filename") for row in files) == list(SOURCE_PATHS)
        and all(
            row.get("status") == ("modified" if row["filename"] == PATCH else "added")
            for row in files
        ),
        "candidate changed-path scope differs",
    )
    full_tree = api.get(
        "/git/trees/" + tree_sha + "?recursive=1", "original-source-tree"
    )
    return (
        {
            "repository": REPOSITORY,
            "PR": number,
            "head": head,
            "tree": tree_sha,
            "sole_parent": PARENT["head"],
            "event_sha": bootstrap["event_sha"],
            "branch": BRANCH,
            "base_branch": BASE_BRANCH,
            "run_id": run_id,
            "run_attempt": 1,
            "job_id": job["id"],
            "runner_id": job["runner_id"],
            "runner_name": job["runner_name"],
            "provider_job_started_at": job["started_at"],
            "workflow": WORKFLOW,
            "whole_provider_job_seconds": None,
            "external_terminal_observation_required": True,
        },
        full_tree,
        files,
    )


def resolve_tool(name, collector, optional=False, explicit=None):
    lookup = explicit if explicit is not None else shutil.which(name, path=BASE_PATH)
    if lookup is None and optional:
        return None
    require(
        isinstance(lookup, str)
        and Path(lookup).is_absolute()
        and "\n" not in lookup
        and "\r" not in lookup,
        "tool is unavailable: " + name,
    )
    path = Path(lookup).resolve(strict=True)
    roots = tuple(
        Path(value)
        for value in ("/usr", "/bin", "/sbin", "/opt", "/Applications", "/Library")
    )
    require(
        any(path.is_relative_to(root) for root in roots), "unapproved tool location"
    )
    before_alias = Path(lookup).lstat()
    row = collector.stable_digest(path, 512 * 1024 * 1024, check)
    require(row["metadata"]["mode"] & 0o111, "tool is not executable")
    require(
        metadata(before_alias) == metadata(Path(lookup).lstat())
        and Path(lookup).resolve(strict=True) == path,
        "tool alias changed",
    )
    return {
        "name": name,
        "lookup_path": lookup,
        "physical_path": str(path),
        "lookup_metadata": metadata(before_alias),
        "file": row,
    }


def verify_tools(rows, collector):
    checked = []
    for row in rows:
        check()
        require(
            Path(row["lookup_path"]).resolve(strict=True) == Path(row["physical_path"])
            and metadata(Path(row["lookup_path"]).lstat()) == row["lookup_metadata"],
            "tool lookup path changed",
        )
        after = collector.stable_digest(
            Path(row["physical_path"]), 512 * 1024 * 1024, check
        )
        require(after == row["file"], "original tool bytes or native identity changed")
        checked.append({"name": row["name"], "unchanged": True, "observed": after})
    return checked


def evidence_outputs(collector):
    pending = [OUT / "evidence", OUT / "artifacts"]
    rows, seen, total = [], 0, 0
    while pending:
        check(STOP, cancel=False)
        root = pending.pop()
        require(
            root.resolve(strict=True) == root and root.is_relative_to(OUT),
            "retention directory alias",
        )
        with os.scandir(root) as entries:
            for entry in entries:
                seen += 1
                require(seen <= 2000, "evidence member bound")
                path = Path(entry.path)
                value = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(value.st_mode):
                    pending.append(path)
                else:
                    require(
                        stat.S_ISREG(value.st_mode) and value.st_nlink == 1,
                        "unexpected evidence link or special file",
                    )
                    row = collector.stable_digest(
                        path, 32 * 1024 * 1024, lambda: check(STOP, cancel=False)
                    )
                    total += row["bytes"]
                    require(total <= 128 * 1024 * 1024, "retained evidence total bound")
                    rows.append({"relative": path.relative_to(OUT).as_posix(), **row})
    return {
        "files": sorted(rows, key=lambda row: row["relative"]),
        "bytes": total,
        "file_count": len(rows),
    }


def retain_generated_diagnostics(collector):
    """Copy only this build's fixed regular diagnostics after its original child closes."""
    rows, errors, total = [], {}, 0
    live_or_unknown = [
        row["name"]
        for row in RESULT["commands"]
        if row.get("pid") is not None
        and (
            row.get("actual_child_reaped") is not True
            or row.get("original_group_terminal_observed") is not True
        )
    ]
    if live_or_unknown:
        return {
            "files": [],
            "errors": {"original_custody": live_or_unknown},
            "copied_bytes": 0,
            "skipped_due_to_unknown_original_group": True,
        }
    source = OUT / "work" / "zsh"
    for relative in (
        "configure",
        "config.log",
        "config.status",
        "config.h",
        "config.h.in",
        "Makefile",
        "Src/Makefile",
    ):
        item = {"relative": relative, "present": None, "retained": False}
        rows.append(item)
        try:
            check(STOP, cancel=False)
            path = source / relative
            try:
                value = path.lstat()
            except FileNotFoundError:
                item["present"] = False
                continue
            item["present"] = True
            require(
                stat.S_ISREG(value.st_mode) and value.st_nlink == 1,
                "generated diagnostic is linked or nonregular",
            )
            raw, identity = collector.stable_raw(
                path, 4 * 1024 * 1024, lambda: check(STOP, cancel=False)
            )
            total += len(raw)
            require(total <= 24 * 1024 * 1024, "generated diagnostic total bound")
            item["source"] = {**pin(raw), "metadata": identity}
            item["output"] = save("evidence/generated-final/" + relative, raw)
            item["retained"] = True
        except BaseException as error:
            item["error"] = repr(error)
            errors[relative] = repr(error)
    return {
        "files": rows,
        "errors": errors,
        "copied_bytes": total,
        "only_fixed_generated_diagnostics": True,
        "partial_compiler_objects_and_full_worktree_uploaded": False,
    }


def validate_input(inp):
    require(
        inp.get("schema") == "hepta-zsh-first-producer-input-v1"
        and inp.get("activated") is True
        and inp.get("scope_id") == SCOPE
        and inp.get("caps") == CAPS
        and inp.get("source_parent") == PARENT
        and inp.get("candidate_head") is None
        and inp.get("candidate_tree") is None
        and inp.get("source_paths") == list(SOURCE_PATHS)
        and inp.get("upstream_commit") == UPSTREAM
        and inp.get("upstream_tree") == UPSTREAM_TREE
        and inp.get("upstream_url") == "https://git.code.sf.net/p/zsh/code"
        and inp.get("deployment_target") == "15.0"
        and inp.get("runner_label") == "macos-26"
        and inp.get("future_provider") is None
        and inp.get("future_archive_digest") is None
        and inp.get("future_blake3") is None
        and inp.get("future_release_tag") is None
        and inp.get("E1_E6_added") == 0
        and inp.get("E6_remaining_seconds") == 1.9960488015785813,
        "inactive or changed producer contract",
    )
    admission = inp.get("root_admission", {})
    raw = inp.get("ordinary_budget_receipt_raw")
    require(
        admission.get("accepted") is True
        and admission.get("reviewer") == "root"
        and isinstance(raw, str)
        and 0 < len(raw.encode()) <= 65536
        and HEX64.fullmatch(admission.get("receipt_sha256") or "")
        and pin(raw.encode())["sha256"] == admission["receipt_sha256"],
        "actual ordinary Root budget receipt is absent",
    )
    budget = unique_json(raw.encode())
    require(
        budget.get("schema") == "root-hepta-zsh-first-producer-budget-v1"
        and budget.get("accepted") is True
        and budget.get("reviewer") == "root"
        and budget.get("scope_id") == SCOPE
        and budget.get("caps") == CAPS
        and budget.get("source_parent") == PARENT
        and budget.get("source_pins") == inp.get("source_pins")
        and budget.get("approved_actor") == inp.get("approved_actor")
        and budget.get("branch") == BRANCH
        and budget.get("base_branch") == BASE_BRANCH
        and budget.get("event") == "pull_request.opened"
        and budget.get("attempt_limit") == 1
        and budget.get("release_or_tag_write") is False
        and budget.get("E1_E6_added") == 0,
        "Root receipt does not authorize this exact ordinary source scope",
    )
    require(
        isinstance(inp.get("approved_actor"), str)
        and inp["approved_actor"]
        and len(inp["approved_actor"]) <= 100,
        "unbound publisher actor",
    )
    rows = inp.get("source_pins")
    require(
        isinstance(rows, list)
        and len(rows) == len(SOURCE_PATHS) - 1
        and sorted(row.get("repo_path") for row in rows)
        == [path for path in SOURCE_PATHS if path != INPUT],
        "noncircular exact source pin roster differs",
    )
    return rows


def setup_scope(retention_only=False):
    global BASE, OUT, ALLOWED_READ_ROOTS, START, STOP, OP_STOP, COMMAND_STOP, OWNED
    run_id, attempt = (
        os.environ.get("GITHUB_RUN_ID", ""),
        os.environ.get("GITHUB_RUN_ATTEMPT", ""),
    )
    require(
        re.fullmatch(r"[1-9][0-9]*", run_id) and attempt == "1",
        "invalid or replayed provider run",
    )
    BASE = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    temp = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    OUT = temp / ("hepta-zsh-first-producer-" + run_id + "-" + attempt)
    ALLOWED_READ_ROOTS = (BASE, temp)
    require(
        sys.platform == "darwin"
        and platform.machine() == "arm64"
        and platform.mac_ver()[0].split(".", 1)[0] == "26"
        and os.environ.get("RUNNER_OS") == "macOS"
        and os.environ.get("RUNNER_ARCH") == "ARM64",
        "only the admitted macOS26 ARM host is allowed",
    )
    require(
        OUT.is_dir() and not OUT.is_symlink() and OUT.resolve(strict=True) == OUT,
        "fresh bootstrap directory is absent",
    )
    raw, bootstrap_pin = source_pin(OUT / "BOOTSTRAP.json")
    bootstrap = unique_json(raw)
    require(
        bootstrap.get("schema") == "hepta-zsh-first-producer-bootstrap-v1"
        and bootstrap.get("scope_id") == SCOPE
        and bootstrap.get("run_id") == run_id
        and bootstrap.get("run_attempt") == attempt
        and bootstrap.get("root") == str(OUT)
        and bootstrap.get("workspace") == str(BASE)
        and bootstrap.get("repository") == REPOSITORY
        and bootstrap.get("event_name") == "pull_request"
        and bootstrap.get("job") == "produce"
        and bootstrap.get("source_head") == os.environ.get("HEPTA_ZSH_SOURCE_HEAD"),
        "bootstrap does not bind this exact source run",
    )
    require(
        type(bootstrap.get("monotonic_seconds")) in (int, float)
        and 0
        <= PROCESS_START - bootstrap["monotonic_seconds"]
        < (1800 if retention_only else 1500),
        "bootstrap elapsed already exhausted",
    )
    START = bootstrap["monotonic_seconds"]
    STOP, OP_STOP, COMMAND_STOP = START + 1800, START + 1500, START + 1440
    return bootstrap, raw, bootstrap_pin


def original_main():
    global OWNED, FINALIZING, COMMAND_ENV
    collector, api, inp, identity, repo_before, upstream_before = (None,) * 6
    tools_before, after_tools, head_fd, head_identity, held_head = (
        [],
        [],
        None,
        None,
        None,
    )
    passed = False
    try:
        for number in (signal.SIGINT, signal.SIGTERM):
            HANDLERS[number] = signal.getsignal(number)
            signal.signal(number, observed_signal)
        require(
            signal.getsignal(signal.SIGCHLD) == signal.SIG_DFL,
            "original SIGCHLD ownership",
        )
        bootstrap, boot_raw, boot_pin = setup_scope()
        require(
            sorted(path.name for path in OUT.iterdir()) == ["BOOTSTRAP.json"],
            "bootstrap output was already consumed or contains extras",
        )
        for name in ("evidence", "artifacts", "work"):
            (OUT / name).mkdir(mode=0o700, exist_ok=False)
        (OUT / "evidence" / "api").mkdir(mode=0o700, exist_ok=False)
        OWNED = True
        save("evidence/BOOTSTRAP.json", boot_raw)
        save(
            "evidence/OWNER_STARTED.json",
            encode(
                {
                    "process_pid": os.getpid(),
                    "owner_started_monotonic": PROCESS_START,
                    "bootstrap_pin": boot_pin,
                    "no_budget_reset": True,
                }
            ),
        )
        input_raw, input_pin = source_pin(BASE / INPUT)
        inp = unique_json(input_raw)
        pin_rows = validate_input(inp)
        RESULT["source_pin_rows"] = pin_rows
        save("evidence/INPUT.actual.json", input_raw)
        source_bytes = {INPUT: input_raw}
        for row in pin_rows:
            require(
                row["repo_path"] in SOURCE_PATHS
                and row["repo_path"] != INPUT
                and row["mode"] in ("100644", "100755"),
                "source pin path or mode",
            )
            ref = {
                "path": str(BASE / row["repo_path"]),
                **{key: row[key] for key in ("bytes", "sha256", "git_blob")},
            }
            source_bytes[row["repo_path"]] = read(ref)
        event_raw, event_pin = source_pin(
            Path(os.environ["GITHUB_EVENT_PATH"]).resolve(strict=True)
        )
        event = unique_json(event_raw)
        save("evidence/EVENT.original.json", event_raw)
        api = IdentityAPI(OUT / "evidence" / "api", OP_STOP)
        identity, full_tree, changed = provider_identity(api, inp, event, bootstrap)
        RESULT["actual_candidate"] = identity
        for path, raw in source_bytes.items():
            leaves = [
                row for row in full_tree.get("tree", []) if row.get("path") == path
            ]
            require(
                len(leaves) == 1
                and leaves[0].get("type") == "blob"
                and leaves[0].get("sha") == pin(raw)["git_blob"]
                and leaves[0].get("size") == len(raw)
                and leaves[0].get("mode")
                == (
                    "100644"
                    if path == INPUT
                    else next(
                        row["mode"] for row in pin_rows if row["repo_path"] == path
                    )
                ),
                "executing source not in actual tree",
            )
        collector = load_collector(source_bytes[COLLECTOR])
        source_leaves = collector.api_tree(full_tree, identity["tree"])
        repo_before = collector.physical_tree(
            BASE, source_leaves, check, reject_untracked=True
        )
        require(
            (BASE / ".git").is_dir() and not (BASE / ".git").is_symlink(),
            "ordinary detached checkout metadata required",
        )
        head_path = BASE / ".git" / "HEAD"
        require(head_path.resolve(strict=True) == head_path, "HEAD ancestor alias")
        head_fd = os.open(head_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        head_identity = metadata(os.fstat(head_fd))
        require(
            stat.S_ISREG(head_identity["st_mode"]) and head_identity["st_nlink"] == 1,
            "HEAD is not an original regular file",
        )
        held_head = os.read(head_fd, 256)
        require(
            held_head == (identity["head"] + "\n").encode()
            and head_identity
            == metadata(os.fstat(head_fd))
            == metadata(head_path.lstat()),
            "local checkout is not the actual source head",
        )
        save(
            "evidence/SOURCE_IDENTITY.json",
            encode(
                {
                    "actual": identity,
                    "event": event_pin,
                    "input": input_pin,
                    "held_HEAD": {"bytes": pin(held_head), "metadata": head_identity},
                    "root_admission": inp["root_admission"],
                    "source_pin_rows": pin_rows,
                    "source_closure": {
                        "tree": identity["tree"],
                        "leaf_count": repo_before["leaf_count"],
                        "tracked_bytes": repo_before["total_bytes"],
                    },
                    "clock": RESULT["clock"],
                }
            ),
        )
        save("evidence/SOURCE_BEFORE.json", encode(repo_before))
        for path, raw in source_bytes.items():
            save("evidence/reviewed-sources/" + path, raw)
        base_names = (
            "bash",
            "git",
            "make",
            "xcrun",
            "xcode-select",
            "tar",
            "gzip",
            "touch",
            "grep",
            "sed",
            "awk",
            "sh",
            "cp",
            "chmod",
            "mkdir",
            "getconf",
            "perl",
            "otool",
            "file",
            "find",
            "cat",
        )
        by_name = {}
        for name in base_names:
            by_name[name] = resolve_tool(name, collector)
        by_name["python"] = resolve_tool("python", collector, explicit=sys.executable)
        by_name["brew"] = resolve_tool("brew", collector, optional=True)
        tools_before = [row for row in by_name.values() if row is not None]
        require(
            by_name["bash"]["physical_path"] == "/bin/bash",
            "the reviewed wrapper requires original /bin/bash",
        )
        COMMAND_ENV = {
            "PATH": BASE_PATH,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
            "HOMEBREW_NO_AUTO_UPDATE": "1",
            "HOMEBREW_NO_INSTALL_CLEANUP": "1",
            "HOMEBREW_NO_ENV_HINTS": "1",
            "COPYFILE_DISABLE": "1",
            "CCACHE_DISABLE": "1",
            "CONFIG_SITE": "/dev/null",
            "ZSH_COMMIT": UPSTREAM,
            "HEPTA_ZSH_PRODUCER_ROOT": str(OUT),
            "HEPTA_ZSH_PATCH_TEXT": source_bytes[PATCH].decode("utf-8"),
            "HEPTA_ALLOW_AUTOCONF_INSTALL": "true",
            "HEPTA_BREW": ""
            if by_name["brew"] is None
            else by_name["brew"]["physical_path"],
            "MACOSX_DEPLOYMENT_TARGET": "15.0",
        }
        for name in base_names:
            COMMAND_ENV["HEPTA_" + name.replace("-", "_").upper()] = by_name[name][
                "physical_path"
            ]
        save("evidence/TOOLS_INITIAL.json", encode(tools_before))
        script = source_bytes[BUILD_SCRIPT].decode("utf-8")
        run(
            "01-prepare-source-and-tools",
            ["/bin/bash", "-c", script, "hepta-zsh-build-only", "prepare"],
        )
        require(
            not (OUT / "work" / "zsh" / "Src" / "zsh").exists(),
            "fresh source unexpectedly contains a binary",
        )
        verify_tools(tools_before, collector)
        for name in ("autoconf", "autoheader", "autom4te", "m4", "clang"):
            raw, _ = regular(OUT / "evidence" / (name + "-command-path.txt"), 4096)
            lookup = raw.decode("utf-8").rstrip("\n")
            require(
                raw == (lookup + "\n").encode(), "tool path is not one original line"
            )
            row = resolve_tool(name, collector, explicit=lookup)
            by_name[name] = row
            tools_before.append(row)
        sdk_raw, _ = regular(OUT / "evidence" / "sdk-path.txt", 4096)
        sdk_path = Path(sdk_raw.decode("utf-8").rstrip("\n")).resolve(strict=True)
        require(
            sdk_path.is_dir() and sdk_path.is_relative_to(Path("/Applications")),
            "actual selected macOS SDK is not an Xcode SDK",
        )
        sdk_settings = {}
        for name in ("SDKSettings.json", "SDKSettings.plist"):
            path = sdk_path / name
            if path.is_file() and not path.is_symlink():
                sdk_settings[name] = collector.stable_digest(
                    path, 8 * 1024 * 1024, check
                )
        require(sdk_settings, "actual SDK settings are unavailable")
        save(
            "evidence/SDK_SETTINGS.json",
            encode(
                {
                    "path": str(sdk_path),
                    "settings": sdk_settings,
                    "complete_SDK_byte_closure_claimed": False,
                }
            ),
        )
        COMMAND_ENV.update(
            {
                "AUTOCONF": by_name["autoconf"]["physical_path"],
                "AUTOHEADER": by_name["autoheader"]["physical_path"],
                "HEPTA_AUTOM4TE": by_name["autom4te"]["physical_path"],
                "M4": by_name["m4"]["physical_path"],
                "CC": by_name["clang"]["physical_path"],
                "HEPTA_MAKE_JOBS": str(min(4, max(1, os.cpu_count() or 1))),
                "SDKROOT": str(sdk_path),
            }
        )
        save("evidence/TOOLS_BEFORE_BUILD.json", encode(tools_before))
        basis = collector.upstream_basis(
            OUT / "evidence", check, UPSTREAM, UPSTREAM_TREE
        )
        substitution = {
            "Src/exec.c": {
                "mode": "100644",
                "bytes": 174844,
                "git_blob": "f9cfa86d59c60592f214af0d12973a6c307baf8f",
            }
        }
        upstream_before = collector.physical_tree(
            OUT / "work" / "zsh",
            basis["leaves"],
            check,
            substitutions=substitution,
            reject_untracked=True,
        )
        require(
            upstream_before["files"]["Src/exec.c"]["sha256"]
            == "45c0a09c2ad874fa3a178a43998b875e44c89f8525b0def7081fdcd31e593622",
            "reviewed candidate exec.c differs",
        )
        save(
            "evidence/UPSTREAM_BASIS.json",
            encode({key: value for key, value in basis.items() if key != "leaves"}),
        )
        save("evidence/UPSTREAM_BEFORE_BUILD.json", encode(upstream_before))
        collector.events(
            OUT / "evidence" / "prepare-events.tsv",
            [
                "autoconf-prerequisite",
                "upstream-clone-once",
                "exact-upstream-checkout",
                "reviewed-patch-once",
            ],
            check,
        )
        RESULT["build_script_invocation_attempts"] = 1
        run(
            "02-build-smoke-and-package",
            ["/bin/bash", "-c", script, "hepta-zsh-build-only", "build"],
        )
        collector.events(
            OUT / "evidence" / "build-events.tsv",
            [
                "tool-identities",
                "preconfig-once",
                "configure-once",
                "make-once",
                "echo-wrapper-smoke-once",
                "missing-path-wrapper-smoke-once",
                "archive-once",
            ],
            check,
        )
        RESULT["preconfig_observation"] = collector.preconfig_observation(OUT, check)
        RESULT["compiler_build_attempts"] = 1
        RESULT["compiler_build_count_basis"] = (
            "one successful cold build script and exact phase transcript; not a kernel process trace"
        )
        RESULT["new_producer_smokes"] = collector.collect_smoke(
            OUT, by_name["touch"]["physical_path"], check
        )
        RESULT["archive"] = collector.collect_archive(OUT, check)
        upstream_after = collector.physical_tree(
            OUT / "work" / "zsh", basis["leaves"], check, substitutions=substitution
        )
        require(
            upstream_after == upstream_before,
            "upstream tracked bytes/identity changed during build",
        )
        save("evidence/UPSTREAM_AFTER_BUILD.json", encode(upstream_after))
        repo_after = collector.physical_tree(
            BASE, source_leaves, check, reject_untracked=True
        )
        require(repo_after == repo_before, "actual project source changed during build")
        save("evidence/SOURCE_AFTER.json", encode(repo_after))
        after_tools = verify_tools(tools_before, collector)
        save("evidence/TOOLS_AFTER.json", encode(after_tools))
        for name, before in sdk_settings.items():
            require(
                collector.stable_digest(sdk_path / name, 8 * 1024 * 1024, check)
                == before,
                "actual SDK settings changed",
            )
        os.lseek(head_fd, 0, os.SEEK_SET)
        require(
            os.read(head_fd, 256) == held_head
            and metadata(os.fstat(head_fd))
            == head_identity
            == metadata(head_path.lstat()),
            "held detached source HEAD changed",
        )
        check()
        passed = True
    except BaseException as error:
        RESULT["error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        FINALIZING = True
        if head_fd is not None:
            try:
                os.close(head_fd)
            except OSError as error:
                RESULT["head_close_error"] = repr(error)
                passed = False
        RESULT["api_requests"] = [] if api is None else api.rows
        audits = []
        for path, expected in READS.items():
            row = {"expected": expected, "unchanged": False}
            try:
                raw, observed = regular(path)
                row["actual"] = pin(raw)
                row["metadata_before"] = BEFORE_METADATA.get(path)
                row["metadata_after"] = observed
                row["unchanged"] = all(
                    row["actual"][key] == expected[key]
                    for key in expected
                    if key != "path"
                ) and observed == BEFORE_METADATA.get(path)
            except BaseException as error:
                row["error"] = repr(error)
            audits.append(row)
        RESULT["input_audit"] = audits
        RESULT["all_declared_inputs_unchanged"] = bool(audits) and all(
            row["unchanged"] for row in audits
        )
        RESULT["observed_signals"] = list(SIGNALS)
        RESULT["all_two_owned_commands_complete"] = len(
            RESULT["commands"]
        ) == 2 and all(
            row["returncode"] == 0
            and row["actual_child_reaped"]
            and row["complete_stdout"]
            and row["complete_stderr"]
            and row["original_group_cleanup"] is not None
            and row.get("original_group_terminal_observed") is True
            and not row.get("error")
            and not row["cleanup_errors"]
            for row in RESULT["commands"]
        )
        RESULT["tools_verified_after_build"] = bool(after_tools)
        RESULT["whole_seconds_before_retention"] = time.monotonic() - START
        RESULT["toolchain_hermetic_claimed"] = False
        RESULT["platform_dependencies"] = (
            "Actual OS/image, compiler/tool byte identities, Xcode SDK settings and otool output "
            "are retained. The complete SDK/dyld/system-library content is not represented as hermetic."
        )
        errors = {}
        own_now = resource.getrusage(resource.RUSAGE_SELF)
        child_now = resource.getrusage(resource.RUSAGE_CHILDREN)
        RESULT["accounted_cpu_seconds"] = {
            "owner": own_now.ru_utime
            + own_now.ru_stime
            - OWN_CPU.ru_utime
            - OWN_CPU.ru_stime,
            "reaped_children": child_now.ru_utime
            + child_now.ru_stime
            - CHILD_CPU.ru_utime
            - CHILD_CPU.ru_stime,
            "full_provider_job_CPU_claimed": False,
        }
        RESULT["process_observation_scope"] = {
            "original_groups_only": True,
            "success_requires_original_leader_pid_birth_parent_pgid": True,
            "no_escaped_descendant_or_hermetic_tree_claim": True,
            "actual_per_command_observations_required": True,
        }
        if OWNED:
            if collector is not None:
                try:
                    generated = retain_generated_diagnostics(collector)
                    RESULT["generated_diagnostics"] = generated
                    save("evidence/GENERATED_DIAGNOSTICS.json", encode(generated))
                    if generated["errors"]:
                        errors["GENERATED_DIAGNOSTICS.json"] = generated["errors"]
                except BaseException as error:
                    errors["GENERATED_DIAGNOSTICS.json"] = repr(error)
            for name, raw in (
                ("INPUT_AUDIT.json", encode(audits)),
                ("COMMANDS.json", encode(RESULT["commands"])),
            ):
                try:
                    check(STOP, cancel=False)
                    save("evidence/" + name, raw)
                except BaseException as error:
                    errors[name] = repr(error)
            if collector is not None:
                try:
                    outputs = evidence_outputs(collector)
                    RESULT["retained_output_inventory"] = save(
                        "evidence/OUTPUT_INVENTORY.json", encode(outputs)
                    )
                except BaseException as error:
                    errors["OUTPUT_INVENTORY.json"] = repr(error)
        RESULT["retention_errors"] = errors
        RESULT["whole_seconds_before_result_io"] = time.monotonic() - START
        ready = (
            passed
            and RESULT["all_declared_inputs_unchanged"]
            and RESULT["all_two_owned_commands_complete"]
            and not errors
            and not SIGNALS
            and time.monotonic() < STOP
        )
        RESULT["status"] = (
            "PRODUCED_AWAITING_UPLOAD_AND_EXTERNAL_ACCEPTANCE"
            if ready
            else "FAIL_OR_UNKNOWN"
        )
        result_pin = None
        if OWNED:
            try:
                result_pin = save("evidence/RESULT.json", encode(RESULT))
            except BaseException as error:
                errors["RESULT.json"] = repr(error)
                ready = False
        print(
            json.dumps(
                {
                    "schema": "hepta-zsh-first-producer-owner-exit-v1",
                    "status": RESULT["status"],
                    "result": result_pin,
                    "retention_errors": errors,
                    "whole_seconds_after_result_io": time.monotonic() - START,
                    "signals_after_result_io": list(SIGNALS),
                    "actual_outer_exit_and_upload_and_provider_terminal_required": True,
                    "unretained_failure": RESULT if result_pin is None else None,
                }
            ),
            flush=True,
        )
        for number, previous in HANDLERS.items():
            signal.signal(number, previous)
        return 0 if ready and not SIGNALS and time.monotonic() < STOP else 1


def post_upload_main():
    global OWNED, FINALIZING, START, STOP, OP_STOP, COMMAND_STOP
    ready, result_pin = False, None
    record = {
        "schema": "hepta-zsh-first-producer-post-upload-v1",
        "status": "FAIL_OR_UNKNOWN",
        "this_local_record_is_not_inside_the_already_uploaded_artifact": True,
    }
    try:
        for number in (signal.SIGINT, signal.SIGTERM):
            HANDLERS[number] = signal.getsignal(number)
            signal.signal(number, observed_signal)
        FINALIZING = True
        bootstrap, _, _ = setup_scope(retention_only=True)
        OWNED = True
        raw, owner_pin = source_pin(OUT / "evidence" / "RESULT.json")
        owner = unique_json(raw)
        identity = owner["actual_candidate"]
        require(
            identity["run_id"] == int(bootstrap["run_id"])
            and identity["run_attempt"] == 1
            and identity["head"] == bootstrap["source_head"]
            and identity["event_sha"] == bootstrap["event_sha"],
            "post-upload identity changed",
        )
        anchor_clock(bootstrap, {"started_at": identity["provider_job_started_at"]})
        FINALIZING = True
        require(
            os.environ.get("HEPTA_PRODUCER_OUTCOME") == "success"
            and os.environ.get("HEPTA_UPLOAD_OUTCOME") == "success"
            and owner["status"] == "PRODUCED_AWAITING_UPLOAD_AND_EXTERNAL_ACCEPTANCE"
            and owner["all_two_owned_commands_complete"] is True
            and owner["all_declared_inputs_unchanged"] is True
            and not owner["observed_signals"]
            and not owner["retention_errors"],
            "producer or sole upload was not successful",
        )
        artifact_id = os.environ.get("HEPTA_ARTIFACT_ID", "")
        digest_raw = os.environ.get("HEPTA_ARTIFACT_DIGEST", "")
        archive_digest = digest_raw.removeprefix("sha256:")
        url = os.environ.get("HEPTA_ARTIFACT_URL", "")
        require(
            re.fullmatch(r"[1-9][0-9]*", artifact_id)
            and HEX64.fullmatch(archive_digest or "")
            and url
            == (
                "https://github.com/"
                + REPOSITORY
                + "/actions/runs/"
                + bootstrap["run_id"]
                + "/artifacts/"
                + artifact_id
            ),
            "actual upload response is incomplete",
        )
        for row in owner["source_pin_rows"]:
            current_raw, _ = regular(BASE / row["repo_path"], 1024 * 1024)
            require(
                all(
                    pin(current_raw)[key] == row[key]
                    for key in ("bytes", "sha256", "git_blob")
                ),
                "source changed before post-upload data observation",
            )
        record.update(
            actual_candidate=identity,
            owner_result=owner_pin,
            uploaded_artifact={
                "id": int(artifact_id),
                "sha256": archive_digest,
                "raw_digest": digest_raw,
                "url": url,
                "source": "actual pinned upload-action outputs; Root API verification pending",
            },
            local_raw_zsh_archive=owner["archive"]["archive"],
            smoke_observations=owner["new_producer_smokes"],
            whole_seconds_before_final_io=time.monotonic() - START,
            external_provider_job_terminal_required=True,
            external_whole_budget_verification_required=True,
            immutable_release_provider=None,
            DotSlash_updated=False,
            old_seven_Mac_regressions_executed=False,
            O_UNIQUE_qualified=False,
        )
        check(STOP)
        ready = True
    except BaseException as error:
        record["error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        FINALIZING = True
        record["signals"] = list(SIGNALS)
        record["status"] = (
            "UPLOAD_OBSERVED_AWAITING_ROOT_ACCEPTANCE"
            if ready and not SIGNALS
            else "FAIL_OR_UNKNOWN"
        )
        if OWNED:
            try:
                check(STOP, cancel=False)
                result_pin = save("POST_UPLOAD_RESULT.json", encode(record))
            except BaseException as error:
                record["retention_error"] = repr(error)
                ready = False
        print(
            json.dumps(
                {
                    "post_upload": record,
                    "local_result": result_pin,
                    "whole_seconds_after_final_io": time.monotonic() - START,
                    "actual_final_job_exit_and_duration_required": True,
                }
            ),
            flush=True,
        )
        for number, previous in HANDLERS.items():
            signal.signal(number, previous)
        return 0 if ready and not SIGNALS and time.monotonic() < STOP else 1


if __name__ == "__main__":
    if sys.argv[1:] == []:
        raise SystemExit(original_main())
    if sys.argv[1:] == ["--post-upload"]:
        raise SystemExit(post_upload_main())
    raise SystemExit(
        "only original build or data-only post-upload observation is admitted"
    )
