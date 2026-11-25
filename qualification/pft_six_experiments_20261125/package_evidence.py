#!/usr/bin/env python3
"""Losslessly package the final synthetic evidence, excluding exploratory reruns."""
import argparse
import gzip
import hashlib
import json
import tarfile
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package(root, output):
    results = root / "results"
    selected = list(results.glob("*.json"))
    for folder in ("pft5_final_artifacts", "pft6_final_artifacts", "pft5_isolation_artifacts"):
        selected.extend(p for p in (results / folder).rglob("*") if p.is_file())
    selected = sorted(set(selected))
    if any(p.is_symlink() for p in selected):
        raise ValueError("Evidence archive accepts regular files only")
    output.parent.mkdir(parents=True, exist_ok=True)
    files = [{"path": str(p.relative_to(root)), "bytes": p.stat().st_size, "sha256": sha(p)}
             for p in selected]
    with output.open("xb") as stream:
        with gzip.GzipFile(filename="", fileobj=stream, mode="wb", mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w") as archive:
                for path in selected:
                    info = archive.gettarinfo(str(path), arcname=str(path.relative_to(root)))
                    info.uid = info.gid = info.mtime = 0
                    info.uname = info.gname = ""
                    with path.open("rb") as source:
                        archive.addfile(info, source)
    manifest = {"schema": "pft_six.lossless_evidence.v1", "archive": output.name,
                "archive_bytes": output.stat().st_size, "archive_sha256": sha(output),
                "files": files, "file_count": len(files),
                "uncompressed_file_bytes": sum(f["bytes"] for f in files),
                "dataset_kind": "synthetic_control_only",
                "scope": "Original bytes, including failed cases and intentional tamper controls; no real user records.",
                "replay_paths": "Old absolute paths in receipts document the actual run. Extracted candidates are also verified by relative paths.",
                "source_sha256": {p.name: sha(p) for p in sorted(root.glob("*.py"))}}
    with output.with_name("evidence_manifest.json").open("x") as stream:
        json.dump(manifest, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: v for k, v in manifest.items() if k not in ("files", "source_sha256")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    package(Path(__file__).resolve().parent, args.output.resolve())
