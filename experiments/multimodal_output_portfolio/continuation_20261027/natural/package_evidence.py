"""Package all experiment media and executed outputs once per content hash."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile
import time


def package(workspace, output, limit_bytes):
    code = Path(__file__).resolve().parent
    recovery = json.loads((code/"evidence/MODEL_RECOVERY.json").read_text())
    external = {row["relative_path"] for row in recovery["models"]}
    excluded, records, blobs = [], [], {}
    roots = [workspace/name for name in ("natural-continuation-assets", "natural-continuation-runs", "natural-continuation-staging")]+[code]
    for root in roots:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if path.is_symlink():
                raise ValueError("Unexpected evidence symlink")
            relative = str(path.relative_to(workspace))
            if relative in external or path.name.startswith(".model.bin."):
                excluded.append({"path": relative, "bytes": path.stat().st_size,
                    "reason": "external pinned model weights" if relative in external else "unmanifested foreign partial model file"})
                continue
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            size = path.stat().st_size
            records.append({"path": relative, "sha256": digest, "bytes": size})
            blobs.setdefault(digest, path)
    index = {"schema": "hepta.ndu.natural.content-addressed-archive.v1", "created_ns": time.time_ns(),
        "recorded_workspace": str(workspace), "paths": records, "external_models": recovery["models"],
        "excluded": excluded, "restore_helper_logical_path": str((code/"restore_evidence.py").relative_to(workspace)),
        "scope": "All selected source media, intermediate/final experiment outputs, failed attempts, fitted checkpoints and code snapshots; two explicitly listed public neural weight files remain external."}
    data = (json.dumps(index, indent=2, sort_keys=True)+"\n").encode()
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz", compresslevel=6) as archive:
        member = tarfile.TarInfo("INDEX.json")
        member.size = len(data)
        member.mtime = 0
        archive.addfile(member, io.BytesIO(data))
        for digest, path in sorted(blobs.items()):
            member = tarfile.TarInfo("blobs/"+digest)
            member.size = path.stat().st_size
            member.mtime = 0
            with path.open("rb") as stream:
                archive.addfile(member, stream)
            if output.stat().st_size > limit_bytes:
                raise ValueError("Archive resource limit exceeded; partial archive retained")
    if output.stat().st_size > limit_bytes:
        raise ValueError("Final archive exceeds resource limit")
    with output.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    sidecar = output.with_suffix(output.suffix+".index.json")
    sidecar.write_bytes(data)
    return {"archive": str(output), "archive_bytes": output.stat().st_size, "archive_sha256": checksum,
        "index": str(sidecar), "index_sha256": hashlib.sha256(data).hexdigest(),
        "logical_paths": len(records), "unique_blobs": len(blobs),
        "logical_bytes": sum(r["bytes"] for r in records), "external_model_bytes": sum(r["bytes"] for r in recovery["models"])}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit-bytes", type=int, default=175_000_000)
    args = parser.parse_args()
    print(json.dumps(package(args.workspace.resolve(), args.output.resolve(), args.limit_bytes), indent=2))
