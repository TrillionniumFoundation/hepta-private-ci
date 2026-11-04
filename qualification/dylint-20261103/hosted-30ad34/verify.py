#!/usr/bin/env python3
"""Verify source-bound original results without executing archived code."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import zipfile


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_bytes(data, size, digest):
    require(len(data) == size and hashlib.sha256(data).hexdigest() == digest,
            "byte length or digest differs")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not sys.flags.optimize, "optimized Python is not accepted")
    root = args.repository.resolve()
    here = Path(__file__).resolve().parent
    head = "30ad34c1895597a04dc42f0d233505aa7566a6b7"
    tree = subprocess.check_output(["git", "rev-parse", head + "^{tree}"],
                                   cwd=root, text=True).strip()
    require(tree == "fcbb3b9c180f929661348dc5d6453e8c04fe369e", "source tree differs")
    manifest = json.loads((here / "manifest.json").read_bytes())
    require(manifest["source_commit"] == head and manifest["source_tree"] == tree,
            "manifest source differs")
    check_bytes(args.artifact.read_bytes(), 610346,
                "c25ce1d58cf5cd92f13d9dea03e33f515140c19b06940793bf5bf488a2cf60ef")
    with zipfile.ZipFile(args.artifact) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)) and archive.testzip() is None,
                "duplicate member or ZIP CRC failure")
        require(sum(i.file_size for i in archive.infolist()) < 8 * 1024 * 1024,
                "ZIP exceeds original bound")
        require(all(not PurePosixPath(n).is_absolute() and ".." not in PurePosixPath(n).parts
                    for n in names), "unsafe ZIP path")
        receipt = json.loads(archive.read("receipt.json"))
        before = json.loads(archive.read("source-inputs.json"))
        require(receipt["commit"] == head and receipt["index_tree"] == tree,
                "tested source differs")
        require(receipt["status"] == "passed" and receipt["committed_lock_required"]
                and receipt["committed_lock_matches"], "original lock gate did not pass")
        require(receipt["source_inputs_unchanged"] and receipt["source_after"] == before,
                "source changed during qualification")
        require([(s["name"], s["command"], s["exit"]) for s in receipt["steps"]] == [
            ("committed-lock-check", ["./scripts/check-module-bazel-lock.sh"], 0),
            ("original-lock-update", ["just", "bazel-lock-update"], 0),
            ("original-lock-check", ["./scripts/check-module-bazel-lock.sh"], 0),
        ], "original command sequence or exits differ")
        require(len(before) == 1664 and len(receipt["outputs"]) == 9,
                "original input or output cardinality differs")
        require(set(names) == set(receipt["outputs"]) | {"receipt.json"},
                "unexpected artifact member")
        for name, row in receipt["outputs"].items():
            check_bytes(archive.read(name), row["bytes"], row["sha256"])
        require(archive.read("MODULE.bazel.lock") == archive.read("committed-MODULE.bazel.lock")
                == subprocess.check_output(["git", "show", head + ":MODULE.bazel.lock"], cwd=root),
                "committed, generated and Git lock bytes differ")
        process = subprocess.Popen(["git", "cat-file", "--batch"], cwd=root,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        try:
            for name, expected in before.items():
                require("\n" not in name and "\0" not in name, "unsafe Git query")
                process.stdin.write((head + ":" + name + "\n").encode())
                process.stdin.flush()
                header = process.stdout.readline().split()
                require(len(header) == 3 and header[1] == b"blob", "missing source: " + name)
                data = process.stdout.read(int(header[2]))
                require(process.stdout.read(1) == b"\n", "invalid Git frame")
                require(hashlib.sha256(data).hexdigest() == expected, "source differs: " + name)
        finally:
            process.stdin.close()
            require(process.wait() == 0, "Git batch reader failed")
    packed = (here / "original-lint-job.log.gz").read_bytes()
    check_bytes(packed, manifest["lint"]["gzip_bytes"], manifest["lint"]["gzip_sha256"])
    log_bytes = gzip.decompress(packed)
    check_bytes(log_bytes, 143712,
                "53be97b11d8b728e7c644bc9e949fcec8396f206669f4ca59aa726acbcf4b160")
    log = log_bytes.decode()
    counts = [list(map(int, row)) for row in re.findall(
        r"test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out", log)]
    require(counts == [[9, 0, 0, 0, 0], [5, 0, 0, 0, 0], [3, 0, 0, 0, 0]],
            "original native test counts differ")
    require("Ran 6 tests in " in log and "test ui ... ok" in log
            and "Building driver for toolchain `nightly-2025-09-18-x86_64-unknown-linux-gnu`" in log,
            "original Python, UI or nightly evidence missing")
    merge = json.loads((here / "original-tested-merge.json").read_bytes())
    require(merge["sha"] == "cf13fb2ffc18e7ef7a814845faf26b95f1fcca89"
            and merge["tree"]["sha"] == tree
            and [p["sha"] for p in merge["parents"]] ==
            ["0b9da54535a7795b2433947a479e6d9e71525e0a", head]
            and merge["sha"] in log, "test merge differs")
    job = json.loads((here / "original-lint-job.json").read_bytes())
    require(job["id"] == 126235308440 and job["run_id"] == 41726681773
            and job["conclusion"] == "success", "original job did not pass")
    steps = {s["name"]: s["conclusion"] for s in job["steps"]}
    require(all(steps.get(n) == "success" for n in [
        "Install cargo-dylint tooling", "Test Python wrapper helpers",
        "Test argument comment lint package", "Check for a clean worktree",
    ]), "required original step did not pass")
    report = {"source_commit": head, "source_tree": tree, "tested_checkout": merge["sha"],
              "verified_git_inputs": len(before), "verified_outputs": len(receipt["outputs"]),
              "lock_commands": [0, 0, 0], "committed_generated_git_lock_equal": True,
              "outer_rust_tests": 8, "nested_ui_cases_inside_one_outer_test": 9,
              "python_wrapper_tests": 6,
              "scope": "Original maintained lint/bootstrap and committed lock only."}
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
