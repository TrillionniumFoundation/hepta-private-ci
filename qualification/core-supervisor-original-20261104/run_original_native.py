#!/usr/bin/env python3
"""Execute two original Core regressions and the complete restart recovery target."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT / "codex-rs"
CORE_CASES = {
    "tools::handlers::multi_agents::tests::multi_agent_v2_wait_agent_uses_configured_default_timeout",
    "environment_selection::tests::blocking_snapshot_waits_for_starting_environment",
}
RESTART_CASES = {"restart_budget_survives_repeated_supervisord_recovery"}
SCOPES = [
    {"name": "core-original-two", "package": "codex-core", "kind": "lib",
     "target_args": ["--lib"], "required": CORE_CASES, "complete_target": False},
    {"name": "supervisor-restart-original", "package": "codex-hepta-supervisor", "kind": "test",
     "target_args": ["--test", "restart_budget_recovery"], "required": RESTART_CASES,
     "complete_target": True},
]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def source_snapshot(verify_git=False):
    entries = subprocess.check_output(
        ["git", "--no-replace-objects", "ls-files", "--stage", "-z"], cwd=ROOT
    ).decode().split("\0")
    result = {}
    for entry in entries:
        if not entry:
            continue
        metadata, name = entry.split("\t", 1)
        mode, expected_blob, stage = metadata.split()
        require(stage == "0" and mode in {"100644", "100755", "120000"},
                "unmerged or unsupported tracked input: " + name)
        path = ROOT / name
        if not path.exists() and not path.is_symlink():
            require(not verify_git, "missing tracked input: " + name)
            result[name] = {"mode": mode, "expected_git_blob": expected_blob, "missing": True}
            continue
        raw = os.fsencode(os.readlink(path)) if path.is_symlink() else path.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if verify_git:
            require(blob == expected_blob, "checkout bytes differ from Git: " + name)
        result[name] = {"mode": mode, "expected_git_blob": expected_blob,
                        "git_blob": blob, "bytes": len(raw), "sha256": digest(raw)}
    return dict(sorted(result.items()))


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def inventory(raw, scope):
    data = json.loads(raw, object_pairs_hook=unique_object)
    suites = data["rust-suites"]
    require(len(suites) == 1, "expected exactly one compiled test binary")
    suite_id, suite = next(iter(suites.items()))
    require(suite["package-name"] == scope["package"] and suite["kind"] == scope["kind"]
            and suite["status"] == "listed", "wrong or unlisted binary")
    cases = suite["testcases"]
    require(cases and data["test-count"] == len(cases), "empty or inconsistent inventory")
    ignored = set()
    for name, case in cases.items():
        require(type(case["ignored"]) is bool and case.get("kind") in (None, "test"),
                "unexpected test kind or ignored marker")
        wanted = {"status": "mismatch", "reason": "ignored"} if case["ignored"] else {"status": "matches"}
        require(case["filter-match"] == wanted, "unexpected compiled inventory filter: " + name)
        if case["ignored"]:
            ignored.add(name)
    runnable = set(cases) - ignored
    required = scope["required"]
    require(required <= runnable, "required original case absent or ignored")
    if scope["complete_target"]:
        require(runnable == required and not ignored, "complete original target case set changed")
    return {"suite": suite_id, "binary": suite["binary-path"], "all_cases": sorted(cases),
            "all_runnable_count": len(runnable), "expected": sorted(required),
            "qualification_filtered_cases": sorted(runnable - required),
            "original_ignored": sorted(ignored), "complete_target": scope["complete_target"]}


def validate_junit(raw, listed):
    root = ET.fromstring(raw)
    suites = list(root.iter("testsuite"))
    require(suites, "missing JUnit suite")
    bad = {"failure", "error", "skipped", "rerunFailure", "rerunError", "flakyFailure", "flakyError"}
    require(not any(element.tag in bad for element in root.iter()), "failed, skipped or retried case")
    cases = list(root.iter("testcase"))
    names = [case.get("name") for case in cases]
    require(len(names) == len(set(names)) and set(names) == set(listed["expected"]),
            "JUnit does not cover every nonignored library case exactly once")
    require(sum(int(s.get("tests", "-1")) for s in suites) == len(names),
            "JUnit test counters do not match executed cases")
    for suite in suites:
        require(all(int(suite.get(key, "0")) == 0 for key in ("failures", "errors", "skipped")),
                "nonzero JUnit failure or skip counter")
    return {"passed": len(names), "failed": 0, "errors": 0, "skipped": 0, "retried": 0,
            "executed": names, "original_ignored": listed["original_ignored"]}



def junit_failure_details(raw):
    """Make original failures visible without changing their acceptance."""
    root = ET.fromstring(raw)
    bad = {"failure", "error", "skipped", "rerunFailure", "rerunError", "flakyFailure", "flakyError"}
    failures = []
    remaining = 65536
    for case in root.iter("testcase"):
        if not any(child.tag in bad for child in case):
            continue
        details = []
        for child in case:
            if child.tag in bad or child.tag in {"system-out", "system-err"}:
                text = (child.text or "")[:min(8192, remaining)]
                remaining -= len(text)
                details.append({"kind": child.tag, "attributes": child.attrib, "text": text})
        failures.append({"name": case.get("name"), "details": details})
    return failures


def main():
    require(__debug__, "optimized Python is not accepted")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    receipt = {"schema": 1, "status": "failed", "run_id": os.environ["GITHUB_RUN_ID"],
               "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"], "host": platform.platform(),
               "machine": platform.machine(), "commands": [], "scopes": {}, "problems": [],
               "scope": "Exactly two original Core cases and the complete one-case Supervisor restart recovery target; not full Core or product acceptance."}
    before = None
    report = WORKSPACE / "target/nextest/local/junit.xml"

    def run(name, argv, cwd=ROOT):
        started = time.monotonic()
        stdout, stderr = output / (name + ".stdout"), output / (name + ".stderr")
        with stdout.open("wb") as out, stderr.open("wb") as err:
            process = subprocess.run(argv, cwd=cwd, stdout=out, stderr=err)
        row = {"name": name, "argv": argv, "exit_code": process.returncode,
               "seconds": time.monotonic() - started}
        receipt["commands"].append(row)
        print(json.dumps(row), flush=True)
        if process.returncode:
            print(stdout.read_text(encoding="utf-8", errors="replace")[-20000:], flush=True)
            print(stderr.read_text(encoding="utf-8", errors="replace")[-20000:], flush=True)
        return process.returncode

    try:
        require(run("source-commit", ["git", "--no-replace-objects", "rev-parse", "HEAD"]) == 0,
                "read source commit failed")
        head = (output / "source-commit.stdout").read_text().strip()
        receipt["source_commit"] = head
        require(head == os.environ["GITHUB_SHA"], "checkout is not dispatched source")
        require(run("source-tree", ["git", "--no-replace-objects", "rev-parse", "HEAD^{tree}"]) == 0,
                "read source tree failed")
        receipt["source_tree"] = (output / "source-tree.stdout").read_text().strip()
        require(run("initial-clean-source", ["git", "--no-replace-objects", "diff", "--exit-code", "HEAD", "--"]) == 0,
                "dirty initial source")
        before = source_snapshot(verify_git=True)
        (output / "source-before.json").write_text(json.dumps(before, indent=2) + "\n", encoding="utf-8")
        require(run("rustc-version", ["rustc", "-Vv"]) == 0, "rustc version failed")
        require((output / "rustc-version.stdout").read_text().startswith("rustc 1.96.0 "),
                "not the committed Rust compiler")
        require(run("nextest-version", ["cargo", "nextest", "--version"], WORKSPACE) == 0,
                "nextest version failed")
        require((output / "nextest-version.stdout").read_text().startswith("cargo-nextest 0.9.151 "),
                "unexpected nextest version")
        require(run("original-formatter", ["just", "fmt", "--base",
                    "fcedede3f945bc75cec6dc7730c7cf0ef9056eda"]) == 0, "original formatter failed")
        require(run("source-clean-after-formatter", ["git", "--no-replace-objects", "diff",
                    "--exit-code", "HEAD", "--"]) == 0, "formatter changed source")
        for scope in SCOPES:
            name = scope["name"]
            item = {"status": "failed"}
            receipt["scopes"][name] = item
            try:
                common = ["--locked", "-p", scope["package"], *scope["target_args"]]
                require(run(name + "-inventory", ["cargo", "nextest", "list", *common,
                            "--message-format=json"], WORKSPACE) == 0, "compiled inventory failed")
                listed = inventory((output / (name + "-inventory.stdout")).read_bytes(), scope)
                item["inventory"] = listed
                binary = Path(listed["binary"])
                item["binary_sha256_before"] = digest(binary.read_bytes())
                if report.exists():
                    report.unlink()
                require(not report.exists(), "stale original JUnit")
                command = ["just", "test", *common, "--no-tests=fail", "--retries", "0",
                           "--success-output=final"]
                if not scope["complete_target"]:
                    command.extend(["-E", " | ".join("test(=" + case + ")" for case in sorted(scope["required"]))])
                code = run(name + "-original-tests", command)
                if report.is_file():
                    shutil.copyfile(report, output / (name + "-junit.xml"))
                    details = junit_failure_details(report.read_bytes())
                    if details:
                        print("ORIGINAL_JUNIT_FAILURES=" + json.dumps({"scope": name, "cases": details}), flush=True)
                require(code == 0, "original tests failed")
                require(report.is_file(), "no fresh original JUnit")
                logs = b"".join((output / (name + "-original-tests." + suffix)).read_bytes()
                                for suffix in ("stdout", "stderr"))
                require(b"skipping test:" not in logs.lower(), "original test reported an early-return skip")
                item["result"] = validate_junit(report.read_bytes(), listed)
                item["binary_sha256_after"] = digest(binary.read_bytes())
                require(item["binary_sha256_after"] == item["binary_sha256_before"],
                        "compiled test binary changed")
                item["status"] = "passed"
            except Exception as error:
                item["error"] = str(error)
                receipt["problems"].append(name + ": " + str(error))
        if run("original-scoped-clippy", ["just", "fix", "--locked", "-p", "codex-core",
                "-p", "codex-hepta-supervisor", "--no-deps"]):
            receipt["problems"].append("original scoped Clippy failed")
        if run("final-clean-source", ["git", "--no-replace-objects", "diff", "--exit-code", "HEAD", "--"]):
            receipt["problems"].append("qualification changed tracked source")
        require(source_snapshot() == before, "source bytes changed")
        require(not receipt["problems"], "; ".join(receipt["problems"]))
        receipt["status"] = "passed"
    finally:
        after = source_snapshot()
        (output / "source-after.json").write_text(json.dumps(after, indent=2) + "\n", encoding="utf-8")
        receipt["source_inputs_unchanged"] = before is not None and before == after
        receipt["outputs"] = {p.name: {"bytes": p.stat().st_size, "sha256": digest(p.read_bytes())}
                              for p in sorted(output.iterdir()) if p.is_file() and p.name != "receipt.json"}
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print("ORIGINAL_FOLLOWUPS_RESULT=" + json.dumps({
            key: value for key, value in receipt.items() if key != "outputs"
        }), flush=True)


if __name__ == "__main__":
    main()
