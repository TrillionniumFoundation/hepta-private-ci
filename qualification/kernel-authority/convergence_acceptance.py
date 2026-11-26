#!/usr/bin/env python3
"""Validate the source-bound kernel.authority remaining-four convergence state.

This validator proves only repository source composition and claim discipline. It
never turns source inspection into native execution, target-host qualification,
production trust, independent acceptance, activation, or release authority.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "qualification/kernel-authority/convergence_manifest.json"
SHA1 = re.compile(r"[0-9a-f]{40}")


class ConvergenceError(RuntimeError):
    """The source anchor, implementation contract, or claim boundary drifted."""


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ConvergenceError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ConvergenceError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise ConvergenceError(f"{path} must contain one JSON object")
    return value


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_NO_LAZY_FETCH="1",
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
    )
    try:
        return subprocess.run(
            ["git", "--literal-pathspecs", "-c", "core.fsmonitor=false", *args],
            cwd=ROOT,
            env=env,
            check=check,
            text=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or "git command failed").strip()
        raise ConvergenceError(detail) from error


def _canonical_relative_file(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConvergenceError(f"{label} must be a non-empty repository-relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) != value:
        raise ConvergenceError(f"{label} is not canonical: {value!r}")
    resolved = (ROOT / value).resolve()
    if not resolved.is_relative_to(ROOT.resolve()) or not resolved.is_file():
        raise ConvergenceError(f"{label} is absent or escapes the repository: {value}")
    return value


def _exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ConvergenceError(f"{label} fields drifted")
    return value


def _false(value: Any, label: str) -> None:
    if value is not False:
        raise ConvergenceError(f"{label} must remain false without independent evidence")


def _true(value: Any, label: str) -> None:
    if value is not True:
        raise ConvergenceError(f"{label} must be true for this source-closure manifest")


def validate_manifest(manifest: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    expected_top = {
        "schema",
        "schemaVersion",
        "module",
        "sourceAnchor",
        "preservedInvariants",
        "trackedSourcePaths",
        "closures",
        "claimBoundary",
    }
    _exact_keys(manifest, expected_top, "manifest")
    if manifest["schema"] != "hepta.kernel-authority-convergence-manifest.v1":
        raise ConvergenceError("unsupported convergence manifest schema")
    if type(manifest["schemaVersion"]) is not int or manifest["schemaVersion"] != 1:
        raise ConvergenceError("unsupported convergence manifest version")
    if manifest["module"] != "kernel.authority":
        raise ConvergenceError("convergence manifest owns only kernel.authority")

    anchor = _exact_keys(manifest["sourceAnchor"], {"commit", "tree"}, "sourceAnchor")
    if any(not isinstance(value, str) or SHA1.fullmatch(value) is None for value in anchor.values()):
        raise ConvergenceError("sourceAnchor requires exact lowercase commit and tree identities")

    invariants = manifest["preservedInvariants"]
    if (
        not isinstance(invariants, list)
        or len(invariants) < 6
        or any(not isinstance(value, str) or not value for value in invariants)
        or len(set(invariants)) != len(invariants)
    ):
        raise ConvergenceError("preservedInvariants must be a unique non-empty closed list")

    paths = manifest["trackedSourcePaths"]
    if (
        not isinstance(paths, list)
        or not paths
        or len(set(paths)) != len(paths)
    ):
        raise ConvergenceError("trackedSourcePaths must be a unique non-empty list")
    canonical_paths = [
        _canonical_relative_file(value, "tracked source path") for value in paths
    ]

    closures = _exact_keys(
        manifest["closures"],
        {
            "trustedClockOwnership",
            "productionTrustBootstrap",
            "executablePortAcceptance",
            "measuredHotPathAndCapacity",
            "sourceBoundDocumentation",
        },
        "closures",
    )
    for name, value in closures.items():
        if not isinstance(value, dict):
            raise ConvergenceError(f"closures.{name} must be an object")
        _true(value.get("sourceClosed"), f"closures.{name}.sourceClosed")

    clock = closures["trustedClockOwnership"]
    _false(clock.get("exactCandidateExecutionProved"), "trustedClockOwnership.exactCandidateExecutionProved")
    _false(clock.get("productionAccepted"), "trustedClockOwnership.productionAccepted")

    bootstrap = closures["productionTrustBootstrap"]
    _false(bootstrap.get("ordinaryDeploymentProviderWired"), "productionTrustBootstrap.ordinaryDeploymentProviderWired")
    _false(bootstrap.get("compatibilityProfileIsProduction"), "productionTrustBootstrap.compatibilityProfileIsProduction")
    _false(bootstrap.get("productionAccepted"), "productionTrustBootstrap.productionAccepted")

    ports = closures["executablePortAcceptance"]
    _true(ports.get("rawNativeLogsRequired"), "executablePortAcceptance.rawNativeLogsRequired")
    _true(ports.get("rawProductProcessLogsRequired"), "executablePortAcceptance.rawProductProcessLogsRequired")
    _false(ports.get("allDeclaredPortsNativelyVerified"), "executablePortAcceptance.allDeclaredPortsNativelyVerified")
    _false(ports.get("allDeclaredPortsProductionAccepted"), "executablePortAcceptance.allDeclaredPortsProductionAccepted")

    capacity = closures["measuredHotPathAndCapacity"]
    _true(capacity.get("realTargetHostRequired"), "measuredHotPathAndCapacity.realTargetHostRequired")
    _false(capacity.get("targetCollectionExecuted"), "measuredHotPathAndCapacity.targetCollectionExecuted")
    _false(capacity.get("runtimeOptimizationAuthorized"), "measuredHotPathAndCapacity.runtimeOptimizationAuthorized")
    _false(capacity.get("productionSloGranted"), "measuredHotPathAndCapacity.productionSloGranted")

    documentation = closures["sourceBoundDocumentation"]
    _false(documentation.get("exactCandidateExecutionProved"), "sourceBoundDocumentation.exactCandidateExecutionProved")
    _false(documentation.get("independentAcceptance"), "sourceBoundDocumentation.independentAcceptance")

    claims = _exact_keys(
        manifest["claimBoundary"],
        {
            "productionImplementation",
            "productExecutionProved",
            "targetHostQualified",
            "independentAcceptance",
            "activationGranted",
            "releaseGranted",
        },
        "claimBoundary",
    )
    for name, value in claims.items():
        _false(value, f"claimBoundary.{name}")

    return {"commit": anchor["commit"], "tree": anchor["tree"]}, canonical_paths


def validate_source(anchor: dict[str, str], paths: list[str]) -> dict[str, bool]:
    if _git("cat-file", "-t", anchor["commit"]).stdout.strip() != "commit":
        raise ConvergenceError("source anchor is not a commit")
    observed_tree = _git("rev-parse", f"{anchor['commit']}^{{tree}}").stdout.strip()
    if observed_tree != anchor["tree"]:
        raise ConvergenceError("source anchor commit/tree identity mismatch")
    _git("merge-base", "--is-ancestor", anchor["commit"], "HEAD")

    for path in paths:
        _git("cat-file", "-e", f"HEAD:{path}")
    changed = _git(
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--name-only",
        anchor["commit"],
        "HEAD",
        "--",
        *paths,
    ).stdout.strip()
    if changed:
        raise ConvergenceError(
            "tracked convergence source changed after the immutable anchor: "
            + changed.replace("\n", ", ")
        )

    contract = (ROOT / "codex-rs/hepta-contracts/src/authority_trust.rs").read_text(encoding="utf-8")
    clock_alias = (ROOT / "codex-rs/hepta-agentd/src/authority_feed_clock.rs").read_text(encoding="utf-8")
    bootstrap = (ROOT / "codex-rs/hepta-agentd/src/automation_authority_bootstrap.rs").read_text(encoding="utf-8")
    host = (ROOT / "codex-rs/hepta-agentd/src/automation_effect_host.rs").read_text(encoding="utf-8")
    runtime = (ROOT / "codex-rs/hepta-agentd/src/runtime.rs").read_text(encoding="utf-8")
    fleet = (ROOT / "codex-rs/hepta-fleet/src/authority_port.rs").read_text(encoding="utf-8")
    port_acceptance = (ROOT / "qualification/kernel-authority/port_acceptance.py").read_text(encoding="utf-8")
    production_workflow = (ROOT / ".github/workflows/kernel-authority-production-closure.yml").read_text(encoding="utf-8")
    process_workflow = (ROOT / ".github/workflows/kernel-authority-product-process-recovery.yml").read_text(encoding="utf-8")
    capacity_workflow = (ROOT / ".github/workflows/kernel-authority-target-capacity.yml").read_text(encoding="utf-8")

    checks = {
        "canonicalFeedClockType": (
            "pub(super) use codex_hepta_contracts::FinalUseFeedClock;" in clock_alias
            and "struct FinalUseFeedClock" not in clock_alias
            and "struct FeedClock" not in clock_alias
            and "pub struct FinalUseFeedClock" in contract
        ),
        "productionTrustBundleRetained": all(
            token in contract
            for token in (
                "pub trait ProductionAuthorityClock",
                "pub trait ProductionAuthorityFrontierStore",
                "pub trait ProductionAuthorityKeyCustody",
                "pub struct ProductionAuthorityTrustBundle",
            )
        ),
        "agentdTypedProductionBootstrap": all(
            token in bootstrap
            for token in (
                "pub struct AgentdProductionAuthorityBootstrap",
                "pub fn from_trust_bundle",
                "ProductionAuthorityTrustBundle",
                "ProductionFinalUseTrustContext::bind",
            )
        ),
        "singleAgentdEffectOwnerComposition": all(
            token in host
            for token in (
                "pub(crate) fn open_production",
                "fn open_with_authority",
                "AgentdProductionAuthorityBootstrap",
                "recover_state_dir_with_issuer_keys",
                "admission_clock.invalidate()",
                "admission_clock.publish",
            )
        ),
        "runtimeSeparatesProductionAndCompatibility": all(
            token in runtime
            for token in (
                "AgentdAutomationEffectHost::open_production",
                "AgentdAutomationEffectHost::open(&identity, &path)",
                "automation effect production authority requires a protected host file",
            )
        ),
        "fleetUsesOneProductionBundle": all(
            token in fleet
            for token in (
                "pub fn open_production",
                "ProductionAuthorityTrustBundle",
                "AuthorityLeaseRegistry::open_production_state_dir",
                ".bind_dispatch(",
            )
        ),
        "portAcceptanceReopensRawEvidence": all(
            token in port_acceptance
            for token in (
                "hepta.kernel-authority-port-acceptance.v2",
                "nativeIntegrationVerified",
                "productionAccepted",
                "two-product-process-recovery",
                "queued-revocation",
                "cancel-before-effect",
                "cancel-after-effect",
            )
        ),
        "productionClosureConsumesPortProjection": all(
            token in production_workflow
            for token in (
                "port_acceptance.py",
                "productProcessVerified",
                "productionTrustProved",
            )
        ),
        "twoProcessRecoveryGateIsNative": all(
            token in process_workflow
            for token in (
                "authority_effect_process_restart",
                "cargo clippy",
                "product_process_recovery.py",
            )
        ),
        "targetCapacityRequiresPinnedRealHost": all(
            token in capacity_workflow
            for token in (
                "runs-on: [self-hosted, kernel-authority-target]",
                "capacity_matrix.py",
                "hot_path_gate.py",
                "productionSloGranted",
                "runtimeOptimizationAuthorized",
            )
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ConvergenceError("source convergence checks failed: " + ", ".join(failed))
    return checks


def project(manifest: dict[str, Any]) -> dict[str, Any]:
    anchor, paths = validate_manifest(manifest)
    checks = validate_source(anchor, paths)
    head = _git("rev-parse", "HEAD").stdout.strip()
    tree = _git("rev-parse", "HEAD^{tree}").stdout.strip()
    if SHA1.fullmatch(head) is None or SHA1.fullmatch(tree) is None:
        raise ConvergenceError("current candidate identity is invalid")
    return {
        "schema": "hepta.kernel-authority-convergence-projection.v1",
        "schemaVersion": 1,
        "module": "kernel.authority",
        "candidate": {"commit": head, "tree": tree},
        "sourceAnchor": anchor,
        "trackedSourcePaths": paths,
        "sourceChecks": checks,
        "repositorySourceClosurePassed": True,
        "exactCandidateExecutionProved": False,
        "ordinaryDeploymentProviderWired": False,
        "allDeclaredPortsNativelyVerified": False,
        "targetCollectionExecuted": False,
        "runtimeOptimizationAuthorized": False,
        "productionImplementation": False,
        "productExecutionProved": False,
        "targetHostQualified": False,
        "independentAcceptance": False,
        "activationGranted": False,
        "releaseGranted": False,
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    resolved = path.resolve()
    if resolved.is_relative_to(ROOT.resolve()):
        raise ConvergenceError("projection output must not mutate the qualified checkout")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary = resolved.with_name(resolved.name + ".next")
    temporary.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, resolved)
    reopened = _load_json(resolved)
    if reopened != value:
        raise ConvergenceError("projection failed exact reopen")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        value = project(_load_json(args.manifest))
        if args.output is not None:
            _write_json(args.output, value)
        else:
            print(json.dumps(value, indent=2, sort_keys=True))
    except (ConvergenceError, OSError, UnicodeError, ValueError) as error:
        print(f"kernel.authority convergence rejected: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
