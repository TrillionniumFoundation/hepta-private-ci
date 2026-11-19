"""Linux-only, no-network actor boundary for prospective memory experiments.

A fresh bubblewrap sandbox receives only fixed system runtime directories,
reviewed public task bytes, the frozen actor, and (on only) explicit context.
The original writer, stores, histories and caches are never mounted. Commands
inherit this boundary; no external tool/RPC gateway is provided.

The caller must keep private data out of public inputs and /usr or /lib. This
is not a semantic leak detector, provider adapter or proof of memory benefit.
An unavailable namespace fails closed; no weakened fallback is attempted.
"""

import hashlib
import json
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import sys
import time
import uuid


MAX_INPUT_BYTES = 65536
MAX_OUTPUT_BYTES = 1048576
NAMESPACES = ("mnt", "pid", "net", "ipc", "uts", "user")
# Source loading is trusted; later on-disk edits cannot relabel already loaded code.
_LOADED_LAUNCHER_SOURCE = Path(__file__).read_bytes()
_BOOTSTRAP = r"""
import json, os, resource, runpy
# Bubblewrap may supply a fixed sandbox PWD after --clearenv.
os.environ.pop("PWD", None)
resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
print(json.dumps({"bootstrap": "hepta.mem9.namespace.v1",
 "pid": os.getpid(), "namespaces": {k: os.readlink("/proc/self/ns/"+k)
 for k in ("mnt", "pid", "net", "ipc", "uts", "user")},
 "home_empty": not os.listdir("/home/actor"),
 "cache_empty": not os.listdir("/cache"),
 "workspace_empty": not os.listdir("/work")}, sort_keys=True), flush=True)
runpy.run_path("/input/actor.py", run_name="__main__")
"""


