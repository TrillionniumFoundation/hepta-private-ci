"""Explicit execution profiles; historical reports remain historical records."""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Mapping

LEGACY_PROFILE = "legacy491"
VENDOR_PROFILE = "vendor-c37-sdk132-v1"
PROFILES = (LEGACY_PROFILE, VENDOR_PROFILE)
LEGACY_REF = "49103de6ed70804e940637bf3e9e29e4a3f54e64"
DESCRIPTOR_SHA256 = "eca54127cc3edf7593162942bf82e69275ae740f83a73a7187e4d2db43d40156"
LEGACY_BASELINE_SHA256 = (
    "896630ee5f2c890152634e84a39d433f68eede8fff0b4ff99317800453b048ca"
)
_DIRECTORY = Path(__file__).resolve().parent


def descriptor() -> dict[str, object]:
    data = (_DIRECTORY / f"{VENDOR_PROFILE}.json").read_bytes()
    if hashlib.sha256(data).hexdigest() != DESCRIPTOR_SHA256:
        raise ValueError("code-owned execution descriptor changed")
    return json.loads(data)


def report_profile(report: Mapping[str, object]) -> str:
    # Original schema-4 reports predate profiles. This only recognizes their
    # historical metadata; it does not retrospectively verify their executable.
    profile = report.get("conformanceProfile", LEGACY_PROFILE)
    if profile not in PROFILES:
        raise ValueError("unknown conformance execution profile")
    return str(profile)


def validate_metadata(report: Mapping[str, object]) -> str:
    profile = report_profile(report)
    official = report.get("officialConformance")
    if not isinstance(official, dict):
        raise ValueError("missing official conformance metadata")
    expected_ref = LEGACY_REF
    if profile == LEGACY_PROFILE and "executionIdentity" in report:
        raise ValueError("historical reports cannot claim a verified vendor identity")
    if profile == VENDOR_PROFILE:
        identity = descriptor()
        expected_ref = identity["gitRef"]
        if report.get("executionIdentity") != {
            "identity": identity,
            "descriptorSha256": DESCRIPTOR_SHA256,
        }:
            raise ValueError(
                "vendor execution identity differs from the code-owned profile"
            )
    if official.get("gitRef") != expected_ref:
        raise ValueError("different pinned upstream conformance revision")
    return profile


def verify_execution(
    profile: str, selected_cli: Path | None
) -> dict[str, object] | None:
    if profile == LEGACY_PROFILE:
        if selected_cli is not None:
            raise ValueError(
                "legacy491 execution requires its original pinned bootstrap; arbitrary CLI overrides are not verified"
            )
        return None
    if profile != VENDOR_PROFILE:
        raise ValueError("unknown conformance execution profile")
    if selected_cli is None:
        raise ValueError("vendor execution requires --conformance-cli")
    node = shutil.which("node")
    if node is None:
        raise ValueError("vendor execution requires the original Node 22 toolchain")
    verifier = _DIRECTORY.parent / "verify-mcp-conformance-profile.mjs"
    result = subprocess.run(
        [node, str(verifier), str(selected_cli)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(
            f"vendor execution verification failed: {result.stderr.strip()}"
        )
    verified = json.loads(result.stdout)
    if (
        verified.get("identity") != descriptor()
        or verified.get("descriptorSha256") != DESCRIPTOR_SHA256
        or verified.get("sourceVerified") is not True
        or verified.get("canonicalRebuildMatched") is not True
        or verified.get("selectedCli") != str(selected_cli.resolve())
    ):
        raise ValueError("vendor verifier returned an unexpected execution identity")
    return verified


def execution_metadata(verified: Mapping[str, object]) -> dict[str, object]:
    return {key: verified[key] for key in ("identity", "descriptorSha256")}


def legacy_baseline() -> dict[str, object]:
    data = (_DIRECTORY / "regression-baseline-v1.json").read_bytes()
    if hashlib.sha256(data).hexdigest() != LEGACY_BASELINE_SHA256:
        raise ValueError("the original legacy baseline changed")
    return json.loads(data)


def required_fixed_checks() -> list[dict[str, str]]:
    # These ten previously failing identities passed in the original 85f full
    # capture. A new profile may not turn an already repaired path into an
    # accepted historical failure while migrating the remaining baseline.
    return [
        {
            "mode": mode,
            "transport": "official-http",
            "source": source,
            "scenario": "auth/metadata-var3",
            "check_id": check_id,
        }
        for mode in ("2025-11-25", "2026-07-28")
        for source, check_id in (
            ("harness", "harness/auth/metadata-var3/codex-adapter"),
            ("official", "authorization-request"),
            ("official", "authorization-server-metadata"),
            ("official", "client-registration"),
            ("official", "token-request"),
        )
    ]
