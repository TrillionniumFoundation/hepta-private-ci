#!/usr/bin/env python3
"""Build a deterministic source/SBOM/provenance receipt for secrets.heptabao."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Iterable

ROOT = Path(__file__).resolve().parents[3]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def digest_paths(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.as_posix()):
        relative = path.relative_to(ROOT).as_posix().encode()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        payload = path.read_bytes()
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def files(pattern: str) -> list[Path]:
    return [path for path in ROOT.glob(pattern) if path.is_file()]


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cargo-metadata", required=True, type=Path)
    parser.add_argument("--artifact", action="append", default=[], type=Path)
    args = parser.parse_args()

    metadata = json.loads(args.cargo_metadata.read_text(encoding="utf-8"))
    packages = sorted(
        {
            (package["name"], package["version"], package.get("source"))
            for package in metadata.get("packages", [])
        }
    )
    artifacts = [
        {
            "path": str(path),
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
        }
        for path in args.artifact
        if path.is_file()
    ]
    receipt = {
        "schema": "hepta.secrets-supply-chain-receipt.v1",
        "sourceHeadSha": git("rev-parse", "HEAD"),
        "sourceTreeSha": git("rev-parse", "HEAD^{tree}"),
        "workflowSha": os.environ.get("GITHUB_WORKFLOW_SHA") or os.environ.get("GITHUB_SHA"),
        "workflowRunId": os.environ.get("GITHUB_RUN_ID"),
        "attemptId": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "runnerImage": os.environ.get("ImageOS"),
        "runnerArchitecture": os.environ.get("RUNNER_ARCH"),
        "targetTriple": os.environ.get("TARGET") or "x86_64-unknown-linux-gnu",
        "cargoLockSha256": sha256(ROOT / "codex-rs/Cargo.lock"),
        "migrationHash": digest_paths(files("codex-rs/hepta-bao-adapter/migrations/*.sql")),
        "testSetHash": digest_paths(files("codex-rs/hepta-bao-adapter/qa/test_*.py")),
        "qualificationProfileHash": digest_paths(
            files("codex-rs/hepta-bao-adapter/qa/*.py")
            + files(".github/workflows/secrets-heptabao*.yml")
        ),
        "implementationMapHash": sha256(
            ROOT / "docs/modules/secrets.heptabao/IMPLEMENTATION_MAP.json"
        ),
        "documentationHash": digest_paths(files("docs/modules/secrets.heptabao/**/*")),
        "sourceHash": digest_paths(files("codex-rs/hepta-bao-adapter/src/**/*.rs")),
        "sbom": [
            {"name": name, "version": version, "source": source}
            for name, version, source in packages
        ],
        "artifacts": artifacts,
        "signed": False,
        "released": False,
        "productionQualified": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