def _pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def run_isolated_actor(
    output, actor_source, public_task, *, mode, memory_context="", timeout_seconds=30
):
    """Retain one attempted launch and its bounded stdout/stderr.

    The actor reads /input/task.json and, only in on, /input/memory.txt. It has
    no inherited stdin, arbitrary environment, original host handles or network.
    Input bytes use sealed memfds; the retained input directory is not mounted.
    stdout after the trusted bootstrap line becomes actor-output.bin. Limits,
    source changes and unavailable namespaces fail closed. This receipt alone
    does not authenticate a remote observation or qualify a provider request.
    """
    if not isinstance(mode, str) or mode not in {"off", "on"}:
        raise ValueError("explicit on/off mode required")
    if not isinstance(actor_source, bytes) or not isinstance(public_task, dict):
        raise ValueError("actor bytes and public task object required")
    if not isinstance(memory_context, str) or (mode == "off" and memory_context):
        raise ValueError("memory-off cannot receive memory context")
    if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 60:
        raise ValueError("timeout must be finite and in (0,60]")
    task = json.dumps(
        public_task,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    context = memory_context.encode()
    if (
        not actor_source
        or max(map(len, (actor_source, task, context))) > MAX_INPUT_BYTES
    ):
        raise ValueError("bounded nonempty actor and bounded task/context required")
    compile(actor_source.decode("utf-8"), "/input/actor.py", "exec")
    launcher_source = _LOADED_LAUNCHER_SOURCE
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=False)
    inputs = output / "inputs"
    inputs.mkdir()
    input_bytes = {"actor.py": actor_source, "task.json": task}
    if mode == "on":
        input_bytes["memory.txt"] = context
    for name, raw in input_bytes.items():
        (inputs / name).write_bytes(raw)
    receipt = {
        "schema": "hepta.mem9.isolated-launch.v1",
        "session_id": uuid.uuid4().hex,
        "mode": mode,
        "status": "SETUP_FAILED",
        "returncode": None,
        "actor_sha256": _pin(actor_source)["sha256"],
        "task": _pin(task),
        "task_sha256": _pin(task)["sha256"],
        "request_sha256": _pin(task)["sha256"],
        "context_sha256": _pin(context)["sha256"],
        "context_bytes": len(context),
        "bootstrap_sha256": _pin(_BOOTSTRAP.encode())["sha256"],
        "launcher_sha256": _pin(launcher_source)["sha256"],
        "started_at_unix_ns": time.time_ns(),
        "started_monotonic_ns": time.monotonic_ns(),
        "bootstrap": None,
        "process_identity": None,
        "host_namespaces": {},
        "system_read_roots": [],
        "scientific_acceptance": "HOLD",
        "provider_execution_established": False,
        "independent_task_benefit": False,
        "model_calls_observed": None,
        "boundary": "local-linux-no-network-actor",
        "private_roots": {
            "home": "/home/actor",
            "cache": "/cache",
            "workspace": "/work",
        },
        "capture_truncated": False,
    }
    stdout, stderr = bytearray(), bytearray()
    process = None
    input_fds = []
    stopped = None
    try:
        if Path(__file__).read_bytes() != launcher_source:
            raise RuntimeError("launcher changed since module import")
        if sys.platform != "linux":
            raise RuntimeError("Linux namespace support is required")
        import fcntl  # Linux-only; other platforms retain SETUP_FAILED receipts.

        bubblewrap = shutil.which("bwrap")
        if not bubblewrap:
            raise RuntimeError("bubblewrap is required")
        receipt["bubblewrap"] = {
            "path": bubblewrap,
            **_pin(Path(bubblewrap).read_bytes()),
        }
        receipt["host_namespaces"] = {
            name: os.readlink("/proc/self/ns/" + name) for name in NAMESPACES
        }
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        command = [
            bubblewrap,
            "--unshare-all",
            "--unshare-user",
            "--die-with-parent",
            "--new-session",
            "--cap-drop",
            "ALL",
            "--clearenv",
        ]
        for source in ("/usr", "/lib", "/lib64"):
            if Path(source).exists():
                command.extend(["--ro-bind", source, source])
                receipt["system_read_roots"].append(source)
        command.extend(
            [
                "--symlink",
                "usr/bin",
                "/bin",
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                "--tmpfs",
                "/tmp",
                "--tmpfs",
                "/home",
                "--dir",
                "/home/actor",
                "--tmpfs",
                "/cache",
                "--tmpfs",
                "/work",
                "--dir",
                "/input",
                "--chdir",
                "/work",
                "--setenv",
                "HOME",
                "/home/actor",
                "--setenv",
                "XDG_CACHE_HOME",
                "/cache",
                "--setenv",
                "TMPDIR",
                "/tmp",
                "--setenv",
                "PATH",
                "/usr/bin:/bin",
                "--setenv",
                "LANG",
                "C.UTF-8",
            ]
        )
        # Linux UAPI linux/fcntl.h; some Python builds omit these names.
        add_seals, get_seals, seals = 1033, 1034, 0x000F
        if not all(
            hasattr(os, name)
            for name in ("memfd_create", "MFD_CLOEXEC", "MFD_ALLOW_SEALING")
        ):
            raise RuntimeError("sealed memfd support is required")
        for name, raw in input_bytes.items():
            descriptor = os.memfd_create(
                "mem9-" + name, os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING
            )
            input_fds.append(descriptor)
            with os.fdopen(os.dup(descriptor), "wb") as stream:
                stream.write(raw)
            os.lseek(descriptor, 0, os.SEEK_SET)
            fcntl.fcntl(descriptor, add_seals, seals)
            if fcntl.fcntl(descriptor, get_seals) != seals:
                raise RuntimeError("immutable input sealing failed")
            command.extend(["--ro-bind-data", str(descriptor), "/input/" + name])
        receipt["input_transport"] = "sealed-memfd-ro-bind-data"
        command.extend(["--", "/usr/bin/python3", "-I", "-B", "-c", _BOOTSTRAP])
        receipt["command_sha256"] = _pin(json.dumps(command).encode())["sha256"]
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
            pass_fds=tuple(input_fds),
            env={"PATH": "/usr/bin:/bin"},
            start_new_session=True,
        )
        receipt["process_identity"] = {
            "host_boot_id": boot_id,
            "launcher_pid": process.pid,
            "launch_monotonic_ns": receipt["started_monotonic_ns"],
        }
        deadline = time.monotonic() + timeout_seconds
        drain_deadline = None
        with selectors.DefaultSelector() as selector:
            for stream, target in ((process.stdout, stdout), (process.stderr, stderr)):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, target)
            while selector.get_map():
                if stopped is None and time.monotonic() >= deadline:
                    stopped = "TIMEOUT"
                    drain_deadline = time.monotonic() + 5
                    process.kill()
                for key, _ in selector.select(0.05):
                    raw = os.read(key.fd, 65536)
                    if not raw:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                        continue
                    room = MAX_OUTPUT_BYTES - len(key.data)
                    key.data.extend(raw[: max(room, 0)])
                    if len(raw) > room:
                        receipt["capture_truncated"] = True
                        if stopped is None:
                            stopped = "OUTPUT_LIMIT"
                            drain_deadline = time.monotonic() + 5
                            process.kill()
                if drain_deadline is not None and time.monotonic() > drain_deadline:
                    receipt["capture_truncated"] = True
                    break
        receipt["returncode"] = process.wait(timeout=5)
        receipt["status"] = stopped or "SETUP_FAILED"
        first, separator, actor_output = bytes(stdout).partition(b"\n")
        bootstrap = json.loads(first) if separator else None
        valid = (
            isinstance(bootstrap, dict)
            and bootstrap.get("bootstrap") == "hepta.mem9.namespace.v1"
            and all(
                bootstrap.get(field) is True
                for field in ("home_empty", "cache_empty", "workspace_empty")
            )
            and set(bootstrap.get("namespaces", {})) == set(NAMESPACES)
            and all(
                bootstrap["namespaces"][name] != receipt["host_namespaces"][name]
                for name in NAMESPACES
            )
        )
        if valid:
            receipt["bootstrap"] = bootstrap
            (output / "actor-output.bin").write_bytes(actor_output)
            receipt["actor_output"] = _pin(actor_output)
            if stopped is None:
                receipt["status"] = (
                    "EXECUTED" if receipt["returncode"] == 0 else "ACTOR_FAILED"
                )
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        receipt["error"] = str(error)
        receipt["status"] = stopped or "SETUP_FAILED"
        if process and process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    finally:
        for stream in () if process is None else (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        for descriptor in input_fds:
            os.close(descriptor)
        try:
            receipt["source_unchanged"] = (
                Path(__file__).read_bytes() == launcher_source
                and {path.name for path in inputs.iterdir()} == set(input_bytes)
                and all(
                    not (inputs / name).is_symlink()
                    and (inputs / name).read_bytes() == raw
                    for name, raw in input_bytes.items()
                )
            )
        except OSError as error:
            receipt["source_unchanged"] = False
            receipt["source_changed_reason"] = str(error)
        if not receipt["source_unchanged"]:
            receipt["status"] = "SOURCE_CHANGED"
        receipt["ended_at_unix_ns"] = time.time_ns()
        receipt["ended_monotonic_ns"] = time.monotonic_ns()
        for name, raw in (("stdout", stdout), ("stderr", stderr)):
            (output / (name + ".bin")).write_bytes(raw)
            receipt[name] = _pin(raw)
        (output / "RECEIPT.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n"
        )
    return receipt
