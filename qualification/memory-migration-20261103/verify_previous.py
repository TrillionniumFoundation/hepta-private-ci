#!/usr/bin/env python3
"""Verify complete original artifacts against the exact tested Git commit."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(__debug__, "optimized Python is not accepted")
    root = args.repository.resolve()
    evidence = root / "qualification/memory-migration-20261103/hosted-398838"
    manifest = json.loads((evidence / "manifest.json").read_bytes())
    head = "398838d15eaa6f2b68939cb227029c71e1083cc4"
    tree = subprocess.check_output(["git", "rev-parse", head + "^{tree}"], cwd=root, text=True).strip()
    require(head == manifest["source_commit"] and tree == manifest["source_tree"], "source identity differs")
    reports = []
    for artifact in manifest["artifacts"]:
        path = evidence / (str(artifact["id"]) + ".zip")
        raw = path.read_bytes()
        require(len(raw) == artifact["bytes"] and hashlib.sha256(raw).hexdigest() == artifact["sha256"],
                "original ZIP bytes differ")
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            require(len(names) == len(set(names)) and archive.testzip() is None, "ZIP member or CRC failure")
            require(sum(i.file_size for i in archive.infolist()) < 4 * 1024 * 1024, "ZIP exceeds size bound")
            require(all(not PurePosixPath(n).is_absolute() and ".." not in PurePosixPath(n).parts
                        for n in names), "unsafe ZIP member")
            receipt = json.loads(archive.read("receipt.json"))
            before = json.loads(archive.read("source-inputs.json"))
            require(receipt["commit"] == head and receipt["status"] == artifact["status"],
                    "original source or status differs")
            require(receipt["source_inputs_unchanged"] and receipt["source_after"] == before,
                    "original input changed during execution")
            require(set(names) == set(receipt["outputs"]) | {"receipt.json"}, "unexpected ZIP member")
            for name, row in receipt["outputs"].items():
                data = archive.read(name)
                require(len(data) == row["bytes"] and hashlib.sha256(data).hexdigest() == row["sha256"],
                        "original output differs: " + name)
            target = [s for s in receipt["steps"] if s["name"] == "original-memory-unit-tests"]
            require(len(target) == 1 and target[0]["exit"] == artifact["original_target_exit"],
                    "original target exit differs")
            require(target[0]["command"][-1] == "//codex-rs/hepta-memory:hepta-memory-unit-tests"
                    and "--nocache_test_results" in target[0]["command"], "original target differs")
            log = archive.read("memory.log").decode()
            summaries = list(re.finditer(
                r"test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; "
                r"(\d+) measured; (\d+) filtered out", log))
            counts = [list(map(int, s.groups()[1:])) for s in summaries]
            require(counts == artifact["counts"], "original native counts differ")
            cases, previous = [], 0
            for summary, count in zip(summaries, counts):
                rows = re.findall(r"^test (\S+) \.\.\. (ok|FAILED|ignored)(?:,.*)?$",
                                  log[previous:summary.start()], re.MULTILINE)
                previous = summary.end()
                require([sum(status == value for _, status in rows)
                         for value in ["ok", "FAILED", "ignored"]] == count[:3],
                        "original case lines differ from summary")
                cases.extend(rows)
            require(len(cases) == len({n for n, _ in cases}) and {sum(c) for c in counts} == {len(cases)},
                    "original batches do not cover the complete disjoint suite")
            failures = sorted(n for n, status in cases if status == "FAILED")
            if artifact["host"] == "Darwin":
                blocks = re.findall(r"^---- (.*?) stdout ----\n(.*?)(?=^---- |^failures:|^test result:|\Z)",
                                    log, re.MULTILINE | re.DOTALL)
                require(len(blocks) == 158 and sorted(n for n, _ in blocks) == failures,
                        "original Mac failure blocks differ")
                require(all('Invalid("per-agent cognitive root must be canonical and must not traverse a symlink")'
                            in body for _, body in blocks), "Mac failure cause differs")
            process = subprocess.Popen(["git", "cat-file", "--batch"], cwd=root,
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            try:
                for name, digest in before.items():
                    require("\n" not in name and "\0" not in name, "unsafe Git query")
                    process.stdin.write((head + ":" + name + "\n").encode())
                    process.stdin.flush()
                    header = process.stdout.readline().split()
                    require(len(header) == 3 and header[1] == b"blob", "missing source input: " + name)
                    data = process.stdout.read(int(header[2]))
                    require(process.stdout.read(1) == b"\n", "invalid Git batch frame")
                    require(hashlib.sha256(data).hexdigest() == digest, "source input differs: " + name)
            finally:
                process.stdin.close()
                require(process.wait() == 0, "Git batch reader failed")
            reports.append({"artifact_id": artifact["id"], "host": artifact["host"],
                            "verified_git_inputs": len(before), "verified_outputs": len(receipt["outputs"]),
                            "status": receipt["status"], "native_batch_counts": counts,
                            "complete_disjoint_cases": len(cases), "original_failures": failures})
    report = {"source_commit": head, "source_tree": tree, "artifacts": reports,
              "scope": "Historical original results: Linux passed; Mac and Windows failed. No successor result implied."}
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"source_commit": head, "artifacts": len(reports),
                      "verified_git_inputs_per_artifact": [r["verified_git_inputs"] for r in reports]}))


if __name__ == "__main__":
    main()
