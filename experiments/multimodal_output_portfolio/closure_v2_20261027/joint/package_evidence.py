"""Package explicit inputs and actual outcomes, then exercise every restore path."""

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
import tempfile


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def restore(archive_path, destination, discard=False):
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(archive_path, "r|gz") as archive:
        first = archive.next()
        if first is None or first.name != "MANIFEST.json" or not first.isfile():
            raise ValueError("Missing leading manifest")
        manifest = json.load(archive.extractfile(first))
        records = {row["path"]: row for row in manifest["files"]}
        if len(records) != len(manifest["files"]):
            raise ValueError("Repeated manifest path")
        seen, total = set(), 0
        while member := archive.next():
            relative = PurePosixPath(member.name)
            if (relative.is_absolute() or ".." in relative.parts or "\\" in member.name
                    or not member.isfile() or member.name not in records or member.name in seen):
                raise ValueError("Unsafe, duplicated or unexpected archive member")
            record = records[member.name]
            if member.size != record["bytes"] or member.size > 100_000_000:
                raise ValueError("Archive member size differs")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(archive.extractfile(member).read())
            if target.stat().st_size != record["bytes"] or checksum(target) != record["sha256"]:
                raise ValueError("Actual restored member differs")
            total += member.size
            seen.add(member.name)
            if discard:
                target.unlink()
        if seen != set(records):
            raise ValueError("Archive is incomplete")
    return {"status": "passed", "actual_members_written_reopened_hashed": len(seen),
        "actual_restored_bytes": total, "verify_discard": discard,
        "archive_sha256": checksum(archive_path)}


def package(workspace, output):
    repository = workspace / "hepta-private-ci"
    code = Path(__file__).resolve().parent
    roots = [workspace / "ndu-direct-gradient-v2", code]
    files = {p for root in roots for p in root.rglob("*")
             if p.is_file() and "__pycache__" not in p.parts and p.name != "RAW_ARCHIVE.json"}
    assets = workspace / "ndu-original-assets/restored"
    files.update((assets / "ndu-data").glob("*.gz"))
    files.update(assets / name for name in (
        "RESTORATION.json", "ndu-runs/full-002/protocol.json",
        "ndu-runs/full-002/reward-observer.pt", "ndu-runs/full-002/audit-observer.pt"))
    prior = workspace / "ndu-joint-continuation/development-full-001"
    files.add(prior / "SELECTIONS.json")
    choices = json.loads((prior / "SELECTIONS.json").read_text())
    for choice in choices:
        if choice["arm"] == "joint_uniform":
            path = prior / choice["selected_path"]
            if checksum(path) != choice["selected_checkpoint_sha256"]:
                raise ValueError("Strong baseline changed")
            files.add(path)
    files.add(code.parent / "SOURCE_ALLOCATION.json")
    files.update(workspace.glob("ndu-direct-gradient-*.log"))
    for directory in ("v6", "repair_20261026/joint", "continuation_20261027/joint"):
        files.update((repository / "experiments/multimodal_output_portfolio" / directory).glob("*.py"))
    records = []
    for path in sorted(files):
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(workspace.resolve()):
            raise ValueError("Invalid package input")
        records.append({"path": str(path.relative_to(workspace)), "bytes": path.stat().st_size,
                        "sha256": checksum(path)})
    manifest = {"schema": "hepta.ndu.actual-gradient-archive.v1", "recorded_workspace": str(workspace),
        "files": records, "baseline_git_commit": "fb9281e4a7ccfc4034281ed6310adea7e50f4474",
        "scope": "Both complete matched training grids, pilot, selected snapshots, all qualification media, all independent gradient probe media, failed launch, exact source datasets, frozen observers and three strong baseline snapshots.",
        "limitation": "Individual original training/validation media were not all retained. Their traces, hashes, model states and RNG contracts are included; no claim of a full original training-media archive.",
        "path_custody": "Files retain their original relative hierarchy. Sealed receipts contain the recorded absolute workspace; do not rewrite those receipts or claim a relocated path has the old receipt hash.",
        "runtime": "Python/Torch versions are in each completed run RUNTIME.json. These packages are not a bundled Python interpreter."}
    data = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    if output.exists():
        raise FileExistsError("Preserve prior archives")
    with tarfile.open(output, "w:gz", compresslevel=6) as archive:
        member = tarfile.TarInfo("MANIFEST.json")
        member.size, member.mtime = len(data), 0
        archive.addfile(member, io.BytesIO(data))
        for record in records:
            path = workspace / record["path"]
            if checksum(path) != record["sha256"]:
                raise ValueError("Package source changed during assembly")
            member = tarfile.TarInfo(record["path"])
            member.size, member.mtime = record["bytes"], 0
            with path.open("rb") as stream:
                archive.addfile(member, stream)
    output.with_suffix(output.suffix + ".manifest.json").write_bytes(data)
    with tempfile.TemporaryDirectory(prefix="ndu-gradient-restore-", dir=workspace) as temporary:
        verification = restore(output, Path(temporary) / "restored", discard=True)
    record = {"archive": str(output), "bytes": output.stat().st_size,
        "sha256": checksum(output), "manifest_sha256": hashlib.sha256(data).hexdigest(),
        "verification": verification, "library_saved": False}
    (code / "results/RAW_ARCHIVE.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--restore", type=Path)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    if args.restore:
        print(json.dumps(restore(args.restore.resolve(), args.destination.resolve())))
    else:
        package(args.workspace.resolve(), args.output.resolve())
