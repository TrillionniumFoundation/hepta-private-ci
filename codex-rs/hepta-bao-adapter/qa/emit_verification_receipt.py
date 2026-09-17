#!/usr/bin/env python3
"""Emit a secret-free exact-candidate receipt from already executed CI records."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    source_sha = os.environ.get("SOURCE_SHA", "").strip()
    tested_sha = os.environ.get("TESTED_SHA", "").strip()
    lane = os.environ.get("HEPTA_CI_LANE", "").strip()
    if not source_sha or not tested_sha or not lane:
        raise SystemExit("SOURCE_SHA, TESTED_SHA and HEPTA_CI_LANE are required")
    if git("rev-parse", "HEAD") != tested_sha:
        raise SystemExit("checked-out HEAD does not match TESTED_SHA")
    if git("status", "--porcelain", "--untracked-files=no"):
        raise SystemExit("tracked source is dirty; refusing to attest candidate")

    records_dir = pathlib.Path(args.records_dir)
    required = ["format.json", "owner-test.json", "clippy.json"]
    record_hashes: dict[str, str] = {}
    for name in required:
        path = records_dir / name
        if not path.is_file():
            raise SystemExit(f"missing executed command record: {path}")
        # Parse once so malformed/truncated command evidence cannot be attested.
        json.loads(path.read_text(encoding="utf-8"))
        record_hashes[name] = sha256_file(path)

    external_path = ROOT / "external" / "HeptaBao" / "EXTERNAL_SOURCE.json"
    external = json.loads(external_path.read_text(encoding="utf-8"))
    receipt = {
        "schema": "hepta.secrets-heptabao-verification-receipt.v1",
        "module": "secrets.heptabao",
        "source_sha": source_sha,
        "tested_sha": tested_sha,
        "tested_tree": git("rev-parse", "HEAD^{tree}"),
        "parents": git("show", "-s", "--format=%P", "HEAD").split(),
        "lane": lane,
        "external_heptabao": {
            "repository": external["repository"],
            "commit": external["commit"],
            "openbao_compatibility_target": external["openbao_compatibility_target"],
        },
        "command_record_sha256": record_hashes,
        "secret_material_present": False,
        "claims": {
            "source_candidate_compiled_and_tested": True,
            "strict_clippy_passed": True,
            "format_check_passed": True,
            "production_activation": False,
            "operator_acceptance": False,
            "release_authority": False,
        },
    }
    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
