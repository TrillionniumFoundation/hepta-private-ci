#!/usr/bin/env python3
"""Rebuild and verify the original evidence ZIP without executing its contents."""

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=ROOT / "local-evidence-manifest.json")
    parser.add_argument("--parts-dir", type=Path, default=ROOT / "local-evidence")
    args = parser.parse_args()
    output = args.output.resolve()
    manifest = json.loads(args.manifest.read_text())
    parts = []
    for row in manifest["parts"]:
        name = Path(row["path"])
        if name.name != str(name):
            raise ValueError("unsafe part path")
        content = (args.parts_dir / name).read_bytes()
        if len(content) != row["bytes"] or hashlib.sha256(content).hexdigest() != row["sha256"]:
            raise ValueError(f"part differs: {name}")
        parts.append(b"".join(content.split()))
    data = base64.b64decode(b"".join(parts), validate=True)
    if len(data) != manifest["bytes"] or hashlib.sha256(data).hexdigest() != manifest["sha256"]:
        raise ValueError("reconstructed ZIP differs")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if archive.testzip() is not None:
            raise ValueError("invalid ZIP CRC")
        rows = json.loads(archive.read("SHA256SUMS.json"))
        if set(archive.namelist()) != {x["path"] for x in rows} | {"SHA256SUMS.json"}:
            raise ValueError("ZIP member set differs")
        for row in rows:
            content = archive.read(row["path"])
            if len(content) != row["bytes"] or hashlib.sha256(content).hexdigest() != row["sha256"]:
                raise ValueError(f"ZIP member differs: {row['path']}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    print(json.dumps({"file": str(output), "sha256": manifest["sha256"], "bytes": len(data), "hashed_members": len(rows)}, indent=2))


if __name__ == "__main__":
    main()
