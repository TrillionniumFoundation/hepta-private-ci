#!/usr/bin/env python3
"""Preserve semantic experiment units under the repository's 512000-byte limit."""
import argparse
import hashlib
import json
import tarfile
from pathlib import Path

LIMIT = 512000


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package(root, output):
    results = root / "results"
    output.mkdir(parents=True, exist_ok=False)
    groups = {p.stem: [p] for p in sorted(results.glob("*.json"))}
    for case in sorted((results / "pft5_final_artifacts").iterdir()):
        groups["pft5_" + case.name + "_inputs"] = sorted(p for p in (case / "data").rglob("*") if p.is_file())
        groups["pft5_" + case.name + "_candidate"] = sorted(
            [p for p in (case / "frozen").rglob("*") if p.is_file()] + [case / "evaluation.json"])
    for case in sorted((results / "pft6_final_artifacts").iterdir()):
        if case.is_dir():
            groups["pft6_" + case.name] = sorted(p for p in case.rglob("*") if p.is_file())
        else:
            groups["pft6_protocol"] = [case]
    groups["pft5_isolation_negative_controls"] = sorted(
        p for p in (results / "pft5_isolation_artifacts").rglob("*") if p.is_file())
    archives, members = [], []
    for name, paths in groups.items():
        target = output / (name + ".tar.xz")
        with tarfile.open(target, "w:xz", preset=6) as archive:
            for path in paths:
                if path.is_symlink():
                    raise ValueError("Regular evidence files required")
                relative = str(path.relative_to(root))
                info = archive.gettarinfo(str(path), arcname=relative)
                info.uid = info.gid = info.mtime = 0
                info.uname = info.gname = ""
                with path.open("rb") as stream:
                    archive.addfile(info, stream)
                members.append({"path": relative, "sha256": sha(path), "bytes": path.stat().st_size,
                                "archive": target.name})
        if target.stat().st_size > LIMIT:
            raise ValueError(f"Semantic evidence unit exceeds repository limit: {name}")
        archives.append({"path": "archives/" + target.name, "sha256": sha(target),
                         "bytes": target.stat().st_size, "members": len(paths)})
    expected = {str(p.relative_to(root)) for paths in groups.values() for p in paths}
    if len(expected) != len(members):
        raise ValueError("Duplicate evidence member")
    for archive in archives:
        with tarfile.open(output.parent / archive["path"], "r:xz") as packed:
            for member in packed:
                original = root / member.name
                if hashlib.sha256(packed.extractfile(member).read()).hexdigest() != sha(original):
                    raise ValueError("Archive roundtrip mismatch")
    manifest = {"schema": "pft_six.semantic_evidence.v2", "max_blob_bytes": LIMIT,
                "archive_count": len(archives), "archive_bytes": sum(a["bytes"] for a in archives),
                "file_count": len(members), "archives": archives, "files": members,
                "roundtrip_all_original_bytes_verified": True,
                "dataset_kind": "synthetic_control_only",
                "organization": "Per experimental case, input fixture or frozen candidate; no opaque byte fragments.",
                "source_sha256": {p.name: sha(p) for p in sorted(root.glob("*.py"))}}
    (output.parent / "evidence_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({k: v for k, v in manifest.items() if k not in ("archives", "files", "source_sha256")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    package(Path(__file__).resolve().parent, args.output_directory.resolve())
