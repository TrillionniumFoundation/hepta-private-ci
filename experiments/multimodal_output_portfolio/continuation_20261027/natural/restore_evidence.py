"""Safely restore a content-addressed archive, or exercise every path and discard."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile


def safe_relative(value):
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in ("", ".", "..") for part in path.parts) or "\\" in value:
        raise ValueError("Unsafe logical archive path")
    return path


def restore(archive, destination, verify_discard=False):
    if destination.exists():
        raise FileExistsError("Restore requires a new destination: "+str(destination))
    destination.mkdir(parents=True)
    destination = destination.resolve()
    paths_by_hash = defaultdict(list)
    logical_bytes, restored_paths, blobs = 0, 0, 0
    with tarfile.open(archive, "r|gz") as stream:
        member = stream.next()
        if member is None or member.name != "INDEX.json" or not member.isfile() or member.size > 30_000_000:
            raise ValueError("Missing bounded index as first archive member")
        index = json.load(stream.extractfile(member))
        if index["schema"] != "hepta.ndu.natural.content-addressed-archive.v1":
            raise ValueError("Unsupported raw evidence archive schema")
        identities = set()
        for row in index["paths"]:
            relative = safe_relative(row["path"])
            if str(relative) in identities:
                raise ValueError("Duplicate logical archive path")
            identities.add(str(relative))
            digest = row["sha256"]
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest) or row["bytes"] < 0:
                raise ValueError("Invalid blob identity")
            paths_by_hash[digest].append((relative, row["bytes"]))
        seen = set()
        while member := stream.next():
            if not member.isfile() or not member.name.startswith("blobs/"):
                raise ValueError("Archive contains an unexpected member or a link")
            digest = member.name.removeprefix("blobs/")
            if digest not in paths_by_hash or digest in seen:
                raise ValueError("Unreferenced or duplicated blob")
            expected_sizes = {size for _, size in paths_by_hash[digest]}
            if expected_sizes != {member.size} or member.size > 200_000_000:
                raise ValueError("Blob size mismatch or limit exceeded")
            data = stream.extractfile(member).read()
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError("Blob SHA256 differs")
            for relative, size in paths_by_hash[digest]:
                target = destination/relative
                if not target.resolve().is_relative_to(destination):
                    raise ValueError("Logical path escapes restore root")
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as output:
                    output.write(data)
                with target.open("rb") as reopened:
                    if hashlib.file_digest(reopened, "sha256").hexdigest() != digest:
                        raise ValueError("Restored logical path failed reopened hash")
                if target.stat().st_size != size:
                    raise ValueError("Restored logical path size differs")
                logical_bytes += size
                restored_paths += 1
                if verify_discard:
                    target.unlink()
            seen.add(digest)
            blobs += 1
        if seen != set(paths_by_hash):
            raise ValueError("Referenced blobs missing from archive")
    with archive.open("rb") as stream:
        archive_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"status": "passed", "unique_blobs_rehashed": blobs, "logical_paths_actually_restored_and_reopened": restored_paths,
        "logical_bytes_restored": logical_bytes, "verify_discard": verify_discard,
        "models_embedded": False, "model_recovery_required": index["external_models"],
        "archive_sha256": archive_hash}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--verify-discard", action="store_true")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    result = restore(args.archive, args.destination, args.verify_discard)
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result, indent=2))
