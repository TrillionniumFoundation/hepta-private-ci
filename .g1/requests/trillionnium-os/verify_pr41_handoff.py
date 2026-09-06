#!/usr/bin/env python3
"""Verify the PR #41 unsigned handoff and trusted probe boundaries."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any, Callable

EXPECTED_PACKAGE_ID = "sha256:03369d6115e587b0baf207c3d361689913853814465a8e881a2f617d98a62e39"
EXPECTED_HEAD = "7e1e611e7299391cf3d4edc1ded322da0d023cc6"
EXPECTED_MAIN = "968968046d69d000f1f9fe03683e92aa7903cf99"
EXPECTED_REPOSITORY = "TrillionniumFoundation/trillionnium-os"
EXPECTED_TRUST_ROOT = "g1-attestation-root-20260902"
EXPECTED_SIGNATURE_ALGORITHM = "rsa-sha256"
EXPECTED_PROBE_RUNS = [34022297088, 34022298108]
EXPECTED_EVIDENCE_IDS = [
    "pull-request-review-5124508101",
    "workflow-run-34014361107-attempt-3",
    "workflow-run-34017552361-attempt-1",
    "protected-main-968968046d69d000f1f9fe03683e92aa7903cf99",
    "availability-probe-dispatcher-run-34018916537-retired",
    "candidate-self-hosted-inventory-run-34022826520-cancelled",
]
REASON_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
TRAVERSAL_SEGMENT_RE = re.compile(r"(?:^|/)\.\.(?:/|$)")
ROOT = Path(__file__).resolve().parents[3]
VERIFIER_RELATIVE_PATH = Path(
    ".g1/requests/trillionnium-os/verify_pr41_handoff.py"
)
REQUEST_RELATIVE_ROOT = Path(".g1/requests/trillionnium-os")
README_NAME = "PR41_L1_ATTESTATION_REQUEST_README.md"
REQUEST_NAME = "pr41-l1-attestation-request.UNSIGNED.json"
VALIDATION_NAME = "pr41-l1-attestation-request.validation.json"
PACKAGE_NAME = "pr41-l1-source-qualification.json"
MANIFEST_NAME = "pr41-l1-attestation-request.manifest.json"
BUNDLE_NAMES = (README_NAME, REQUEST_NAME, VALIDATION_NAME, PACKAGE_NAME)
ALL_BUNDLE_NAMES = (*BUNDLE_NAMES, MANIFEST_NAME)
ALLOWED_CHANGED_PATHS = {
    *(f".g1/requests/trillionnium-os/{name}" for name in BUNDLE_NAMES),
    f".g1/requests/trillionnium-os/{MANIFEST_NAME}",
    str(VERIFIER_RELATIVE_PATH),
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
REQUEST_KEYS = {
    "automatic_redispatch", "expected_receipt", "forbidden_shortcuts",
    "package", "promotion_authorized", "public_release", "repository",
    "requested_at", "required_external_actions", "schema", "status", "version",
}
REQUEST_PACKAGE_KEYS = {"bytes", "package_id", "path", "sha256"}
EXPECTED_RECEIPT_KEYS = {
    "authority", "evidence_ids", "expires_at_exactly",
    "independent_verification", "package_ids", "schema",
    "signature_algorithm", "source_commit", "subject", "trust_root",
    "verification_method", "verified_at", "version",
}
SUBJECT_KEYS = {"base", "head", "merge"}
SUBJECT_ENDPOINT_KEYS = {"commit", "ref", "repository", "tree"}
SUBJECT_MERGE_KEYS = {"commit", "kind", "parents", "tree"}
VALIDATION_KEYS = {
    "blockers", "checks", "package_file_bytes", "package_file_sha256",
    "package_id", "promotable", "repository_contract_revision",
    "request_file_sha256", "schema", "status", "validated_at",
}
EXPECTED_VALIDATION_CHECKS = {
    "artifact_retention_covers_package": True,
    "authorization_shape": True,
    "automatic_redispatch_false": True,
    "availability_probe_dispatches_recorded": True,
    "candidate_controlled_dispatcher_retired": True,
    "candidate_self_hosted_inventory_cancelled": True,
    "claim_ceiling": True,
    "desktop_runner_group_preallocation_bound": True,
    "detached_attestation_present": False,
    "detached_signature_present": False,
    "external_public_key_present": False,
    "negative_claims": True,
    "ordered_base_head_parents": True,
    "package_id_canonicalization": True,
    "probe_input_shell_interpolation_removed": True,
    "public_release_false": True,
    "required_source_observations": True,
    "role_separation": True,
    "source_subject_identity": True,
    "strict_top_level_keys": True,
    "target_evidence_capture_dispatch_count_zero": True,
}
EXPECTED_VALIDATION_BLOCKERS = [
    "independently created strict v2 attestation receipt",
    "out-of-band attestation raw-byte digest",
    "detached RSA-SHA256 signature",
    "independently administered public key and pinned SHA-256",
    "successful tools/verify-g1-evidence-live.py execution",
]
MANIFEST_KEYS = {
    "files", "promotion_authorized", "public_release", "schema", "status",
}
MANIFEST_FILE_KEYS = {"bytes", "sha256"}


class VerificationError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def valid_reason(value: str) -> bool:
    return (
        REASON_RE.fullmatch(value) is not None
        and TRAVERSAL_SEGMENT_RE.search(value) is None
    )


def reject_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON member: {key}")
        result[key] = value
    return result


def read_regular_bytes(path: Path) -> bytes:
    metadata = path.lstat()
    require(stat.S_ISREG(metadata.st_mode), f"{path} is not a regular file")
    require(not stat.S_ISLNK(metadata.st_mode), f"{path} is a symlink")
    require(metadata.st_nlink == 1, f"{path} has multiple hard links")
    raw = path.read_bytes()
    require(raw and len(raw) == metadata.st_size, f"{path} changed or is empty")
    return raw


def load_json(path: Path) -> tuple[Any, bytes]:
    raw = read_regular_bytes(path)
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


def write_json(path: Path, value: Any) -> bytes:
    raw = (
        json.dumps(value, ensure_ascii=True, allow_nan=False, indent=2) + "\n"
    ).encode("utf-8")
    path.write_bytes(raw)
    return raw


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, allow_nan=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def request_root(root: Path) -> Path:
    return root / REQUEST_RELATIVE_ROOT


def git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "--no-replace-objects", "-C", str(root), *args],
        check=True, capture_output=True, text=True, timeout=30,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
    )
    return completed.stdout


def verify_root_binding(root: Path) -> None:
    expected = root / VERIFIER_RELATIVE_PATH
    require(expected.exists(), "root does not contain the invoked verifier")
    metadata = expected.lstat()
    require(stat.S_ISREG(metadata.st_mode), "root verifier is not a regular file")
    require(not stat.S_ISLNK(metadata.st_mode), "root verifier is a symlink")
    require(metadata.st_nlink == 1, "root verifier has multiple hard links")
    require(
        Path(__file__).resolve() == expected.resolve(),
        "--root does not contain the invoked verifier",
    )


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

    length_guard = 'test "${#PROBE_REASON}" -le 128'
    grammar = '[[ "$PROBE_REASON" =~ ^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$ ]]'
    traversal_guard = '[[ ! "/$PROBE_REASON/" =~ /\\.\\./ ]]'
    for name, text, count in (("desktop", desktop, 1), ("fleet", fleet, 3)):
        expression_lines = [line for line in text.splitlines() if "${{ inputs.reason }}" in line]
        require(len(expression_lines) == count, f"{name} reason expression count drifted")
        require(all("PROBE_REASON:" in line for line in expression_lines),
                f"{name} interpolates reason into shell source")
        require(text.count(length_guard) == count, f"{name} reason length guard drifted")
        require(text.count(grammar) == count, f"{name} reason grammar drifted")
        require(text.count(traversal_guard) == count,
                f"{name} traversal-segment guard drifted")
        require(text.count('"$PROBE_REASON"') >= count, f"{name} reason is not quoted")

    positives = (
        "operator-check", "trillionnium-os-promoted-main-968968",
        "manual:TICKET/ABC-123", "operator/a..b",
    )
    negatives = (
        "", "has space", "x';touch/tmp/pwn", "$(touch/tmp/pwn)", "`touch/tmp/pwn`",
        "a\nb", "a\rb", "a;id", "${{github.token}}", 'x"y', "../escape",
        "a/../b", "a/..", "a/../../b",
    )
    require(all(valid_reason(value) for value in positives), "safe reason rejected")
    require(not any(valid_reason(value) for value in negatives), "hostile reason accepted")


def verify_subject(subject: Any, package: dict[str, Any]) -> None:
    require(isinstance(subject, dict) and set(subject) == SUBJECT_KEYS,
            "package subject shape drifted")
    base = subject["base"]
    head = subject["head"]
    merge = subject["merge"]
    require(isinstance(base, dict) and set(base) == SUBJECT_ENDPOINT_KEYS,
            "package base subject shape drifted")
    require(isinstance(head, dict) and set(head) == SUBJECT_ENDPOINT_KEYS,
            "package head subject shape drifted")
    require(isinstance(merge, dict) and set(merge) == SUBJECT_MERGE_KEYS,
            "package merge subject shape drifted")
    require(base["repository"] == EXPECTED_REPOSITORY, "base repository drifted")
    require(head["repository"] == EXPECTED_REPOSITORY, "head repository drifted")
    require(head["commit"] == EXPECTED_HEAD, "subject head commit drifted")
    require(head["commit"] == package["source"]["commit"],
            "subject and source commits differ")
    require(head["tree"] == package["source"]["tree"],
            "subject and source trees differ")
    require(merge["kind"] == "deterministic_synthetic", "merge kind drifted")
    require(merge["parents"] == [base["commit"], head["commit"]],
            "ordered merge parents drifted")
    require(merge["tree"] == head["tree"], "merge tree drifted")
    require(merge["commit"] == package["observations"]["synthetic_merge_commit"],
            "merge observation drifted")


def verify_bundle(root: Path) -> None:
    bundle_root = request_root(root)
    package, package_raw = load_json(bundle_root / PACKAGE_NAME)
    request, request_raw = load_json(bundle_root / REQUEST_NAME)
    validation, validation_raw = load_json(bundle_root / VALIDATION_NAME)
    manifest, _ = load_json(bundle_root / MANIFEST_NAME)

    require(isinstance(package, dict) and set(package) == PACKAGE_KEYS, "package keys drifted")
    require(package["schema"] == "org.trillionnium.g1.evidence-package.v2", "package schema drifted")
    require(package["version"] == "2", "package version drifted")
    require(package["status"] == "COMPLETE" and package["level"] == "L1",
            "package status or level drifted")
    require(isinstance(package["source"], dict), "package source is not an object")
    require(package["source"]["repository"] == EXPECTED_REPOSITORY,
            "package source repository drifted")
    require(package["source"]["commit"] == EXPECTED_HEAD, "package source head drifted")
    require(isinstance(package["observations"], dict),
            "package observations are not an object")
    require(package["observations"]["protected_main_commit"] == EXPECTED_MAIN,
            "protected main drifted")
    require(package["automatic_redispatch"] is False, "automatic redispatch widened")
    require(package["public_release"] is False, "public release widened")
    preimage = dict(package)
    preimage["package_id"] = ""
    require(f"sha256:{digest(canonical(preimage))}" == package["package_id"] == EXPECTED_PACKAGE_ID,
            "package ID mismatch")
    verify_subject(package["subject"], package)

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

    require(isinstance(request, dict) and set(request) == REQUEST_KEYS,
            "request keys drifted")
    require(request["schema"] == "org.trillionnium.g1.evidence-attestation-request.v1",
            "request schema drifted")
    require(request["version"] == "1", "request version drifted")
    require(request["repository"] == package["source"]["repository"] == EXPECTED_REPOSITORY,
            "request repository drifted")
    require(request["status"] == "UNSIGNED_NOT_PROMOTABLE", "request status widened")
    require(request["automatic_redispatch"] is False, "request redispatch widened")
    require(request["promotion_authorized"] is False and request["public_release"] is False,
            "request authority widened")
    require(isinstance(request["requested_at"], str) and request["requested_at"],
            "request timestamp is missing")
    require(isinstance(request["forbidden_shortcuts"], list)
            and request["forbidden_shortcuts"]
            and all(isinstance(item, str) and item for item in request["forbidden_shortcuts"]),
            "forbidden shortcuts shape drifted")
    require(isinstance(request["required_external_actions"], list)
            and request["required_external_actions"]
            and all(isinstance(item, str) and item for item in request["required_external_actions"]),
            "external actions shape drifted")

    package_ref = request["package"]
    require(isinstance(package_ref, dict) and set(package_ref) == REQUEST_PACKAGE_KEYS,
            "request package reference shape drifted")
    require(package_ref["path"] == PACKAGE_NAME, "request package path drifted")
    require(package_ref["package_id"] == package["package_id"], "request package ID mismatch")
    require(package_ref["bytes"] == len(package_raw), "request package size mismatch")
    require(package_ref["sha256"] == digest(package_raw), "request package digest mismatch")

    expected_receipt = request["expected_receipt"]
    require(isinstance(expected_receipt, dict)
            and set(expected_receipt) == EXPECTED_RECEIPT_KEYS,
            "expected receipt keys drifted")
    require(expected_receipt["schema"] == "org.trillionnium.g1.evidence-attestation.v2",
            "expected receipt schema drifted")
    require(expected_receipt["version"] == "2", "expected receipt version drifted")
    require(expected_receipt["signature_algorithm"] == EXPECTED_SIGNATURE_ALGORITHM,
            "signature algorithm drifted")
    require(expected_receipt["trust_root"] == EXPECTED_TRUST_ROOT,
            "trust root drifted")
    require(expected_receipt["source_commit"] == package["source"]["commit"] == EXPECTED_HEAD,
            "expected receipt source commit drifted")
    require(expected_receipt["subject"] == package["subject"],
            "expected receipt subject differs from package")
    require(expected_receipt["package_ids"] == [package["package_id"]],
            "expected receipt package IDs drifted")
    require(expected_receipt["expires_at_exactly"] == package["expires_at"],
            "expected receipt expiry drifted")
    require(package["authorization"]["expires_at"] == package["expires_at"],
            "package authorization expiry drifted")
    require(expected_receipt["evidence_ids"] == EXPECTED_EVIDENCE_IDS,
            "expected receipt evidence IDs drifted")
    for field in (
        "authority", "independent_verification", "verification_method", "verified_at",
    ):
        require(expected_receipt[field] is None,
                f"unsigned expected receipt field is already issued: {field}")

    require(isinstance(validation, dict) and set(validation) == VALIDATION_KEYS,
            "validation keys drifted")
    require(validation["schema"] ==
            "org.trillionnium.g1.evidence-attestation-request-validation.v1",
            "validation schema drifted")
    require(validation["status"] == "PASS_PACKAGE_STRUCTURE_ONLY_ATTESTATION_ABSENT",
            "validation status drifted")
    require(validation["checks"] == EXPECTED_VALIDATION_CHECKS,
            "validation checks drifted")
    require(validation["blockers"] == EXPECTED_VALIDATION_BLOCKERS,
            "validation blockers drifted")
    require(validation["package_id"] == package["package_id"], "validation package ID mismatch")
    require(validation["package_file_bytes"] == len(package_raw),
            "validation package size mismatch")
    require(validation["package_file_sha256"] == digest(package_raw),
            "validation package digest mismatch")
    require(validation["request_file_sha256"] == digest(request_raw),
            "validation request digest mismatch")
    require(validation["repository_contract_revision"] == EXPECTED_MAIN,
            "validation contract revision drifted")
    require(validation["validated_at"] == request["requested_at"],
            "request and validation timestamps differ")
    require(validation["promotable"] is False, "validation promotes unsigned request")

    require(isinstance(manifest, dict) and set(manifest) == MANIFEST_KEYS,
            "manifest keys drifted")
    require(manifest["schema"] ==
            "org.trillionnium.g1.unsigned-attestation-bundle-manifest.v1",
            "manifest schema drifted")
    require(manifest["status"] == "UNSIGNED_NOT_PROMOTABLE", "manifest status widened")
    require(manifest["promotion_authorized"] is False and manifest["public_release"] is False,
            "manifest authority widened")
    files = manifest["files"]
    require(isinstance(files, dict) and set(files) == set(BUNDLE_NAMES),
            "manifest file set drifted")
    actual = {
        README_NAME: read_regular_bytes(bundle_root / README_NAME),
        REQUEST_NAME: request_raw,
        VALIDATION_NAME: validation_raw,
        PACKAGE_NAME: package_raw,
    }
    for name, raw in actual.items():
        entry = files[name]
        require(isinstance(entry, dict) and set(entry) == MANIFEST_FILE_KEYS,
                f"manifest entry shape drifted: {name}")
        require(type(entry["bytes"]) is int and entry["bytes"] == len(raw),
                f"manifest size mismatch: {name}")
        require(entry["sha256"] == digest(raw), f"manifest digest mismatch: {name}")


def copy_bundle(source_root: Path, destination_root: Path) -> None:
    source = request_root(source_root)
    destination = request_root(destination_root)
    destination.mkdir(parents=True)
    for name in ALL_BUNDLE_NAMES:
        shutil.copy2(source / name, destination / name)


def refresh_request_fixture(root: Path) -> None:
    bundle_root = request_root(root)
    request_raw = read_regular_bytes(bundle_root / REQUEST_NAME)
    validation, _ = load_json(bundle_root / VALIDATION_NAME)
    validation["request_file_sha256"] = digest(request_raw)
    validation_raw = write_json(bundle_root / VALIDATION_NAME, validation)
    manifest, _ = load_json(bundle_root / MANIFEST_NAME)
    manifest["files"][REQUEST_NAME] = {
        "bytes": len(request_raw),
        "sha256": digest(request_raw),
    }
    manifest["files"][VALIDATION_NAME] = {
        "bytes": len(validation_raw),
        "sha256": digest(validation_raw),
    }
    write_json(bundle_root / MANIFEST_NAME, manifest)


def expect_verification_failure(action: Callable[[], None], case: str) -> None:
    try:
        action()
    except VerificationError:
        return
    raise VerificationError(f"self-test hostile case was accepted: {case}")


def run_self_tests(root: Path) -> None:
    mutations: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
        (
            "changed_expected_subject_head",
            lambda request: request["expected_receipt"]["subject"]["head"].__setitem__(
                "commit", "0" * 40
            ),
        ),
        (
            "deleted_expected_subject",
            lambda request: request["expected_receipt"].pop("subject"),
        ),
        (
            "changed_expected_source_commit",
            lambda request: request["expected_receipt"].__setitem__(
                "source_commit", "1" * 40
            ),
        ),
        (
            "changed_trust_root",
            lambda request: request["expected_receipt"].__setitem__(
                "trust_root", "candidate-controlled-root"
            ),
        ),
        ("deleted_request_schema", lambda request: request.pop("schema")),
        (
            "changed_receipt_schema",
            lambda request: request["expected_receipt"].__setitem__(
                "schema", "org.trillionnium.g1.evidence-attestation.v1"
            ),
        ),
        (
            "changed_signature_algorithm",
            lambda request: request["expected_receipt"].__setitem__(
                "signature_algorithm", "none"
            ),
        ),
        (
            "changed_receipt_package_ids",
            lambda request: request["expected_receipt"].__setitem__(
                "package_ids", ["sha256:" + "0" * 64]
            ),
        ),
        (
            "changed_receipt_expiry",
            lambda request: request["expected_receipt"].__setitem__(
                "expires_at_exactly", "2026-10-07T05:38:25Z"
            ),
        ),
        (
            "changed_ordered_parents",
            lambda request: request["expected_receipt"]["subject"]["merge"].__setitem__(
                "parents", list(reversed(
                    request["expected_receipt"]["subject"]["merge"]["parents"]
                ))
            ),
        ),
        (
            "changed_request_repository",
            lambda request: request.__setitem__("repository", "example/other"),
        ),
        (
            "changed_package_path",
            lambda request: request["package"].__setitem__("path", "other.json"),
        ),
        (
            "extra_request_member",
            lambda request: request.__setitem__("candidate_extension", True),
        ),
    ]
    with tempfile.TemporaryDirectory(prefix="hepta-handoff-self-test-") as temporary:
        temporary_root = Path(temporary)
        baseline = temporary_root / "baseline"
        copy_bundle(root, baseline)
        verify_bundle(baseline)
        for index, (name, mutate) in enumerate(mutations):
            case_root = temporary_root / f"case-{index:02d}-{name}"
            copy_bundle(baseline, case_root)
            fixture_request, _ = load_json(request_root(case_root) / REQUEST_NAME)
            require(isinstance(fixture_request, dict), "self-test request is not an object")
            mutate(fixture_request)
            write_json(request_root(case_root) / REQUEST_NAME, fixture_request)
            refresh_request_fixture(case_root)
            expect_verification_failure(lambda root=case_root: verify_bundle(root), name)

        other_root = temporary_root / "other-root"
        other_verifier = other_root / VERIFIER_RELATIVE_PATH
        other_verifier.parent.mkdir(parents=True)
        shutil.copy2(Path(__file__).resolve(), other_verifier)
        expect_verification_failure(
            lambda: verify_root_binding(other_root), "two-root verifier mismatch"
        )

    print(json.dumps({
        "status": "PASS_HANDOFF_VERIFIER_SELF_TESTS",
        "hostile_request_cases": len(mutations),
        "two_root_mismatch_rejected": True,
        "authority_granted": False,
    }, sort_keys=True))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--self-test-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve()
        verify_root_binding(root)
        run_self_tests(root)
        if args.self_test_only:
            return 0
        require(args.base is not None, "--base is required")
        require(args.head is not None, "--head is required")
        verify_changed_paths(root, args.base, args.head)
        verify_workflows(root)
        verify_bundle(root)
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
