"""Package a hosted attempt without dropping failures or exceeding blob policy.

Only the dedicated new experiment prefix can enter the publication directory.
The separate publication job verifies every byte before an ordinary fast-forward
push, and refuses publication if the branch moved away from the execution seal.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import time

from experiments.hcsn_free_boundary_v1.archive import pack


ROOT = Path(__file__).resolve().parents[3]
PREFIX = "experiments/hcsn_conservative_acceleration_v1"
BASE = ROOT / PREFIX
MAX_BLOB = 512000


def digest(path, git=False):
    data = path.read_bytes()
    return (hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            if git else hashlib.sha256(data).hexdigest())


def safe_path(root, name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or not name.startswith(PREFIX + "/"):
        raise ValueError("Publication path is outside the declared experiment")
    suffix = name.removeprefix(PREFIX + "/")
    if suffix != "HOSTED_PROTOCOL.json" and not suffix.startswith(("results/", "artifacts/hosted002/")):
        raise ValueError("Publication may contain only declared evidence, not code or configuration")
    target = root.joinpath(*path.parts)
    if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Publication path escapes through a symlink")
    return target


def package(output):
    began_cpu, began_wall = time.process_time(), time.perf_counter()
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    target = output / PREFIX
    artifact = target / "artifacts/hosted002"
    artifact.mkdir(parents=True)
    if not (BASE / "results").is_dir():
        raise FileNotFoundError("No attempt evidence directory exists")
    manifest = pack(BASE / "results", artifact, "hosted_attempt", part_bytes=327680)
    # Full raw evidence is in the archive. These small files are copied verbatim
    # as review entry points; they never replace the unselected checkpoints.
    candidates = [BASE / "HOSTED_PROTOCOL.json"]
    for folder in ("hosted_prepare001", "hosted_validation001", "hosted_preflight001",
                   "comparison002_hosted", "comparison002_hosted_analysis",
                   "hosted_finalize001", "trained_stream001", "trained_native001",
                   "trained_native_causal001"):
        directory = BASE / "results" / folder
        if directory.is_dir():
            candidates.extend(sorted(directory.glob("*.json")))
            candidates.extend(sorted(directory.glob("*.md")))
    for source in candidates:
        if not source.is_file() or source.is_symlink() or source.stat().st_size > MAX_BLOB:
            continue
        path = source.relative_to(ROOT).as_posix()
        destination = safe_path(output, path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    analysis_path = BASE / "results/comparison002_hosted_analysis/ANALYSIS.json"
    analysis = json.loads(analysis_path.read_text()) if analysis_path.exists() else {}
    rows = []
    for path in sorted(output.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(output).as_posix()
        safe_path(output, relative)
        if path.stat().st_size > MAX_BLOB:
            raise ValueError("Archive or review file exceeds existing Git blob limit")
        rows.append(dict(path=relative, bytes=path.stat().st_size,
                         sha256=digest(path), git_blob_sha1=digest(path, git=True)))
    record = dict(schema="hcsn-hosted-publication.v1", execution_seal=os.environ["GITHUB_SHA"],
                  github_run_id=os.environ.get("GITHUB_RUN_ID"), prefix=PREFIX,
                  archive_members=len(manifest["members"]),
                  archive_sha256=manifest["archive_sha256"],
                  compressed_bytes=manifest["compressed_bytes"],
                  maximum_git_blob_bytes=MAX_BLOB, files=rows,
                  complete=analysis.get("complete") is True,
                  audited_jobs=analysis.get("valid_jobs", 0),
                  expected_jobs=analysis.get("expected_jobs", 70),
                  failed_attempts_preserved=True,
                  packaging_cpu_seconds=time.process_time()-began_cpu,
                  packaging_wall_seconds=time.perf_counter()-began_wall,
                  cost_scope="Packaging function body, separate from training/analysis; not added to nested full-process receipts")
    manifest_path = artifact / "PUBLICATION.json"
    manifest_path.write_text(json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n")
    if manifest_path.stat().st_size > MAX_BLOB:
        raise ValueError("Publication manifest exceeds existing blob limit")
    return record


def verify(output, expected_seal):
    output = output.resolve()
    manifest_path = output / PREFIX / "artifacts/hosted002/PUBLICATION.json"
    record = json.loads(manifest_path.read_text())
    if record["execution_seal"] != expected_seal or record["prefix"] != PREFIX:
        raise ValueError("Artifact seal or publication prefix mismatch")
    names = [row["path"] for row in record["files"]]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate publication entry")
    expected = set(names) | {manifest_path.relative_to(output).as_posix()}
    actual = {p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()}
    if actual != expected:
        raise ValueError("Unlisted or missing publication file")
    for row in record["files"]:
        path = safe_path(output, row["path"])
        if (path.stat().st_size != row["bytes"] or row["bytes"] > MAX_BLOB
                or digest(path) != row["sha256"] or digest(path, git=True) != row["git_blob_sha1"]):
            raise ValueError("Publication file identity mismatch: " + row["path"])
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("package", "verify"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-seal")
    args = parser.parse_args()
    record = package(args.output) if args.command == "package" else verify(args.output, args.expected_seal)
    print(json.dumps({key: record[key] for key in
                     ("execution_seal", "complete", "audited_jobs", "archive_members", "compressed_bytes")}))


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    main()
