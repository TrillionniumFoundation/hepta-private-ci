"""Package closed run bytes with hashes; do not substitute reruns for evidence."""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
import time


def file_sha(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def package(spec_path, output):
    spec = json.loads(spec_path.read_text())
    entries = []
    for root in spec.get("roots", []):
        path = Path(root["path"])
        for file in sorted(path.rglob("*")):
            if file.is_symlink():
                raise ValueError("Symlink not permitted in evidence package: " + str(file))
            if file.is_file():
                entries.append({"path": str(file), "name": str(PurePosixPath(root["prefix"]) / file.relative_to(path).as_posix())})
    entries += spec.get("files", [])
    names, records = set(), []
    for item in entries:
        path, name = Path(item["path"]), PurePosixPath(item["name"])
        if (not path.is_absolute() or not path.is_file() or path.is_symlink()
                or name.is_absolute() or ".." in name.parts or str(name) in names):
            raise ValueError("Invalid or duplicated evidence member")
        names.add(str(name))
        digest = file_sha(path)
        if item.get("sha256", digest) != digest:
            raise ValueError("Frozen input changed: " + str(path))
        records.append({"original_path": str(path), "member": str(name),
                        "bytes": path.stat().st_size, "sha256": digest})
    manifest = {"schema": "hepta.closure.evidence-package.v1", "study": spec["study"],
                "description": spec["description"], "files": records,
                "source_repository": "https://github.com/TrillionniumFoundation/hepta-private-ci",
                "recorded_unix_ns": time.time_ns(), "input_spec_sha256": file_sha(spec_path)}
    raw_manifest = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0, compresslevel=3) as compressed:
        with tarfile.open(fileobj=compressed, mode="w|") as archive:
            meta = tarfile.TarInfo("MANIFEST.json")
            meta.size, meta.mode = len(raw_manifest), 0o644
            archive.addfile(meta, io.BytesIO(raw_manifest))
            for record in records:
                path = Path(record["original_path"])
                info = tarfile.TarInfo(record["member"])
                info.size, info.mode = record["bytes"], path.stat().st_mode & 0o777
                with path.open("rb") as stream:
                    archive.addfile(info, stream)
                if file_sha(path) != record["sha256"]:
                    raise ValueError("A run was still changing during packaging: " + str(path))
    receipt = {"schema": manifest["schema"], "study": spec["study"],
               "archive": str(output), "archive_bytes": output.stat().st_size,
               "archive_sha256": file_sha(output), "member_count": len(records),
               "uncompressed_input_bytes": sum(r["bytes"] for r in records),
               "manifest_sha256": hashlib.sha256(raw_manifest).hexdigest()}
    with output.with_suffix(output.suffix + ".receipt.json").open("x") as stream:
        json.dump(receipt, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps(receipt, sort_keys=True), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    package(args.spec, args.output)
