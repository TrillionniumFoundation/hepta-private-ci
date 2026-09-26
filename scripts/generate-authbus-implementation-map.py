#!/usr/bin/env python3
"""Generate the non-self-referential auth.authbus implementation map.

The map binds to the exact code commit tested before the attestation/map commit.
The subsequent qualification receipt binds the attestation commit and workflow
run. This avoids pretending a file can contain the SHA of the commit that also
contains that file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "docs/modules/auth.authbus/IMPLEMENTATION_MAP.json"
SOURCE_PATHS = [
    "codex-rs/hepta-authbus/Cargo.toml",
    "codex-rs/hepta-authbus/src/lib.rs",
    "codex-rs/hepta-authbus/src/authority.rs",
    "codex-rs/hepta-authbus/src/authority_store.rs",
    "codex-rs/hepta-authbus/src/host.rs",
    "codex-rs/hepta-authbus/src/issuer_registry.rs",
    "codex-rs/hepta-authbus/src/owner_lock.rs",
    "codex-rs/hepta-authbus/src/policy.rs",
    "codex-rs/hepta-authbus/src/quota.rs",
    "codex-rs/hepta-authbus/src/quota_store.rs",
    "codex-rs/hepta-authbus/src/recovery.rs",
    "codex-rs/hepta-authbus/src/settlement.rs",
    "codex-rs/hepta-authbus/src/settlement_store.rs",
    "codex-rs/hepta-authbus/src/signed.rs",
    "codex-rs/hepta-authbus/src/trust.rs",
    "codex-rs/hepta-authbus/src/trust_store.rs",
    "codex-rs/hepta-authbus/migrations/0001_authority.sql",
    "codex-rs/hepta-authbus/migrations/0002_quota_reservation.sql",
    "codex-rs/hepta-authbus/migrations/0003_issuer_registry.sql",
    "codex-rs/hepta-authbus/migrations/0004_recovery_retention.sql",
]
PRODUCT_CALLERS = {
    "agentdMessageIngress": [
        "codex-rs/hepta-agentd/src/authbus_ingress.rs",
        "codex-rs/hepta-agentd/src/authbus_trust.rs",
        "codex-rs/hepta-agentd/src/authbus_dispatch.rs",
    ],
    "kernelEvidenceOutbox": [
        "codex-rs/hepta-evidence/src/authbus_outbox.rs",
        "codex-rs/hepta-evidence/src/authbus_outbox_worker.rs",
    ],
    "baoFinalUse": [
        "codex-rs/hepta-bao-adapter/src/https_consumer.rs",
    ],
}
DOCS = [
    "docs/modules/auth.authbus/TECHNICAL.md",
    "docs/modules/auth.authbus/THREAT_MODEL.md",
    "docs/modules/auth.authbus/OPERATIONS.md",
    "docs/modules/auth.authbus/SLO.md",
    "docs/modules/auth.authbus/RECOVERY.md",
    "docs/modules/auth.authbus/KEY_ROTATION.md",
    "docs/modules/auth.authbus/SCHEMA_COMPATIBILITY.md",
    "docs/modules/auth.authbus/PRODUCTION_TOPOLOGY.md",
    "docs/modules/auth.authbus/OBSERVABILITY.md",
    "docs/modules/auth.authbus/observability/metrics.yaml",
    "docs/modules/auth.authbus/observability/alerts.yaml",
    "docs/modules/auth.authbus/observability/dashboard.json",
]


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def digest_files(paths: list[str]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(paths):
        target = ROOT / relative
        if not target.is_file():
            raise SystemExit(f"missing implementation-map input: {relative}")
        data = target.read_bytes()
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def public_host_operations() -> list[str]:
    source = (ROOT / "codex-rs/hepta-authbus/src/host.rs").read_text()
    operations = re.findall(r"(?m)^    pub async fn ([a-zA-Z0-9_]+)\(", source)
    expected = {
        "open",
        "sync_checkpoint",
        "enroll_issuer",
        "rotate_issuer",
        "revoke_issuer",
        "retire_issuer_epoch",
        "observe_trusted_time_attestation",
        "message_issuer",
        "create_policy",
        "replace_policy",
        "revoke_policy",
        "retire_policy",
        "authorize",
        "create_quota",
        "replace_quota",
        "reserve",
        "mark_dispatch_attempted",
        "mark_indeterminate",
        "cancel_reservation",
        "reconcile_expired_reservation",
        "sweep_expired_reservations",
        "settle",
        "compact_terminal_reservations",
        "quota_snapshot",
        "reservation",
        "authority_frontier_digest",
    }
    missing = sorted(expected.difference(operations))
    if missing:
        raise SystemExit(f"host operation inventory is incomplete: {missing}")
    return sorted(set(operations))


def public_exports() -> list[str]:
    source = (ROOT / "codex-rs/hepta-authbus/src/lib.rs").read_text()
    exports = re.findall(r"(?m)^pub use [^;]+::([A-Za-z0-9_]+);", source)
    forbidden = {"AuthBusAuthorityStore", "SettlementIssuerRegistration"}
    leaked = sorted(forbidden.intersection(exports))
    if leaked:
        raise SystemExit(f"forbidden public exports: {leaked}")
    return sorted(set(exports))


def require_callsites() -> dict[str, list[str]]:
    markers = {
        "agentdMessageIngress": ["IssuerRegistration", "enqueue_authbus_message"],
        "kernelEvidenceOutbox": ["IssuerRegistration", "claim_authbus_delivery"],
        "baoFinalUse": ["AuthBusAuthorityHost", "mark_dispatch_attempted", ".settle("],
    }
    result: dict[str, list[str]] = {}
    for name, paths in PRODUCT_CALLERS.items():
        contents = "\n".join((ROOT / path).read_text() for path in paths)
        missing = [marker for marker in markers[name] if marker not in contents]
        if missing:
            raise SystemExit(f"{name} missing product-call markers: {missing}")
        result[name] = paths
    return result


def build(args: argparse.Namespace) -> dict[str, object]:
    code_commit = args.code_commit or os.environ.get("AUTHBUS_CODE_COMMIT") or git("rev-parse", "HEAD")
    code_tree = args.code_tree or os.environ.get("AUTHBUS_CODE_TREE") or git("rev-parse", f"{code_commit}^{{tree}}")
    if not re.fullmatch(r"[0-9a-f]{40}", code_commit):
        raise SystemExit("code commit must be a 40-character lowercase SHA")
    if not re.fullmatch(r"[0-9a-f]{40}", code_tree):
        raise SystemExit("code tree must be a 40-character lowercase SHA")
    implementation_digest = digest_files(SOURCE_PATHS)
    schema_paths = [path for path in SOURCE_PATHS if "/migrations/" in path]
    return {
        "schemaVersion": 2,
        "module": "auth.authbus",
        "generated": True,
        "binding": {
            "codeCommit": code_commit,
            "codeTree": code_tree,
            "implementationSha256": implementation_digest,
            "migrationSha256": digest_files(schema_paths),
            "qualificationReceipt": "qualification/authbus-exact-head/RECEIPT.json",
            "selfReferencePolicy": "map attests the preceding code commit; receipt attests the exact workflow commit",
        },
        "authority": {
            "writer": "AuthBusAuthorityHost",
            "rawWriterPublic": False,
            "singleOwnerFence": "AuthorityOwnerLock/flock",
            "checkpoint": "owner-fenced external rollback witness",
            "issuerResolution": {
                "message": "VerifiedIssuerRegistry sealed handle",
                "settlement": "same-transaction SQLite registry lookup",
                "trustedTime": "same-authority SQLite registry lookup",
            },
        },
        "publicHostOperations": public_host_operations(),
        "publicExports": public_exports(),
        "productCallers": require_callsites(),
        "lifecycle": {
            "boundedExpiredReservationSweep": True,
            "dispatchAttemptedExpiry": "indeterminate",
            "heldExpiry": "release exactly once",
            "terminalCompaction": True,
        },
        "closedWorldChecks": [
            "scripts/check-authbus-api-inventory.py",
            "forbid public raw writer",
            "forbid public trusted issuer fields",
            "forbid production test-support dependency",
        ],
        "qualification": {
            "ownerAllTargets": "cargo test -p codex-hepta-authbus --all-targets",
            "modernQualification": "cargo test -p codex-hepta-authbus-p1-3-qualification --all-targets",
            "evidenceCaller": "cargo test -p codex-hepta-evidence --lib authbus",
            "baoCaller": "cargo test -p codex-hepta-bao-adapter --lib authbus",
            "agentdComposition": "cargo check -p codex-hepta-agentd",
            "strictClippy": "cargo clippy -p codex-hepta-authbus --all-targets -- -D warnings",
            "syntheticMerge": "required",
            "skippedOrCancelledIsSuccess": False,
        },
        "sourcePaths": SOURCE_PATHS,
        "documentation": DOCS,
        "status": {
            "source": "implemented_pending_exact_head_receipt",
            "semanticReview": "trust_and_owner_boundaries_encoded",
            "productionActivation": "blocked_until_green_receipt_and_environment_provider_binding",
        },
    }


def encoded(value: dict[str, object]) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--code-commit")
    parser.add_argument("--code-tree")
    args = parser.parse_args()
    generated = encoded(build(args))
    if args.write:
        MAP_PATH.write_text(generated)
        print(MAP_PATH.relative_to(ROOT))
        return 0
    if not MAP_PATH.is_file():
        print(f"missing {MAP_PATH.relative_to(ROOT)}", file=sys.stderr)
        return 1
    current = MAP_PATH.read_text()
    if current != generated:
        print("auth.authbus implementation map is stale", file=sys.stderr)
        return 1
    print("auth.authbus implementation map: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
