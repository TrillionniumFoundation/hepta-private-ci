#!/usr/bin/env python3
"""Prepared only. Bind actual terminal evidence before final source maintenance."""
BINDING = None
if BINDING is None:
    raise SystemExit("INERT: actual 8bf main/native/fullcaller/Root29 evidence is not bound; no filesystem action is permitted")

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time
import uuid

SOURCE = "8bf3881afa8cccff286fc58909995c96f3e0b260"
TREE = "c8730bab75eabe47a3b0b3260a6203a0d86d1443"
BASE = "be8adcbb5e9925f72e05330b8fb30509cba4544b"
REPO = Path("/home/qian-qi/hepta-learn-positive-ce434-8bf3881afa8c-isolated-v1")
EVIDENCE = Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111/native")
MAIN = EVIDENCE / "live-owners-full-8bf3881afa8c-isolated-v1"
OUTER = EVIDENCE / "unified-8bf3881afa8c-isolated-v1"
CALLER = EVIDENCE / "fullcaller-8bf3881afa8c-isolated-v1"
LAUNCH = EVIDENCE / "fullcaller-8bf3881afa8c-isolated-launch-v1"
TARGET = Path("/data/hepta-learn-ce434-runtime-20261112-v3/target")
TARGET_RECORD = EVIDENCE / "build-root-recovery-4537458b51b6-v3-attempt2/result.json"
TARGET_HASH = "1054be1b7545dd29dfa2058ae6d7c7b35180aac3ee838d2d8c7bbdbacf7fba3b"
MANIFEST = EVIDENCE / "v8-pinned-150-4-0-v2/manifest.json"
MANIFEST_HASH = "9969b385cfffaf8a16071033460b505fd98e7a8b6a7f8fd47762e526d78b5ff5"
RECOVERY = EVIDENCE / "dependency-recovery-441de918-v1/result.json"
RECOVERY_HASH = "8db2c096ff2c16b8e02f293a67c26939c5de6bf6e0dd69888179c4b0d31ca3fc"
PINS = Path("/data/hepta-learn-ce434-runtime-20261112-v1/v8-private-pins")
PREFIX = "/home/qian-qi/hepta-learn-ce434-tools/uv-venv/bin:/home/qian-qi/.local/bin:/home/qian-qi/.cargo/bin:"
SEMANTIC_PINS = {
    "AGENTS.md": "faa57cc0db48123e1011f1eb47692cd3bbbcfc3a",
    "justfile": "a215a76cf407ace9715bca39c20497014e7dd4dc",
    "scripts/format.py": "d4eabe70b68605933240e9129245f7f4cccbde5d",
    "scripts/just-shell.py": "bb2db6ebc4312a301ee39d2793fde16289d046d8",
}
COMMANDS = [
    ("fix", ["just", "fix", "--locked", "--offline", "-p", "codex-hepta-agentd",
             "-p", "codex-hepta-learning-ledger", "-p", "codex-hepta-learning-artifacts",
             "-p", "codex-hepta-intelligence-eval", "-p", "codex-hepta-neuron"]),
    ("fmt", ["just", "fmt", "--base", BASE]),
]
# Replace only the leading sentinel with a separately frozen actual-evidence binding.


def require(condition, code):
    if not condition:
        raise RuntimeError(code)


def utc():
    return datetime.now(timezone.utc).isoformat()


def identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_uid,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def directory(path):
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and path.resolve(strict=True) == path, "owned canonical directory required")
    return (info.st_dev, info.st_ino, info.st_uid, info.st_mode)


def stable_bytes(path):
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
            and before.st_uid == os.getuid(), "original owned regular file required")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        value = stream.read()
        after = os.fstat(stream.fileno())
    require(identity(before) == identity(opened) == identity(after)
            == identity(path.lstat()) and len(value) == after.st_size,
            "file changed during actual read")
    return value


def file_digest(path):
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and path.resolve(strict=True) == path,
            "original regular artifact required")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    digest = hashlib.sha256()
    size = 0
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
        after = os.fstat(stream.fileno())
    require(identity(before) == identity(opened) == identity(after)
            == identity(path.lstat()) and size == after.st_size, "artifact changed")
    return {"bytes": size, "sha256": digest.hexdigest()}


