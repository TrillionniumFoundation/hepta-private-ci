#!/usr/bin/env python3
"""Verify downloaded native/Bazel artifacts against an immutable Git commit."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--allow-recorded-windows-crlf", action="store_true")
    args = parser.parse_args()
    root = args.artifacts.resolve()
    downloads = json.loads((root / "download-verification.json").read_text())
    sources = {}
    for row in downloads:
        data = (root / f"{row['artifact_id']}.zip").read_bytes()
        if len(data) != row["bytes"] or digest(data) != row["sha256"]:
            raise ValueError("downloaded ZIP differs")
        directory = root / str(row["artifact_id"])
        sources[row["artifact_id"]] = json.loads((directory / "source-inputs.json").read_text())
    names = sorted({name for source in sources.values() for name in source})
    if any("\n" in name or "\r" in name or Path(name).is_absolute() or ".." in Path(name).parts for name in names):
        raise ValueError("unsafe source path")
    query = "".join(f"{args.commit}:{name}\n" for name in names).encode()
    data = subprocess.check_output(["git", "cat-file", "--batch"], cwd=args.repository, input=query)
    offset = 0
    expected = {}
    for name in names:
        end = data.index(b"\n", offset)
        header = data[offset:end].split()
        if header[1] != b"blob":
            raise ValueError(f"missing immutable source: {name}")
        length = int(header[2])
        blob = data[end + 1:end + 1 + length]
        offset = end + 2 + length
        expected[name] = {
            "git": digest(blob),
            "crlf": digest(blob.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")),
        }
    if offset != len(data):
        raise ValueError("unexpected Git object output")
    results = []
    for artifact_id, inputs in sorted(sources.items()):
        directory = root / str(artifact_id)
        receipt = json.loads((directory / "receipt.json").read_text())
        if receipt["commit"] != args.commit or receipt["status"] != "passed" or (directory / "source-commit.txt").read_text().strip() != args.commit:
            raise ValueError("failed result or different source commit")
        rustc_file = directory / "rustc-version.txt"
        rustc = rustc_file.read_text() if rustc_file.exists() else ""
        windows = "host: x86_64-pc-windows-msvc" in rustc
        exact = []
        crlf = []
        for name, actual in inputs.items():
            if actual == expected[name]["git"]:
                exact.append(name)
            elif args.allow_recorded_windows_crlf and windows and actual == expected[name]["crlf"]:
                crlf.append(name)
            else:
                raise ValueError(f"source differs: artifact {artifact_id}: {name}")
        result = {"artifact_id": artifact_id, "source_inputs": len(inputs), "exact_git_bytes": len(exact), "exact_crlf_checkout_transform": crlf}
        if "tests" in receipt:
            if not rustc.startswith("rustc 1.95.0 "):
                raise ValueError("unexpected native toolchain")
            for name, count in [("aws-auth", 5), ("dpop", 8)]:
                document = ET.parse(directory / f"{name}.junit.xml")
                cases = document.findall(".//testcase")
                if len(cases) != count or document.getroot().get("tests") != str(count) or any(child.tag in {"failure", "error", "skipped"} for case in cases for child in case):
                    raise ValueError(f"native cases differ: {name}")
            metadata = json.loads(gzip.decompress((directory / "production-metadata.json.gz").read_bytes()))
            packages = metadata["packages"]
            versions = {"aws-config": ["1.8.12"], "p256": ["0.14.0"], "crypto-bigint": ["0.7.10"]}
            if {name: sorted(p["version"] for p in packages if p["name"] == name) for name in versions} != versions:
                raise ValueError("production crypto versions differ")
            if [p["version"] for p in packages if p["name"] == "chacha20" and p["version"].startswith("0.10.")] != ["0.10.2"]:
                raise ValueError("production RNG backend differs")
            nodes = {node["id"]: node for node in metadata["resolve"]["nodes"]}
            aws = next(p for p in packages if p["name"] == "aws-config")
            if aws["source"] is not None or "credentials-login" not in nodes[aws["id"]]["features"]:
                raise ValueError("patched provider/feature not selected")
            result.update(kind="native", tests=[5, 8], zero_skipped=True, rustc=rustc.splitlines())
        else:
            names = [step["name"] for step in receipt["steps"]]
            required = ["lock-update", "lock-check", "aws-config-build", "aws-auth-test", "generated-target"]
            if names not in [required, ["committed-lock-check", *required]] or any(step["exit"] for step in receipt["steps"]):
                raise ValueError("Bazel acceptance incomplete")
            for name, item in receipt["outputs"].items():
                value = (directory / name).read_bytes()
                if len(value) != item["bytes"] or digest(value) != item["sha256"]:
                    raise ValueError(f"Bazel output differs: {name}")
            lock = (directory / "MODULE.bazel.lock").read_bytes()
            json.loads(lock)
            result.update(kind="bazel", steps=receipt["steps"], generated_lock_bytes=len(lock), generated_lock_sha256=digest(lock))
        results.append(result)
    result = {"commit": args.commit, "unique_immutable_inputs": len(expected), "unexpected_source_differences": 0, "results": results}
    (root / "root-independent-verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"commit": args.commit, "artifacts": len(results), "unique_inputs": len(expected), "unexpected_source_differences": 0, "native_cases": [r["tests"] for r in results if r["kind"] == "native"]}, indent=2))


if __name__ == "__main__":
    main()
