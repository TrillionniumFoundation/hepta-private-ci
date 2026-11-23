"""One owned offline verifier restoration; candidate seal needs actual PTY admission."""
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import sysconfig
import time


SCOPE = "complete venv tree plus explicitly hashed external symlink file targets; host /usr,/lib,/lib64 dependency closure is not fully inventoried"
PHASES = ("create_venv_without_pip", "bootstrap_exact_pip24", "install_exact_original9", "pip_check", "installed_metadata_and_pytest_import_identity")
OWNER = Path("/home/qian-qi/work/hepta-e2-native-verifier-recovery-v1-20261121-ac5459")
WORK_SECONDS = 180
FINAL_SECONDS = 210
MAX_STREAM = 262144
ALLOW_SPAWN = False
ALLOWED_ARGV = None
sys.dont_write_bytecode = True


class Refused(RuntimeError):
    pass


def require(condition, reason):
    if not condition:
        raise Refused(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode()


def stamp(value):
    return [value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_gid,
            value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns]


def fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def mkdir_new(path):
    path.mkdir(mode=0o700)
    fsync_directory(path.parent)


def write_bytes_new(path, raw):
    require(len(raw) <= 8388608, "owned evidence file exceeds cap")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(raw)
        while view:
            amount = os.write(descriptor, view)
            require(amount > 0, "incomplete owned write")
            view = view[amount:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    fsync_directory(path.parent)
    return {"path": str(path), "bytes": len(raw), "sha256": sha(raw)}


def write_new(path, value):
    return write_bytes_new(path, canonical(value))


def hash_regular(path, maximum=16777216, raw=False):
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and 0 <= before.st_size <= maximum, "bounded regular file required: " + str(path))
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    digest, count, pieces = hashlib.sha256(), 0, []
    try:
        require(stamp(os.fstat(descriptor)) == stamp(before), "file changed before open")
        while True:
            block = os.read(descriptor, min(1048576, maximum - count + 1))
            if not block:
                break
            count += len(block)
            require(count <= maximum, "file grew over cap")
            digest.update(block)
            if raw:
                pieces.append(block)
        require(count == before.st_size and stamp(os.fstat(descriptor)) == stamp(before) == stamp(path.lstat()), "file changed while hashing")
    finally:
        os.close(descriptor)
    row = {"path": str(path), "bytes": count, "sha256": digest.hexdigest(), "identity": stamp(before)}
    return (row, b"".join(pieces)) if raw else row


def check_binding(binding, expected_version=None, raw=False):
    value = hash_regular(Path(binding["path"]), max(16777216, binding["bytes"]), raw)
    row = value[0] if raw else value
    require(row["bytes"] == binding["bytes"] and row["sha256"] == binding["sha256"], "bound bytes differ: " + binding["path"])
    if expected_version:
        identity = row["identity"]
        actual_version = ":".join(str(identity[index]) for index in (0, 1, 6, 7, 8))
        require(actual_version == expected_version, "bound source version differs: " + binding["path"])
    return value


def alarm(signum, frame):
    raise TimeoutError("absolute owned restoration deadline or termination")


def arm(deadline):
    remaining = deadline - time.monotonic()
    require(remaining > 0, "absolute deadline already passed")
    signal.setitimer(signal.ITIMER_REAL, remaining)


def install_signals():
    signal.signal(signal.SIGALRM, alarm)
    signal.signal(signal.SIGTERM, alarm)
    signal.signal(signal.SIGINT, alarm)


def proc_identity(pid):
    text = Path("/proc", str(pid), "stat").read_text()
    values = text[text.rfind(")") + 2:].split()
    return {"pid": pid, "ppid": int(values[1]), "pgrp": int(values[2]), "session": int(values[3]),
            "starttime": values[19], "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip()}


def interpreter_gate(plan):
    expected = plan["python_identity"]
    require(sys.flags.isolated and sys.dont_write_bytecode and list(sys.version_info[:3]) == [3, 12, 3], "isolated exact CPython3.12.3 required")
    require(Path("/proc/self/exe").resolve(strict=True) == Path(expected["path"]), "actual interpreter target differs")
    row = check_binding(expected)
    descriptor = os.open("/proc/self/exe", os.O_RDONLY)
    try:
        require(stamp(os.fstat(descriptor)) == row["identity"], "actual interpreter FD differs from named binary")
        digest = hashlib.sha256()
        while True:
            data = os.read(descriptor, 1048576)
            if not data:
                break
            digest.update(data)
        require(digest.hexdigest() == row["sha256"] and stamp(os.fstat(descriptor)) == row["identity"], "actual interpreter FD bytes changed")
    finally:
        os.close(descriptor)
    frozen = expected["identity"]
    for key, index in (("device", 0), ("inode", 1), ("mode", 2), ("size", 6), ("mtime_ns", 7), ("ctime_ns", 8)):
        require(str(row["identity"][index]) == str(frozen[key]), "frozen interpreter identity differs: " + key)
    return row


def read_plan(path, expected_sha):
    row, raw = hash_regular(path, 1048576, True)
    require(row["sha256"] == expected_sha, "input plan changed")
    plan = json.loads(raw)
    require(plan["schema"] == "hepta.native-verifier-owned-offline-restoration.v1" and plan["status"] == "FROZEN_READY_FOR_ROOT_SINGLE_EXECUTION", "unfrozen restoration plan")
    require(Path(plan["owner"]) == OWNER and Path(plan["venv"]) == OWNER / "venv", "owner changed")
    require(plan["input_plan_path"] == str(path) and Path(__file__).resolve(strict=True) == Path(plan["runner_source_path"]), "input location changed")
    require(plan["runner_source_sha256"] == hash_regular(Path(__file__), 1048576)["sha256"], "runner source changed")
    require(plan["global_engineering_limits_seconds"] == {"absolute_python_final": 210, "outer_at_most": 240, "proposed_outer_KILL_grace": 5, "proposed_outer_TERM": 235, "python_alarm_is_not_OS_preemption": True, "work": 180}, "engineering deadlines changed")
    require(plan["phase_limits_seconds"] == dict(zip(PHASES, (30, 30, 60, 20, 20))), "phase limits changed")
    require(plan["network_http_requests"] == 0 and plan["qualified_C_changes"] == 0 and all(value == 0 for value in plan["scientific_calls"].values()), "scope changed")
    require(len(plan["wheels"]) == 9 and len({row["package"].casefold() for row in plan["wheels"]}) == 9, "original nine wheels required")
    require(plan["bootstrap_pip"]["version"] == "24.0" and plan["bootstrap_pip"]["sha256"] == "e995a37590643450898cfa5bd5113831a547506cd545c335a409339d0c1e87ab", "original pip24 bootstrap differs")
    require(plan["actual_launch_transport"] == "H_PERSISTENT_OPERATOR_PTY" and plan["actual_session_or_job_id"] is None, "prelaunch transport contract differs")
    return plan, row, raw


def input_inventory(plan, plan_row):
    rows = {"plan": hash_regular(Path(plan_row["path"]), 1048576),
            "runner": check_binding({"path": plan["runner_source_path"], "bytes": plan["runner_source_bytes"], "sha256": plan["runner_source_sha256"]}),
            "python": interpreter_gate(plan), "timeout": check_binding(plan["timeout_binary"], plan["timeout_binary"]["immutable_read_version"]),
            "bootstrap_pip": check_binding(plan["bootstrap_pip"], plan["bootstrap_pip"]["immutable_read_version"])}
    require(rows["plan"] == plan_row, "plan changed")
    for key in ("requirements", "bootstrap_requirements"):
        rows[key] = check_binding(plan[key])
    for wheel in plan["wheels"]:
        rows["wheel:" + wheel["filename"]] = check_binding({"path": wheel["source_path"], "bytes": wheel["bytes"], "sha256": wheel["sha256"]}, wheel["version"])
    return rows


def audit(event, args):
    if event.startswith("socket."):
        raise Refused("offline scope denies " + event)
    if event == "subprocess.Popen":
        if ALLOW_SPAWN and args[0] == ALLOWED_ARGV[0] and list(args[1]) == ALLOWED_ARGV:
            return
        raise Refused("unowned subprocess denied")
    if event in ("os.system", "os.fork", "os.forkpty", "os.exec", "os.posix_spawn"):
        raise Refused("offline scope denies " + event)


def configure_pip_distro_backend():
    """Same real-function backend repair as the accepted original C successor."""
    from pip._vendor import distro
    module = importlib.import_module("pip._vendor.distro.distro")
    backend = module.LinuxDistribution(include_lsb=False, include_uname=False, include_oslevel=False)
    module._distro = backend
    flags = {name: getattr(backend, name) for name in ("include_lsb", "include_uname", "include_oslevel")}
    bound = all(getattr(distro, name).__globals__.get("_distro") is backend for name in ("name", "version", "codename"))
    require(flags == {"include_lsb": False, "include_uname": False, "include_oslevel": False} and bound, "pip public functions lack reviewed no-command backend")
    return {"module": module.__name__, "class": type(backend).__name__, **flags, "exported_functions": ["name", "version", "codename"], "exported_function_globals_bound": bound}


def pip_main(arguments, bootstrap=None):
    if bootstrap is not None:
        sys.path.insert(0, bootstrap["path"])
    import pip
    require(pip.__version__ == "24.0", "pip backend differs from reviewed24.0")
    backend = configure_pip_distro_backend()
    from pip._internal.configuration import Configuration
    from pip._internal.cli.main import main
    config = Configuration(isolated=True)
    config.load()
    require(not dict(config.items()), "isolated devnull pip configuration is not empty")
    code = main(["--isolated", "--disable-pip-version-check", "--no-input", *arguments])
    require(code == 0, "offline pip returned " + str(code))
    return {"pip_version": pip.__version__, "pip_module_origin": pip.__file__, "arguments": arguments,
            "returncode": code, "isolated_configuration_items": 0, "distro_backend": backend}


def package_name(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def metadata_inventory(plan, site):
    expected = {package_name(row["package"]): {"version": row["package_version"], "metadata_sha256": row["metadata_sha256"]} for row in plan["wheels"]}
    expected["pip"] = {"version": "24.0", "metadata_sha256": plan["bootstrap_pip"]["metadata_sha256"]}
    observed = {}
    for distribution in importlib.metadata.distributions(path=[str(site)]):
        name = package_name(distribution.metadata["Name"])
        require(name in expected and name not in observed, "extra or duplicate installed package")
        path = Path(distribution._path) / "METADATA"
        require(path.resolve().is_relative_to(site), "installed metadata escaped new venv")
        row = hash_regular(path)
        require(distribution.version == expected[name]["version"] and row["sha256"] == expected[name]["metadata_sha256"], "installed package metadata differs: " + name)
        observed[name] = {"package": name, "version": distribution.version, "metadata": row}
    require(set(observed) == set(expected), "installed package set is not exact nine plus pip")
    return [observed[key] for key in sorted(observed)]


def child_main(plan_path, plan_sha, phase, context_sha):
    install_signals()
    arm(time.monotonic() + 10)
    plan, plan_row, _ = read_plan(plan_path, plan_sha)
    require(phase in PHASES, "unregistered child phase")
    context_row, context_raw = hash_regular(OWNER / "EXECUTION_CONTEXT.json", 1048576, True)
    require(context_row["sha256"] == context_sha, "execution clock context changed")
    context = json.loads(context_raw)
    require(context["plan_sha256"] == plan_sha and context["owner"] == str(OWNER), "context belongs elsewhere")
    started = time.monotonic()
    work_deadline = min(context["work_deadline_monotonic"], started + plan["phase_limits_seconds"][phase])
    final_deadline = min(context["final_deadline_monotonic"], work_deadline + 4)
    arm(work_deadline)
    require(os.environ.get("PIP_CONFIG_FILE") == os.devnull and os.environ.get("CUDA_VISIBLE_DEVICES") == "", "child environment changed")
    interpreter = interpreter_gate(plan)
    inputs = input_inventory(plan, plan_row)
    folder = OWNER / "phases" / phase
    require(folder.is_dir() and not folder.is_symlink(), "owned phase directory missing")
    identity = proc_identity(os.getpid())
    claim = {"phase": phase, "identity": identity, "plan_sha256": plan_sha, "context_sha256": context_sha,
             "started_at_ns": str(time.time_ns()), "automatic_retry": False}
    write_new(folder / "CHILD_CLAIM.json", claim)
    result = {"schema": "hepta.native-verifier-restore-child.v1", "phase": phase, "plan_sha256": plan_sha,
              "context_sha256": context_sha, "identity": identity, "actual_interpreter": interpreter,
              "status": "FAILED", "error": None, "native_test_cases": 0, "model_calls": 0, "training_updates": 0,
              "network_guard": "Python socket/process audit hook after interpreter startup; no OS namespace or host-wide enforcement claim"}
    sys.addaudithook(audit)
    try:
        venv = OWNER / "venv"
        if phase == "create_venv_without_pip":
            require(not os.path.lexists(venv) and Path(sys.prefix).resolve() != venv, "new venv path already exists")
            import venv as stdlib_venv
            stdlib_venv.EnvBuilder(with_pip=False, symlinks=True, clear=False, upgrade=False).create(venv)
            fsync_directory(OWNER)
            result["venv_creation"] = {"without_pip": True, "symlinks": True, "root": str(venv)}
        else:
            require(Path(sys.prefix).resolve() == venv and Path(sys.base_prefix).resolve() != venv, "child outside new venv")
            site = Path(sysconfig.get_path("purelib")).resolve()
            require(site.is_relative_to(venv), "new site-packages prefix differs")
            options = ["--no-index", "--no-deps", "--no-cache-dir", "--no-compile", "--require-hashes", "--only-binary=:all:", "--retries", "0", "--progress-bar", "off"]
            if phase == "bootstrap_exact_pip24":
                result["pip"] = pip_main(["install", "--ignore-installed", *options, "--report", str(OWNER / "BOOTSTRAP_PIP_REPORT.json"), "-r", plan["bootstrap_requirements"]["path"]], plan["bootstrap_pip"])
                distributions = list(importlib.metadata.distributions(path=[str(site)]))
                require(len(distributions) == 1 and package_name(distributions[0].metadata["Name"]) == "pip" and distributions[0].version == "24.0", "bootstrap installed more than pip24")
                require(hash_regular(Path(distributions[0]._path) / "METADATA")["sha256"] == plan["bootstrap_pip"]["metadata_sha256"], "bootstrap pip metadata changed")
            elif phase == "install_exact_original9":
                result["pip"] = pip_main(["install", *options, "--report", str(OWNER / "INSTALL_REPORT.json"), "-r", plan["requirements"]["path"]])
            elif phase == "pip_check":
                result["pip"] = pip_main(["check"])
            else:
                result["metadata_before_import"] = metadata_inventory(plan, site)
                import pytest
                require(pytest.__version__ == "9.2.0" and Path(pytest.__file__).resolve().is_relative_to(site), "pytest version or import origin differs")
                result["pytest_import"] = {"version": pytest.__version__, "module_file": hash_regular(Path(pytest.__file__).resolve()), "native_cases_executed": 0}
                result["metadata_after_import"] = metadata_inventory(plan, site)
                require(result["metadata_before_import"] == result["metadata_after_import"], "metadata changed during import-only gate")
                require(not any(name in sys.modules for name in ("torch", "transformers", "peft", "tokenizers", "safetensors")), "training framework unexpectedly imported")
        require(inputs == input_inventory(plan, plan_row), "original inputs changed during child")
        require(time.monotonic() < work_deadline, "phase work deadline exceeded")
        result["status"] = "COMPLETE_PENDING_PARENT"
    except BaseException as error:
        arm(final_deadline)
        result["error"] = type(error).__name__ + ": " + str(error)
    arm(final_deadline)
    result["wall_seconds"] = time.monotonic() - started
    binding = write_new(folder / "CHILD_RESULT.json", result)
    post = {"phase": phase, "result": binding, "plan_sha256": plan_sha, "context_sha256": context_sha,
            "success_pending_parent": result["status"] == "COMPLETE_PENDING_PARENT" and result["error"] is None,
            "after_result_fsync_unix_ns": str(time.time_ns())}
    write_new(folder / "CHILD_POST_FSYNC.json", post)
    print(json.dumps(post, sort_keys=True), flush=True)
    signal.setitimer(signal.ITIMER_REAL, 0)
    return 0 if post["success_pending_parent"] else 1


def journal(path, event):
    raw = canonical({"at_ns": str(time.time_ns()), **event})
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        require(os.write(descriptor, raw) == len(raw), "short journal write")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    fsync_directory(path.parent)


def stop_owned(process, identity, final_deadline):
    if process.poll() is None:
        current = proc_identity(process.pid)
        require(current["starttime"] == identity["starttime"] and current["boot_id"] == identity["boot_id"] and current["pgrp"] == process.pid and current["session"] == process.pid, "owned child group identity changed")
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=max(0.01, min(3, final_deadline - time.monotonic())))
        except subprocess.TimeoutExpired:
            if process.poll() is None:
                current = proc_identity(process.pid)
                require(current["starttime"] == identity["starttime"] and current["pgrp"] == process.pid, "owned kill identity changed")
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=max(0.01, min(2, final_deadline - time.monotonic())))
    return process.returncode


def run_phase(plan, plan_path, plan_sha, phase, context_binding, context):
    global ALLOW_SPAWN, ALLOWED_ARGV
    phase_started = time.monotonic()
    remaining = context["work_deadline_monotonic"] - phase_started
    require(remaining > 0, "no remaining restoration work budget")
    timeout_seconds = min(float(plan["phase_limits_seconds"][phase]), remaining)
    folder = OWNER / "phases" / phase
    mkdir_new(folder)
    interpreter = plan["python_identity"]["path"] if phase == PHASES[0] else str(OWNER / "venv/bin/python")
    argv = [plan["timeout_binary"]["path"], "--signal=TERM", "--kill-after=5s", format(timeout_seconds, ".6f") + "s",
            interpreter, "-I", "-B", plan["runner_source_path"], "--child", str(plan_path), plan_sha, phase, context_binding["sha256"]]
    environment = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "HOME": str(OWNER / "home"),
                   "TMPDIR": str(OWNER / "tmp"), "PIP_CONFIG_FILE": os.devnull, "CUDA_VISIBLE_DEVICES": "", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    claim = {"phase": phase, "argv": argv, "environment": environment, "plan_sha256": plan_sha,
             "context_sha256": context_binding["sha256"], "started_at_ns": str(time.time_ns()), "automatic_retry": False}
    write_new(folder / "PARENT_CLAIM.json", claim)
    output = {name: open(folder / (name.upper() + ".log"), "xb", buffering=0) for name in ("stdout", "stderr")}
    fsync_directory(folder)
    captures = {"stdout": bytearray(), "stderr": bytearray()}
    observed = {"stdout": 0, "stderr": 0}
    process, identity, failure = None, None, None
    selector = selectors.DefaultSelector()
    try:
        ALLOWED_ARGV, ALLOW_SPAWN = argv, True
        try:
            process = subprocess.Popen(argv, cwd=OWNER, env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        finally:
            ALLOW_SPAWN = False
        identity = proc_identity(process.pid)
        require(identity["pgrp"] == process.pid and identity["session"] == process.pid, "phase lacks owned process group")
        journal(OWNER / "PHASE_EVENTS.jsonl", {"event": "PHASE_STARTED", "phase": phase, "identity": identity, "argv": argv})
        for name in ("stdout", "stderr"):
            stream = getattr(process, name)
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
        while selector.get_map():
            require(time.monotonic() < context["work_deadline_monotonic"], "global work deadline while waiting for phase")
            for key, _ in selector.select(min(0.1, max(0.001, context["work_deadline_monotonic"] - time.monotonic()))):
                block = os.read(key.fileobj.fileno(), 65536)
                if not block:
                    selector.unregister(key.fileobj)
                    continue
                name = key.data
                observed[name] += len(block)
                available = MAX_STREAM - len(captures[name])
                piece = block[:available]
                if piece:
                    output[name].write(piece)
                    captures[name].extend(piece)
                require(len(block) <= available, "child " + name + " exceeded fixed capture cap; retained prefix and refused")
        process.wait(timeout=max(0.001, context["work_deadline_monotonic"] - time.monotonic()))
    except BaseException as error:
        arm(context["final_deadline_monotonic"])
        failure = type(error).__name__ + ": " + str(error)
        if process is not None and identity is not None:
            try:
                stop_owned(process, identity, context["final_deadline_monotonic"])
            except BaseException as cleanup_error:
                failure += " | OWNED_CLEANUP_UNKNOWN: " + repr(cleanup_error)
    finally:
        selector.close()
        for stream in output.values():
            os.fsync(stream.fileno())
            stream.close()
        fsync_directory(folder)
        if process is not None:
            for name in ("stdout", "stderr"):
                stream = getattr(process, name)
                if stream is not None:
                    stream.close()
    record = {"phase": phase, "argv": argv, "identity": identity, "actual_wait_returncode": None if process is None else process.returncode,
              "wall_seconds": time.monotonic() - phase_started, "error": failure,
              "streams": {name: {"bytes_retained": len(captures[name]), "bytes_observed": observed[name], "sha256": sha(captures[name]), "complete": failure is None} for name in captures},
              "automatic_retry": False, "cleanup_targets": "only this owned subprocess group"}
    record["successful"] = False
    record["owned_group_absent_after_wait"] = False
    if process is not None and process.returncode is not None:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            record["owned_group_absent_after_wait"] = True
    if failure is None and process.returncode == 0:
        try:
            require(record["owned_group_absent_after_wait"], "phase process group remains; no further phase admitted")
            post_row, post_raw = hash_regular(folder / "CHILD_POST_FSYNC.json", 1048576, True)
            post = json.loads(post_raw)
            require(post["result"]["path"] == str(folder / "CHILD_RESULT.json"), "child result path differs")
            result_row, result_raw = check_binding(post["result"], raw=True)
            result = json.loads(result_raw)
            require(post["phase"] == phase and post["plan_sha256"] == plan_sha and post["context_sha256"] == context_binding["sha256"], "child post binding differs")
            require(post["success_pending_parent"] is True and result["status"] == "COMPLETE_PENDING_PARENT" and result["error"] is None, "child inner terminal is not successful")
            require(bytes(captures["stdout"]).endswith((json.dumps(post, sort_keys=True) + "\n").encode()), "actual child stdout does not bind post-fsync receipt")
            record["child_post"] = post_row
            record["child_result"] = result_row
            record["successful"] = True
        except BaseException as error:
            arm(context["final_deadline_monotonic"])
            record["error"] = "CHILD_RECEIPT_ADMISSION: " + type(error).__name__ + ": " + str(error)
    write_new(folder / "PARENT_RESULT.json", record)
    journal(OWNER / "PHASE_EVENTS.jsonl", {"event": "PHASE_TERMINAL", **record})
    if record["successful"]:
        arm(context["work_deadline_monotonic"])
    return record


def inventory(root, deadline, fsync_files=False):
    before_root = root.lstat()
    require(stat.S_ISDIR(before_root.st_mode) and root.resolve(strict=True) == root, "owned venv root changed")
    stack, files, directories, logical, entries_seen = [root], [], [], 0, 0
    while stack:
        require(time.monotonic() < deadline, "tree inventory exceeded work deadline")
        folder = stack.pop()
        before = folder.lstat()
        require(stat.S_ISDIR(before.st_mode) and len(directories) < 20000, "tree directory limit or type")
        directories.append({"path": folder.relative_to(root).as_posix(), "identity": stamp(before)})
        entries = []
        with os.scandir(folder) as stream:
            for entry in stream:
                entries_seen += 1
                require(entries_seen <= 40000, "tree entry cap")
                entries.append(entry)
        for entry in sorted(entries, key=lambda item: item.name):
            path = Path(entry.path)
            current = path.lstat()
            relative = path.relative_to(root).as_posix()
            if stat.S_ISDIR(current.st_mode):
                stack.append(path)
                continue
            require(len(files) < 20000, "tree file cap")
            if stat.S_ISREG(current.st_mode):
                row = hash_regular(path, 4294967296 - logical)
                logical += row["bytes"]
                row["path"] = relative
                if fsync_files:
                    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                    try:
                        require(stamp(os.fstat(descriptor)) == row["identity"], "fsync file identity changed")
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
            elif stat.S_ISLNK(current.st_mode):
                target, resolved = path.readlink().as_posix(), path.resolve(strict=True)
                row = {"path": relative, "symlink_target": target, "identity": stamp(current)}
                if not resolved.is_relative_to(root):
                    require(resolved.is_file() and not resolved.is_symlink(), "external directory symlink refused")
                    external = hash_regular(resolved, 4294967296 - logical)
                    logical += external["bytes"]
                    row["external_target"] = external
                require(stamp(current) == stamp(path.lstat()) and path.readlink().as_posix() == target and path.resolve(strict=True) == resolved, "symlink changed")
            else:
                raise Refused("unsupported verifier filesystem object: " + relative)
            require(logical <= 4294967296, "tree logical byte cap")
            files.append(row)
        require(stamp(before) == stamp(folder.lstat()), "directory changed during traversal")
    for row in reversed(directories):
        path = root / row["path"]
        require(stamp(path.lstat()) == row["identity"], "directory changed after traversal")
        if fsync_files:
            fsync_directory(path)
    require(stamp(before_root) == stamp(root.lstat()), "venv root changed")
    return {"root": str(root), "files": sorted(files, key=lambda row: row["path"]), "directories": sorted(directories, key=lambda row: row["path"]),
            "entries_seen": entries_seen, "logical_bytes_hashed": logical}


def owned_retained_bytes():
    total, count = 0, 0
    for folder, dirs, names in os.walk(OWNER, followlinks=False):
        count += len(dirs) + len(names)
        require(count <= 40000, "owner retained entry cap")
        for name in names:
            current = (Path(folder) / name).lstat()
            if stat.S_ISREG(current.st_mode):
                total += current.st_size
                require(total <= 134217728, "owner retained sampled byte threshold")
    return total


def evidence_inventory():
    names = ["CLAIM.json", "PLAN.json", "EXECUTION_CONTEXT.json", "INPUTS_BEFORE.json", "INPUTS_AFTER.json",
             "PHASE_EVENTS.jsonl", "BOOTSTRAP_PIP_REPORT.json", "INSTALL_REPORT.json", "TREE_BEFORE.json",
             "TREE_AFTER.json", "NATIVE_ENVIRONMENT_CANDIDATE.json"]
    names.extend("phases/" + phase + "/" + name for phase in PHASES for name in
                 ("PARENT_CLAIM.json", "CHILD_CLAIM.json", "CHILD_RESULT.json", "CHILD_POST_FSYNC.json", "STDOUT.log", "STDERR.log", "PARENT_RESULT.json"))
    rows = []
    for name in names:
        path = OWNER / name
        if not os.path.lexists(path):
            continue
        row = hash_regular(path, 8388608)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            require(stamp(os.fstat(descriptor)) == row["identity"], "evidence changed before fsync")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        fsync_directory(path.parent)
        rows.append(row)
    fsync_directory(OWNER)
    return rows


def parent_main(plan_path, plan_sha):
    started, started_ns = time.monotonic(), time.time_ns()
    install_signals()
    arm(started + WORK_SECONDS)
    os.umask(0o077)
    plan, plan_row, plan_raw = read_plan(plan_path, plan_sha)
    require(OWNER.parent.resolve(strict=True) == OWNER.parent and not os.path.lexists(OWNER), "independent owner already exists or parent differs")
    inputs_before = input_inventory(plan, plan_row)
    require(shutil.disk_usage(OWNER.parent).free >= 268435456, "insufficient initial free disk")
    identity = proc_identity(os.getpid())
    parent_path = Path("/proc", str(identity["ppid"]), "exe").resolve(strict=True)
    require(parent_path == Path(plan["timeout_binary"]["path"]), "direct outer timeout parent required")
    require(hash_regular(parent_path)["sha256"] == plan["timeout_binary"]["sha256"], "outer timeout parent binary differs")
    parent_cmdline = Path("/proc", str(identity["ppid"]), "cmdline").read_bytes().split(b"\0")
    parent_cmdline = [piece.decode() for piece in parent_cmdline if piece]
    expected_argv = [plan["timeout_binary"]["path"], "--signal=TERM", "--kill-after=5s", "235s", plan["python_identity"]["path"], "-I", "-B", plan["runner_source_path"], str(plan_path), plan_sha]
    require(parent_cmdline == expected_argv, "actual outer timeout argv differs")
    mkdir_new(OWNER)
    claim = {"schema": "hepta.native-verifier-restore-claim.v1", "identity": identity, "outer_timeout_parent_argv": parent_cmdline,
             "plan_sha256": plan_sha, "started_at_ns": str(started_ns), "automatic_retry": False}
    write_new(OWNER / "CLAIM.json", claim)
    write_bytes_new(OWNER / "PLAN.json", plan_raw)
    context = {"owner": str(OWNER), "plan_sha256": plan_sha, "started_monotonic": started,
               "work_deadline_monotonic": started + WORK_SECONDS, "final_deadline_monotonic": started + FINAL_SECONDS,
               "started_at_ns": str(started_ns), "automatic_retry": False}
    context_binding = write_new(OWNER / "EXECUTION_CONTEXT.json", context)
    result = {"schema": "hepta.native-verifier-owned-restoration-result.v1", "status": "RESTORATION_INCOMPLETE", "error": None,
              "plan_sha256": plan_sha, "context_sha256": context_binding["sha256"], "owner": str(OWNER), "venv": plan["venv"],
              "identity": identity, "phases": [], "network_http_requests": 0, "qualified_C_changes": 0, "scientific_calls": plan["scientific_calls"],
              "actual_transport_pending_external_proof": "H_PERSISTENT_OPERATOR_PTY", "actual_session_id": None,
              "environment_candidate": None, "environment_qualified": False, "host_mount_closure_complete": False,
              "python_alarm_is_not_OS_preemption": True, "network_guard": "Python socket/process audit hooks; no OS namespace or host dependency closure claim"}
    write_new(OWNER / "INPUTS_BEFORE.json", inputs_before)
    sys.addaudithook(audit)
    try:
        for name in ("home", "tmp", "phases", "wheelhouse"):
            mkdir_new(OWNER / name)
        copied = []
        for wheel in plan["wheels"]:
            if wheel["copy_to_new_owned_wheelhouse"]:
                require(wheel["filename"] == "pygments-2.21.0-py3-none-any.whl" and Path(wheel["installation_path"]) == OWNER / "wheelhouse" / wheel["filename"], "only original cached Pygments copy allowed")
                _, raw = check_binding({"path": wheel["source_path"], "bytes": wheel["bytes"], "sha256": wheel["sha256"]}, wheel["version"], True)
                copied.append(write_bytes_new(Path(wheel["installation_path"]), raw))
            else:
                require(wheel["installation_path"] == wheel["source_path"], "unexpected installation input rewrite")
        require(len(copied) == 1, "exact one cached-wheel filename restoration required")
        result["owned_wheel_copies"] = copied
        for phase in PHASES:
            require(input_inventory(plan, plan_row) == inputs_before, "inputs changed before phase")
            result["phases"].append(run_phase(plan, plan_path, plan_sha, phase, context_binding, context))
            require(result["phases"][-1]["successful"], "phase failed or unknown; no subsequent phase: " + phase)
            result["retained_bytes_last_phase"] = owned_retained_bytes()
        first = inventory(OWNER / "venv", context["work_deadline_monotonic"], fsync_files=True)
        result["tree_before"] = write_new(OWNER / "TREE_BEFORE.json", first)
        second = inventory(OWNER / "venv", context["work_deadline_monotonic"])
        result["tree_after"] = write_new(OWNER / "TREE_AFTER.json", second)
        require(first == second, "venv/external targets changed between complete passes")
        require((OWNER / "venv/bin/python").resolve(strict=True) == Path(plan["python_identity"]["path"]), "new venv interpreter differs")
        for binding in copied:
            check_binding(binding)
        environment = {"schema": "hepta.readonly-native-environment.v1", "root": plan["venv"], "inventory_scope": SCOPE,
                       "host_mount_closure_complete": False, "python_binary_sha256": plan["python_identity"]["sha256"],
                       "files": first["files"], "two_full_passes_equal": True, "directory_count": len(first["directories"]),
                       "logical_bytes_hashed_per_pass": first["logical_bytes_hashed"], "created_at_ns": str(time.time_ns()),
                       "restoration_plan_sha256": plan_sha, "restoration_context_sha256": context_binding["sha256"],
                       "qualification_status": "CANDIDATE_REQUIRES_ACTUAL_PTY_TERMINAL_AND_COMPLETE_STREAM_BINDING"}
        result["environment_candidate"] = write_new(OWNER / "NATIVE_ENVIRONMENT_CANDIDATE.json", environment)
        require(time.monotonic() < context["work_deadline_monotonic"], "global work deadline exceeded")
        result["status"] = "OFFLINE_VERIFIER_RESTORED_PENDING_ACTUAL_PTY_TERMINAL"
    except BaseException as error:
        arm(context["final_deadline_monotonic"])
        result["error"] = type(error).__name__ + ": " + str(error)
    arm(context["final_deadline_monotonic"])
    try:
        inputs_after = input_inventory(plan, plan_row)
        result["inputs_after"] = write_new(OWNER / "INPUTS_AFTER.json", inputs_after)
        require(inputs_after == inputs_before, "original inputs changed after restoration")
        result["inputs_unchanged"] = True
        result["retained_bytes_before_terminal"] = owned_retained_bytes()
        result["original_artifacts"] = evidence_inventory()
    except BaseException as error:
        arm(context["final_deadline_monotonic"])
        result["error"] = str(result["error"]) + " | FINAL_INPUT_OR_RETAINED_CHECK: " + repr(error)
        result["inputs_unchanged"] = False
        result["status"] = "RESTORATION_INCOMPLETE"
    result["wall_seconds"] = time.monotonic() - started
    binding = write_new(OWNER / "RESULT.json", result)
    success = result["status"] == "OFFLINE_VERIFIER_RESTORED_PENDING_ACTUAL_PTY_TERMINAL" and result["error"] is None and result["inputs_unchanged"]
    post = {"result": binding, "plan_sha256": plan_sha, "context_sha256": context_binding["sha256"], "success_pending_outer": success,
            "automatic_next_phase": False, "transport_kind": "H_PERSISTENT_OPERATOR_PTY", "after_result_fsync_unix_ns": str(time.time_ns())}
    write_new(OWNER / "POST_FSYNC.json", post)
    print(json.dumps(post, sort_keys=True), flush=True)
    signal.setitimer(signal.ITIMER_REAL, 0)
    return 0 if success else 1


if __name__ == "__main__":
    if len(sys.argv) == 6 and sys.argv[1] == "--child":
        raise SystemExit(child_main(Path(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5]))
    require(len(sys.argv) == 3, "expected PLAN SHA or internal child invocation")
    raise SystemExit(parent_main(Path(sys.argv[1]), sys.argv[2]))
