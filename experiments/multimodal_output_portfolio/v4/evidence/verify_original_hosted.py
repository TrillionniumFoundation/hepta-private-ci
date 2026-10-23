"""Verify the newly completed original v2 hosted artifact; preserve smoke scope."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile


ARCHIVE_SHA256 = "6ed6265f6fa493eafdc55850426e7bf4bc8f5b2685181ad08ad901573be6ca00"
SOURCE = "c5c6b9df0a83a9a2f95d5583b95909829a982b06"
PROTOCOL = "2a5a206024c3837223e1db83a4515a4d2ba0a0416d48c482989cc5130bdf97cf"
RESULT_PREFIX = "_temp/ndu-controlled-v2/39899251197-1-hosted/"
SOURCE_PREFIX = "hepta-private-ci/hepta-private-ci/source/"


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def verify(archive, repo, destination):
    payload = archive.read_bytes()
    if sha(payload) != ARCHIVE_SHA256:
        raise AssertionError("artifact differs from observed GitHub digest")
    destination.mkdir(parents=True, exist_ok=False)
    source_count, result_count = 0, 0
    with zipfile.ZipFile(archive) as data:
        if data.testzip() is not None or len(data.namelist()) != len(set(data.namelist())):
            raise AssertionError("archive CRC or duplicate member")
        for name in data.namelist():
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts:
                raise AssertionError("unsafe archive path")
            if name.startswith(SOURCE_PREFIX):
                relative = name[len(SOURCE_PREFIX):]
                committed = subprocess.check_output(["git", "show", SOURCE + ":" + relative], cwd=repo)
                if data.read(name) != committed:
                    raise AssertionError("frozen uploaded source mismatch: " + relative)
                source_count += 1
            elif name.startswith(RESULT_PREFIX):
                relative = name[len(RESULT_PREFIX):]
                path = destination / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data.read(name))
                result_count += 1
            else:
                raise AssertionError("unexpected artifact member: " + name)
    read = lambda name: json.loads((destination / name).read_text())
    runtime, completion, results = (read("run/" + name) for name in
                                     ("runtime-start.json", "completion.json", "results.json"))
    launcher, request = read("launcher-receipt.json"), read("request.json")
    if (runtime["source_commit"] != SOURCE or not runtime["source_frozen"]
            or not runtime["smoke_only"] or not completion["smoke_only"]
            or launcher["source_sha"] != SOURCE or launcher["exit_code"] != 0
            or not completion["execution_completed"] or not completion["source_unchanged"]
            or request["protocol_sha256"] != PROTOCOL
            or sha((destination / "protocol.json").read_bytes()) != PROTOCOL):
        raise AssertionError("launcher/source/protocol/smoke contract")
    manifest = runtime["source_manifest"]
    if sha(json.dumps(manifest["files"], sort_keys=True).encode()) != manifest["combined_sha256"]:
        raise AssertionError("runtime combined source digest")
    for relative, expected in manifest["files"].items():
        committed = subprocess.check_output(["git", "show", SOURCE + ":" + relative], cwd=repo)
        if sha(committed) != expected:
            raise AssertionError("runtime source digest: " + relative)
    artifact_manifest = read("run/artifact-manifest.json")
    for relative, expected in artifact_manifest.items():
        body = (destination / "run" / relative).read_bytes()
        if len(body) != expected["bytes"] or sha(body) != expected["sha256"]:
            raise AssertionError("runtime artifact digest: " + relative)
    counts = []
    for name in ("tests.log", "v2-tests.log"):
        log = (destination / name).read_text()
        found = re.findall(r"Ran (\d+) tests? in", log)
        if len(found) != 1 or not re.search(r"^OK\s*$", log, re.MULTILINE):
            raise AssertionError("recorded unit suite outcome")
        counts.append(int(found[0]))
    if results["primary_passed"] != completion["primary_passed"] or results["eligible_confirmation"]:
        raise AssertionError("scientific outcome and smoke eligibility disagree")
    return {"schema": "hepta.original-hosted-artifact-verification.v1", "passed": True,
            "run_id": 39899251197, "artifact_id": 12480676664,
            "archive_sha256": ARCHIVE_SHA256, "archive_bytes": len(payload),
            "source_commit": SOURCE, "source_files_verified": source_count,
            "runtime_source_hashes_verified": len(manifest["files"]),
            "runtime_artifact_hashes_verified": len(artifact_manifest),
            "results_only_files_retained": result_count, "unit_tests_passed": sum(counts),
            "launcher": launcher, "completion": completion,
            "scientific_primary_passed": results["primary_passed"],
            "confirmation_eligible": results["eligible_confirmation"],
            "scope": "Artifact/source integrity and observed hosted smoke execution; no dedicated-runner qualification or new independent scientific confirmation.",
            "verifier_sha256": sha(Path(__file__).read_bytes())}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "repo", "destination", "report"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.archive, args.repo, args.destination)
    with args.report.open("x") as output:
        json.dump(report, output, indent=2)
        output.write("\n")
    print(json.dumps(report))
