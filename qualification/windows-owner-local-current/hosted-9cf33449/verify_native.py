#!/usr/bin/env python3
"""Read-only verification of immutable scoped owner-local hosted artifacts."""
import argparse
import ast
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git_inputs(repo, commit, names):
    requests = [f"{commit}:{name}" for name in names]
    result = subprocess.run(
        ["git", "--no-replace-objects", "cat-file", "--batch"], cwd=repo,
        input=("\n".join(requests) + "\n").encode(), capture_output=True, check=True,
    ).stdout
    position = 0
    actual = {}
    for name in names:
        end = result.index(b"\n", position)
        header = result[position:end].split()
        assert len(header) == 3 and header[1] == b"blob", (name, header)
        size = int(header[2])
        raw = result[end + 1:end + 1 + size]
        assert len(raw) == size and result[end + 1 + size:end + 2 + size] == b"\n"
        actual[name] = sha(raw)
        position = end + 2 + size
    assert position == len(result)
    return actual


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument("--archive-bytes", type=int, required=True)
    args = parser.parse_args()
    archive = args.artifact / "artifact.zip"
    raw = archive.read_bytes()
    assert len(raw) == args.archive_bytes and sha(raw) == args.archive_sha256
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert len(z.namelist()) == len(set(z.namelist()))
        files = {name: z.read(name) for name in z.namelist() if not name.endswith("/")}
    receipt = json.loads(files["receipt.json"])
    assert receipt["source_commit"] == args.commit and receipt["status"] == "passed"
    assert receipt["mode"] == "native" and receipt["source_unchanged"] is True
    names = sorted(receipt["source_before"])
    actual = git_inputs(args.repo, args.commit, names)
    assert actual == receipt["source_before"] == receipt["source_after"]
    assert files["rustc-version.log"].startswith(b"rustc 1.96.0 ")
    windows = receipt["platform"].startswith("Windows-")
    if windows:
        assert b"host: x86_64-pc-windows-msvc\n" in files["rustc-version.log"]
    metadata_raw = gzip.decompress(files["metadata.json.gz"])
    assert sha(metadata_raw) == receipt["metadata"]["sha256"]
    metadata = json.loads(metadata_raw)
    assert receipt["metadata"]["exit_code"] == 0
    assert len(metadata["packages"]) == receipt["metadata"]["package_count"] == 1517
    expected = ["codex-uds", "codex-hepta-matrixd", "codex-hepta-fleet", "codex-hepta-automation"]
    harness = subprocess.check_output(
        ["git", "--no-replace-objects", "show", args.commit + ":qualification/windows-owner-local-current/run_qualification.py"],
        cwd=args.repo,
    )
    required_nodes = [node.value for node in ast.parse(harness).body
                      if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == "REQUIRED" for target in node.targets)]
    assert len(required_nodes) == 1
    required = ast.literal_eval(required_nodes[0])
    assert list(receipt["tests"]) == expected
    commands = receipt["commands"]
    assert len({c["name"] for c in commands}) == len(commands)
    command_map = {c["name"]: c for c in commands}
    for command in commands:
        log = files[command["name"] + ".log"]
        assert command["exit_code"] == 0 and sha(log) == command["log_sha256"]
    counts = {}
    for package in expected:
        argv = ["just", "test", "--locked", "-p", package, "--lib", "--no-tests=fail", "--retries", "0", "--success-output=final"]
        if package in {"codex-uds", "codex-hepta-matrixd"}:
            argv += ["--test-threads", "1"]
        assert command_map[package]["argv"] == argv
        xml_raw = files[package + ".junit.xml"]
        tree = ET.fromstring(xml_raw)
        cases = tree.findall(".//testcase")
        case_names = [case.get("name") for case in cases]
        assert cases and len(cases) == len(set(case_names)) == int(tree.get("tests", "-1"))
        assert not any(child.tag in {"failure", "error", "skipped"} for case in cases for child in case)
        for suite in tree.iter("testsuite"):
            assert all(int(suite.get(field, "0")) == 0 for field in ["failures", "errors", "skipped"])
        reported = receipt["tests"][package]
        assert len(cases) == reported["count"] and sorted(case_names) == reported["names"]
        assert required[package] <= set(case_names)
        assert not reported["failed_or_skipped"] and reported["required_present"] is True
        assert sha(xml_raw) == reported["sha256"]
        log = re.sub(rb"\x1b\[[0-9;]*m", b"", files[package + ".log"]).decode("utf-8", errors="replace")
        assert "skipping test:" not in log.lower()
        summary = re.findall(r"Summary[^\n]*?\b(\d+) tests run: (\d+) passed, (\d+) skipped", log)
        assert len(summary) == 1 and tuple(map(int, summary[0])) == (len(cases), len(cases), 0), (package, summary)
        counts[package] = len(cases)
    assert counts["codex-uds"] == (14 if windows else 10)
    assert command_map["scoped-clippy-fix"]["argv"] == ["just", "fix", "--locked", "-p", "codex-uds", "-p", "codex-hepta-matrixd", "-p", "codex-hepta-automation", "--no-deps"]
    assert files["initial-tracked-source.log"] == files["final-tracked-source.log"] == b""
    dbus_verified = None
    if receipt["platform"].startswith("Linux-"):
        dbus = json.loads(files["pinned-dbus-receipt.json"])
        assert dbus["status"] == "PASS" and len(dbus["commands"]) == 52
        assert all(command["exit"] == 0 for command in dbus["commands"])
        assert dbus["archive"]["bytes"] == 1115644
        assert dbus["archive"]["sha256"] == "0ba2a1a4b16afe7bceb2c07e9ce99a8c2c3508e5dec290dbb643384bd6beb7e2"
        assert len(dbus["inputs"]) == 7
        assert all(actual["third_party/dbus/" + name] == digest for name, digest in dbus["inputs"].items())
        assert dbus["commands"][-1]["stdout"] == "PASS: D-Bus 1.16.2, wire ABI, pidfd identity, non-pidfd rejection, peer UID/PID, high-fd closure\n"
        dbus_verified = {"commands_exit_zero": 52, "immutable_git_inputs": 7,
                         "native_identity_exit": 0, "receipt_sha256": sha(files["pinned-dbus-receipt.json"])}
    result = {
        "status": "verified", "source_commit": args.commit, "platform": receipt["platform"],
        "artifact_bytes": len(raw), "artifact_sha256": sha(raw), "zip_crc": "passed",
        "immutable_git_inputs": len(names), "source_before_and_after_match_exact_git_bytes": True,
        "rustc": files["rustc-version.log"].decode().splitlines()[0],
        "metadata_packages": len(metadata["packages"]), "library_tests": counts,
        "native_test_executions_passed": sum(counts.values()), "failed": 0, "skipped": 0,
        "original_commands_verified": len(commands), "scoped_clippy_exit": 0,
        "receipt_sha256": sha(files["receipt.json"]),
        "pinned_dbus": dbus_verified,
        "outputs": {name: {"bytes": len(data), "sha256": sha(data)} for name, data in sorted(files.items())},
        "scope": "Exact scoped native owner-local consumers; full CI, private-state foundation, and other platforms are separate gates.",
    }
    (args.artifact / "VERIFIED.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "outputs"}, indent=2))


if __name__ == "__main__":
    main()
