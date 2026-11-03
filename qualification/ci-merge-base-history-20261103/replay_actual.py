#!/usr/bin/env python3
"""Replay the exact failed V8 range in a new, isolated shallow Git directory."""

import argparse
import hashlib
import importlib.util
import json
import subprocess
import time
from pathlib import Path


BASE = "adaeb1854c9b2abe3f8c65a4407344d07e1c7589"
HEAD = "1ef3216ffb86271d87e6aea049ce7ca7f2b76809"
ORIGIN = "https://github.com/TrillionniumFoundation/hepta-private-ci"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path):
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repository = args.repository.resolve()
    root = Path(__file__).resolve().parent
    oracle = json.loads((root / "remote-comparison-oracle.json").read_text())
    if (oracle["base"], oracle["head"]) != (BASE, HEAD):
        raise ValueError("wrong exact comparison oracle")
    args.workdir.mkdir(parents=True, exist_ok=False)
    helper_path = repository / "scripts/hepta_ci_history.py"
    original_path = root / "original_hepta_ci_history.py"
    detector_path = repository / ".github/scripts/v8_canary_changes.py"
    before = {str(p.relative_to(repository)): digest(p)
              for p in (helper_path, original_path, detector_path)}
    original = load("original_history", original_path)
    candidate = load("candidate_history", helper_path)
    detector = load("original_v8_detector", detector_path)
    commands = []

    def command(*arguments, expected=0):
        argv = ["git", "--no-replace-objects", *arguments]
        start = time.monotonic()
        process = subprocess.run(argv, cwd=args.workdir, capture_output=True, text=True)
        row = {"argv": argv, "exit_code": process.returncode,
               "elapsed_seconds": time.monotonic() - start,
               "stdout": process.stdout, "stderr": process.stderr}
        commands.append(row)
        if process.returncode != expected:
            raise RuntimeError(f"unexpected Git result: {row}")
        return process

    command("init", "-q")
    command("remote", "add", "origin", ORIGIN)
    command("fetch", "--no-tags", "--depth=1", "--filter=blob:none", "origin", HEAD)
    original.prepare(args.workdir, [BASE, HEAD])
    command("rev-parse", "--is-shallow-repository")
    negative = command("diff", "--name-only", "--no-renames", f"{BASE}...{HEAD}", expected=128)
    if "no merge base" not in negative.stderr:
        raise RuntimeError("the original failure was not reproduced")
    original_git = candidate.git
    fetches = []

    def record_git(directory, *arguments, **kwargs):
        start = time.monotonic()
        result = original_git(directory, *arguments, **kwargs)
        if arguments[0] == "fetch":
            fetches.append({"arguments": list(arguments),
                            "elapsed_seconds": time.monotonic() - start})
        return result

    candidate.git = record_git
    candidate.prepare(args.workdir, [BASE, HEAD], merge_base=True)
    actual_base = command("merge-base", BASE, HEAD).stdout.strip()
    actual_files = command("diff", "--name-only", "--no-renames", f"{BASE}...{HEAD}").stdout.splitlines()
    if actual_base != oracle["merge_base"]:
        raise RuntimeError("merge base differs from GitHub's complete-graph oracle")
    expected_files = set()
    for entry in oracle["files"]:
        expected_files.add(entry["path"])
        if entry.get("previous_filename"):
            expected_files.add(entry["previous_filename"])
    if set(actual_files) != expected_files:
        raise RuntimeError("three-dot paths differ from the complete-graph oracle")
    actual = {}
    for name, directory in (("candidate_shallow", args.workdir), ("existing_source_graph", repository)):
        files = detector.changed_files(BASE, HEAD, root=directory)
        common = detector.merge_base(BASE, HEAD, root=directory)
        base_version = detector.v8_version_at_revision(common, root=directory)
        head_version = detector.v8_version_at_revision(HEAD, root=directory)
        actual[name] = {"merge_base": common, "files": sorted(files),
                        "base_v8_version": base_version, "head_v8_version": head_version,
                        "canary_required": detector.canary_required(files, base_version, head_version),
                        "windows_source_required": detector.windows_source_required(files, base_version, head_version)}
    if actual["candidate_shallow"] != actual["existing_source_graph"]:
        raise RuntimeError("unchanged V8 detector differs between the two graphs")
    if command("for-each-ref", "--format=%(refname)").stdout or command("tag").stdout:
        raise RuntimeError("unexpected branch or tag acquisition")
    after = {str(p.relative_to(repository)): digest(p)
             for p in (helper_path, original_path, detector_path)}
    if before != after:
        raise RuntimeError("replay source changed during execution")
    report = {"schema_version": 1, "base": BASE, "head": HEAD,
              "source_before": before, "source_after": after,
              "command_records": commands, "progressive_fetches": fetches,
              "original_expected_failure": "NO_MERGE_BASE", "candidate_result": "PASS",
              "full_graph_oracle_url": oracle["url"], "detector_results": actual,
              "scope": "exact Git history and original V8 selector only; no V8/native build claim"}
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"result": "PASS", "merge_base": actual_base,
                      "changed_files": len(actual_files), "progressive_fetches": fetches,
                      "canary_required": actual["candidate_shallow"]["canary_required"],
                      "windows_source_required": actual["candidate_shallow"]["windows_source_required"]}))


if __name__ == "__main__":
    main()
