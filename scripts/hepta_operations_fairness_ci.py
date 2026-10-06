"""Bounded source diagnostic only, never merge/deployment qualification."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import signal
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import time

import hepta_ci_exec
from hepta_frozen_bounded import xml_record

BASE = "66f0ba01bb444a245001d7d1fd21121fc8c01206"
SOURCE_TREE = "09ede9a8cea00da3fd920dcdd43d1bcc3410bcd8"
BASELINE_TREE = "ca41e6081f17dfe48e4c5bafe91969c36736943e"
BRANCH = "refs/heads/dot/operations-fairness-qualification-20261006"
ADDITIONS = (".github/workflows/operations-fairness-qualification.yml", "scripts/hepta_operations_fairness_ci.py")
TEST_PATHS = tuple("codex-rs/hepta-memory/src/" + name for name in (
    "production_cognitive_source_target_tests.rs", "production_reconciliation_fairness_tests.rs", "production_reconciliation_edge_tests.rs"))
RED = {
    "same_destination_unavailable_prefix_does_not_starve_later_operation": "unavailable prefix must not hide later identity",
    "cloned_dispatcher_reserves_beyond_paused_observer_and_cancelled_page_wraps": "concurrent reservations must reach all three identities",
    "limit_two_binding_error_propagates_without_permanently_hiding_later_items": "later valid rows remain observable",
    "still_indeterminate_cycle_is_fair_and_short_cycle_never_repeats_within_one_call": "still-indeterminate prefix must rotate",
}
REQUIRED = tuple(RED) + (
    "cursor_does_not_retain_writer_lock_and_resets_on_reopened_owner",
    "tied_and_new_keys_wrap_past_terminal_holes_without_crossing_destinations",
    "concurrent_cross_wrap_observations_preserve_terminal_cas_and_never_dispatch",
)

def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")

def git(*args, cwd=None, env=None):
    return subprocess.check_output(["git", "--no-replace-objects", *args], cwd=cwd, env=env, text=True).strip()

def remaining(cap=3000):
    seconds = int(float(os.environ["OPERATIONS_DEADLINE"]) - time.time())
    if seconds < 30:
        raise ValueError("shared deadline exhausted; remaining stages NOT RUN")
    return min(cap, seconds)

def identity():
    if os.environ.get("GITHUB_EVENT_NAME") != "push" or os.environ.get("GITHUB_REF") != BRANCH:
        raise ValueError("only the single reviewed diagnostic push is allowed")
    result = hepta_ci_exec.identity()
    if result["dirty"] or result["commit"] != os.environ["SOURCE_SHA"] or result["commit"] != os.environ["TESTED_SHA"]:
        raise ValueError("dirty or wrong source identity")
    if result["parents"] != [BASE] or os.environ.get("HEPTA_CI_LANE") != "source-head":
        raise ValueError("diagnostic requires the exact sole parent and source-head lane")
    with tempfile.TemporaryDirectory() as temp:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(temp) / "index"))
        git("read-tree", result["commit"], env=env)
        git("update-index", "--force-remove", "--", *ADDITIONS, env=env)
        projection = git("write-tree", env=env)
    if projection != SOURCE_TREE:
        raise ValueError("unreviewed product projection")
    return {**result, "source_projection": projection, "diagnostic_blobs": {p: git("rev-parse", f'{result["commit"]}:{p}') for p in ADDITIONS}}

def recorded(output, command, minimum, cap):
    cancellation = hepta_ci_exec.CommandCancellation()
    old = {}
    try:
        for number in (signal.SIGINT, signal.SIGTERM):
            old[number] = signal.signal(number, cancellation.request)
        return hepta_ci_exec.run(output, command, minimum_tests=minimum, timeout_seconds=remaining(cap), cancellation=cancellation)
    finally:
        for number, handler in old.items(): signal.signal(number, handler)

def assert_native(record):
    if record.get("timed_out") or record.get("output_limit_exceeded") or record.get("interrupted_signal") is not None:
        raise ValueError("incomplete native execution")
    if record.get("before") != record.get("after") or record.get("before", {}).get("dirty", True):
        raise ValueError("source changed during execution")

def short_name(name):
    return name.rsplit("::", 1)[-1]

def verify_red(record, junit):
    assert_native(record)
    failures = {short_name(item["name"]): item["details"] for item in junit["failures"]}
    names = [short_name(name) for name in junit["executed_test_names"]]
    if record.get("command_exit_code") != 100 or names and len(names) != len(set(names)):
        raise ValueError("baseline was not one ordinary fresh failing test run")
    if set(names) != set(RED) or set(failures) != set(RED) or junit["passed"] != 0 or junit["skipped"] != 0:
        raise ValueError("baseline did not execute exactly the four expected failing controls")
    for name, expected in RED.items():
        if expected not in failures[name]:
            raise ValueError("baseline failure was not the expected behavioral assertion: " + name)

def verify_green(record, junit, focused):
    assert_native(record)
    names = [short_name(name) for name in junit["executed_test_names"]]
    if record.get("command_exit_code") != 0 or junit["failures"] or any(names.count(name) != 1 for name in REQUIRED):
        raise ValueError("required named native controls did not pass exactly once")
    if focused and (len(names) != len(REQUIRED) or junit["skipped"] != 0 or junit["passed"] != len(REQUIRED)):
        raise ValueError("focused control inventory is not exactly seven fresh passes")

@contextlib.contextmanager
def source(root, sha):
    old_cwd, old_source, old_tested = Path.cwd(), os.environ["SOURCE_SHA"], os.environ["TESTED_SHA"]
    try:
        os.chdir(root)
        os.environ["SOURCE_SHA"] = os.environ["TESTED_SHA"] = sha
        yield
    finally:
        os.chdir(old_cwd)
        os.environ["SOURCE_SHA"], os.environ["TESTED_SHA"] = old_source, old_tested

def test_command(root, directory, selected):
    args = ["--locked", "-p", "codex-hepta-memory", "--retries=0", "--test-threads=4"]
    if selected: args += ["-E", " | ".join("test(=" + name + ")" for name in selected)]
    # Exact suffixes are not full qualified names; use anchored regex suffixes.
    if selected: args[-1] = " | ".join("test(/::" + name + "$/)" for name in selected)
    policy = runpy.run_path(str(root / "scripts/run-nextest.py"), run_name="operations_metadata_policy")
    if not policy["use_scoped_metadata"](args, root / "codex-rs"):
        raise ValueError("scoped metadata policy rejected fixed Memory test command")
    metadata = directory / "cargo-metadata.json"
    with metadata.open("x") as stream:
        subprocess.run(["cargo", "metadata", "--no-deps", "--format-version=1", "--locked", "--manifest-path", str(root / "codex-rs/Cargo.toml")], stdout=stream, check=True, timeout=remaining())
    data = json.loads(metadata.read_text())
    if data["resolve"] is not None or Path(data["workspace_root"]).resolve() != (root / "codex-rs").resolve():
        raise ValueError("metadata workspace/resolve mismatch")
    if not any(p["name"] == "codex-hepta-memory" and p["id"] in data["workspace_members"] for p in data["packages"]):
        raise ValueError("Memory absent from fresh metadata")
    config = directory / "junit.toml"
    config.write_text('[profile.local.junit]\npath = ' + json.dumps(str(directory / "junit.xml")) + '\n')
    return ["just", "test", "--tool-config-file", f"operations-fairness:{config}", "--cargo-metadata", str(metadata), *args]

def run():
    root, evidence = Path.cwd(), Path(os.environ["OPERATIONS_EVIDENCE"])
    before = identity()
    if json.loads((evidence / "source-before.json").read_text()) != before:
        raise ValueError("source changed since pre-setup verification")
    baseline = Path(os.environ["RUNNER_TEMP"]) / "operations-test-baseline"
    git("worktree", "add", "--detach", str(baseline), BASE)
    for path in TEST_PATHS:
        destination = baseline / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / path, destination)
    git("add", "--", *TEST_PATHS, cwd=baseline)
    tree = git("write-tree", cwd=baseline)
    if tree != BASELINE_TREE or set(git("diff", "--cached", "--name-only", BASE, cwd=baseline).splitlines()) != set(TEST_PATHS):
        raise ValueError("instrumented baseline changed unapproved source")
    env = dict(os.environ, GIT_AUTHOR_NAME="dot source diagnostic", GIT_AUTHOR_EMAIL="diagnostic@example.invalid", GIT_COMMITTER_NAME="dot source diagnostic", GIT_COMMITTER_EMAIL="diagnostic@example.invalid")
    sha = git("commit-tree", tree, "-p", BASE, "-m", "Local test-only instrumented baseline", cwd=baseline, env=env)
    git("checkout", "--detach", sha, cwd=baseline)
    save(evidence / "baseline-source.json", {"commit": sha, "tree": tree, "parent": BASE, "test_paths": TEST_PATHS, "scope": "test-only instrumented baseline, not remote source"})
    stages = [{"name": name, "status": "not-run"} for name in ("baseline-red", "candidate-focused", "memory-default", "memory-strict")]
    save(evidence / "stages.json", stages)
    for stage in stages:
        name = stage["name"]
        directory = evidence / name
        directory.mkdir()
        tested_root, tested_sha = (baseline, sha) if name == "baseline-red" else (root, before["commit"])
        try:
            with source(tested_root, tested_sha):
                if name == "memory-strict":
                    command = ["just", "clippy", "--locked", "-p", "codex-hepta-memory", "--all-targets", "--", "-D", "warnings"]
                else:
                    selected = RED if name == "baseline-red" else REQUIRED if name == "candidate-focused" else None
                    command = test_command(tested_root, directory, selected)
                output = directory / "native.json"
                code = recorded(output, command, 0 if name in ("baseline-red", "memory-strict") else len(REQUIRED), 1500 if name == "baseline-red" else 900)
                record = json.loads(output.read_text())
                stage["exit_code"] = code
                if record.get("interrupted_signal") is not None:
                    stage["status"] = "interrupted"
                    save(evidence / "stages.json", stages)
                    return code or 2
                if name == "memory-strict":
                    assert_native(record)
                    if code: raise ValueError("strict lint failed")
                else:
                    junit = xml_record(directory / "junit.xml")
                    save(directory / "junit-summary.json", junit)
                    if name == "baseline-red": verify_red(record, junit)
                    else:
                        if code: raise ValueError("candidate execution wrapper rejected the run")
                        verify_green(record, junit, name == "candidate-focused")
                    stage["passed"], stage["skipped"] = junit["passed"], junit["skipped"]
                stage["status"] = "expected-behavioral-failure" if name == "baseline-red" else "passed"
        except (OSError, ValueError, subprocess.SubprocessError, ET.ParseError) as error:
            stage.update(status="failed-or-incomplete", error=str(error))
        save(evidence / "stages.json", stages)
    after = identity()
    save(evidence / "source-after.json", after)
    if after != before: raise ValueError("candidate source changed")
    return int(any(s["status"] not in ("passed", "expected-behavioral-failure") for s in stages))

def before_setup():
    evidence = Path(os.environ["OPERATIONS_EVIDENCE"])
    path = evidence / "source-before.json"
    if path.exists(): raise ValueError("pre-setup source receipt already exists")
    save(path, identity())

def after_setup():
    evidence = Path(os.environ["OPERATIONS_EVIDENCE"])
    current = identity()
    if current != json.loads((evidence / "source-before.json").read_text()):
        raise ValueError("source changed since pre-setup verification")
    save(evidence / "source-after.json", current)

def stage_evidence():
    evidence = Path(os.environ["OPERATIONS_EVIDENCE"])
    upload = evidence / "upload"
    upload.mkdir(exist_ok=True)
    total, manifest = 0, []
    for file in sorted(evidence.rglob("*")):
        if file.is_relative_to(upload):
            continue
        if file.is_symlink():
            raise ValueError("symlink evidence is not allowed")
        if not file.is_file() or file.suffix not in (".json", ".xml", ".log", ".toml"):
            continue
        size = file.stat().st_size
        if size > 16 * 1024**2 or total + size > 64 * 1024**2:
            raise ValueError("evidence bound exceeded; never silently omit a receipt")
        total += size
        relative = file.relative_to(evidence)
        dest = upload / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(file, dest)
        manifest.append({"path": str(relative), "bytes": size, "sha256": hashlib.sha256(file.read_bytes()).hexdigest()})
    save(upload / "manifest.json", manifest)

if __name__ == "__main__":
    if sys.argv[1:] == ["run"]: raise SystemExit(run())
    elif sys.argv[1:] == ["before"]: before_setup()
    elif sys.argv[1:] == ["after"]: after_setup()
    elif sys.argv[1:] == ["stage"]: stage_evidence()
    else: raise SystemExit("expected before, run, after or stage")