def bound_json(path, expected, captured):
    require(isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected),
            "actual receipt hash is unbound")
    raw = stable_bytes(path)
    require(hashlib.sha256(raw).hexdigest() == expected, "actual receipt hash differs")
    captured.append((path, raw))
    return json.loads(raw)


def source_pin(value):
    return value.get("source_sha") == SOURCE and value.get("source_tree") == TREE


def root29_eligible(value):
    steps = {row["name"]: row for row in value.get("steps", [])}
    return (
        source_pin(value) and value.get("state") == "passed"
        and value.get("native_tests_executed") == 201
        and value.get("owner_coverage", {}).get("exact_selected_cases") is True
        and not value.get("owner_coverage", {}).get("failed_or_skipped", [])
        and value.get("original_observer_coverage", {}).get("exact_pass_coverage") is True
        and value.get("source_after") == SOURCE and value.get("source_status_after") == ""
        and type(value.get("native_exit_code")) is int and value["native_exit_code"] == 0
        and type(value.get("collection_exit_code")) is int and value["collection_exit_code"] == 0
        and steps.get("helper-build", {}).get("exit_code") == 0
        and steps.get("helper-verify", {}).get("exit_code") == 0
        and steps.get("focused-native", {}).get("exit_code") == value["native_exit_code"]
        and steps.get("focused-junit", {}).get("exit_code") == value["collection_exit_code"]
    )


def native_terminal(outer_steps, native, hashes, captured):
    steps = {row["name"]: row for row in native.get("steps", [])}
    state = native.get("state")
    if state in ("helper-failed", "helper-verification-failed"):
        failed_step = "helper-build" if state == "helper-failed" else "helper-verify"
        require(failed_step in steps and type(steps[failed_step].get("exit_code")) is int
                and steps[failed_step]["exit_code"] != 0
                and outer_steps["original-full-native"]["exit_code"] == steps[failed_step]["exit_code"]
                and (state == "helper-failed"
                     or type(steps.get("helper-build", {}).get("exit_code")) is int
                     and steps["helper-build"]["exit_code"] == 0),
                "original helper failure is not a completed direct attempt")
        return {"kind": "actual_helper_failure_before_native_tests", "state": state}
    require(state in ("passed", "failed"), "native inner report is partial or unknown")
    execution = bound_json(MAIN / "focused-native.json", hashes["main_execution"], captured)
    cases = native.get("expected_owner_cases")
    require(isinstance(cases, list) and len(cases) == 201
            and all(isinstance(row, list) and len(row) == 2
                    and all(isinstance(value, str) and value for value in row) for row in cases)
            and len({tuple(row) for row in cases}) == 201, "original native case inventory differs")
    packages = sorted({row[0] for row in cases})
    require(packages == ["codex-hepta-agentd", "codex-hepta-intelligence-eval",
                          "codex-hepta-learning-artifacts", "codex-hepta-neuron"],
            "original native package set differs")
    expression = " | ".join("(package(=" + package + ") & test(=" + name + "))"
                            for package, name in cases)
    expected_command = [
        "just", "test", "--locked", "--offline",
        *(arg for package in packages for arg in ("-p", package)),
        "--lib", "-E", expression, "--test-threads", "2", "--retries", "0",
        "--no-tests", "fail", "--status-level", "pass", "--success-output", "final",
        "--failure-output", "final",
    ]
    require(execution.get("source_sha") == execution.get("tested_sha") == SOURCE
            and execution.get("lane") == "source-head"
            and execution.get("working_directory") == str(REPO / "codex-rs")
            and execution.get("before", {}).get("commit") == SOURCE
            and execution.get("before", {}).get("tree") == TREE
            and execution.get("before", {}).get("dirty") is False
            and execution.get("command") == expected_command
            and execution.get("status") in ("passed", "failed")
            and isinstance(execution.get("finished_at"), str) and bool(execution["finished_at"])
            and type(execution.get("returncode")) is int
            and type(execution.get("command_exit_code")) is int
            and execution["returncode"] == execution["command_exit_code"]
            and type(execution.get("exit_code")) is int
            and type(steps.get("focused-native", {}).get("exit_code")) is int
            and steps["focused-native"]["exit_code"] == execution["exit_code"]
            and type(native.get("native_exit_code")) is int
            and native["native_exit_code"] == execution["exit_code"]
            and type(steps.get("focused-junit", {}).get("exit_code")) is int
            and type(native.get("collection_exit_code")) is int
            and steps["focused-junit"]["exit_code"] == native["collection_exit_code"]
            and outer_steps["original-full-native"]["exit_code"] == (0 if state == "passed" else 1),
            "original native child terminal/command or classifier accounting differs")
    return {"kind": "actual_original_native_terminal", "state": state,
            "classifier_exit": execution["exit_code"], "actual_child_exit": execution["returncode"]}


