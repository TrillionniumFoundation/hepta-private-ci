"""Package and verify the executed V2 evidence without changing sealed inputs."""

import argparse
import hashlib
import io
import json
import lzma
from pathlib import Path
import tarfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--evidence", type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    workspace, evidence = args.workspace, args.evidence
    archive_path = workspace / "cell-retention-v2-raw.tar.xz"
    members = {}
    for name in ("data", "features", "run", "evaluation"):
        source = workspace / f"cell-retention-v2-{name}"
        for path in sorted(source.rglob("*")):
            if path.is_file():
                members[f"{name}/{path.relative_to(source).as_posix()}"] = path
    for name in ("previous-v1", "recovery", "logs"):
        source = evidence / name
        for path in sorted(source.rglob("*")):
            if path.is_file():
                members[f"{name}/{path.relative_to(source).as_posix()}"] = path
    for name in ("input-audit.json", "input-audit-execution.json", "run-audit.json",
                 "final-audit.json", "math-analysis.json", "math-analysis.py",
                 "math-supplement.json", "protocol.json", "protocol-freeze.json",
                 "source-freeze.json", "source-recovery-validation.json",
                 "publication-source-stages.json", "results.json"):
        members[f"metadata/{name}"] = evidence / name
    manifest = {name: {"bytes": path.stat().st_size, "sha256": digest(path.read_bytes())}
                for name, path in sorted(members.items())}
    with lzma.open(archive_path, "wb", preset=6) as stream:
        with tarfile.open(fileobj=stream, mode="w|") as archive:
            for name, path in sorted(members.items()):
                data = path.read_bytes()
                info = tarfile.TarInfo("cell-retention-v2-raw/" + name)
                info.size = len(data)
                info.mode = 0o644
                info.mtime = 0
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                archive.addfile(info, io.BytesIO(data))
    verified = {}
    with tarfile.open(archive_path, "r:xz") as archive:
        for item in archive:
            assert item.isfile()
            name = item.name.removeprefix("cell-retention-v2-raw/")
            data = archive.extractfile(item).read()
            verified[name] = {"bytes": len(data), "sha256": digest(data)}
    assert verified == manifest
    seal_path = workspace / "cell-retention-v2-run/pre_evaluation_seal.json"
    seal = json.loads(seal_path.read_text())
    for name, expected in seal["files"].items():
        assert verified["run/" + name] == expected, name
    parts_path = evidence / "archive"
    parts_path.mkdir(exist_ok=True)
    assert not list(parts_path.iterdir()), "Use an empty archive output directory"
    raw = archive_path.read_bytes()
    parts = []
    width = 512 * 1024
    for i, start in enumerate(range(0, len(raw), width)):
        data = raw[start:start + width]
        name = f"raw-evidence.tar.xz.part-{i:03d}"
        (parts_path / name).write_bytes(data)
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        parts.append({"path": "archive/" + name, "bytes": len(data),
                      "sha256": digest(data), "git_blob_sha1": blob})
    parts_manifest = {"schema": "hepta.cell-retention-archive-parts.v2",
                      "archive_name": "raw-evidence.tar.xz", "bytes": len(raw),
                      "sha256": digest(raw), "part_size_limit": width, "parts": parts}
    (evidence / "archive-parts.json").write_text(json.dumps(parts_manifest, indent=2) + "\n")
    (evidence / "archive-members.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    (evidence / "archive.sha256").write_text(digest(raw) + "  raw-evidence.tar.xz\n")
    verification = {"schema": "hepta.cell-retention-archive-verification.v2",
                    "archive_sha256": digest(raw), "all_member_hashes_equal": True,
                    "members_verified": len(verified),
                    "sealed_run_files_verified": len(seal["files"]),
                    "sealed_run_bytes_verified": sum(row["bytes"] for row in seal["files"].values()),
                    "pre_evaluation_seal_sha256": digest(seal_path.read_bytes()),
                    "method": "Read every compressed tar member and compare size/SHA256, then compare every pre-evaluation seal entry.",
                    "original_sealed_inputs_modified": False}
    (evidence / "archive-verification.json").write_text(json.dumps(verification, indent=2) + "\n")
    print(json.dumps({"archive_bytes": len(raw), "members": len(verified),
                      "parts": len(parts), "sealed_run_files_verified": len(seal["files"])}))


if __name__ == "__main__":
    main()
