#!/usr/bin/env python3
"""Reassemble the original hosted lock ZIP and compare its inputs to Git bytes."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import zipfile


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(data, length, digest):
    require(len(data) == length and hashlib.sha256(data).hexdigest() == digest,
            "byte length or SHA-256 differs")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(__debug__, "optimized Python is not accepted")
    root = args.repository.resolve()
    evidence = root / "qualification/dylint-20261103/hosted-ef384"
    manifest = json.loads((evidence / "lock-artifact-manifest.json").read_bytes())
    head = "ef384309bde52e30e9dd0bc5b625157bfaa77bd1"
    require(manifest["source_commit"] == head and manifest["artifact_id"] == 13271804423,
            "original artifact identity differs")
    chunks = []
    offset = 0
    for part in manifest["parts"]:
        require(Path(part["file"]).name == part["file"] and part["offset"] == offset,
                "part name or order differs")
        packed = (evidence / part["file"]).read_bytes()
        verify(packed, part["gzip_bytes"], part["gzip_sha256"])
        chunk = gzip.decompress(packed)
        verify(chunk, part["raw_bytes"], part["raw_sha256"])
        chunks.append(chunk)
        offset += len(chunk)
    raw = b"".join(chunks)
    verify(raw, 609421, "99aab5d5c73ce7017b35167838e9d539b39634755de68ed7b8220f4d99de699d")
    negative = json.loads((evidence / "bootstrap-failure.json").read_bytes())
    packed_negative = (evidence / "original-bootstrap-failure.log.gz").read_bytes()
    verify(packed_negative, negative["gzip_bytes"], negative["gzip_sha256"])
    decoded_negative = gzip.decompress(packed_negative)
    verify(decoded_negative, negative["decoded_bytes"], negative["decoded_sha256"])
    require(b"rustc 1.92.0-nightly is not supported" in decoded_negative
            and b"cargo-util@0.2.32 requires rustc 1.97" in decoded_negative
            and b"cargo-util-schemas@0.14.3 requires rustc 1.97" in decoded_negative,
            "original bootstrap failure is missing")
    toolchain = gzip.decompress((evidence / "channel-rust-1.97.0.toml.gz").read_bytes())
    verify(toolchain, 845916, "3804d2666f7c12ce64205baa69b6be52f910b45b158091013264beb7aa1de7f5")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)) and archive.testzip() is None, "ZIP member/CRC failure")
        require(sum(info.file_size for info in archive.infolist()) < 8 * 1024 * 1024,
                "archive exceeds its uncompressed bound")
        for name in names:
            path = PurePosixPath(name)
            require(not path.is_absolute() and ".." not in path.parts, "unsafe archive member")
        receipt = json.loads(archive.read("receipt.json"))
        before = json.loads(archive.read("source-inputs.json"))
        require(receipt["commit"] == head and receipt["index_tree"] == manifest["source_tree"],
                "tested source differs")
        tree = subprocess.check_output(["git", "rev-parse", head + "^{tree}"], cwd=root, text=True).strip()
        require(tree == receipt["index_tree"], "actual Git tree differs")
        require(receipt["status"] == "passed" and receipt["committed_lock_required"]
                and receipt["committed_lock_matches"], "committed lock did not qualify")
        require(receipt["source_inputs_unchanged"] and receipt["source_after"] == before,
                "input bytes changed during qualification")
        commands = [(step["name"], step["command"], step["exit"]) for step in receipt["steps"]]
        require(commands == [
            ("committed-lock-check", ["./scripts/check-module-bazel-lock.sh"], 0),
            ("original-lock-update", ["just", "bazel-lock-update"], 0),
            ("original-lock-check", ["./scripts/check-module-bazel-lock.sh"], 0),
        ], "original command sequence or exits differ")
        require(set(names) == set(receipt["outputs"]) | {"receipt.json"}, "unexpected artifact member")
        for name, row in receipt["outputs"].items():
            verify(archive.read(name), row["bytes"], row["sha256"])
        require(archive.read("MODULE.bazel.lock") == archive.read("committed-MODULE.bazel.lock")
                == subprocess.check_output(["git", "show", head + ":MODULE.bazel.lock"], cwd=root),
                "committed, regenerated and Git lock bytes differ")
        process = subprocess.Popen(["git", "cat-file", "--batch"], cwd=root,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        try:
            for name, expected in before.items():
                require("\n" not in name and "\0" not in name, "unsafe Git object query")
                process.stdin.write((head + ":" + name + "\n").encode())
                process.stdin.flush()
                header = process.stdout.readline().split()
                require(len(header) == 3 and header[1] == b"blob", "missing source blob: " + name)
                data = process.stdout.read(int(header[2]))
                require(process.stdout.read(1) == b"\n", "invalid Git batch frame")
                require(hashlib.sha256(data).hexdigest() == expected, "source input differs: " + name)
        finally:
            process.stdin.close()
            require(process.wait() == 0, "Git batch reader failed")
    report = {"source_commit": head, "source_tree": tree, "artifact_id": 13271804423,
              "verified_git_inputs": len(before), "verified_outputs": len(receipt["outputs"]),
              "original_command_exits": [0, 0, 0], "committed_generated_git_lock_equal": True,
              "original_bootstrap_failure_and_official_toolchain_manifest_verified": True,
              "scope": "original committed lock only; original lint installation failed on this head"}
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