def validation_evidence(binding, captured):
    hashes = binding["receipt_sha256"]
    outer = bound_json(OUTER / "result.json", hashes["main_outer"], captured)
    native = bound_json(MAIN / "result.json", hashes["main_native"], captured)
    require(source_pin(outer) and source_pin(native)
            and outer.get("state") in ("passed", "failed")
            and outer.get("source_after") == SOURCE and outer.get("source_status_after") == "",
            "actual main attempt terminal/source not established")
    names = {row["name"]: row for row in outer.get("steps", [])}
    require(set(names) >= {"source-suite", "original-full-native", "caller-scanner-self-test"}
            and all(type(names[name].get("exit_code")) is int
                    for name in ("source-suite", "original-full-native", "caller-scanner-self-test")),
            "main attempts lack actual terminal exit codes")
    native_observation = native_terminal(names, native, hashes, captured)
    launch = bound_json(LAUNCH / "launch-result.json", hashes["fullcaller_launch"], captured)
    caller = bound_json(CALLER / "result.json", hashes["fullcaller_result"], captured)
    require(source_pin(launch) and source_pin(caller)
            and launch.get("status") in ("recorder_returned_zero", "recorder_returned_nonzero")
            and type(launch.get("actual_child_exit")) is int
            and not launch.get("errors") and len(launch.get("logs", [])) == 2
            and all(row.get("complete") is True for row in launch["logs"])
            and caller.get("status") in ("passed_original_gates", "failed_original_gates")
            and type(caller.get("exit_code")) is int
            and launch["actual_child_exit"] == caller["exit_code"]
            and launch.get("actual_child_pid") == caller.get("recorder_pid")
            and launch.get("direct_child_is_full_caller_recorder") is True
            and launch.get("command") == [
                "/usr/bin/python3", "-I", "-S", "-B", str(LAUNCH / "full-caller-recorder.py"),
                "--repo", str(REPO), "--evidence-dir", str(CALLER)]
            and caller.get("worktree") == str(REPO)
            and caller.get("evidence_directory") == str(CALLER)
            and type(caller.get("recorder_pid")) is int and caller["recorder_pid"] > 0
            and isinstance(caller.get("run_id"), str) and bool(caller["run_id"]),
            "full caller recorder terminal not established")
    phases = caller.get("phases", [])
    require([row.get("phase") for row in phases] in (["self-test"], ["self-test", "verify"]),
            "unknown full caller phase ownership")
    require(set(binding["fullcaller_phases"]) == {row["phase"] for row in phases},
            "actual phase bindings differ")
    for row in phases:
        phase = row["phase"]
        pin = binding["fullcaller_phases"][phase]
        started = bound_json(CALLER / (phase + ".started.json"), pin["started"], captured)
        terminal = bound_json(CALLER / (phase + ".original.json"), pin["original"], captured)
        require(set(started) == {
                    "run_id", "phase", "command", "child_pid", "recorder_pid", "started_at",
                    "started_monotonic", "source_sha", "source_tree", "budget_seconds",
                    "classification_exit_is_not_child_exit"}
                and terminal == row and source_pin(terminal)
                and terminal.get("status") == "terminal"
                and terminal.get("original_process_complete") is True
                and type(terminal.get("actual_child_exit")) is int
                and terminal.get("run_id") == caller.get("run_id")
                and terminal.get("recorder_pid") == caller.get("recorder_pid")
                and type(terminal.get("child_pid")) is int
                and terminal["child_pid"] > 0
                and terminal.get("command") == ["python3", "scripts/verify_hepta_callers.py", phase]
                and all(terminal.get(key) == value for key, value in started.items()),
                "an original verifier child is not proven terminal")
    if len(phases) == 2:
        require(type(phases[0].get("gate_classification_exit")) is int
                and phases[0]["gate_classification_exit"] == 0,
                "verify contradicts the original self-test gate")
    if len(phases) == 1:
        require(type(phases[0].get("gate_classification_exit")) is int
                and phases[0]["gate_classification_exit"] != 0,
                "missing verify is not explained by the original self-test gate")
    root = binding["root29"]
    root_summary = {"eligible_by_original_main_gate": root29_eligible(native)}
    if root["kind"] == "not_admissible":
        require(not root_summary["eligible_by_original_main_gate"]
                and root.get("basis_main_sha256") == hashes["main_native"]
                and root.get("dispatch") == "not_dispatched_due_to_original_main_gate",
                "Root29 conditional non-execution lacks its actual gate basis")
        root_summary.update(disposition=root["dispatch"], actual_pass=False)
    else:
        require(root["kind"] == "attempt_terminal", "Root29 binding is unbound")
        name = root["directory"]
        require(re.fullmatch(r"root-29-8bf3881afa8c-isolated-v[1-9][0-9]*", name),
                "Root29 evidence directory differs")
        folder = EVIDENCE / name
        record = bound_json(folder / "result.json", root["result_sha256"], captured)
        require(source_pin(record) and record.get("state") in ("passed", "failed")
                and record.get("main_terminal_record", {}).get("sha256")
                == hashes["main_native"],
                "Root29 attempt has no actual terminal state")
        if record.get("root_command_dispatched") is True:
            execution = bound_json(folder / "root.json", root["execution_sha256"], captured)
            require(record.get("original_execution_terminal") is True
                    and record.get("original_execution") == execution
                    and execution.get("source_sha") == execution.get("tested_sha") == SOURCE
                    and execution.get("working_directory") == str(REPO)
                    and execution.get("before", {}).get("commit") == SOURCE
                    and execution.get("before", {}).get("tree") == TREE
                    and execution.get("before", {}).get("dirty") is False
                    and execution.get("command") == record.get("actual_recorded_command")
                    and record.get("root_wrapper_returned") is True
                    and record.get("original_execution_record_sha256") == root["execution_sha256"]
                    and type(execution.get("exit_code")) is int
                    and execution.get("status") in ("passed", "failed")
                    and type(execution.get("returncode")) is int
                    and type(execution.get("command_exit_code")) is int
                    and execution["returncode"] == execution["command_exit_code"]
                    and isinstance(execution.get("finished_at"), str)
                    and bool(execution["finished_at"]), "original Root test child not proven terminal")
        else:
            require(record.get("root_command_dispatched") is False,
                    "Root29 dispatch is unknown")
        root_summary.update(disposition="actual_terminal_attempt", state=record["state"])
    return native, {"main_state": outer["state"], "native_state": native.get("state"),
                    "native_original_terminal": native_observation,
                    "caller_status": caller["status"],
                    "caller_actual_phases": phases, "Root29": root_summary}


