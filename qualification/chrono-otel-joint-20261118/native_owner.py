"""Run the frozen otel and UTC codec packages once and retain native originals."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path("/Users/qianqi/work/hepta-chrono-otel-joint-20261118-2e9b")
SOURCE = ROOT / "source"
TARGET = ROOT / "native-target-1"
OUT = ROOT / "native-validation-1"
COMMAND = ["just", "test", "--locked", "--offline", "-p", "codex-otel", "-p",
           "codex-utils-time", "--retries", "0", "--test-threads", "2",
           "--no-tests", "fail", "--success-output", "final", "--failure-output", "final"]


def save(name, value):
    (OUT / name).write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def git(*args):
    return subprocess.check_output(["git", *args], cwd=SOURCE)


def inventory():
    rows = []
    absent = []
    for name in git("ls-files", "-z").split(b"\0"):
        if not name:
            continue
        path = SOURCE / os.fsdecode(name)
        if not path.exists() and not path.is_symlink():
            absent.append(os.fsdecode(name))
            continue
        data = os.fsencode(os.readlink(path)) if path.is_symlink() else path.read_bytes()
        rows.append({"path": os.fsdecode(name), "bytes": len(data),
                     "sha256": digest(data), "mode": path.lstat().st_mode & 0o7777,
                     "symlink": path.is_symlink()})
    value = {"materialized": rows, "absent_sparse_paths": absent}
    return value, digest((json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode())


def main():
    expected = sys.argv[1]
    assert len(expected) == 40
    assert not OUT.exists(), "This original execution namespace already exists."
    OUT.mkdir()
    lock = (ROOT / "native-owner.lock").open("a+b")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert git("rev-parse", "HEAD").decode().strip() == expected
    assert not git("status", "--porcelain", "--untracked-files=all")
    before, before_sha = inventory()
    save("SOURCE_BEFORE.json", before)
    os.environ["PATH"] = str(ROOT / "tool-wrapper") + ":/opt/homebrew/bin:/Users/qianqi/.cargo/bin:" + os.environ["PATH"]
    os.environ["CARGO_TARGET_DIR"] = str(TARGET)
    os.environ["CARGO_BUILD_JOBS"] = "2"
    os.environ["CARGO_INCREMENTAL"] = "0"
    os.environ["CARGO_NET_OFFLINE"] = "true"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["GIT_TERMINAL_PROMPT"] = "0"
    result = {"source_head": expected, "source_tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
              "command": COMMAND, "retries": 0, "timeout_seconds": 7200,
              "source_before_sha256": before_sha, "new_model_calls": 0,
              "runner_backend": "persistent_target_account_pty",
              "timed_out": False, "passed": False, "cost_scopes_nested": True,
              "physical_energy_joules": None, "charges": None}
    save("INTENT.json", result)
    junit = SOURCE / "codex-rs/target/nextest/local/junit.xml"
    if junit.exists():
        shutil.copyfile(junit, OUT / "prior-junit.xml")
        result["prior_junit_sha256"] = digest(junit.read_bytes())
    started_ns = time.time_ns()
    owner_start = time.monotonic()
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    with (OUT / "native.stdout").open("xb") as stdout, (OUT / "native.stderr").open("xb") as stderr:
        child = subprocess.Popen(COMMAND, cwd=SOURCE / "codex-rs", stdout=stdout, stderr=stderr)
        result["native_child_pid"] = child.pid
        save("RUNNING.json", result)
        try:
            result["wait_returncode"] = child.wait(timeout=7200)
        except subprocess.TimeoutExpired:
            result["timed_out"] = True
            result["native_child_still_owned"] = True
            result["note"] = "Deadline exceeded; original Rust process is not killed or rerun."
            save("RESULT.json", result)
            print(json.dumps(result), flush=True)
            return 1
    result["exit_source"] = "subprocess.Popen.wait"
    result["command_wall_seconds"] = time.monotonic() - owner_start
    after, after_sha = inventory()
    save("SOURCE_AFTER.json", after)
    result["source_after_sha256"] = after_sha
    result["dirty"] = git("status", "--porcelain", "--untracked-files=all").decode()
    if junit.exists() and junit.stat().st_mtime_ns >= started_ns:
        raw = junit.read_bytes()
        (OUT / "original-junit.xml").write_bytes(raw)
        root = ET.fromstring(raw)
        cases = []
        suites = {}
        for suite in root.iter("testsuite"):
            suite_cases = list(suite.findall("testcase"))
            suites[suite.attrib.get("name", "")] = len(suite_cases)
            for case in suite_cases:
                cases.append({"suite": suite.attrib.get("name", ""), "attributes": case.attrib,
                              "failed": case.find("failure") is not None,
                              "error": case.find("error") is not None,
                              "skipped": case.find("skipped") is not None})
        save("CASES.json", cases)
        result.update(junit_sha256=digest(raw), junit_original_path=str(junit),
                      junit_attributes=root.attrib, testcases=len(cases),
                      unique_cases=len({(c["suite"], c["attributes"].get("name")) for c in cases}),
                      failed=sum(c["failed"] for c in cases), errors=sum(c["error"] for c in cases),
                      skipped=sum(c["skipped"] for c in cases), suite_counts=suites)
        codec_cases = sum(v for k, v in suites.items() if "codex-utils-time" in k)
        otel_cases = sum(v for k, v in suites.items() if "codex-otel" in k)
        result["passed"] = (result["wait_returncode"] == 0 and before == after
                            and not result["dirty"] and len(cases) == result["unique_cases"]
                            and result["failed"] == result["errors"] == result["skipped"] == 0
                            and codec_cases == 10 and otel_cases > 0)
    else:
        result["junit_missing_or_stale"] = True
    end_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    result.update(owner_wall_seconds=time.monotonic() - owner_start,
                  child_user_cpu_seconds=end_usage.ru_utime - usage.ru_utime,
                  child_system_cpu_seconds=end_usage.ru_stime - usage.ru_stime,
                  max_child_rss_bytes=end_usage.ru_maxrss)
    save("RESULT.json", result)
    print(json.dumps(result), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
