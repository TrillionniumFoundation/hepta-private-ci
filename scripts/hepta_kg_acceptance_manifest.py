#!/usr/bin/env python3
"""Issue and verify fail-closed knowledge.graph acceptance manifests.

The repository may issue an unsigned request, but it cannot accept itself.
Acceptance is valid only when an allowed independent identity signs the exact
candidate commit/tree plus workflow, executed harness, dependency-lock, schema
and complete source fingerprints. Any bound change invalidates the manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "hepta.knowledge-graph.acceptance.v1"
SIGNATURE_NAMESPACE = "hepta-knowledge-graph-acceptance"
DEFAULT_IMPLEMENTATION_OWNER = "knowledge-graph"

WORKFLOW_PATH = ".github/workflows/hepta-knowledge-graph-qualification.yml"
HARNESS_PATH = "scripts/hepta_kg_qualification_lane.sh"
LOCK_PATH = "codex-rs/Cargo.lock"
SCHEMA_PATH = "codex-rs/hepta-memory/migrations/0013_kg_generation_semantics.sql"
MAP_PATH = "docs/modules/knowledge.graph/IMPLEMENTATION_MAP.json"

FINGERPRINT_ROOTS = (
    ".github/actions/hepta-synthetic-merge",
    ".github/workflows/hepta-kg-abc-execution.yml",
    WORKFLOW_PATH,
    "codex-rs/hepta-kg",
    "codex-rs/hepta-memory/src/cognitive_intelligence_writer.rs",
    "codex-rs/hepta-memory/src/cognitive_kg_store.rs",
    "codex-rs/hepta-memory/src/cognitive_retrieval.rs",
    "codex-rs/hepta-memory/src/cognitive_store.rs",
    SCHEMA_PATH,
    "codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs",
    "codex-rs/hepta-prompt-optimizer",
    "codex-rs/hepta-prompt-registry",
    LOCK_PATH,
    MAP_PATH,
    "docs/modules/knowledge.graph/CURRENT_STATUS.json",
    "docs/modules/knowledge.graph/CURRENT_STATUS.md",
    "docs/modules/knowledge.graph/TECHNICAL.md",
    "scripts/hepta_kg_acceptance_manifest.py",
    HARNESS_PATH,
    "scripts/hepta_kg_status.py",
)


class AcceptanceError(ValueError):
    """A fail-closed acceptance validation failure."""


def run_git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args],
        text=True,
        stderr=subprocess.STDOUT,
    ).strip()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_clean(root: Path) -> None:
    status = run_git(root, "status", "--porcelain", "--untracked-files=no")
    if status:
        raise AcceptanceError("candidate checkout is not clean")


def tracked_fingerprint_paths(root: Path) -> list[str]:
    tracked = run_git(root, "ls-files", "-z")
    paths = [value for value in tracked.split("\0") if value]
    selected = [
        path
        for path in paths
        if any(
            path == prefix or path.startswith(prefix.rstrip("/") + "/")
            for prefix in FINGERPRINT_ROOTS
        )
    ]
    if not selected:
        raise AcceptanceError("knowledge.graph fingerprint path set is empty")
    return sorted(selected)


def source_manifest(root: Path) -> tuple[list[dict[str, Any]], str]:
    entries: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    for relative in tracked_fingerprint_paths(root):
        path = root / relative
        if not path.is_file():
            raise AcceptanceError(f"tracked fingerprint path is not a file: {relative}")
        blob = run_git(root, "rev-parse", f"HEAD:{relative}")
        size = path.stat().st_size
        entry = {"path": relative, "blob": blob, "bytes": size}
        entries.append(entry)
        encoded = json.dumps(entry, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return entries, digest.hexdigest()


def candidate_fingerprint(root: Path) -> dict[str, Any]:
    require_clean(root)
    entries, manifest_sha256 = source_manifest(root)

    def required_digest(relative: str) -> str:
        path = root / relative
        if not path.is_file():
            raise AcceptanceError(f"required acceptance input is missing: {relative}")
        return sha256_file(path)

    return {
        "commit": run_git(root, "rev-parse", "HEAD"),
        "tree": run_git(root, "rev-parse", "HEAD^{tree}"),
        "workflowBlob": run_git(root, "rev-parse", f"HEAD:{WORKFLOW_PATH}"),
        "qualificationHarnessBlob": run_git(root, "rev-parse", f"HEAD:{HARNESS_PATH}"),
        "qualificationHarnessSha256": required_digest(HARNESS_PATH),
        "cargoLockSha256": required_digest(LOCK_PATH),
        "schemaSha256": required_digest(SCHEMA_PATH),
        "implementationMapSha256": required_digest(MAP_PATH),
        "sourceManifestSha256": manifest_sha256,
        "sourceManifest": entries,
    }


def canonical_payload(manifest: dict[str, Any]) -> bytes:
    unsigned = dict(manifest)
    unsigned.pop("signature", None)
    return (
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def load_receipts(paths: Iterable[Path]) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    for path in paths:
        raw = path.read_bytes()
        row = json.loads(raw)
        if row.get("schema") != "hepta.knowledge-graph.qualification-receipt.v1":
            raise AcceptanceError(f"unsupported qualification receipt: {path}")
        parents = row.get("testedParents", [])
        if not isinstance(parents, list) or any(not isinstance(value, str) for value in parents):
            raise AcceptanceError(f"invalid testedParents in qualification receipt: {path}")
        receipts.append(
            {
                "lane": row.get("lane"),
                "testedCommit": row.get("testedCommit"),
                "testedTree": row.get("testedTree"),
                "testedParents": parents,
                "sourceCommit": row.get("sourceCommit"),
                "baseCommit": row.get("baseCommit"),
                "testedWorkflowBlob": row.get("testedWorkflowBlob", row.get("workflowBlob")),
                "sourceWorkflowBlob": row.get("sourceWorkflowBlob"),
                "sourceHarnessBlob": row.get("sourceHarnessBlob"),
                "executedHarnessSha256": row.get("executedHarnessSha256"),
                "cargoLockSha256": row.get("cargoLockSha256"),
                "schemaSha256": row.get("kgSchemaSha256"),
                "allRequiredPassed": row.get("allRequiredPassed") is True,
                "receiptSha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    receipts.sort(key=lambda value: str(value.get("lane")))
    return receipts


def issue_request(root: Path, receipt_paths: Iterable[Path]) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "candidate": candidate_fingerprint(root),
        "qualificationReceipts": load_receipts(receipt_paths),
        "acceptance": {
            "status": "pending_independent_signature",
            "signerIdentity": None,
            "signerRole": "independent_operator",
        },
        "implementationOwner": DEFAULT_IMPLEMENTATION_OWNER,
        "activation": False,
        "release": False,
    }


def require_lane_receipts(manifest: dict[str, Any], candidate: dict[str, Any]) -> None:
    rows = manifest.get("qualificationReceipts")
    if not isinstance(rows, list):
        raise AcceptanceError("qualificationReceipts must be a list")
    by_lane: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("lane"), str):
            raise AcceptanceError("invalid qualification receipt row")
        lane = row["lane"]
        if lane in by_lane:
            raise AcceptanceError(f"duplicate qualification lane: {lane}")
        by_lane[lane] = row
    required_lanes = {"source-head", "main-head", "base-merge"}
    if set(by_lane) != required_lanes:
        missing = sorted(required_lanes.difference(by_lane))
        extra = sorted(set(by_lane).difference(required_lanes))
        raise AcceptanceError(f"qualification lane set mismatch: missing={missing}, extra={extra}")

    for lane, row in by_lane.items():
        if row.get("allRequiredPassed") is not True:
            raise AcceptanceError(f"qualification lane did not pass: {lane}")
        if row.get("sourceCommit") != candidate["commit"]:
            raise AcceptanceError(f"{lane} receipt does not bind the candidate source commit")
        if row.get("sourceWorkflowBlob") != candidate["workflowBlob"]:
            raise AcceptanceError(f"{lane} receipt source workflow binding drifted")
        if row.get("sourceHarnessBlob") != candidate["qualificationHarnessBlob"]:
            raise AcceptanceError(f"{lane} receipt source harness binding drifted")
        if row.get("executedHarnessSha256") != candidate["qualificationHarnessSha256"]:
            raise AcceptanceError(f"{lane} executed a different qualification harness")
        if not isinstance(row.get("testedCommit"), str) or not isinstance(
            row.get("testedTree"), str
        ):
            raise AcceptanceError(f"{lane} receipt is missing tested identity")

    source = by_lane["source-head"]
    if source.get("testedCommit") != candidate["commit"]:
        raise AcceptanceError("source-head receipt does not bind the candidate commit")
    if source.get("testedTree") != candidate["tree"]:
        raise AcceptanceError("source-head receipt does not bind the candidate tree")
    if source.get("testedWorkflowBlob") != candidate["workflowBlob"]:
        raise AcceptanceError("source-head tested workflow binding drifted")
    if source.get("cargoLockSha256") != candidate["cargoLockSha256"]:
        raise AcceptanceError("source-head receipt dependency lock drifted")
    if source.get("schemaSha256") != candidate["schemaSha256"]:
        raise AcceptanceError("source-head receipt schema drifted")

    main = by_lane["main-head"]
    if main.get("testedCommit") != main.get("baseCommit"):
        raise AcceptanceError("main-head receipt did not execute the declared base commit")

    merge = by_lane["base-merge"]
    if merge.get("baseCommit") != main.get("testedCommit"):
        raise AcceptanceError("base-merge and main-head receipts disagree on the base commit")
    parents = merge.get("testedParents")
    if not isinstance(parents, list) or set(parents) != {
        candidate["commit"],
        main["testedCommit"],
    }:
        raise AcceptanceError("base-merge receipt does not bind both source and base parents")


def verify_manifest(
    root: Path,
    manifest_path: Path,
    signature_path: Path,
    allowed_signers_path: Path,
    identity: str,
    forbidden_identities: Iterable[str] = (),
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != SCHEMA:
        raise AcceptanceError("unsupported acceptance schema")
    if manifest.get("activation") is not False or manifest.get("release") is not False:
        raise AcceptanceError("acceptance manifest cannot self-activate or self-release")

    acceptance = manifest.get("acceptance")
    if not isinstance(acceptance, dict) or acceptance.get("status") != "accepted":
        raise AcceptanceError("operator acceptance is not accepted")
    if acceptance.get("signerRole") != "independent_operator":
        raise AcceptanceError("acceptance signer is not an independent operator")
    if acceptance.get("signerIdentity") != identity:
        raise AcceptanceError("acceptance signer identity mismatch")

    normalized_identity = identity.casefold()
    forbidden = {DEFAULT_IMPLEMENTATION_OWNER.casefold()}
    forbidden.update(value.casefold() for value in forbidden_identities)
    if normalized_identity in forbidden:
        raise AcceptanceError("implementation identity cannot sign its own acceptance")

    observed = candidate_fingerprint(root)
    expected = manifest.get("candidate")
    if expected != observed:
        raise AcceptanceError("candidate fingerprint changed after acceptance")

    require_lane_receipts(manifest, observed)

    payload = canonical_payload(manifest)
    command = [
        "ssh-keygen",
        "-Y",
        "verify",
        "-f",
        str(allowed_signers_path),
        "-I",
        identity,
        "-n",
        SIGNATURE_NAMESPACE,
        "-s",
        str(signature_path),
    ]
    result = subprocess.run(
        command,
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode != 0:
        raise AcceptanceError(
            "independent acceptance signature verification failed: "
            + result.stdout.decode("utf-8", errors="replace").strip()
        )
    return {
        "status": "PASS_HEPTA_KG_INDEPENDENT_ACCEPTANCE",
        "candidate": observed,
        "signerIdentity": identity,
        "activation": False,
        "release": False,
    }


def write_json(path: Path | None, value: dict[str, Any]) -> None:
    payload = json.dumps(value, sort_keys=True, indent=2) + "\n"
    if path is None:
        sys.stdout.write(payload)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    subparsers = parser.add_subparsers(dest="command", required=True)

    request = subparsers.add_parser("request")
    request.add_argument("--receipt", type=Path, action="append", default=[])
    request.add_argument("--output", type=Path)

    fingerprint = subparsers.add_parser("fingerprint")
    fingerprint.add_argument("--output", type=Path)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--signature", type=Path, required=True)
    verify.add_argument("--allowed-signers", type=Path, required=True)
    verify.add_argument("--identity", required=True)
    verify.add_argument("--forbid-identity", action="append", default=[])

    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.command == "request":
            write_json(args.output, issue_request(root, args.receipt))
        elif args.command == "fingerprint":
            write_json(args.output, candidate_fingerprint(root))
        else:
            result = verify_manifest(
                root,
                args.manifest,
                args.signature,
                args.allowed_signers,
                args.identity,
                args.forbid_identity,
            )
            write_json(None, result)
    except (
        AcceptanceError,
        OSError,
        subprocess.CalledProcessError,
        json.JSONDecodeError,
    ) as exc:
        print(f"FAIL_HEPTA_KG_ACCEPTANCE: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
