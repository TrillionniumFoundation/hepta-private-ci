"""Package byte-bound research evidence for the unchanged safe Round2 restorer."""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile

from ...round2.restore_evidence import verify_members


LIMIT = 8 * 1024 * 1024
PROJECT = Path(__file__).resolve().parents[1]
REPO = PROJECT.parents[2]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def pack(run_dir, collections, name, category):
    run_dir = Path(run_dir).resolve()
    selected = []
    for relative in collections:
        collection = (run_dir / relative).resolve()
        if not collection.is_relative_to(run_dir) or not collection.exists():
            raise ValueError("Invalid evidence collection: " + relative)
        selected.extend([collection] if collection.is_file() else
                        [path for path in collection.rglob("*") if path.is_file()])
    selected = sorted(set(selected))
    if not selected or any(path.is_symlink() for path in selected):
        raise ValueError("Require nonempty regular evidence files")
    members = {"run/" + str(path.relative_to(run_dir)): digest(path) for path in selected}
    manifest_name = name + "_MANIFEST.json"
    destination = PROJECT / "evidence" / category
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="aen-r4-package-") as temporary:
        archive_path = Path(temporary) / (name + ".tar.gz")
        with archive_path.open("xb") as output, gzip.GzipFile(fileobj=output, mode="wb", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for path in selected:
                    relative = "run/" + str(path.relative_to(run_dir))
                    info = archive.gettarinfo(str(path), arcname=relative)
                    info.mtime = 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    with path.open("rb") as stream:
                        archive.addfile(info, stream)
                data = (json.dumps(members, sort_keys=True, indent=2) + "\n").encode()
                info = tarfile.TarInfo(manifest_name)
                info.size, info.mode, info.mtime = len(data), 0o644, 0
                archive.addfile(info, io.BytesIO(data))
        verified = verify_members(archive_path, manifest_name)
        if verified != members:
            raise ValueError("Archive membership differs")
        size, sha = archive_path.stat().st_size, digest(archive_path)
        parts = []
        with archive_path.open("rb") as stream:
            index = 0
            while data := stream.read(LIMIT):
                suffix = "" if size <= LIMIT else f".part{index:03d}"
                target = destination / (archive_path.name + suffix)
                with target.open("xb") as output:
                    output.write(data)
                expected = hashlib.sha256(data).hexdigest()
                if digest(target) != expected:
                    raise ValueError("Partition differs")
                parts.append({"path": str(target.relative_to(REPO)), "bytes": len(data), "sha256": expected})
                index += 1
    descriptor = {"name": name, "bytes": size, "sha256": sha,
                  "member_manifest": manifest_name, "restore_root": ".",
                  "data_files": len(members), "data_bytes": sum(path.stat().st_size for path in selected),
                  "member_hashes_verified": True, "scientific_data_regenerated": False,
                  "source_collections": collections}
    if len(parts) == 1:
        descriptor.update(parts[0])
    else:
        descriptor["parts"] = parts
    receipt = destination / (name + ".json")
    with receipt.open("x") as stream:
        json.dump(descriptor, stream, sort_keys=True, indent=2)
        stream.write("\n")
    return descriptor


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--category", choices=["prepared", "confirmation", "operational"], required=True)
    parser.add_argument("--collection", action="append", required=True)
    args = parser.parse_args()
    print(json.dumps(pack(args.run_dir, args.collection, args.name, args.category)))
