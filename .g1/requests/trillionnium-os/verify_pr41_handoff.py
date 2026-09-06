#!/usr/bin/env python3
"""Verify the PR #41 unsigned handoff and trusted probe boundaries."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Any

EXPECTED_PACKAGE_ID = "sha256:03369d6115e587b0baf207c3d361689913853814465a8e881a2f617d98a62e39"
EXPECTED_HEAD = "7e1e611e7299391cf3d4edc1ded322da0d023cc6"
EXPECTED_MAIN = "968968046d69d000f1f9fe03683e92aa7903cf99"
EXPECTED_PROBE_RUNS = [34022297088, 34022298108]
REASON_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
ROOT = Path(__file__).resolve().parents[3]
REQUEST_ROOT = ROOT / ".g1" / "requests" / "trillionnium-os"
BUNDLE_NAMES = (
    "PR41_L1_ATTESTATION_REQUEST_README.md",
    "pr41-l1-attestation-request.UNSIGNED.json",
    "pr41-l1-attestation-request.validation.json",
    "pr41-l1-source-qualification.json",
)
ALLOWED_CHANGED_PATHS = {
    *(f".g1/requests/trillionnium-os/{name}" for name in BUNDLE_NAMES),
    ".g1/requests/trillionnium-os/pr41-l1-attestation-request.manifest.json",
    ".g1/requests/trillionnium-os/verify_pr41_handoff.py",
    ".github/workflows/self-hosted-desktop-availability.yml",
    ".github/workflows/self-hosted-fleet-availability.yml",
    ".github/workflows/trillionnium-os-attestation-handoff-check.yml",
}
PACKAGE_KEYS = {
    "schema", "version", "package_id", "program_revision", "level",
    "evidence_class", "status", "source", "subject", "lineage", "gaps",
    "artifacts", "observations", "roles", "authorization", "created_at",
    "expires_at", "retention_days", "claim_ceiling", "negative_claims",
    "automatic_redispatch", "public_release", "holds",
}


class VerificationError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def reject_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON member: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> tuple[Any, bytes]:
    metadata = path.lstat()
    require(stat.S_ISREG(metadata.st_mode), f"{path} is not a regular file")
    require(not stat.S_ISLNK(metadata.st_mode), f"{path} is a symlink")
    require(metadata.st_nlink == 1, f"{path} has multiple hard links")
    raw = path.read_bytes()
    require(raw and len(raw) == metadata.st_size, f"{path} changed or is empty")
    try:
        value = json.loads(
            raw,
            object_pairs_hook=reject_pairs,
            parse_constant=lambda item: (_ for _ in ()).throw(
                VerificationError(f"non-finite JSON value: {item}")
            ),
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise VerificationError(f"invalid JSON {path}: {error}") from error
    return value, raw


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, allow_nan=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "--no-replace-objects", "-C", str(root), *args],
        check=True, capture_output=True, text=True, timeout=30,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
    )
    return completed.stdout


def verify_changed_paths(root: Path, base: str, head: str) -> None:
    require(re.fullmatch(r"[0-9a-f]{40}", base) is not None, "invalid base SHA")
    require(re.fullmatch(r"[0-9a-f]{40}", head) is not None, "invalid head SHA")
    require(git(root, "rev-parse", "HEAD").strip() == head, "checkout is not exact head")
    changed = git(
        root, "diff", "--name-only", "--diff-filter=ACDMRTUXB", f"{base}...{head}"
    ).splitlines()
    require(set(changed) == ALLOWED_CHANGED_PATHS, f"changed paths drifted: {sorted(changed)}")
    require(len(changed) == len(set(changed)), "changed paths contain duplicates")
    require(git(root, "status", "--porcelain=v1", "--untracked-files=all") == "",
            "checkout is not clean")


def verify_workflows(root: Path) -> None:
    dispatcher = root / ".github/workflows/trillionnium-os-runner-probe-dispatch.yml"
    inventory = root / ".github/workflows/trillionnium-os-r5-capability-inventory-v30.yml"
    require(not dispatcher.exists(), "candidate dispatcher still exists")
    require(not inventory.exists(), "candidate self-hosted inventory still exists")

    desktop = (root / ".github/workflows/self-hosted-desktop-availability.yml").read_text()
    fleet = (root / ".github/workflows/self-hosted-fleet-availability.yml").read_text()
    check = (root / ".github/workflows/trillionnium-os-attestation-handoff-check.yml").read_text()
    for name, text in {"desktop": desktop, "fleet": fleet, "check": check}.items():
        require("actions: write" not in text, f"{name} grants actions:write")
        require("/dispatches" not in text, f"{name} dispatches workflows")
        require("curl --request POST" not in text, f"{name} contains a write request")
    require("group: trillionnium-android-gpu" in desktop,
            "desktop is not pre-bound to its runner group")
    require("runs-on: [self-hosted" not in check, "candidate check targets self-hosted")
    require("\n  push:" not in desktop and "\n  push:" not in fleet,
            "availability probe is push-triggered")

    grammar = '[[ "$PROBE_REASON" =~ ^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$ ]]'
    for name, text, count in (("desktop", desktop, 1), ("fleet", fleet, 3)):
        expression_lines = [line for line in text.splitlines() if "${{ inputs.reason }}" in line]
        require(len(expression_lines) == count, f"{name} reason expression count drifted")
        require(all("PROBE_REASON:" in line for line in expression_lines),
                f"{name} interpolates reason into shell source")
        require(text.count(grammar) == count, f"{name} reason grammar drifted")
        require(text.count('"$PROBE_REASON"') >= count, f"{name} reason is not quoted")

    positives = ("operator-check", "trillionnium-os-promoted-main-968968", "manual:TICKET/ABC-123")
    negatives = (
        "", "has space", "x';touch/tmp/pwn", "$(touch/tmp/pwn)", "`touch/tmp/pwn`",
        "a\nb", "a\rb", "a;id", "${{github.token}}", 'x"y', "../escape",
    )
    require(all(REASON_RE.fullmatch(value) for value in positives), "safe reason rejected")
    require(not any(REASON_RE.fullmatch(value) for value in negatives), "hostile reason accepted")


def verify_bundle() -> None:
    package, package_raw = load_json(REQUEST_ROOT / "pr41-l1-source-qualification.json")
    request, request_raw = load_json(REQUEST_ROOT / "pr41-l1-attestation-request.UNSIGNED.json")
    validation, validation_raw = load_json(REQUEST_ROOT / "pr41-l1-attestation-request.validation.json")
    manifest, _ = load_json(REQUEST_ROOT / "pr41-l1-attestation-request.manifest.json")

    require(isinstance(package, dict) and set(package) == PACKAGE_KEYS, "package keys drifted")
    require(package["schema"] == "org.trillionnium.g1.evidence-package.v2", "package schema drifted")
    require(package["status"] == "COMPLETE" and package["level"] == "L1",
            "package status or level drifted")
    require(package["source"]["commit"] == EXPECTED_HEAD, "package source head drifted")
    require(package["observations"]["protected_main_commit"] == EXPECTED_MAIN,
            "protected main drifted")
    require(package["automatic_redispatch"] is False, "automatic redispatch widened")
    require(package["public_release"] is False, "public release widened")
    preimage = dict(package)
    preimage["package_id"] = ""
    require(f"sha256:{digest(canonical(preimage))}" == package["package_id"] == EXPECTED_PACKAGE_ID,
            "package ID mismatch")

    observations = package["observations"]
    require(observations["availability_probe_dispatch_count"] == 2, "probe count drifted")
    require(observations["availability_probe_dispatch_workflow_run_ids"] == EXPECTED_PROBE_RUNS,
            "probe run identities drifted")
    require(observations["candidate_controlled_dispatcher_retired"] is True,
            "candidate dispatcher is not retired")
    require(observations["candidate_controlled_self_hosted_inventory_cancelled_before_allocation"] is True,
            "candidate inventory cancellation is not bound")
    for field in (
        "automatic_redispatch_count", "target_evidence_capture_dispatch_count",
        "target_evidence_package_count", "target_authorization_nonce_consumed_count",
    ):
        require(type(observations[field]) is int and observations[field] == 0,
                f"{field} is not integer zero")
    require(observations["probe_dispatch_was_evidence_capture"] is False,
            "availability probe was promoted to evidence")

    package_ref = request["package"]
    require(package_ref["package_id"] == package["package_id"], "request package ID mismatch")
    require(package_ref["bytes"] == len(package_raw), "request package size mismatch")
    require(package_ref["sha256"] == digest(package_raw), "request package digest mismatch")
    require(request["status"] == "UNSIGNED_NOT_PROMOTABLE", "request status widened")
    require(request["promotion_authorized"] is False and request["public_release"] is False,
            "request authority widened")
    expected_ids = request["expected_receipt"]["evidence_ids"]
    require("availability-probe-dispatcher-run-34018916537-retired" in expected_ids,
            "retired dispatcher identity missing")
    require("candidate-self-hosted-inventory-run-34022826520-cancelled" in expected_ids,
            "cancelled inventory identity missing")

    require(validation["package_id"] == package["package_id"], "validation package ID mismatch")
    require(validation["package_file_sha256"] == digest(package_raw),
            "validation package digest mismatch")
    require(validation["request_file_sha256"] == digest(request_raw),
            "validation request digest mismatch")
    require(validation["promotable"] is False, "validation promotes unsigned request")

    files = manifest["files"]
    require(set(files) == set(BUNDLE_NAMES), "manifest file set drifted")
    actual = {
        "PR41_L1_ATTESTATION_REQUEST_README.md":
            (REQUEST_ROOT / "PR41_L1_ATTESTATION_REQUEST_README.md").read_bytes(),
        "pr41-l1-attestation-request.UNSIGNED.json": request_raw,
        "pr41-l1-attestation-request.validation.json": validation_raw,
        "pr41-l1-source-qualification.json": package_raw,
    }
    for name, raw in actual.items():
        require(files[name]["bytes"] == len(raw), f"manifest size mismatch: {name}")
        require(files[name]["sha256"] == digest(raw), f"manifest digest mismatch: {name}")
    require(manifest["status"] == "UNSIGNED_NOT_PROMOTABLE", "manifest status widened")
    require(manifest["promotion_authorized"] is False and manifest["public_release"] is False,
            "manifest authority widened")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve()
        verify_changed_paths(root, args.base, args.head)
        verify_workflows(root)
        verify_bundle()
        print(json.dumps({
            "result": "PASS_UNSIGNED_HANDOFF_AND_PROBE_BOUNDARIES",
            "package_id": EXPECTED_PACKAGE_ID,
            "availability_probe_dispatch_count": 2,
            "target_evidence_capture_dispatch_count": 0,
            "automatic_redispatch": False,
            "promotion_authorized": False,
            "public_release": False,
        }, sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"handoff verification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
