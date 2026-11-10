"""Reuse the reviewed one-edge repair for the exact failed CTRL candidate lock."""

import argparse
import hashlib
import json
from pathlib import Path
import tomllib


BEFORE = "c3d1fec8c1291a9689d91c6fda6b7f593e95d1416730b00decf43e9dd31166a0"
AFTER = "98b3767c6e74bf6eeb5894db760259dbc400cbfd0685af8ad915c92d25408d69"


def aligned_bytes(original):
    if hashlib.sha256(original).hexdigest() != BEFORE:
        raise ValueError("candidate lock differs from the retained failed graph")
    start = original.index(b'[[package]]\nname = "bindgen"\nversion = "0.73.2"\n')
    end = original.index(b"\n[[package]]", start + 1)
    block = original[start:end]
    old = b' "syn 3.0.9",\n'
    if block.count(old) != 1:
        raise ValueError("expected one bindgen Syn edge")
    repaired = (
        original[:start] + block.replace(old, b' "syn 2.0.119",\n') + original[end:]
    )
    if hashlib.sha256(repaired).hexdigest() != AFTER:
        raise ValueError("repair differs from the reviewed common lock blob")
    before = tomllib.loads(original.decode())
    after = tomllib.loads(repaired.decode())
    expected = json.loads(json.dumps(before))
    matches = [
        p
        for p in expected["package"]
        if (p["name"], p["version"]) == ("bindgen", "0.73.2")
    ]
    if len(matches) != 1:
        raise ValueError("expected one bindgen package")
    deps = matches[0]["dependencies"]
    deps[deps.index("syn 3.0.9")] = "syn 2.0.119"
    if after != expected:
        raise ValueError("unexpected package or dependency change")
    return repaired


def align(lock, output):
    with lock.open("rb") as source:
        original = source.read(1024 * 1024 + 1)
    if len(original) > 1024 * 1024:
        raise ValueError("candidate lock exceeds this profile")
    repaired = aligned_bytes(original)
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": "hepta.ctrl.bindgen-syn-alignment.v1",
        "original_ctrl_run_id": 42776841937,
        "original_ctrl_artifact_id": 13747333102,
        "before_sha256": BEFORE,
        "after_sha256": AFTER,
        "reused_source": "5019fc36f636850902d940ad2152cde1c73cb085",
        "reused_cargo_lock_git_blob": "025813e20504f31d12dae2092a0807a1a4066419",
        "change": "bindgen 0.73.2: syn 3.0.9 -> syn 2.0.119",
        "package_versions_and_checksums_changed": False,
        "locked_metadata_qualification": "REQUIRED_AFTER_ALIGNMENT",
        "production_adoption": False,
        "status": "PENDING_LOCK_WRITE",
    }
    output.write_text(json.dumps(report, indent=2) + "\n")
    lock.write_bytes(repaired)
    report["status"] = "ALIGNED_NOT_QUALIFIED"
    output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    align(args.lock, args.output)
