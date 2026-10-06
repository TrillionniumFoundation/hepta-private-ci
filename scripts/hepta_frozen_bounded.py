"""Branch-only exact-source diagnostics. Failures are evidence, never waived."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

TREE = "ba49d9ed32e2c1e628c715d419f6d926d727b53a"
BASE = "69d951e0577e5d6ba537775252896cd1ed028fae"
BRANCH = "refs/heads/dot/frozen-bounded-qualification-20261006"
ADDITIONS = (".github/workflows/frozen-bounded-qualification.yml", "scripts/hepta_frozen_bounded.py")
LIMIT = 16 * 1024**2
SUPERVISOR_REQUIRED_TESTS = (
    "robrix_control_v2_generated_projection_and_cross_parser_corpus",
    "writer_reproduces_the_tracked_artifact_set_byte_for_byte",
    *["fixture_backing_tests::" + name for name in (
        "regular_backing_passes", "symlink_delivery_passes", "missing_resource_rejected_even_when_backing_exists",
        "partial_declaration_rejected", "different_parent_rejected", "extra_file_rejected", "directory_entry_rejected",
        "backing_symlink_entry_rejected", "renamed_backing_rejected", "nonregular_resource_rejected",
    )],
)
HELPER_MANIFEST_LABEL = "//codex-rs/windows-sandbox-rs:windows-sandbox-rs-helper_manifest-test"
HELPER_MANIFEST_TEST = "setup_helper_embeds_as_invoker_manifest"
SUPERVISOR_LABELS = ("//codex-rs/hepta-supervisor:hepta-supervisor-robrix_control_projection-test",)
LABELS = (
    "//codex-rs/core/tests/common:common-unit-tests",
    "//codex-rs/ext/queue:queue-queue_service-test",
    "//codex-rs/windows-sandbox-rs:windows-sandbox-rs-unit-tests",
    "//codex-rs/sandboxing:sandboxing-unit-tests",
    HELPER_MANIFEST_LABEL,
)

def git(*args, env=None):
    return subprocess.check_output(["git", *args], text=True, env=env).strip()

def save(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def identity():
    if os.environ.get("GITHUB_EVENT_NAME") != "push" or os.environ.get("GITHUB_REF") != BRANCH:
        raise ValueError("Only the single approved source branch push is accepted")
    head = git("rev-parse", "HEAD")
    if head != os.environ["SOURCE_SHA"] or head != os.environ["TESTED_SHA"]:
        raise ValueError("head/source/tested mismatch")
    if os.environ.get("HEPTA_CI_LANE") != "source-head":
        raise ValueError("source-head lane required")
    dirty = git("status", "--porcelain", "--untracked-files=normal")
    if dirty:
        raise ValueError("source is dirty: " + dirty)
    subprocess.run(["git", "merge-base", "--is-ancestor", BASE, head], check=True)
    with tempfile.TemporaryDirectory() as temporary:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(temporary) / "index"))
        subprocess.run(["git", "read-tree", "HEAD"], env=env, check=True)
        subprocess.run(["git", "update-index", "--force-remove", "--", *ADDITIONS], env=env, check=True)
        projected = git("write-tree", env=env)
    if projected != TREE:
        raise ValueError(f"source projection {projected} differs from reviewed {TREE}")
    return {"head": head, "tree": git("rev-parse", "HEAD^{tree}"), "reviewed_tree": projected,
            "base": BASE, "lane": "source-head", "diagnostic_blobs": {p: git("rev-parse", f"HEAD:{p}") for p in ADDITIONS}}

def test(name, packages, selection=(), umask=None):
    command = ["just", "test", "--locked", "--retries", "0"]
    for package in packages:
        command += ["-p", package]
    return {"name": name, "command": command + list(selection), "tests": True, "umask": umask}

def lint(name, packages, no_deps=True):
    command = ["just", "clippy", "--locked", "--all-targets"]
    for package in packages:
        command += ["-p", package]
    return {"name": name, "command": command + (["--no-deps"] if no_deps else []) + ["--", "-D", "warnings"], "tests": False}

def commands(group):
    if group == "client":
        return [test("client-default", ["codex-app-server-client"]), lint("client-strict-selected", ["codex-app-server-client"])]
    if group == "fixture":
        packages = ["codex-exec", "core_test_support", "codex-hepta-memory-extension"]
        result = [test("fixture-exec-memory-default", packages),
                  test("environment-selection", ["codex-core"], ["--lib", "environment_selection"]),
                  test("bedrock-setup", ["codex-app-server"], ["suite::v2::bedrock_setup"]),
                  test("bedrock-broad", ["codex-app-server"], ["bedrock"]),
                  test("thread-inject", ["codex-app-server"], ["suite::v2::thread_inject_items"])]
        result += [test("private-home-" + mask, ["core_test_support"], ["exec_fixture_home_is_private"], int(mask, 8)) for mask in ("000", "022", "077")]
        return result + [lint("affected-strict-selected", packages + ["codex-core", "codex-app-server"])]
    if group == "lifecycle":
        packages = ["codex-hepta-control-plane", "codex-hepta-supervisor", "codex-hepta-intelligence-eval", "codex-hepta-agent-protocol"]
        return [test("lifecycle-default", packages), lint("control-supervisor-strict-dependencies", packages[:2], False),
                {"name": "owned-development-docs", "command": [sys.executable, "scripts/hepta-docs.py", "verify", "--profile", "development"], "tests": False}]
    raise ValueError("unknown Linux group")

def xml_record(path):
    data = path.read_bytes()
    if len(data) > LIMIT:
        raise ValueError("XML exceeds evidence bound")
    root = ET.fromstring(data)
    cases = list(root.iter("testcase"))
    return {"sha256": hashlib.sha256(data).hexdigest(), "root": dict(root.attrib),
            "testcases": len(cases), "executed_test_names": [case.get("name", "") for case in cases if not any(c.tag == "skipped" for c in case)], "passed": sum(not any(c.tag in ("failure", "error", "skipped") for c in case) for case in cases),
            "failures": [{"name": case.get("name"), "classname": case.get("classname"), "details": ET.tostring(case, encoding="unicode")} for case in cases if any(c.tag in ("failure", "error") for c in case)],
            "skipped": sum(any(c.tag == "skipped" for c in case) for case in cases)}

def remaining():
    seconds = int(float(os.environ["BOUNDED_DEADLINE"]) - time.time())
    if seconds < 30:
        raise ValueError("group budget exhausted; remaining stages are NOT RUN")
    return seconds

def recorded_run(output, command, *, minimum_tests, timeout_seconds):
    import hepta_ci_exec
    cancellation = hepta_ci_exec.CommandCancellation()
    previous = {}
    try:
        for number in (signal.SIGINT, signal.SIGTERM):
            previous[number] = signal.signal(number, cancellation.request)
        return hepta_ci_exec.run(output, command, minimum_tests=minimum_tests,
                                 timeout_seconds=timeout_seconds, cancellation=cancellation)
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)

def linux(group, directory):
    records = [{**item, "status": "not-run"} for item in commands(group)]
    failure = False
    for record in records:
        item = record
        name = item["name"]
        save(directory / "stages.json", records)
        try:
            budget = remaining()
            report = Path(os.environ["CARGO_TARGET_DIR"]) / "nextest/local/junit.xml"
            if item["tests"]:
                report.unlink(missing_ok=True)  # Only stale evidence, never a compiled artifact.
            mask = item.get("umask")
            oldmask = os.umask(mask) if mask is not None else None
            try:
                code = recorded_run(directory / (name + ".json"), item["command"], minimum_tests=int(item["tests"]), timeout_seconds=budget)
            finally:
                if oldmask is not None:
                    os.umask(oldmask)
            record["exit_code"] = code
            native = json.loads((directory / (name + ".json")).read_text())
            if native.get("interrupted_signal") is not None:
                record.update(status="interrupted", interrupted_signal=native["interrupted_signal"])
                save(directory / "stages.json", records)
                return code or 2
            record["status"] = "failed" if code else "passed"
            failure |= bool(code)
            if item["tests"]:
                record["junit"] = xml_record(report)
                shutil.copyfile(report, directory / (name + ".junit.xml"))
                if name == "lifecycle-default":
                    observed = record["junit"]["executed_test_names"]
                    record["required_supervisor_tests"] = {name: any(item == name or item.endswith("::" + name) for item in observed) for name in SUPERVISOR_REQUIRED_TESTS}
                    if not all(record["required_supervisor_tests"].values()):
                        raise ValueError("full default supervisor run omitted required integration controls")
                if record["junit"]["failures"] or not record["junit"]["testcases"]:
                    record["status"] = "failed"
                    failure = True
        except (OSError, ValueError, subprocess.SubprocessError, ET.ParseError) as error:
            record["error"] = str(error)
            record["status"] = "incomplete"
            failure = True
        save(directory / "stages.json", records)
    return int(failure)

def windows(directory):
    if os.name != "nt":
        raise ValueError("native Windows host required")
    remaining()
    bash = Path(os.environ["HEPTA_BAZEL_BASH"])
    if bash.name.lower() == "bash":
        bash = bash.with_name("bash.exe")
    if not bash.is_absolute() or not bash.is_file() or bash.name.lower() != "bash.exe":
        raise ValueError("absolute native Git Bash required")
    command = [str(bash), ".github/scripts/run-bazel-ci.sh", "--print-failed-action-summary", "--print-failed-test-logs", "--windows-msvc-host-platform", "--remote-download-toplevel", "--",
               "test", "--platforms=//:windows_x86_64_msvc", "--nocache_test_results", "--remote_upload_local_results=false", "--disk_cache=", "--runs_per_test=1", "--flaky_test_attempts=1", "--keep_going", "--jobs=2", "--test_tag_filters=-argument-comment-lint", "--test_verbose_timeout_warnings", "--test_output=all", "--lockfile_mode=error",
               "--build_metadata=COMMIT_SHA=" + os.environ["TESTED_SHA"], "--build_event_json_file=" + (directory / "tests.bep.jsonl").as_posix(), "--", *LABELS]
    record = {"command": command, "status": "running", "timeout_owner": "Actions remaining group-budget step", "targets": {}}
    save(directory / "windows.json", record)
    kept = 0
    truncated = False
    with (directory / "command.log").open("xb") as log, subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
        while chunk := os.read(process.stdout.fileno(), 65536):
            saved = chunk[:max(0, 64 * 1024**2 - kept)]
            log.write(saved)
            log.flush()
            kept += len(saved)
            truncated |= len(saved) != len(chunk)
            sys.stdout.buffer.write(saved)
            sys.stdout.buffer.flush()
        code = process.wait()
    record.update(exit_code=code, log_truncated=truncated)
    save(directory / "windows.json", record)
    return int(bool(code or truncated))

def supervisor_bazel(directory):
    if sys.platform != "linux":
        raise ValueError("native Linux Bazel job required")
    command = [sys.executable, ".github/scripts/run_bazel_with_buildbuddy.py", "--batch",
               "--output_base=" + os.environ["BAZEL_OUTPUT_BASE"], "test", "--config=ci-linux",
               "--disk_cache=", "--remote_upload_local_results=false", "--remote_download_outputs=toplevel", "--nocache_test_results",
               "--runs_per_test=1", "--flaky_test_attempts=1", "--jobs=2", "--keep_going",
               "--test_tag_filters=-argument-comment-lint", "--test_verbose_timeout_warnings", "--test_output=all",
               "--lockfile_mode=error", "--build_metadata=COMMIT_SHA=" + os.environ["TESTED_SHA"],
               "--build_event_json_file=" + str(directory / "tests.bep.jsonl"), "--", *SUPERVISOR_LABELS]
    record = {"command": command, "status": "running", "targets": {}}
    save(directory / "supervisor-bazel.json", record)
    code = recorded_run(directory / "native.json", command, minimum_tests=1, timeout_seconds=remaining())
    native = json.loads((directory / "native.json").read_text())
    record.update(exit_code=code, log_truncated=native.get("output_limit_exceeded", True))
    save(directory / "supervisor-bazel.json", record)
    return code

def collect_bazel(directory, group="windows"):
    labels = LABELS if group == "windows" else SUPERVISOR_LABELS
    receipt = directory / (group + ".json")
    record = json.loads(receipt.read_text())
    failed = bool(record.get("exit_code", 2) or record.get("log_truncated", True))
    try:
        bep = directory / "tests.bep.jsonl"
        if bep.stat().st_size > 32 * 1024**2:
            raise ValueError("BEP exceeds bounded evidence reader")
        for line in bep.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            label = event.get("id", {}).get("testSummary", {}).get("label")
            if label in labels:
                if label in record["targets"]:
                    raise ValueError("duplicate target summary")
                summary = event["testSummary"]
                record["targets"][label] = {"summary": summary}
                failed |= summary.get("overallStatus") != "PASSED" or summary.get("totalRunCount") != 1 or summary.get("totalNumCached", 0) != 0
        failed |= set(record["targets"]) != set(labels)
    except (OSError, ValueError) as error:
        record["bep_error"] = str(error)
        failed = True
    # Every selected target is examined even when another fails or is missing.
    base = Path(os.environ["BAZEL_OUTPUT_BASE"]).resolve()
    for label in labels:
        target = record["targets"].setdefault(label, {})
        relative = label[2:].replace(":", "/")
        dest = directory / label.split(":")[-1]
        dest.mkdir()
        try:
            configurations = list((base / "execroot/_main/bazel-out").iterdir())
            if len(configurations) > 32:
                raise ValueError("too many Bazel output configurations")
            matches = [path / "testlogs" / relative for path in configurations if (path / "testlogs" / relative / "test.xml").is_file()]
            if len(matches) != 1:
                raise ValueError("expected one exact selected-target log directory")
            for name in ("test.log", "test.xml"):
                source = matches[0] / name
                if not source.resolve().is_relative_to(base) or not source.is_file() or source.stat().st_size > LIMIT:
                    raise ValueError("missing, unsafe or oversized target evidence: " + name)
                shutil.copyfile(source, dest / name)
            target["xml"] = xml_record(dest / "test.xml")
            log = (dest / "test.log").read_text(encoding="utf-8", errors="replace")
            target["libtest_summaries"] = re.findall(r"test result: (?:ok|FAILED)\. [^\n]+", log)
            target["libtest_counts"] = [{"passed": int(a), "failed": int(b), "ignored": int(c)} for a, b, c in re.findall(r"test result: (?:ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored;", log)]
            if label == HELPER_MANIFEST_LABEL and not re.search(r"^test " + re.escape(HELPER_MANIFEST_TEST) + r" \.\.\. (?:ok|FAILED)$", log, re.M):
                raise ValueError("native helper manifest control was not observed executing")
            if group == "supervisor-bazel":
                target["required_supervisor_tests"] = {name: bool(re.search(r"^test " + re.escape(name) + r" \.\.\. (?:ok|FAILED)$", log, re.M)) for name in SUPERVISOR_REQUIRED_TESTS}
                if not all(target["required_supervisor_tests"].values()):
                    raise ValueError("Bazel omitted one or more of the twelve Supervisor controls")
            target["failed_test_names"] = re.findall(r"^test (.*?) \.\.\. FAILED$", log, re.M)
            if not target["libtest_counts"] or any(item["failed"] for item in target["libtest_counts"]) or not sum(item["passed"] + item["failed"] for item in target["libtest_counts"]) or target["xml"]["failures"]:
                failed = True
        except (OSError, ValueError, ET.ParseError) as error:
            target["error"] = str(error)
            failed = True
    record["status"] = "failed" if failed else "passed"
    save(receipt, record)
    return int(failed)

def stage(directory):
    upload = directory / "upload"
    upload.mkdir(exist_ok=True)
    manifest = {}
    total = 0
    for source in sorted(directory.rglob("*")):
        if upload in source.parents or not source.is_file():
            continue
        relative = source.relative_to(directory)
        limit = 64 * 1024**2 if source.suffix == ".log" else 32 * 1024**2 if source.name == "tests.bep.jsonl" else LIMIT
        size = source.stat().st_size
        if source.is_symlink() or not source.resolve().is_relative_to(directory.resolve()) or size > limit or total + size > 256 * 1024**2:
            manifest[str(relative)] = {"retained": False, "reason": "unsafe or evidence bound exceeded", "bytes": size}
            continue
        dest = upload / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
        total += size
        manifest[str(relative)] = {"retained": True, "bytes": size, "sha256": hashlib.sha256(dest.read_bytes()).hexdigest()}
    save(upload / "manifest.json", manifest)
    if not manifest or any(not item["retained"] for item in manifest.values()):
        raise ValueError("incomplete bounded evidence; see manifest")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("before", "after", "run", "collect-bazel", "stage", "budget"))
    parser.add_argument("group", choices=("client", "fixture", "lifecycle", "windows", "supervisor-bazel"))
    args = parser.parse_args()
    directory = Path(os.environ["BOUNDED_EVIDENCE"]).resolve()
    root = Path(git("rev-parse", "--show-toplevel")).resolve()
    if not directory.is_absolute() or directory.is_relative_to(root):
        raise ValueError("evidence must be outside source")
    directory.mkdir(parents=True, exist_ok=True)
    if args.phase == "collect-bazel":
        return collect_bazel(directory, args.group)
    if args.phase == "stage":
        stage(directory)
    elif args.phase in ("before", "after"):
        try:
            record = identity()
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            save(directory / ("source-" + args.phase + ".error.json"), {"error": str(error), "head": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}"), "status": git("status", "--porcelain", "--untracked-files=normal")})
            raise
        save(directory / ("source-" + args.phase + ".json"), record)
        if args.phase == "before":
            save(directory / "target-plan.json", {"group": args.group, "targets": list(LABELS) if args.group == "windows" else list(SUPERVISOR_LABELS) if args.group == "supervisor-bazel" else commands(args.group), "source": record})
        if args.phase == "after" and record != json.loads((directory / "source-before.json").read_text()):
            raise ValueError("source before/after mismatch")
    elif args.phase == "budget":
        with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
            stream.write(f"minutes={max(1, remaining() // 60)}\n")
    else:
        identity()
        return windows(directory) if args.group == "windows" else supervisor_bazel(directory) if args.group == "supervisor-bazel" else linux(args.group, directory)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
