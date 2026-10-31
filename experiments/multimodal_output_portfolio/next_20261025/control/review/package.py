"""Package immutable control evidence and verify every archived member byte."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import time


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(1024 * 1024): value.update(block)
    return value.hexdigest()


def run(repository, runs, archive):
    folder = repository / "experiments/multimodal_output_portfolio/next_20261025/control"
    manifest_path, receipt_path = folder / "EVIDENCE_MANIFEST.json", folder / "EVIDENCE_ARCHIVE.json"
    if any(p.exists() for p in (archive, manifest_path, receipt_path)):
        raise FileExistsError("Never overwrite a completed evidence package")
    protocol = json.loads((folder / "PROTOCOL.json").read_text())
    if not (runs / "control-next-prospective-001/analysis.json").exists():
        raise ValueError("The frozen primary analysis must complete before packaging")
    files, external = {}, {}
    for filename, expected in protocol["frozen_sha256"].items():
        path = Path(filename)
        if digest(path) != expected: raise ValueError("Frozen dependency changed: " + filename)
        if path.is_relative_to(repository): files["repository/" + str(path.relative_to(repository))] = path
        else: external[filename] = {"sha256": expected, "bytes": path.stat().st_size}
    for path in folder.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts and path not in (manifest_path, receipt_path):
            files["repository/" + str(path.relative_to(repository))] = path
    for root in runs.glob("control-next-*"):
        if root.name == "control-next-agent-progress.json": continue
        paths = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
        for path in paths:
            if "__pycache__" not in path.parts: files["runs/" + str(path.relative_to(runs))] = path
    records = [{"member": name, "original_path": str(path), "bytes": path.stat().st_size, "sha256": digest(path)}
               for name, path in sorted(files.items())]
    manifest = {"schema": "hepta.next.control-complete-evidence-manifest.v1", "created_unix_ns": time.time_ns(),
        "files": records, "external_frozen_inputs_verified": external,
        "external_input_custody": "Original inputs remain in the separately verified hepta-ndu-shared-inputs-20261025 archive; this archive carries their exact protocol pins, not duplicate model and dataset bytes.",
        "scope": "Both historical development runs including original frozen source archives, qualification, all prospective requests/media/graphs/scores, process and host receipts, frozen code and independent reviews. No new-source outcomes removed.",
        "source_pairs_confirmation": 512, "writer_clusters_confirmation": 128, "actual_requests_confirmation": 147456,
        "primary_protocol_sha256": digest(folder / "PROTOCOL.json"), "packager_sha256": digest(__file__)}
    raw_manifest = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    with manifest_path.open("xb") as stream:
        stream.write(raw_manifest); stream.flush(); os.fsync(stream.fileno())
    with archive.open("xb") as stream:
        with tarfile.open(fileobj=stream, mode="w:gz", compresslevel=3) as packed:
            member = tarfile.TarInfo("MANIFEST.json"); member.size = len(raw_manifest)
            packed.addfile(member, io.BytesIO(raw_manifest))
            for row in records:
                path = files[row["member"]]
                if digest(path) != row["sha256"]: raise ValueError("Evidence changed while packaging")
                packed.add(path, arcname=row["member"], recursive=False)
        stream.flush(); os.fsync(stream.fileno())
    expected = {r["member"]: r for r in records}
    expected["MANIFEST.json"] = {"bytes": len(raw_manifest), "sha256": hashlib.sha256(raw_manifest).hexdigest()}
    verified = set()
    with tarfile.open(archive, "r:gz") as packed:
        for member in packed:
            if not member.isfile() or member.name not in expected or member.name in verified:
                raise ValueError("Wrong or repeated archive member")
            row = expected[member.name]; value = hashlib.sha256()
            with packed.extractfile(member) as stream:
                while block := stream.read(1024 * 1024): value.update(block)
            if member.size != row["bytes"] or value.hexdigest() != row["sha256"]:
                raise ValueError("Archive byte identity differs: " + member.name)
            verified.add(member.name)
    if verified != set(expected): raise ValueError("Archive evidence census differs")
    receipt = {"schema": "hepta.next.control-verified-archive.v1", "status": "passed", "archive": str(archive),
        "archive_sha256": digest(archive), "archive_bytes": archive.stat().st_size,
        "manifest_sha256": hashlib.sha256(raw_manifest).hexdigest(), "manifest": str(manifest_path),
        "verified_members": len(verified), "original_file_bytes": sum(r["bytes"] for r in records),
        "all_member_bytes_rehashed_after_archive_close": True, "original_files_retained": True,
        "external_frozen_input_count": len(external), "upload_performed": False, "completed_unix_ns": time.time_ns()}
    with receipt_path.open("x") as stream:
        json.dump(receipt, stream, sort_keys=True, indent=2); stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
    print(json.dumps(receipt))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repository", type=Path, required=True); p.add_argument("--runs", type=Path, required=True)
    p.add_argument("--archive", type=Path, required=True)
    a = p.parse_args(); run(a.repository.resolve(), a.runs.resolve(), a.archive.resolve())
