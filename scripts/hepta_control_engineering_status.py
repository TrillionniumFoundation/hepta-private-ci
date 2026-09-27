#!/usr/bin/env python3
"""Generate the canonical tracked and runtime control.engineering status records."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "docs/modules/control.engineering/IMPLEMENTATION_MAP.json"
STATUS = ROOT / "docs/modules/control.engineering/STATUS.json"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _tracked_status() -> dict[str, object]:
    row = _load(MAP)
    boundary = row["claimBoundary"]
    body: dict[str, object] = {
        "schema": "hepta.control-engineering-status.v1",
        "schemaVersion": 1,
        "module": "control.engineering",
        "generatedFrom": "docs/modules/control.engineering/IMPLEMENTATION_MAP.json",
        "sourceBinding": {
            "sourceBase": row["sourceBase"],
            "observedAtHead": row["observedAtHead"],
            "observationIdentityMode": row.get(
                "observationIdentityMode", "ancestor_only"
            ),
            "mappingSourceIdentityMode": row["mappingSourceIdentityMode"],
            "sourceIdentityPolicy": row["sourceIdentityPolicy"],
        },
        "implementation": {
            "sourceRootPresent": bool(row["sourceRootPresent"]),
            "productionImplementation": bool(row["productionImplementation"]),
            "productCallerState": row["productCallerState"],
            "productionWriterState": row["productionWriterState"],
            "claimBoundary": boundary,
        },
        "qualificationPolicy": {
            "pullRequestLanes": ["source-head", "base-merge"],
            "postMergeExactMainReceiptRequired": True,
            "productCallerFailureBlocksCIRequired": True,
            "independentCurrentHeadApprovalRequired": True,
            "mergeMethodForExactBlobChanges": "merge_commit",
        },
        "externalGates": [
            {"gate": gate, "state": "required_external"}
            for gate in row.get("externalEvidenceGates", [])
        ],
        "authority": {
            "runtime": False,
            "merge": False,
            "deployment": False,
            "release": False,
        },
    }
    body["statusDigest"] = _digest(body)
    return body


def _render(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write() -> None:
    STATUS.write_text(_render(_tracked_status()), encoding="utf-8")


def check() -> None:
    expected = _render(_tracked_status())
    actual = STATUS.read_text(encoding="utf-8") if STATUS.is_file() else ""
    if actual != expected:
        raise SystemExit("control.engineering STATUS.json is stale; run --write")


def _git(*args: str) -> str:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_TERMINAL_PROMPT="0",
    )
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def runtime(output: Path) -> None:
    tracked = _tracked_status()
    head = _git("rev-parse", "HEAD")
    tree = _git("rev-parse", "HEAD^{tree}")
    value = {
        "schema": "hepta.control-engineering-runtime-status.v1",
        "trackedStatus": tracked,
        "testedIdentity": {
            "commit": head,
            "tree": tree,
            "parents": _git("show", "-s", "--format=%P", "HEAD").split(),
            "lane": os.environ.get("HEPTA_CI_LANE", "source-head"),
        },
        "workflow": {
            "repository": os.environ.get("GITHUB_REPOSITORY", ""),
            "runId": os.environ.get("GITHUB_RUN_ID", ""),
            "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
        },
    }
    value["runtimeStatusDigest"] = _digest(value)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_render(value), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    group.add_argument("--runtime-output", type=Path)
    args = parser.parse_args()
    if args.write:
        write()
    elif args.check:
        check()
    else:
        runtime(args.runtime_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
