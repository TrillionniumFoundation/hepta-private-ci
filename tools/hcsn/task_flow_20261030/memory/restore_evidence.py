"""Restore or verify the lossless memory evidence archive using stdlib only."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile

HERE = Path(__file__).resolve().parent


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def restore(destination, verify_only=False):
    manifest_path = HERE / "raw_evidence_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    archive = HERE / manifest["archive"]
    if sha(archive) != manifest["archive_sha256"]:
        raise RuntimeError("Archive SHA256 mismatch")
    destination = Path(destination).resolve()
    records = manifest["files"]
    names = [r["path"] for r in records]
    if len(set(names)) != len(names):
        raise RuntimeError("Duplicate manifest paths")
    targets = {}
    for record in records:
        relative = PurePosixPath(record["path"])
        if relative.is_absolute() or ".." in relative.parts or relative.parts[0] != "runs":
            raise RuntimeError("Unexpected evidence path")
        target = destination / relative
        if not target.resolve().is_relative_to(destination):
            raise RuntimeError("Evidence path escapes destination")
        if target.exists() and (not target.is_file() or sha(target) != record["sha256"]):
            raise RuntimeError("Refuse to overwrite differing evidence: " + str(target))
        if verify_only and not target.exists():
            raise RuntimeError("Missing evidence: " + str(target))
        targets[record["path"]] = target
    restored = 0
    with zipfile.ZipFile(archive) as bundle:
        if sorted(bundle.namelist()) != sorted(names):
            raise RuntimeError("Archive paths differ from manifest")
        for record in records:
            name, target = record["path"], targets[record["path"]]
            if bundle.getinfo(name).file_size != record["bytes"]:
                raise RuntimeError("Archive size differs from manifest")
            if target.exists():
                continue
            data = bundle.read(name)
            if len(data) != record["bytes"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
                raise RuntimeError("Extracted evidence hash mismatch")
            target.parent.mkdir(parents=True, exist_ok=True)
            pending = target.with_name(target.name + ".restore.pending")
            if pending.exists():
                raise RuntimeError("Prior incomplete restore exists")
            pending.write_bytes(data)
            pending.replace(target)
            restored += 1
    for record in records:
        target = targets[record["path"]]
        if target.stat().st_size != record["bytes"] or sha(target) != record["sha256"]:
            raise RuntimeError("Final evidence verification failed")
    return dict(passed=True, files_verified=len(records), files_restored=restored,
                total_uncompressed_bytes=manifest["total_uncompressed_bytes"],
                archive_sha256=manifest["archive_sha256"], manifest_sha256=sha(manifest_path),
                verify_only=verify_only)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", type=Path, default=HERE)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    print(json.dumps(restore(args.dest, args.verify_only), indent=2))


if __name__ == "__main__":
    main()