def runtime_environment(binding, native, captured):
    created = bound_json(TARGET_RECORD, TARGET_HASH, captured)
    manifest = bound_json(MANIFEST, MANIFEST_HASH, captured)
    recovered = bound_json(RECOVERY, RECOVERY_HASH, captured)
    require(created["state"] == "isolated-build-target-created-original-pins-retained"
            and created["source_sha"] == created["source_after"]
            == "4537458b51b6ca936264aecea7cfe384b941d0d1"
            and created["source_tree"] == "8cbd7b269c9c39df4ee3ffcefed8473060696184"
            and created["source_status_after"] == ""
            and created["uid"] == os.getuid()
            and created["target"] == str(TARGET)
            and created["runtime_root"] == str(TARGET.parent)
            and created["original_manifest_sha256"] == MANIFEST_HASH
            and created["original_recovery_sha256"] == RECOVERY_HASH,
            "original target creation provenance differs")
    target_ids = {}
    for path, field in ((TARGET.parent, "root_identity"), (TARGET, "target_identity")):
        info = path.lstat()
        directory(path)
        previous = created[field]
        require(stat.S_IMODE(info.st_mode) == 0o700
                and (info.st_dev, info.st_ino, info.st_uid, oct(info.st_mode))
                == (previous["device"], previous["inode"], previous["uid"], previous["mode"]),
                "dedicated target was replaced")
        target_ids[str(path)] = directory(path)
    require(recovered["state"] == "original-assets-recovered-and-full-hash-verified"
            and recovered["source_sha"] == "441de918b863dd15b2faeae920017c1b4b08f59d"
            and recovered["uid"] == os.getuid()
            and recovered["environment"]["CARGO_TARGET_DIR"]
            == "/data/hepta-learn-ce434-runtime-20261112-v1/target",
            "original recovery differs")
    require(manifest["cargo_lock_sha256"] == file_digest(REPO / "codex-rs/Cargo.lock")["sha256"]
            and manifest["resolver_sha256"] == file_digest(REPO / "scripts/codex_package/v8.py")["sha256"],
            "original V8 source differs")
    expected = {
        "RUSTY_V8_ARCHIVE": "a35c75d1f26e6a983885a45b33490a4ebe54f05050568b32b89cfb421b30b583",
        "RUSTY_V8_SRC_BINDING_PATH": "7727826ae479bdb645e807239fb12d1f8e2e23de7a6cf16f5ee592690d1d8506",
    }
    require(set(manifest["environment"]) == set(expected), "original V8 pair differs")
    environment = dict(os.environ)
    require(not any(environment.get(key) for key in
                    ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")),
            "inherited Git location override")
    environment.update(
        CODEX_REPO_ROOT=str(REPO), CARGO_TARGET_DIR=str(TARGET), CARGO_BUILD_JOBS="4",
        CARGO_INCREMENTAL="0", CARGO_PROFILE_TEST_DEBUG="0", CARGO_PROFILE_DEV_DEBUG="0",
        CARGO_NET_OFFLINE="true", PYTHONDONTWRITEBYTECODE="1", SOURCE_SHA=SOURCE,
        TESTED_SHA=SOURCE, BASE_SHA=BASE, HEPTA_CI_LANE="source-head", GIT_OPTIONAL_LOCKS="0",
    )
    environment["PATH"] = PREFIX + PREFIX + environment["PATH"]
    for key, expected_hash in expected.items():
        original = Path(manifest["environment"][key])
        path = PINS / original.name
        entry = manifest["artifacts"][key]
        observed = file_digest(path)
        recovery_entries = [row for row in recovered["artifacts"] if row["key"] == key]
        require(original.parent == MANIFEST.parent and entry["path"] == str(original)
                and path.lstat().st_uid == os.getuid() and path.lstat().st_nlink == 1
                and entry["sha256"] == observed["sha256"] == expected_hash
                and entry["bytes"] == observed["bytes"]
                and len(recovery_entries) == 1
                and recovery_entries[0]["path"] == str(path)
                and recovery_entries[0]["sha256"] == expected_hash
                and recovery_entries[0]["bytes"] == observed["bytes"]
                and recovered["environment"][key] == str(path), "original private V8 bytes differ")
        environment[key] = str(path)
    temporary = Path(native["canonical_tmpdir"])
    temporary_id = directory(temporary)
    require(temporary.parent == Path("/tmp") and temporary.name.startswith("hlca-")
            and len(os.fsencode(temporary)) <= 32, "original retained TMPDIR differs")
    environment["TMPDIR"] = str(temporary)
    helper_names = {"CARGO_BIN_EXE_hepta-joint-propose", "CARGO_BIN_EXE_hepta_joint_propose"}
    helper = binding["helper"]
    if helper["kind"] == "bound_original":
        actual_steps = {row["name"]: row for row in native.get("steps", [])}
        require(all(type(actual_steps.get(name, {}).get("exit_code")) is int
                    and actual_steps[name]["exit_code"] == 0
                    for name in ("helper-build", "helper-verify")),
                "original native did not complete helper build and verification before import")
        exported = bound_json(MAIN / "helpers/env.json", helper["env_sha256"], captured)
        metadata = bound_json(MAIN / "helpers/manifest.json", helper["manifest_sha256"], captured)
        executable = MAIN / "helpers/bin/hepta-joint-propose"
        require(exported == {name: str(executable) for name in helper_names}
                and metadata.get("complete") is True
                and type(metadata.get("exit_code")) is int and metadata["exit_code"] == 0
                and set(metadata.get("artifacts", {})) == {"hepta-joint-propose"}
                and metadata.get("source_sha") == metadata.get("source_sha_after") == SOURCE
                and metadata.get("source_status_before") == metadata.get("source_status_after") == ""
                and metadata.get("workspace") == str(REPO / "codex-rs")
                and metadata.get("selected_packages") == ["codex-hepta-infer-worker-host"],
                "original helper metadata differs")
        artifact = metadata["artifacts"]["hepta-joint-propose"]
        observed = file_digest(executable)
        require(artifact["executable"] == str(executable)
                and artifact["package"] == "codex-hepta-infer-worker-host"
                and artifact["bytes"] == observed["bytes"]
                and artifact["sha256"] == observed["sha256"]
                and not stat.S_IMODE(executable.stat().st_mode) & 0o222
                and os.access(executable, os.X_OK), "original pinned helper differs")
        environment.update(exported)
    else:
        require(helper["kind"] == "not_completed"
                and any(row.get("name") in ("helper-build", "helper-verify")
                        and type(row.get("exit_code")) is int and row["exit_code"] != 0
                        for row in native.get("steps", []))
                and not any(key in environment for key in helper_names),
                "missing helper exports lack an actual failed preparation basis")
    return environment, target_ids, temporary, temporary_id


def write_bytes(path, value):
    with path.open("xb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def save_json(path, value):
    raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary = path.with_name(path.name + ".pending-" + uuid.uuid4().hex)
    write_bytes(temporary, raw)
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def command(folder, label, argv, cwd, environment):
    stdout_path, stderr_path = folder / (label + ".stdout"), folder / (label + ".stderr")
    started = time.monotonic()
    row = {"argv": argv, "cwd": str(cwd), "started_at": utc(), "pid": None,
           "actual_returncode": None, "signals_sent": [], "complete": False}
    process = None
    try:
        with stdout_path.open("xb", buffering=0) as stdout, stderr_path.open("xb", buffering=0) as stderr:
            try:
                process = subprocess.Popen(argv, cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
                                           stdout=stdout, stderr=stderr)
                row["pid"] = process.pid
                save_json(folder / (label + ".started.json"), row)
                row["actual_returncode"] = process.wait()
            finally:
                if process is not None:
                    row["actual_returncode"] = process.wait()
                stdout.flush()
                stderr.flush()
                os.fsync(stdout.fileno())
                os.fsync(stderr.fileno())
        row["complete"] = process is not None and type(row["actual_returncode"]) is int
    finally:
        row.update(finished_at=utc(), elapsed_seconds=time.monotonic() - started)
        row["logs"] = [{"file": path.name, **file_digest(path)}
                       for path in (stdout_path, stderr_path) if path.exists()]
        save_json(folder / (label + ".json"), row)
    return row, stdout_path


def git_capture(folder, label, arguments, environment):
    argv = ["git", "--no-optional-locks", "-c", "core.fsmonitor=false",
            "-c", "core.untrackedCache=false", *arguments]
    row, path = command(folder, label, argv, REPO, environment)
    require(row["complete"] and row["actual_returncode"] == 0, "Git observation failed")
    return path.read_bytes(), row


def relative_path(raw):
    require(raw and not raw.startswith(b"/")
            and all(part not in (b"", b".", b"..") for part in raw.split(b"/")),
            "invalid source-relative path")
    return REPO / os.fsdecode(raw)


def postimage(folder, index, raw, original):
    path = relative_path(raw)
    record = {"path": os.fsdecode(raw), "path_bytes_hex": raw.hex(),
              "original_HEAD_entry": original, "postimage": None}
    parent = REPO
    for part in raw.split(b"/")[:-1]:
        parent = parent / os.fsdecode(part)
        try:
            info = parent.lstat()
        except FileNotFoundError:
            record.update(kind="deleted", reason="parent_absent")
            return record
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            require(original is not None, "new source path has a non-directory parent")
            record.update(kind="deleted", reason="original_parent_type_changed")
            return record
    try:
        before = path.lstat()
    except FileNotFoundError:
        record["kind"] = "deleted"
        return record
    target = folder / ("postimage-%06d.bin" % index)
    if stat.S_ISLNK(before.st_mode):
        data = os.fsencode(os.readlink(path))
        require(identity(before) == identity(path.lstat()), "source symlink changed")
        write_bytes(target, data)
        sha256 = hashlib.sha256(data).hexdigest()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()
        size = len(data)
        kind = "symlink_target_bytes"
    else:
        require(stat.S_ISREG(before.st_mode), "changed source is not a file or symlink")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        sha = hashlib.sha256()
        git_hash = hashlib.sha1(b"blob " + str(before.st_size).encode("ascii") + b"\0")
        size = 0
        with os.fdopen(descriptor, "rb") as source, target.open("xb") as destination:
            opened = os.fstat(source.fileno())
            for block in iter(lambda: source.read(1024 * 1024), b""):
                destination.write(block)
                sha.update(block)
                git_hash.update(block)
                size += len(block)
            destination.flush()
            os.fsync(destination.fileno())
            after = os.fstat(source.fileno())
        require(identity(before) == identity(opened) == identity(after)
                == identity(path.lstat()) and size == before.st_size, "source changed during copy")
        sha256, blob, kind = sha.hexdigest(), git_hash.hexdigest(), "regular"
    require(file_digest(target) == {"bytes": size, "sha256": sha256}, "postimage readback differs")
    record.update(kind=kind, mode=oct(before.st_mode), uid=before.st_uid,
                  postimage={"file": target.name, "bytes": size, "sha256": sha256, "git_blob": blob})
    return record


def snapshot(out, name, environment, initial_entries, history):
    folder = out / name
    folder.mkdir(mode=0o700)
    head, _ = git_capture(folder, "head", ["rev-parse", "--verify", "HEAD"], environment)
    tree, _ = git_capture(folder, "tree", ["rev-parse", "--verify", "HEAD^{tree}"], environment)
    status, _ = git_capture(folder, "status",
                            ["status", "--porcelain=v1", "-z", "--untracked-files=all"], environment)
    binary_args = ["diff", "--binary", "--full-index", "--no-ext-diff", "--no-textconv",
                   "--no-renames", "HEAD", "--"]
    git_capture(folder, "diff-head", binary_args, environment)
    actual_head, actual_tree = head.decode("ascii").strip(), tree.decode("ascii").strip()
    if actual_head != SOURCE:
        git_capture(folder, "diff-fixed-source", [*binary_args[:-2], SOURCE, "--"], environment)
    names, _ = git_capture(folder, "changed-tracked",
                           ["diff", "--name-only", "-z", "--no-ext-diff", "--no-textconv",
                            "--no-renames", SOURCE, "--"], environment)
    untracked, _ = git_capture(folder, "untracked",
                               ["ls-files", "--others", "--exclude-standard", "-z"], environment)
    changes = sorted(history | set(item for item in names.split(b"\0") + untracked.split(b"\0") if item))
    history.update(changes)
    images = [postimage(folder, i, raw, initial_entries.get(raw)) for i, raw in enumerate(changes)]
    status_after, _ = git_capture(folder, "status-after",
                                  ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
                                  environment)
    head_after, _ = git_capture(folder, "head-after", ["rev-parse", "--verify", "HEAD"], environment)
    require(status_after == status and head_after == head, "source changed across snapshot")
    value = {"phase": name, "head": actual_head, "HEAD_tree": actual_tree,
             "status_file": "status.stdout", "status_bytes": len(status),
             "status_sha256": hashlib.sha256(status).hexdigest(), "clean": not status,
             "postimages": images, "complete": True,
             "HEAD_tree_is_dirty_working_tree": False, "working_tree_commit": None}
    save_json(folder / "snapshot.json", value)
    return value


def main():
    require(isinstance(BINDING, dict), "UNBOUND_TEMPLATE: actual terminal/hash binding required")
    require(os.getuid() == os.geteuid() != 0, "original normal user required")
    directory(REPO)
    directory(EVIDENCE)
    name = BINDING["output_name"]
    require(isinstance(name, str)
            and re.fullmatch(r"maintenance-8bf3881afa8c-isolated-v[1-9][0-9]*", name),
            "new exclusive evidence name is unbound")
    out = EVIDENCE / name
    require(not os.path.lexists(out), "exclusive maintenance evidence already exists")
    captured = []
    native, validation = validation_evidence(BINDING, captured)
    environment, target_ids, temporary, temporary_id = runtime_environment(BINDING, native, captured)
    out.mkdir(mode=0o700)
    report = {"state": "recording-before-fix", "bound_source": SOURCE, "bound_tree": TREE,
              "repo": str(REPO), "ordinary_acceptance": 0, "validation": validation,
              "commands": [], "snapshots": [], "post_maintenance_sha": None,
              "post_maintenance_tree": None, "tests_after_maintenance": [],
              "signals_sent": [], "started_at": utc(), "complete": False}
    try:
        prerequisites = out / "prerequisites"
        prerequisites.mkdir(mode=0o700)
        saved = []
        for index, (path, raw) in enumerate(captured):
            require(stable_bytes(path) == raw, "bound original evidence changed")
            filename = "receipt-%03d.json" % index
            write_bytes(prerequisites / filename, raw)
            saved.append({"original_path": str(path), "file": filename, "bytes": len(raw),
                          "sha256": hashlib.sha256(raw).hexdigest()})
        save_json(prerequisites / "manifest.json", saved)
        setup = out / "source-identity"
        setup.mkdir(mode=0o700)
        base, _ = git_capture(setup, "baseline", ["rev-parse", "--verify", BASE + "^{commit}"], environment)
        require(base.decode("ascii").strip() == BASE, "original formatter baseline differs")
        listing, _ = git_capture(setup, "initial-tree",
                                  ["ls-tree", "-r", "-z", "--full-tree", SOURCE], environment)
        initial_entries = {}
        require(listing.endswith(b"\0"), "incomplete original Git tree listing")
        for entry in listing[:-1].split(b"\0"):
            header, path = entry.split(b"\t", 1)
            mode, kind, blob = header.split()
            initial_entries[path] = {"mode": mode.decode("ascii"), "type": kind.decode("ascii"),
                                     "blob": blob.decode("ascii")}
        for index, (path, expected) in enumerate(SEMANTIC_PINS.items()):
            observed, _ = git_capture(setup, "pin-%d" % index,
                                       ["hash-object", path], environment)
            require(observed.decode("ascii").strip() == expected, "maintenance semantics changed")
        history = set()
        before = snapshot(out, "before-fix", environment, initial_entries, history)
        report["snapshots"].append(before)
        require(before["head"] == SOURCE and before["HEAD_tree"] == TREE and before["clean"],
                "fixed clean initial source required")
        report["runtime"] = {"target": str(TARGET), "target_identities": target_ids,
                             "TMPDIR": str(temporary), "TMPDIR_identity": temporary_id,
                             "environment_origin": "original outer + actual bound 8bf native carrier; same fixed resources; no global environment mutation"}
        save_json(out / "result.json", report)
        for phase, argv in COMMANDS:
            for path, expected in target_ids.items():
                require(directory(Path(path)) == tuple(expected), "dedicated target identity changed")
            require(directory(temporary) == temporary_id, "original retained TMPDIR changed")
            record, _ = command(out, phase, argv, REPO / "codex-rs", environment)
            report["commands"].append(record)
            require(record["complete"], "maintenance command terminal unknown")
            after = snapshot(out, phase + "-after", environment, initial_entries, history)
            report["snapshots"].append(after)
            save_json(out / "result.json", report)
            require(after["head"] == SOURCE and after["HEAD_tree"] == TREE,
                    "unexpected commit change; preserve source and do not advance")
        report["complete"] = True
        # Git status alone is not a physical-byte equality proof. The recorder
        # never assigns a commit identity to the post-maintenance worktree.
        report["publication_performed"] = False
        report["state"] = ("commands-finished-zero" if all(row["actual_returncode"] == 0
                           for row in report["commands"]) else "commands-finished-nonzero")
    except BaseException as error:
        report.update(state="incomplete-or-rejected", error_type=type(error).__name__,
                      error=str(error), complete=False)
        raise
    finally:
        report["finished_at"] = utc()
        save_json(out / "result.json", report)
    print(json.dumps({"state": report["state"], "result": str(out / "result.json"),
                      "complete": report["complete"], "ordinary_acceptance": 0}), flush=True)
    return 0 if report["state"] == "commands-finished-zero" else 1


if __name__ == "__main__":
    raise SystemExit(main())
