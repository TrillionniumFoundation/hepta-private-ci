#!/usr/bin/env python3
"""Verify/materialize the retired exact JS regression oracle in a temporary tree."""
import argparse
import hashlib
import io
import json
import re
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parent.parent
ORACLE = ROOT / "qualification/ui-control/oracle"


def verified_members():
    manifest = json.loads((ORACLE / "MANIFEST.json").read_text())
    if manifest["activeProductEntrypoint"] is not False:
        raise ValueError("oracle must never become a product entrypoint")
    name = manifest["archive"]
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9._-]+\.tar\.gz", name):
        raise ValueError("invalid archive path")
    archive = (ORACLE / name).read_bytes()
    if len(archive) != manifest["archiveBytes"] or hashlib.sha256(archive).hexdigest() != manifest["archiveSha256"]:
        raise ValueError("oracle archive identity mismatch")
    # Archive member addresses are component arrays, not live repository links.
    expected = {"/".join(row["pathComponents"]): row for row in manifest["files"]}
    if len(expected) != len(manifest["files"]) or len(expected) > 512:
        raise ValueError("invalid closed oracle inventory")
    observed = {}
    total = 0
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as stream:
        for member in stream:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or "\\" in member.name or ":" in member.name:
                raise ValueError("oracle path escaped its temporary root")
            if member.isdir():
                continue
            if not member.isfile() or member.name in observed or member.name not in expected:
                raise ValueError("unexpected oracle member")
            total += member.size
            if member.size > 4 * 1024 * 1024 or total > 16 * 1024 * 1024:
                raise ValueError("oracle exceeds materialization budget")
            data = stream.extractfile(member).read()
            row = expected[member.name]
            if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
                raise ValueError("oracle member identity mismatch")
            observed[member.name] = data
    if set(observed) != set(expected):
        raise ValueError("oracle inventory is incomplete")
    return manifest, observed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true", help="run the unchanged retired Node unit suite")
    args = parser.parse_args()
    manifest, members = verified_members()
    print(f"Verified {len(members)} non-product oracle files from {manifest['sourceCommit']}", flush=True)
    if args.test:
        with tempfile.TemporaryDirectory(prefix="hepta-ui-control-oracle-") as directory:
            root = Path(directory)
            for name, data in members.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            result = subprocess.run(["npm", "test", "--prefix", str(root / "apps/hepta-control-ui")], cwd=root, check=False)
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
