"""Prepare verified 512KiB Git blobs/manifest from an already-final evidence ZIP.

Run as a module from the repository root. This writes only local transport
files and never creates a ZIP, uploads, publishes or changes a branch.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

from .restore_transport import CHUNK_BYTES, blob_sha, guard, normalize, publish, read_part

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--expected-bytes", type=int, required=True)
    parser.add_argument("--repository", default="TrillionniumFoundation/hepta-private-ci")
    parser.add_argument("--branch", default="research/hcsn-next-blockers-r2-20261101")
    args = parser.parse_args()
    archive = guard(args.archive); manifest_path = guard(HERE / "TRANSPORT_MANIFEST.json")
    if manifest_path.exists():
        raise FileExistsError(manifest_path)
    if archive.stat().st_size != args.expected_bytes:
        raise ValueError("Final archive byte count differs from expected")
    h = hashlib.sha256()
    with archive.open("rb") as source:
        for data in iter(lambda: source.read(1 << 20), b""): h.update(data)
    if h.hexdigest() != args.expected_sha:
        raise ValueError("Final archive SHA256 differs from expected")
    directory = guard(HERE / "evidence_parts"); directory.mkdir(exist_ok=True)
    parts = []; combined = hashlib.sha256(); total = 0
    with archive.open("rb") as source:
        while data := source.read(CHUNK_BYTES):
            path = guard(directory / f"part-{len(parts):04d}.bin")
            part = dict(path=str(path.relative_to(ROOT)), bytes=len(data),
                        sha256=hashlib.sha256(data).hexdigest(), git_blob_sha=blob_sha(data))
            if path.exists():
                read_part(path, part)
            else:
                partial = guard(path.with_name(path.name + ".partial"))
                with partial.open("xb") as stream:
                    stream.write(data); stream.flush(); os.fsync(stream.fileno())
                read_part(partial, part); publish(partial, path)
            parts.append(part); combined.update(data); total += len(data)
    if total != args.expected_bytes or combined.hexdigest() != args.expected_sha:
        raise ValueError("Archive changed while preparing parts; no manifest written")
    result = dict(schema="hcsn.r2.evidence-transport.v1", repository=args.repository, branch=args.branch,
                  archive_name=archive.name, bytes=total, sha256=combined.hexdigest(),
                  chunk_bytes=CHUNK_BYTES, parts=parts,
                  restorer_sha256=hashlib.sha256((HERE / "restore_transport.py").read_bytes()).hexdigest())
    normalize(result)
    with manifest_path.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True); stream.write("\n")
    print(json.dumps(dict(manifest=str(manifest_path), archive_bytes=total,
                         archive_sha256=combined.hexdigest(), parts=len(parts)), sort_keys=True))


if __name__ == "__main__":
    main()
