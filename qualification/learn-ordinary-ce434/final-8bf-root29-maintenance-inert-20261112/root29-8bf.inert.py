#!/usr/bin/env python3
"""Prepared 8bf3881afa8c-only Root29 append. Not dispatched by the preparing agent.

Reuse the original CI recorder and just test entry. This script never builds
helpers, repeats the 201-case suite, changes HOME, or signals an existing process.
"""
BINDING = None
if BINDING is None:
    raise SystemExit("INERT: actual 8bf native201 and terminal evidence is not bound; no filesystem action is permitted")

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

if not isinstance(BINDING, dict) or set(BINDING) != {
    "main_native_sha256", "main_execution_sha256"
}:
    raise RuntimeError("actual Root29 prerequisite binding shape differs")
if any(not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None
       for value in BINDING.values()):
    raise RuntimeError("actual Root29 prerequisite hash is unbound")

SOURCE = "8bf3881afa8cccff286fc58909995c96f3e0b260"
TREE = "c8730bab75eabe47a3b0b3260a6203a0d86d1443"
REPO = Path("/home/qian-qi/hepta-learn-positive-ce434-8bf3881afa8c-isolated-v1")
EVIDENCE = Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111/native")
MAIN = EVIDENCE / "live-owners-full-8bf3881afa8c-isolated-v1"
HELPERS = MAIN / "helpers"
TARGET = Path("/data/hepta-learn-ce434-runtime-20261112-v3/target")
TARGET_CREATION = EVIDENCE / "build-root-recovery-4537458b51b6-v3-attempt2/result.json"
TARGET_CREATION_SHA256 = "1054be1b7545dd29dfa2058ae6d7c7b35180aac3ee838d2d8c7bbdbacf7fba3b"
PINS = Path("/data/hepta-learn-ce434-runtime-20261112-v1/v8-private-pins")
RECOVERY = EVIDENCE / "dependency-recovery-441de918-v1/result.json"
RECOVERY_SHA256 = "8db2c096ff2c16b8e02f293a67c26939c5de6bf6e0dd69888179c4b0d31ca3fc"
MANIFEST = EVIDENCE / "v8-pinned-150-4-0-v2/manifest.json"
MANIFEST_SHA256 = "9969b385cfffaf8a16071033460b505fd98e7a8b6a7f8fd47762e526d78b5ff5"
NATIVE_DRIVER = EVIDENCE / "unified-8bf3881afa8c-isolated-v1/native-runner.py"
NATIVE_DRIVER_SHA256 = "3afa05b3543896c6f87b7ce557a57bc46ff245dbc8f0d7540ac4065ce076d25a"
PATH_PREFIX = "/home/qian-qi/hepta-learn-ce434-tools/uv-venv/bin:/home/qian-qi/.local/bin:/home/qian-qi/.cargo/bin:"
PARENTS = [
    "authority_host_service::writer::learning_registration::tests::root_learning_registration_reopens_without_replacing_original_history",
    "authority_host_service::writer::learning_registration::tests::root_learning_sealed_pin_and_dedicated_uds_recover_original_checkpoint",
    "authority_host_service::writer::learning_registration::tests::root_scoped_learning_reopens_exact_scope_and_refuses_legacy_client",
    "authority_host_service::writer::learning_registration::tests::root_learning_scoped_sealed_pin_preserves_scope_on_cold_reopen",
    "root_production_handoff::learning::tests::root_learning_handoff_reaches_dedicated_uid_with_original_root_pin",
    "authority_host_learning_service_root_tests::root_learning_public_registration_serves_retained_writer_and_recovers_history",
    "learning_iteration_evidence_client::tests::root::original_external_uid_returns_a_verified_receipt_through_held_pidfd",
    "authority_host_service::resident::authority::tests::resident_root_formatter_and_original_registration_pin_both_scopes",
    "authority_host_service::resident::authority::tests::resident_root_reissued_intent_cannot_create_another_operation_namespace",
    "authority_host_service::resident::authority::tests::resident_root_only_actual_vacant_cas_creates_one_live_continuation",
    "authority_host_service::resident::authority::tests::resident_root_same_epoch_grant_revocation_fences_the_pending_effect",
    "authority_host_service::resident::authority::tests::resident_root_exact_lease_revocation_fences_without_restarting_dispatch",
    "authority_host_service::resident::authority::tests::resident_root_lost_fresh_ack_recovers_only_under_explicit_readback_intent",
    "authority_host_service::resident::authority::tests::resident_root_queued_admit_cancellation_sends_no_frame_and_consumes_channel",
    "authority_host_service::resident::authority::tests::resident_root_structured_uncertain_allows_only_same_operation_readback",
    "authority_host_service::resident::authority::tests::checkpoint_expiry::resident_root_checkpoint_expiry_stops_next_stage_and_preserves_committed_bytes",
    "authority_host_service::resident::authority::tests::evaluation::resident_root_original_evaluation_requires_actual_checkpoint_and_independent_signature",
    "runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::retained_publication::retained_support::version_issuer::tests::retained_version_issuer_uses_actual_prepared_binding_and_installs_distinct_c",
    "runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::retained_publication::retained_support::version_issuer::tests::retained_version_issuer_denied_once_keeps_actual_prepared_operation_read_only",
    "runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::retained_publication::retained_support::version_issuer::tests::retained_version_issuer_lost_ack_never_reissues_original_intent",
    "runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::retained_publication::retained_support::version_issuer::tests::retained_version_issuer_wrong_grant_cannot_replace_prepared_purpose",
    "runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::retained_publication::retained_support::version_issuer::tests::retained_version_issuer_withdrawal_before_root_request_sends_no_frame",
    "runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::retained_publication::retained_support::version_issuer::tests::retained_version_issuer_queued_cancellation_sends_no_frame_and_never_reopens_once",
    "authority_host_service::resident::authority::tests::original_model::resident_root_model_four_cut_preserves_original_wire_and_all_signatures",
    "authority_host_service::resident::authority::tests::original_model::resident_root_model_five_cut_uses_original_record_without_fifth_signature",
    "authority_host_service::resident::authority::tests::original_model::resident_root_model_refuses_missing_extra_wrong_stage_or_reordered_evidence",
    "authority_host_service::resident::authority::tests::original_model::resident_root_model_refuses_changed_record_context_and_signature_window",
    "authority_host_service::resident::authority::tests::original_model::resident_root_model_cold_checkpoint_is_readonly_and_pins_complete_original_bytes",
    "authority_host_service::resident::authority::tests::original_model::resident_root_model_unknown_dispatch_never_recommits_or_mints_fresh_gate"
]
CI_PINS = {
    ".github/workflows/hepta-daemon-learning-native.yml": "380b6d50f871e7eaa5a8bbc12fb75e59d45b868d",
    "scripts/hepta_cell_test_helpers.py": "f5b702a55b44c081c6d8f5556da3a2152a33eec3",
    "scripts/hepta_ci_exec.py": "c9434b3a4afb31f80e323d543936386a2fa738de",
    "scripts/hepta_ci_junit.py": "683626df091bdfe160a8965fdc92bf40f5783cf8",
    "scripts/run-nextest.py": "1ed63abe84267b320cbfb0123a70aac5507f4595",
    "scripts/hepta_ci_v8.py": "088b737c0cca7386161e06b254c794bf972380ad",
    "justfile": "a215a76cf407ace9715bca39c20497014e7dd4dc",
    "codex-rs/.config/nextest.toml": "0904c42a41594d3ae4dc6f196e64f35f0b85bd2c",
}
ROOT_ALLOWLIST = (
    "PATH", "SOURCE_SHA", "TESTED_SHA", "HEPTA_CI_LANE",
    "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB",
    "PYTHONDONTWRITEBYTECODE", "CARGO_INCREMENTAL", "CARGO_BUILD_JOBS",
    "CARGO_PROFILE_TEST_DEBUG", "CARGO_PROFILE_DEV_DEBUG", "CARGO_TARGET_DIR",
    "RUSTY_V8_ARCHIVE", "RUSTY_V8_SRC_BINDING_PATH", "LIBCLANG_PATH",
    "RUSTUP_TOOLCHAIN", "BINDGEN_EXTRA_CLANG_ARGS",
)
V8_DIGESTS = {
    "RUSTY_V8_ARCHIVE": "a35c75d1f26e6a983885a45b33490a4ebe54f05050568b32b89cfb421b30b583",
    "RUSTY_V8_SRC_BINDING_PATH": "7727826ae479bdb645e807239fb12d1f8e2e23de7a6cf16f5ee592690d1d8506",
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def read_stable(path, maximum=1024 * 1024):
    before_path = path.lstat()
    require(stat.S_ISREG(before_path.st_mode), "expected original regular file: " + str(path))
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        data = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    require(len(data) <= maximum, "input exceeded original bound: " + str(path))
    require(all(getattr(before_path, k) == getattr(before, k) == getattr(after, k)
                == getattr(path.lstat(), k) for k in fields),
            "input changed while reading: " + str(path))
    return data


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def git(*arguments):
    command = ["git", "--no-optional-locks", *arguments]
    process = subprocess.Popen(command, cwd=REPO, env=normal_env, stdout=subprocess.PIPE)
    try:
        stdout, _ = process.communicate()
    except BaseException:
        try:
            process.communicate()
        finally:
            process.wait()
        raise
    process.wait()
    if process.returncode:
        raise subprocess.CalledProcessError(process.returncode, command, output=stdout)
    return stdout.decode("utf-8").strip()


def identity():
    value = {
        "head": git("rev-parse", "HEAD"),
        "tree": git("rev-parse", "HEAD^{tree}"),
        "status": git("status", "--porcelain=v1", "--untracked-files=all"),
    }
    require(value == {"head": SOURCE, "tree": TREE, "status": ""},
            "Root29 requires the same clean 8bf3881afa8c checkout")
    return value


def save():
    pending = out / "result.pending.json"
    with pending.open("w", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(out / "result.json")


def record_step(name, command, environment):
    log = out / (name + ".driver.log")
    started = time.monotonic()
    with log.open("xb") as stream:
        process = subprocess.Popen(command, cwd=REPO, env=environment,
                                   stdout=stream, stderr=subprocess.STDOUT)
        try:
            returncode = process.wait()
        except BaseException:
            process.wait()
            raise
    row = {"name": name, "command": command, "exit_code": returncode,
           "seconds": time.monotonic() - started, "log": str(log),
           "log_bytes": log.stat().st_size, "log_sha256": file_hash(log)}
    report["steps"].append(row)
    save()
    return returncode, log


def verify_helpers(label):
    code, log = record_step(
        label, ["/usr/bin/python3", "-B", str(REPO / "scripts/hepta_cell_test_helpers.py"),
                "--package", "codex-hepta-infer-worker-host",
                "--output-dir", str(HELPERS), "--verify-only"], normal_env
    )
    require(code == 0, "same-source helper verification failed: " + label)
    checked = json.loads(read_stable(log))
    require(checked.get("complete") is True and checked.get("exit_code") == 0
            and checked.get("mode") == "verify-only"
            and checked.get("selected_packages") == ["codex-hepta-infer-worker-host"]
            and checked.get("source_before") == checked.get("source_after")
            == {"head": SOURCE, "tree": TREE, "status": ""},
            "original helper verifier did not certify this clean 8bf3881afa8c source")
    return checked


def verify_main_execution(main):
    data = read_stable(MAIN / "focused-native.json")
    require(digest_bytes(data) == BINDING["main_execution_sha256"],
            "bound original native201 execution record differs")
    execution = json.loads(data)
    cases = main.get("expected_owner_cases")
    require(isinstance(cases, list) and len(cases) == 201
            and all(isinstance(row, list) and len(row) == 2
                    and all(isinstance(value, str) and value for value in row) for row in cases)
            and len({tuple(row) for row in cases}) == 201,
            "original native201 case inventory differs")
    packages = sorted({row[0] for row in cases})
    require(packages == ["codex-hepta-agentd", "codex-hepta-intelligence-eval",
                         "codex-hepta-learning-artifacts", "codex-hepta-neuron"],
            "original native201 package set differs")
    expression = " | ".join("(package(=" + package + ") & test(=" + name + "))"
                            for package, name in cases)
    expected = ["just", "test", "--locked", "--offline",
                *(arg for package in packages for arg in ("-p", package)),
                "--lib", "-E", expression, "--test-threads", "2", "--retries", "0",
                "--no-tests", "fail", "--status-level", "pass",
                "--success-output", "final", "--failure-output", "final"]
    require(execution.get("source_sha") == execution.get("tested_sha") == SOURCE
            and execution.get("lane") == "source-head"
            and execution.get("working_directory") == str(REPO / "codex-rs")
            and execution.get("before") == execution.get("after")
            and execution.get("before", {}).get("commit") == SOURCE
            and execution.get("before", {}).get("tree") == TREE
            and execution.get("before", {}).get("dirty") is False
            and execution.get("command") == expected
            and execution.get("status") == "passed"
            and isinstance(execution.get("finished_at"), str) and bool(execution["finished_at"])
            and all(type(execution.get(key)) is int and execution[key] == 0
                    for key in ("exit_code", "returncode", "command_exit_code"))
            and execution.get("timed_out") is False
            and execution.get("output_limit_exceeded") is False,
            "the actual original native201 child did not pass this exact source and command")
    return data, execution


def verify_v8():
    manifest_bytes = read_stable(MANIFEST)
    recovery_bytes = read_stable(RECOVERY)
    require(digest_bytes(manifest_bytes) == MANIFEST_SHA256, "original V8 manifest changed")
    require(digest_bytes(recovery_bytes) == RECOVERY_SHA256, "original recovery record changed")
    manifest = json.loads(manifest_bytes)
    recovery = json.loads(recovery_bytes)
    require(manifest["cargo_lock_sha256"] == file_hash(REPO / "codex-rs/Cargo.lock")
            and manifest["resolver_sha256"] == file_hash(REPO / "scripts/codex_package/v8.py"),
            "original V8 source inputs changed")
    require(recovery["state"] == "original-assets-recovered-and-full-hash-verified"
            and recovery["source_sha"] == "441de918b863dd15b2faeae920017c1b4b08f59d"
            and recovery["environment"]["CARGO_TARGET_DIR"]
            == "/data/hepta-learn-ce434-runtime-20261112-v1/target"
            and recovery["uid"] == os.getuid(),
            "original successful recovery identity differs")
    require(set(manifest["environment"]) == set(V8_DIGESTS), "V8 pair incomplete")
    result = {}
    for key, expected in V8_DIGESTS.items():
        original = Path(manifest["environment"][key])
        entry = manifest["artifacts"][key]
        path = PINS / original.name
        info = path.lstat()
        data = read_stable(path, 32 * 1024 * 1024)
        recovered = [a for a in recovery["artifacts"] if a["key"] == key]
        require(original.parent == MANIFEST.parent and entry["path"] == str(original)
                and entry["sha256"] == expected and entry["bytes"] == len(data)
                and path.resolve(strict=True) == path and stat.S_ISREG(info.st_mode)
                and info.st_uid == os.getuid() and info.st_nlink == 1
                and digest_bytes(data) == expected and len(recovered) == 1
                and recovered[0]["path"] == str(path)
                and recovered[0]["bytes"] == len(data)
                and recovered[0]["sha256"] == expected
                and recovery["environment"][key] == str(path),
                "original recovered V8 artifact differs: " + key)
        result[key] = {"path": str(path), "bytes": len(data), "sha256": expected}
    return result


def verify_target_v3():
    # 453 is immutable creation provenance, not this run's tested source.
    before = TARGET_CREATION.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
            and before.st_nlink == 1 and before.st_size <= 16_384,
            "original target-v3 creation record differs")
    fd = os.open(TARGET_CREATION, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        data = stream.read(16_385)
        after = os.fstat(stream.fileno())
    fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_uid", "st_size",
              "st_mtime_ns", "st_ctime_ns")
    require(len(data) == before.st_size
            and all(getattr(before, key) == getattr(opened, key) == getattr(after, key)
                    == getattr(TARGET_CREATION.lstat(), key) for key in fields),
            "original target-v3 creation record changed while reading")
    require(digest_bytes(data) == TARGET_CREATION_SHA256,
            "original target-v3 creation record hash differs")
    created = json.loads(data)
    require(created["state"] == "isolated-build-target-created-original-pins-retained"
            and created["source_sha"] == created["source_after"]
            == "4537458b51b6ca936264aecea7cfe384b941d0d1"
            and created["source_tree"] == "8cbd7b269c9c39df4ee3ffcefed8473060696184"
            and created["source_status_after"] == ""
            and created["uid"] == os.getuid()
            and created["target"] == str(TARGET)
            and created["runtime_root"] == str(TARGET.parent)
            and created["original_manifest_sha256"] == MANIFEST_SHA256
            and created["original_recovery_sha256"] == RECOVERY_SHA256,
            "original target-v3 creation provenance differs")
    actual_identities = {}
    for path, field in ((TARGET.parent, "root_identity"), (TARGET, "target_identity")):
        actual = path.lstat()
        original = created[field]
        require(stat.S_ISDIR(actual.st_mode) and path.resolve(strict=True) == path
                and actual.st_uid == os.getuid() and stat.S_IMODE(actual.st_mode) == 0o700
                and (actual.st_dev, actual.st_ino, actual.st_uid, oct(actual.st_mode))
                == (original["device"], original["inode"], original["uid"], original["mode"]),
                "original target-v3 directory was replaced")
        actual_identities[field] = {"device": actual.st_dev, "inode": actual.st_ino,
                                    "uid": actual.st_uid, "mode": oct(actual.st_mode)}
    return {"record_path": str(TARGET_CREATION), "record_sha256": digest_bytes(data),
            "creation_source_sha": created["source_sha"],
            "creation_source_tree": created["source_tree"],
            "creation_is_provenance_only": True, "tested_source_sha": SOURCE,
            "target": str(TARGET), "actual_identities": actual_identities}


ROOT_SETUP = r"""
import json, os, subprocess, sys
from pathlib import Path
assert os.geteuid() == 0
p = Path(sys.argv[1])
assert p.parent == Path("/run") and p.name.startswith("hepta-learn-root29-8bf3881afa8c-")
p.mkdir(mode=0o700)
for name in ("source", "bind", "checkpoints"):
    (p / name).mkdir(mode=0o700)
process = subprocess.Popen(["/usr/bin/mount", "--bind", str(p / "source"), str(p / "bind")])
try:
    code = process.wait()
except BaseException:
    process.wait()
    raise
if code:
    raise subprocess.CalledProcessError(code, process.args)
entries = [line.split() for line in Path("/proc/self/mountinfo").read_text().splitlines()
           if line.split()[4] == str(p / "bind")]
assert len(entries) == 1
root = p.stat()
source = (p / "source").stat()
bound = (p / "bind").stat()
assert root.st_uid == 0 and source.st_uid == 0
assert (source.st_dev, source.st_ino) == (bound.st_dev, bound.st_ino)
print(json.dumps({"uid": os.geteuid(), "root": str(p),
                  "root_dev": root.st_dev, "root_ino": root.st_ino,
                  "source_dev": source.st_dev, "source_ino": source.st_ino,
                  "mount_id": entries[0][0]}), flush=True)
"""
ROOT_UNMOUNT = r"""
import json, os, subprocess, sys
from pathlib import Path
assert os.geteuid() == 0
p = Path(sys.argv[1])
saved = json.loads(sys.argv[2])
assert str(p) == saved["root"] and p.parent == Path("/run")
root = p.stat()
source = (p / "source").stat()
bound = (p / "bind").stat()
assert root.st_uid == 0 and (root.st_dev, root.st_ino) == (saved["root_dev"], saved["root_ino"])
assert (source.st_dev, source.st_ino) == (saved["source_dev"], saved["source_ino"])
assert (bound.st_dev, bound.st_ino) == (saved["source_dev"], saved["source_ino"])
entries = [line.split() for line in Path("/proc/self/mountinfo").read_text().splitlines()
           if line.split()[4] == str(p / "bind")]
assert len(entries) == 1 and entries[0][0] == saved["mount_id"]
process = subprocess.Popen(["/usr/bin/umount", "--", str(p / "bind")])
try:
    code = process.wait()
except BaseException:
    process.wait()
    raise
if code:
    raise subprocess.CalledProcessError(code, process.args)
assert not any(line.split()[4] == str(p / "bind")
               for line in Path("/proc/self/mountinfo").read_text().splitlines())
print(json.dumps({"unmounted_only": str(p / "bind"),
                  "fixture_bytes_preserved": True}), flush=True)
"""

if len(sys.argv) != 2 or re.fullmatch(r"v[1-9][0-9]*", sys.argv[1]) is None:
    raise SystemExit("usage: root29-8bf3881afa8c-runner.py vN (new, explicitly selected attempt)")
require(os.getuid() == os.geteuid() != 0, "start as the original normal user, never sudo this runner")
require(REPO.resolve(strict=True) == REPO, "qualification checkout path differs")
require(len(PARENTS) == len(set(PARENTS)) == 29, "original Root29 list differs")
attempt = sys.argv[1]
out = EVIDENCE / ("root-29-8bf3881afa8c-isolated-" + attempt)
root_dir = Path("/run") / ("hepta-learn-root29-8bf3881afa8c-" + attempt)
require(not out.exists() and not out.is_symlink(), "new exclusive evidence directory required")
normal_env = dict(os.environ)
normal_env.update(
    PATH=PATH_PREFIX + normal_env["PATH"],
    SOURCE_SHA=SOURCE, TESTED_SHA=SOURCE, HEPTA_CI_LANE="source-head",
    PYTHONDONTWRITEBYTECODE="1", CARGO_TARGET_DIR=str(TARGET),
    CARGO_BUILD_JOBS="4", CARGO_INCREMENTAL="0",
    CARGO_PROFILE_TEST_DEBUG="0", CARGO_PROFILE_DEV_DEBUG="0", CARGO_NET_OFFLINE="true",
)
sys.dont_write_bytecode = True
os.chdir(REPO)
initial = identity()
require(file_hash(NATIVE_DRIVER) == NATIVE_DRIVER_SHA256, "frozen original 8bf3881afa8c native driver differs")
main_bytes = read_stable(MAIN / "result.json")
require(digest_bytes(main_bytes) == BINDING["main_native_sha256"],
        "bound original native201 main receipt differs")
main = json.loads(main_bytes)
require(main.get("source_sha") == SOURCE and main.get("source_tree") == TREE
        and main.get("state") == "passed"
        and main.get("native_tests_executed") == 201
        and main.get("owner_coverage", {}).get("exact_selected_cases") is True
        and not main.get("owner_coverage", {}).get("failed_or_skipped", [])
        and main.get("original_observer_coverage", {}).get("exact_pass_coverage") is True
        and main.get("source_after") == SOURCE and main.get("source_status_after") == ""
        and type(main.get("native_exit_code")) is int and main["native_exit_code"] == 0
        and type(main.get("collection_exit_code")) is int and main["collection_exit_code"] == 0,
        "wait for the original same-SHA full 201-case main run to pass; never overlap its target or JUnit")
steps = {step["name"]: step for step in main.get("steps", [])}
require(steps.get("helper-build", {}).get("exit_code") == 0
        and steps.get("helper-verify", {}).get("exit_code") == 0
        and steps.get("focused-native", {}).get("exit_code") == main["native_exit_code"]
        and steps.get("focused-junit", {}).get("exit_code") == main["collection_exit_code"],
        "original main preparation/terminal receipts incomplete")
main_execution_bytes, main_execution = verify_main_execution(main)
target_stat = TARGET.lstat()
require(stat.S_ISDIR(target_stat.st_mode) and TARGET.resolve(strict=True) == TARGET
        and target_stat.st_uid == os.getuid(), "same original owned target required")
target_creation = verify_target_v3()
for path, blob in CI_PINS.items():
    require(git("hash-object", path) == blob, "original CI source changed: " + path)
out.mkdir(mode=0o700, parents=False, exist_ok=False)
report = {
    "schema": "hepta.learn.root29-8bf3881afa8c-original-ci-append.v1",
    "source_sha": SOURCE, "source_tree": TREE, "state": "preparing",
    "initiating_uid": os.getuid(), "initiating_gid": os.getgid(),
    "main_terminal_record": {"path": str(MAIN / "result.json"),
                             "sha256": digest_bytes(main_bytes), "state": main["state"]},
    "main_native_result_is_not_overridden": True,
    "main_original_execution_record": {"path": str(MAIN / "focused-native.json"),
                                       "sha256": digest_bytes(main_execution_bytes),
                                       "status": main_execution["status"]},
    "helper_directory": str(HELPERS), "target": str(TARGET),
    "target_initialization": target_creation,
    "before": initial, "steps": [], "expected_parents": PARENTS,
    "root_fixture": str(root_dir), "root_command_dispatched": False,
    "root_wrapper_returned": False, "root_command_returned": False,
    "original_execution_terminal": False, "root_native_test_count": 0,
    "ordinary_acceptance": {"positive": 0, "no_update": 0, "fresh_C": 0,
                           "daemon_root_cold_restart": 0},
}
mount_owned = None
root_started = False
root_wrapper_returned = False
original_execution_terminal = False
passed = False
try:
    save()
    report["v8_before"] = verify_v8()
    normal_env.update({key: value["path"] for key, value in report["v8_before"].items()})
    report["helper_before"] = verify_helpers("helper-verify-before")
    helper_env_bytes = read_stable(HELPERS / "env.json")
    helper_manifest_bytes = read_stable(HELPERS / "manifest.json")
    helper_env = json.loads(helper_env_bytes)
    pinned_helper = report["helper_before"]["artifacts"]["hepta-joint-propose"]["executable"]
    require(helper_env == {"CARGO_BIN_EXE_hepta-joint-propose": pinned_helper,
                           "CARGO_BIN_EXE_hepta_joint_propose": pinned_helper},
            "original helper environment differs from the just-verified exact artifact")
    report["helper_input_hashes"] = {"env": digest_bytes(helper_env_bytes),
                                     "manifest": digest_bytes(helper_manifest_bytes)}
    root_env = {key: normal_env[key] for key in ROOT_ALLOWLIST if key in normal_env}
    cargo_home = os.environ.get("CARGO_HOME", str(Path.home() / ".cargo"))
    rustup_home = os.environ.get("RUSTUP_HOME", str(Path.home() / ".rustup"))
    require(Path(cargo_home).is_dir() and Path(rustup_home).is_dir(),
            "reuse existing normal-user Cargo/Rustup directories only")
    root_env.update(
        CARGO_HOME=cargo_home, RUSTUP_HOME=rustup_home,
        GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="safe.directory", GIT_CONFIG_VALUE_0=str(REPO),
        HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT=str(root_dir / "bind"),
        HEPTA_HOST_AUTHORITY_QUALIFICATION_SOURCE=str(root_dir / "source"),
        HEPTA_CHECKPOINT_TEST_ROOT=str(root_dir / "checkpoints"),
    )
    root_env.update(helper_env)
    require("HOME" not in root_env and "TMPDIR" not in root_env, "private HOME/TMPDIR must not cross Root boundary")
    report["root_environment"] = root_env
    report["root_environment_origins"] = {
        "allowlist": ".github/workflows/hepta-daemon-learning-native.yml: test(root=True)",
        "resource_values_and_path_prefix": "actual frozen 8bf native-runner.py 7b38fb189736532092d88f59da6a71dd63498ae3; original resources unchanged",
        "cargo_home": "existing CARGO_HOME" if "CARGO_HOME" in os.environ else "original CI normal-user Path.home()/.cargo fallback",
        "rustup_home": "existing RUSTUP_HOME" if "RUSTUP_HOME" in os.environ else "original CI normal-user Path.home()/.rustup fallback",
        "optional_toolchain_clang_ci_fields": "inherited existing values only; never synthesized",
        "v8": "hash-verified original successful recovery ledger",
        "helper": "same-8bf3881afa8c original helper --verify-only and exact env.json",
        "fixture_paths": "new invocation-owned isolated /run directory only",
    }
    save()
    junit = REPO / "codex-rs/target/nextest/local/junit.xml"
    if junit.exists() or junit.is_symlink():
        require(stat.S_ISREG(junit.lstat().st_mode), "prior JUnit must be an original regular file")
        old_junit = out / "prior-junit-excluded.xml"
        junit.rename(old_junit)
        report["excluded_prior_junit"] = {"path": str(old_junit), "sha256": file_hash(old_junit)}
        save()
    setup_command = ["sudo", "-n", "env", "-i", "PATH=/usr/sbin:/usr/bin:/sbin:/bin",
                     "/usr/bin/python3", "-B", "-c", ROOT_SETUP, str(root_dir)]
    code, setup_log = record_step("root-fixture-setup", setup_command, normal_env)
    require(code == 0, "new Root fixture setup failed; no test dispatched")
    mount_owned = json.loads(read_stable(setup_log))
    require(mount_owned["uid"] == 0 and mount_owned["root"] == str(root_dir),
            "actual Root setup receipt differs")
    report["owned_mount"] = mount_owned
    expression = " | ".join("test(=" + name + ")" for name in PARENTS)
    test_command = ["just", "test", "--locked", "--offline", "-p", "codex-hepta-agentd",
                    "--lib", "--run-ignored", "only", "-E", expression,
                    "--test-threads", "1", "--retries", "0",
                    "--status-level", "pass", "--success-output", "final", "--failure-output", "final"]
    recorder = ["scripts/hepta_ci_exec.py", "--timeout-seconds", "7200",
                "--minimum-tests", "1", "--output", str(out / "root.json"), "--", *test_command]
    uid_check = "import os,runpy,sys; assert os.geteuid()==0; print('Root test uid=0',flush=True); runpy.run_path(sys.argv.pop(1),run_name='__main__')"
    root_command = ["sudo", "-n", "env", "-i",
                    *(key + "=" + value for key, value in sorted(root_env.items())),
                    "/usr/bin/python3", "-B", "-c", uid_check, *recorder]
    require(identity() == initial and read_stable(MAIN / "result.json") == main_bytes
            and read_stable(MAIN / "focused-native.json") == main_execution_bytes,
            "source or prior native terminal receipt changed before Root dispatch")
    report.update(state="root-running", root_command=root_command,
                  actual_recorded_command=test_command, required_root_euid=0)
    save()
    root_log = out / "root.driver.log"
    root_begin = time.monotonic()
    with root_log.open("xb") as stream:
        process = subprocess.Popen(root_command, cwd=REPO, env=normal_env,
                                   stdout=stream, stderr=subprocess.STDOUT)
        root_started = True
        report.update(root_command_dispatched=True, root_wrapper_pid=process.pid)
        save()
        root_code = process.wait()
        root_wrapper_returned = True
    report.update(root_wrapper_returned=True, root_wrapper_exit_code=root_code,
                  root_seconds=time.monotonic() - root_begin,
                  root_driver_log_sha256=file_hash(root_log), root_driver_log_bytes=root_log.stat().st_size)
    save()
    # A returned sudo/Python wrapper does not prove that the original recorder
    # waited for its just-test child. Read the new invocation's actual terminal
    # record before any chown or unmount. Missing/unreadable/partial evidence
    # remains uncertain and leaves the owned fixture intact.
    record_bytes = read_stable(out / "root.json")
    record = json.loads(record_bytes)
    require(record.get("source_sha") == record.get("tested_sha") == SOURCE
            and record.get("lane") == "source-head"
            and record.get("working_directory") == str(REPO)
            and record.get("before", {}).get("commit") == SOURCE
            and record.get("before", {}).get("tree") == TREE
            and record.get("before", {}).get("dirty") is False
            and record.get("command") == test_command
            and record.get("status") in ("passed", "failed")
            and isinstance(record.get("finished_at"), str) and bool(record["finished_at"])
            and type(record.get("exit_code")) is int
            and type(record.get("returncode")) is int
            and type(record.get("command_exit_code")) is int
            and record["command_exit_code"] == record["returncode"],
            "original just-test terminal record is not proven; retain owned fixture without chown or unmount")
    original_execution_terminal = True
    report.update(root_command_returned=True, original_execution_terminal=True,
                  original_execution=record,
                  original_execution_record_sha256=digest_bytes(record_bytes))
    save()
    # Restore only the existing dedicated target, this new evidence, and CI's nextest directory.
    target_after = TARGET.lstat()
    require((target_after.st_dev, target_after.st_ino) == (target_stat.st_dev, target_stat.st_ino)
            and TARGET.resolve(strict=True) == TARGET, "owned target identity changed")
    restore = [TARGET, out]
    nextest = REPO / "codex-rs/target/nextest"
    if nextest.exists():
        require(nextest.resolve(strict=True) == nextest and stat.S_ISDIR(nextest.lstat().st_mode),
                "original nextest output path changed")
        restore.append(nextest)
    code, _ = record_step("restore-owned-build-evidence", [
        "sudo", "-n", "/usr/bin/chown", "-R", "--no-dereference",
        f"{os.getuid()}:{os.getgid()}", "--", *(str(path) for path in restore)
    ], normal_env)
    require(code == 0, "owned build/evidence ownership restoration failed")
    collect_code, _ = record_step("root-junit", [
        "/usr/bin/python3", "-B", str(REPO / "scripts/hepta_ci_junit.py"),
        "--execution", str(out / "root.json"), "--junit", str(junit),
        "--output", str(out / "root.xml")
    ], normal_env)
    require(read_stable(out / "root.json") == record_bytes,
            "original execution terminal bytes changed after scoped ownership restoration")
    require(record.get("source_sha") == record.get("tested_sha") == SOURCE
            and record.get("before") == record.get("after")
            and record.get("before", {}).get("tree") == TREE
            and record.get("command") == test_command, "original execution identity or command differs")
    if (out / "root.xml").exists():
        sys.path.insert(0, str(REPO / "scripts"))
        from hepta_ci_junit import NoDoctypeTreeBuilder
        xml_bytes = read_stable(out / "root.xml", 64 * 1024 * 1024)
        document = ET.fromstring(xml_bytes, parser=ET.XMLParser(target=NoDoctypeTreeBuilder()))
        cases = list(document.iter("testcase"))
        rejected_tags = {"failure", "error", "skipped", "flakyFailure", "flakyError", "rerunFailure", "rerunError"}
        actual = Counter((case.get("classname"), case.get("name")) for case in cases)
        expected = Counter(("codex-hepta-agentd", name) for name in PARENTS)
        bad = [{"classname": case.get("classname"), "name": case.get("name"),
                "tags": [child.tag for child in case if child.tag in rejected_tags]}
               for case in cases if any(child.tag in rejected_tags for child in case)]
        report["root_parent_coverage"] = {
            "total_cases": len(cases), "exact_package_and_name_multiset": actual == expected,
            "failed_skipped_or_retried": bad, "xml_bytes": len(xml_bytes),
            "xml_sha256": digest_bytes(xml_bytes),
        }
        if actual == expected and not bad:
            report["root_native_test_count"] = 29
    report["helper_after"] = verify_helpers("helper-verify-after")
    require(read_stable(HELPERS / "env.json") == helper_env_bytes
            and read_stable(HELPERS / "manifest.json") == helper_manifest_bytes,
            "helper evidence changed during Root append")
    report["v8_after"] = verify_v8()
    require(report["v8_before"] == report["v8_after"], "original V8 pair changed")
    report["after"] = identity()
    root_marker = b"Root test uid=0\n" in read_stable(root_log, 64 * 1024 * 1024)
    report["actual_root_marker_observed"] = root_marker
    report["collection_exit_code"] = collect_code
    passed = (
        root_code == collect_code == 0 and root_marker
        and record.get("status") == "passed" and record.get("exit_code") == 0
        and record.get("command_exit_code") == 0 and record.get("timed_out") is False
        and record.get("output_limit_exceeded") is False
        and report["root_native_test_count"] == 29
        and report["after"] == initial
        and read_stable(MAIN / "result.json") == main_bytes
        and read_stable(MAIN / "focused-native.json") == main_execution_bytes
    )
    require(passed, "original Root29 gate did not pass; all receipts retained")
except BaseException as error:
    passed = False
    report.update(error_type=type(error).__name__, error=str(error))
finally:
    # Wrapper completion alone is insufficient. Never clean up under an
    # unproven original execution, even when sudo/Python already returned.
    if root_started and not original_execution_terminal:
        report["cleanup"] = "not attempted: original just-test completion is uncertain; owned fixture retained, no chown, unmount or process signal"
        passed = False
    elif mount_owned is not None:
        try:
            code, _ = record_step("unmount-owned-fixture", [
                "sudo", "-n", "env", "-i", "PATH=/usr/sbin:/usr/bin:/sbin:/bin",
                "/usr/bin/python3", "-B", "-c", ROOT_UNMOUNT,
                str(root_dir), json.dumps(mount_owned, sort_keys=True)
            ], normal_env)
            require(code == 0, "owned mount cleanup failed; no other mount touched")
            report["cleanup"] = "only invocation-owned bind unmounted; fixture bytes preserved"
        except BaseException as error:
            report["cleanup_error"] = f"{type(error).__name__}: {error}"
            passed = False
    else:
        report["cleanup"] = "no certified owned mount receipt; no unmount attempted"
    report["state"] = "passed" if passed else ("uncertain" if root_started and not original_execution_terminal else "failed")
    report["source_identity_claim"] = "same fixed 8bf3881afa8c fixture mechanisms only; no ordinary daemon cold-start or adoption claim"
    save()
print(json.dumps({"state": report["state"], "result": str(out / "result.json"),
                  "root_native_test_count": report["root_native_test_count"]}), flush=True)
raise SystemExit(0 if passed else 1)
