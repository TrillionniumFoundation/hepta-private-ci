#!/usr/bin/env python3
"""Verify Browser/Servo build, attestation and trusted-target evidence.

This verifier never grants activation, operator acceptance, promotion or release.
It only emits bounded evidence receipts after exact-source, two-builder, signed
provenance and target-execution checks succeed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import urllib.request
from typing import Any, NoReturn

REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
PRIMARY_WORKFLOW = ".github/workflows/hepta-browser-servo-worker-dev.yml"
INDEPENDENT_WORKFLOW = ".github/workflows/hepta-browser-servo-independent-rebuild.yml"
PRIMARY_WORKFLOW_ID = f"{REPOSITORY}/{PRIMARY_WORKFLOW}"
INDEPENDENT_WORKFLOW_ID = f"{REPOSITORY}/{INDEPENDENT_WORKFLOW}"
SLSA_PREDICATE = "https://slsa.dev/provenance/v1"
SPDX_PREDICATE = "https://spdx.dev/Document/v2.3"


def fail(message: str) -> NoReturn:
    raise SystemExit(message)


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        fail(f"{name} is required")
    return value


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            fail(f"duplicate evidence JSON key: {key}")
        value[key] = item
    return value


def _reject_constant(value: str) -> NoReturn:
    fail(f"non-finite evidence JSON number: {value}")


def load_json(path: pathlib.Path) -> Any:
    require_file(path, 16 << 20)
    try:
        # Bound the actual read as well as the preceding metadata check.
        with path.open("rb") as handle:
            body = handle.read((16 << 20) + 1)
        if len(body) > 16 << 20:
            fail(f"evidence JSON exceeds byte limit: {path}")
        return json.loads(
            body.decode("utf-8"), object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        fail(f"cannot load {path}: {error}")


def require_file(path: pathlib.Path, maximum: int = 1 << 30) -> pathlib.Path:
    if type(maximum) is not int or maximum < 1:
        fail("evidence file byte limit must be a positive integer")
    try:
        metadata = path.lstat()
    except OSError as error:
        fail(f"missing required evidence {path}: {error}")
    if not stat.S_ISREG(metadata.st_mode) or not 1 <= metadata.st_size <= maximum:
        fail(f"evidence file is not a bounded non-symlink regular file: {path}")
    return path


def require_fields(value: dict[str, Any], expected: dict[str, Any], name: str) -> None:
    for key, wanted in expected.items():
        actual = value.get(key)
        # Python considers True == 1. Evidence must not coerce Boolean flags,
        # counts, run identities or source identity fields across JSON types.
        if type(actual) is not type(wanted) or actual != wanted:
            fail(f"{name}.{key} mismatch")


def require_run_id(value: str) -> str:
    if not value.isascii() or not value.isdecimal() or value.startswith("0"):
        fail("build run ID must be a canonical positive decimal integer")
    return value


def verify_source_lock(source_sha: str, artifact_lock: pathlib.Path) -> None:
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if actual != source_sha:
        fail("checked-out source does not match SOURCE_SHA")
    committed = subprocess.check_output([
        "git", "show", f"{source_sha}:apps/hepta-browser/servo-worker/Cargo.lock",
    ])
    if hashlib.sha256(committed).hexdigest() != sha256(artifact_lock):
        fail("builder lock does not match the exact committed source lock")


def write_json(path: pathlib.Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def git_tree() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD^{tree}"], text=True
    ).strip()


def fetch_run(run_id: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPOSITORY}/actions/runs/{run_id}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            value = json.load(response)
    except Exception as error:  # urllib exposes several transport subclasses.
        fail(f"cannot fetch workflow run {run_id}: {error}")
    if not isinstance(value, dict):
        fail(f"workflow run {run_id} is not an object")
    return value


def verify_run(
    run: dict[str, Any],
    *,
    run_id: str,
    source_sha: str,
    name: str,
    path: str,
) -> None:
    expected = {
        "id": int(run_id),
        "head_sha": source_sha,
        "head_branch": "main",
        "name": name,
        "path": path,
        "conclusion": "success",
        "status": "completed",
    }
    require_fields(run, expected, f"workflow run {run_id}")
    if run.get("event") not in {"push", "workflow_dispatch"}:
        fail(f"workflow run {run_id} has unsupported event {run.get('event')!r}")
    repository = run.get("repository")
    if not isinstance(repository, dict) or repository.get("full_name") != REPOSITORY:
        fail(f"workflow run {run_id} repository mismatch")


def copy_evidence(source: pathlib.Path, destination: pathlib.Path) -> None:
    require_file(source, 64 * 1024 * 1024)
    shutil.copyfile(source, destination)


def preflight() -> None:
    source_sha = required_env("SOURCE_SHA")
    primary_run_id = require_run_id(required_env("BUILD_RUN_ID"))
    independent_run_id = require_run_id(required_env("INDEPENDENT_BUILD_RUN_ID"))
    expected_worker = required_env("EXPECTED_WORKER_SHA256")
    servo_pin = required_env("SERVO_PIN")
    token = required_env("GH_TOKEN")
    if len(source_sha) != 40 or any(char not in "0123456789abcdef" for char in source_sha):
        fail("SOURCE_SHA must be lowercase Git SHA-1")
    if len(expected_worker) != 64 or any(
        char not in "0123456789abcdef" for char in expected_worker
    ):
        fail("EXPECTED_WORKER_SHA256 must be lowercase SHA-256")
    if primary_run_id == independent_run_id:
        fail("primary and independent build runs must differ")

    primary_run = fetch_run(primary_run_id, token)
    independent_run = fetch_run(independent_run_id, token)
    verify_run(
        primary_run,
        run_id=primary_run_id,
        source_sha=source_sha,
        name="Hepta Browser Servo worker dev",
        path=PRIMARY_WORKFLOW,
    )
    verify_run(
        independent_run,
        run_id=independent_run_id,
        source_sha=source_sha,
        name="Hepta Browser Servo independent rebuild",
        path=INDEPENDENT_WORKFLOW,
    )

    primary_root = pathlib.Path("worker-evidence")
    independent_root = pathlib.Path("independent-evidence")
    target_root = pathlib.Path("deployment-evidence")
    target_root.mkdir(parents=True, exist_ok=True)

    primary_binary = require_file(primary_root / "hepta-servo-worker", 512 << 20)
    independent_binary = require_file(
        independent_root / "hepta-servo-worker", 512 << 20
    )
    primary_lock = require_file(primary_root / "Cargo.lock", 32 << 20)
    independent_lock = require_file(independent_root / "Cargo.lock", 32 << 20)
    sbom = require_file(primary_root / "hepta-servo-worker.spdx.json", 16 << 20)
    primary_receipt_path = require_file(primary_root / "build-receipt.json", 4 << 20)
    independent_receipt_path = require_file(
        independent_root / "independent-rebuild-receipt.json", 4 << 20
    )
    require_file(primary_root / "build-provenance-attestation.jsonl", 16 << 20)
    require_file(primary_root / "sbom-attestation.jsonl", 16 << 20)
    require_file(primary_root / "attestation-summary.json", 4 << 20)
    require_file(
        independent_root / "build-provenance-attestation.jsonl", 16 << 20
    )
    require_file(independent_root / "attestation-summary.json", 4 << 20)

    primary_worker_sha = sha256(primary_binary)
    independent_worker_sha = sha256(independent_binary)
    if primary_worker_sha != expected_worker or independent_worker_sha != expected_worker:
        fail("primary/independent worker digest does not match reviewed digest")
    if primary_binary.read_bytes() != independent_binary.read_bytes():
        fail("independent worker binaries are not byte-identical")
    if sha256(primary_lock) != sha256(independent_lock):
        fail("independent builders did not consume the same Cargo.lock")

    verify_source_lock(source_sha, primary_lock)
    source_tree = git_tree()
    primary = load_json(primary_receipt_path)
    independent = load_json(independent_receipt_path)
    primary_summary = load_json(primary_root / "attestation-summary.json")
    independent_summary = load_json(independent_root / "attestation-summary.json")

    if not isinstance(primary, dict) or primary.get("schema") != (
        "hepta.browser.servo-worker-build-receipt.v2"
    ):
        fail("primary build receipt schema mismatch")
    expected_primary = {
        "sourceSha": source_sha,
        "sourceTree": source_tree,
        "servoPin": servo_pin,
        "cargoLockSha256": sha256(primary_lock),
        "workerSha256": expected_worker,
        "sbomSha256": sha256(sbom),
        "cargoLockCommitted": True,
        "sameRunnerByteIdenticalBuilds": True,
        "reproducibleIndependentBuilds": False,
        "independentRunnerBuildCount": 1,
        "signedProvenanceRequiredForDeployment": True,
    }
    require_fields(primary, expected_primary, "primary build receipt")

    if not isinstance(independent, dict) or independent.get("schema") != (
        "hepta.browser.servo-independent-rebuild-receipt.v1"
    ):
        fail("independent build receipt schema mismatch")
    expected_independent = {
        "sourceSha": source_sha,
        "sourceTree": source_tree,
        "servoPin": servo_pin,
        "cargoLockSha256": sha256(independent_lock),
        "workerSha256": expected_worker,
        "githubRunId": independent_run_id,
        "committedLock": True,
        "independentEphemeralRunner": True,
        "signedProvenanceRequiredForDeployment": True,
    }
    require_fields(independent, expected_independent, "independent build receipt")

    expected_summaries = (
        (primary_summary, PRIMARY_WORKFLOW_ID),
        (independent_summary, INDEPENDENT_WORKFLOW_ID),
    )
    for summary, workflow in expected_summaries:
        if not isinstance(summary, dict):
            fail("attestation summary must be an object")
        if summary.get("sourceSha") != source_sha:
            fail("attestation summary source SHA mismatch")
        if summary.get("signerWorkflow") != workflow:
            fail("attestation summary signer workflow mismatch")

    checks = (
        ("linuxSandboxProbe", "externalNetworkDenied"),
        ("linuxSandboxProbe", "hostSecretHidden"),
        ("linuxSandboxProbe", "parentDeathCleanupObserved"),
        ("linuxSandboxProbe", "descendantCleanupObserved"),
        ("linuxSandboxProbe", "resourceLimitsEnforced"),
        ("realWorkerSmoke", "currentPinWorkerBooted"),
        ("realWorkerSmoke", "privateProtocolRoundTrip"),
        ("realBrowserE2E", "openNavigateObserveTypeClickClose"),
        ("realBrowserE2E", "crossOriginSubresourceDenied"),
        ("realBrowserE2E", "redirectEscapeDenied"),
        ("realBrowserE2E", "profileAllowedCrossOriginRedirectDeniedByEffectGrant"),
        ("realBrowserE2E", "crossProfileCookieIsolation"),
        ("realBrowserE2E", "persistedCrashReconciliation"),
        ("realBrowserSoak", "boundedFdGrowth"),
        ("realBrowserSoak", "boundedRssGrowth"),
    )
    for group, field in checks:
        value = primary.get(group)
        if not isinstance(value, dict) or value.get(field) is not True:
            fail(f"primary evidence missing {group}.{field}=true")
    if primary.get("realBrowserSoak", {}).get("cycles") != 32:
        fail("primary Browser soak did not complete 32 cycles")

    multi = {
        "schema": "hepta.browser.servo-multi-builder-receipt.v1",
        "sourceSha": source_sha,
        "sourceTree": source_tree,
        "servoPin": servo_pin,
        "primaryBuildRunId": primary_run_id,
        "independentBuildRunId": independent_run_id,
        "cargoLockSha256": sha256(primary_lock),
        "workerSha256": expected_worker,
        "primaryReceiptSha256": sha256(primary_receipt_path),
        "independentReceiptSha256": sha256(independent_receipt_path),
        "reproducibleIndependentBuilds": True,
        "independentRunnerBuildCount": 2,
        "byteIdentical": True,
        "signedProvenancePendingCryptographicVerification": True,
    }
    write_json(target_root / "multi-builder-receipt.json", multi)
    copy_evidence(primary_receipt_path, target_root / "source-build-receipt.json")
    copy_evidence(
        independent_receipt_path,
        target_root / "independent-rebuild-receipt.json",
    )
    copy_evidence(
        primary_root / "attestation-summary.json",
        target_root / "primary-attestation-summary.json",
    )
    copy_evidence(
        independent_root / "attestation-summary.json",
        target_root / "independent-attestation-summary.json",
    )
    (target_root / "worker.sha256").write_text(
        f"{expected_worker}  hepta-servo-worker\n", encoding="utf-8"
    )
    primary_binary.chmod(0o555)


def verification_subject_digest(entry: dict[str, Any]) -> str | None:
    result = entry.get("verificationResult")
    if not isinstance(result, dict):
        return None
    statement = result.get("statement")
    if not isinstance(statement, dict):
        return None
    subjects = statement.get("subject")
    if not isinstance(subjects, list):
        return None
    for subject in subjects:
        if not isinstance(subject, dict):
            continue
        digest = subject.get("digest")
        if isinstance(digest, dict) and isinstance(digest.get("sha256"), str):
            return digest["sha256"]
    return None


def verify_attestation_document(
    path: pathlib.Path, *, expected_worker: str, predicate_type: str
) -> int:
    value = load_json(path)
    if not isinstance(value, list) or not value:
        fail(f"{path} contains no verified attestations")
    verified = 0
    for entry in value:
        if not isinstance(entry, dict):
            fail(f"{path} contains a non-object entry")
        result = entry.get("verificationResult")
        if not isinstance(result, dict):
            fail(f"{path} lacks verificationResult")
        statement = result.get("statement")
        if not isinstance(statement, dict):
            fail(f"{path} lacks verified statement")
        if statement.get("predicateType") != predicate_type:
            fail(f"{path} predicate type mismatch")
        if verification_subject_digest(entry) != expected_worker:
            fail(f"{path} subject digest mismatch")
        timestamps = result.get("verifiedTimestamps")
        if not isinstance(timestamps, list) or not timestamps:
            fail(f"{path} lacks a verified transparency/timestamp witness")
        signature = result.get("signature")
        if not isinstance(signature, dict) or not isinstance(
            signature.get("certificate"), dict
        ):
            fail(f"{path} lacks a verified signing certificate")
        verified += 1
    return verified


def attestations() -> None:
    expected_worker = required_env("EXPECTED_WORKER_SHA256")
    target_root = pathlib.Path("deployment-evidence")
    primary_provenance = require_file(
        target_root / "primary-provenance-verification.json", 16 << 20
    )
    primary_sbom = require_file(
        target_root / "primary-sbom-verification.json", 16 << 20
    )
    independent_provenance = require_file(
        target_root / "independent-provenance-verification.json", 16 << 20
    )
    counts = {
        "primaryProvenance": verify_attestation_document(
            primary_provenance,
            expected_worker=expected_worker,
            predicate_type=SLSA_PREDICATE,
        ),
        "primarySbom": verify_attestation_document(
            primary_sbom,
            expected_worker=expected_worker,
            predicate_type=SPDX_PREDICATE,
        ),
        "independentProvenance": verify_attestation_document(
            independent_provenance,
            expected_worker=expected_worker,
            predicate_type=SLSA_PREDICATE,
        ),
    }
    receipt = {
        "schema": "hepta.browser.servo-signed-attestation-verification.v1",
        "sourceSha": required_env("SOURCE_SHA"),
        "sourceRef": "refs/heads/main",
        "workerSha256": expected_worker,
        "repository": REPOSITORY,
        "primarySignerWorkflow": PRIMARY_WORKFLOW_ID,
        "independentSignerWorkflow": INDEPENDENT_WORKFLOW_ID,
        "primaryProvenanceVerificationSha256": sha256(primary_provenance),
        "primarySbomVerificationSha256": sha256(primary_sbom),
        "independentProvenanceVerificationSha256": sha256(
            independent_provenance
        ),
        "verifiedAttestationCounts": counts,
        "signedBuildProvenanceVerified": True,
        "signedSbomVerified": True,
        "selfHostedBuilderAttestationsDenied": True,
    }
    write_json(target_root / "signed-attestation-verification.json", receipt)


def require_true(value: dict[str, Any], fields: tuple[str, ...], name: str) -> None:
    for field in fields:
        if value.get(field) is not True:
            fail(f"{name}.{field} must be true")


def finalize() -> None:
    target_root = pathlib.Path("deployment-evidence")
    multi_path = require_file(target_root / "multi-builder-receipt.json", 4 << 20)
    attestation_path = require_file(
        target_root / "signed-attestation-verification.json", 4 << 20
    )
    sandbox_path = require_file(target_root / "linux-sandbox-probe.json", 4 << 20)
    smoke_path = require_file(target_root / "real-worker-smoke.json", 4 << 20)
    e2e_path = require_file(target_root / "real-browser-e2e.json", 8 << 20)
    public_path = require_file(target_root / "public-egress-probe.json", 4 << 20)
    soak_path = require_file(target_root / "real-browser-soak.json", 4 << 20)

    multi = load_json(multi_path)
    attestation = load_json(attestation_path)
    sandbox = load_json(sandbox_path)
    smoke = load_json(smoke_path)
    e2e = load_json(e2e_path)
    public = load_json(public_path)
    soak = load_json(soak_path)
    values = (multi, attestation, sandbox, smoke, e2e, public, soak)
    if any(not isinstance(value, dict) for value in values):
        fail("target evidence contains a non-object receipt")

    source_sha = required_env("SOURCE_SHA")
    source_tree = git_tree()
    worker_sha = required_env("EXPECTED_WORKER_SHA256")
    primary_run_id = require_run_id(required_env("BUILD_RUN_ID"))
    independent_run_id = require_run_id(required_env("INDEPENDENT_BUILD_RUN_ID"))
    if primary_run_id == independent_run_id:
        fail("primary and independent build runs must differ")
    # Never relabel old successful receipts with new environment identities.
    require_fields(multi, {
        "schema": "hepta.browser.servo-multi-builder-receipt.v1",
        "sourceSha": source_sha, "sourceTree": source_tree,
        "workerSha256": worker_sha, "servoPin": required_env("SERVO_PIN"),
        "primaryBuildRunId": primary_run_id,
        "independentBuildRunId": independent_run_id,
        "independentRunnerBuildCount": 2,
    }, "multiBuilder")
    require_fields(attestation, {
        "schema": "hepta.browser.servo-signed-attestation-verification.v1",
        "sourceSha": source_sha, "sourceRef": "refs/heads/main",
        "workerSha256": worker_sha, "repository": REPOSITORY,
        "primarySignerWorkflow": PRIMARY_WORKFLOW_ID,
        "independentSignerWorkflow": INDEPENDENT_WORKFLOW_ID,
    }, "attestation")

    require_true(
        multi,
        ("reproducibleIndependentBuilds", "byteIdentical"),
        "multiBuilder",
    )
    if multi.get("independentRunnerBuildCount") != 2:
        fail("multiBuilder.independentRunnerBuildCount must be 2")
    require_true(
        attestation,
        (
            "signedBuildProvenanceVerified",
            "signedSbomVerified",
            "selfHostedBuilderAttestationsDenied",
        ),
        "attestation",
    )
    require_true(
        sandbox,
        (
            "externalNetworkDenied",
            "hostSecretHidden",
            "parentDeathCleanupObserved",
            "descendantCleanupObserved",
            "resourceLimitsEnforced",
        ),
        "sandbox",
    )
    require_true(
        smoke,
        ("currentPinWorkerBooted", "privateProtocolRoundTrip", "sandboxedStartStop"),
        "smoke",
    )
    require_true(
        e2e,
        (
            "openNavigateObserveTypeClickClose",
            "crossOriginSubresourceDenied",
            "redirectEscapeDenied",
            "profileAllowedCrossOriginRedirectDeniedByEffectGrant",
            "profileExpiryContainsBackgroundNetwork",
            "profileCloseRevocationContainsBackgroundNetwork",
            "crossProfileCookieIsolation",
            "persistedCrashReconciliation",
            "authenticatedPersistedCrashReconciliation",
            "crossProfileStorageIsolation",
            "crossProfileCacheIsolation",
            "noExternallyReachableWorkerListener",
        ),
        "e2e",
    )
    require_true(
        public,
        (
            "publicDnsResolved",
            "publicTlsValidated",
            "realServoPublicHttps",
            "profileScopeEscapeDenied",
            "ungrantedPublicOriginDenied",
        ),
        "publicEgress",
    )
    if public.get("realServoObservedOrigin") != "https://example.com":
        fail("publicEgress.realServoObservedOrigin mismatch")
    require_true(soak, ("boundedFdGrowth", "boundedRssGrowth"), "soak")
    if soak.get("cycles") != 32:
        fail("target Browser soak did not complete 32 cycles")

    receipt = {
        "schema": "hepta.browser.servo-linux-target-qualification.v3",
        "sourceSha": required_env("SOURCE_SHA"),
        "sourceTree": git_tree(),
        "buildRunId": required_env("BUILD_RUN_ID"),
        "independentBuildRunId": required_env("INDEPENDENT_BUILD_RUN_ID"),
        "workerSha256": required_env("EXPECTED_WORKER_SHA256"),
        "multiBuilderReceiptSha256": sha256(multi_path),
        "signedAttestationVerificationSha256": sha256(attestation_path),
        "signedBuildProvenanceVerified": True,
        "signedSbomVerified": True,
        "reproducibleIndependentBuilds": True,
        "independentRunnerBuildCount": 2,
        "sandboxProbeSha256": sha256(sandbox_path),
        "realWorkerSmokeSha256": sha256(smoke_path),
        "realBrowserE2ESha256": sha256(e2e_path),
        "publicEgressProbeSha256": sha256(public_path),
        "realBrowserSoakSha256": sha256(soak_path),
        "publicDnsResolved": True,
        "publicTlsValidated": True,
        "realServoPublicHttps": True,
        "profileScopeEscapeDenied": True,
        "noExternallyReachableWorkerListener": True,
        "crossProfileCookieIsolation": True,
        "crossProfileStorageIsolation": True,
        "crossProfileCacheIsolation": True,
        "boundedRssGrowth": True,
        "boundedFdGrowth": True,
        "operatorAcceptance": False,
        "activation": False,
        "promotion": False,
        "releaseQualified": False,
        "interpretation": (
            "two-builder signed provenance plus target execution evidence only; "
            "independent operator, activation, promotion and release authority is not self-issued"
        ),
    }
    output = target_root / "target-qualification-receipt.json"
    write_json(output, receipt)
    (target_root / "target-qualification-receipt.json.sha256").write_text(
        f"{sha256(output)}  target-qualification-receipt.json\n", encoding="utf-8"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("preflight", "attestations", "finalize"))
    return parser.parse_args()


def main() -> None:
    phase = parse_args().phase
    if phase == "preflight":
        preflight()
    elif phase == "attestations":
        attestations()
    elif phase == "finalize":
        finalize()
    else:  # pragma: no cover
        fail(f"unsupported phase {phase}")


if __name__ == "__main__":
    main()
