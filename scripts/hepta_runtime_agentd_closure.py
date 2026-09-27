#!/usr/bin/env python3
"""Verify runtime.agentd product-composition closure at one exact Git candidate.

This verifier is intentionally source-derived. It does not cache a branch name,
workflow conclusion, deployment decision, or production activation claim in the
repository. CI binds the generated implementation map and closure receipt to the
exact candidate SHA, tree and Git blobs.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

SCHEMA = 2
SHA = re.compile(r"[0-9a-f]{40}\Z")
STATIC_IMPLEMENTATION_MAP = "docs/modules/runtime.agentd/IMPLEMENTATION_MAP.json"

SOURCE_REQUIREMENTS: dict[str, dict[str, tuple[str, ...]]] = {
    "codex-rs/hepta-agentd/src/canonical_runtime_bootstrap.rs": {
        "required": (
            "pub struct AgentdCanonicalRuntimeBootstrapV1",
            "runner: Arc<AgentdIntelligenceProductRunnerV1>",
            "invocation: Arc<dyn AgentdIntelligenceInvocationProviderV1>",
            "neuron: Arc<dyn AgentdCanonicalNeuronOwnerV1>",
            "executor: Arc<ProcessRuntimeCodexExecutorV1>",
            "input_provider: Arc<dyn RuntimeCodexInputProviderV1>",
            "final_use_authority_digest: Digest32",
            "install_agentd_supervisor_with_limits",
            "NeuronSealedInvocationProviderV1",
            "AgentdNeuronInvocationSealV1",
        ),
        "ordered": (
            "with_intelligence_product_runner",
            "with_intelligence_invocation_provider",
            "install_agentd_supervisor_with_limits",
        ),
        "forbidden": (),
    },
    "codex-rs/hepta-agentd/src/runtime.rs": {
        "required": (
            '"runtime-codex-supervisor"',
            "ProcessRuntimeCodexExecutorV1::run_installed_agentd_supervisor",
            "ProcessRuntimeCodexExecutorV1::cancel_installed_runs",
        ),
        "ordered": (),
        "forbidden": (),
    },
    "codex-rs/hepta-agentd/src/state.rs": {
        "required": (
            "pub(crate) fn canonical_intelligence_configured",
            "pub(crate) fn canonical_intelligence_enabled",
            "agentd_supervisor_snapshot",
            "snapshot.ready && !snapshot.closed",
            "pub(crate) fn refresh_runtime_codex_readiness",
            "ProcessRuntimeCodexExecutorV1::cancel_installed_runs",
            "canonical intelligence physical executor is not ready",
        ),
        "ordered": (),
        "forbidden": (),
    },
    "codex-rs/hepta-agentd/src/run_start_authority.rs": {
        "required": (
            "ProcessRuntimeCodexExecutorV1::reserve_canonical_run",
            "start_canonical_intelligence",
            "cancel_canonical_run_after_schedule_rejection",
            "runtime_codex_schedule_rejected",
        ),
        "ordered": (
            "ProcessRuntimeCodexExecutorV1::reserve_canonical_run",
            "start_canonical_intelligence",
        ),
        "forbidden": ("AgentdClient::new",),
    },
    "codex-rs/hepta-agentd/src/runtime_codex_executor.rs": {
        "required": (
            "operation_locks: StdMutex<BTreeMap<String, Arc<Mutex<()>>>>",
            "fn operation_lock_for",
            "fn release_operation_lock",
            "pub struct RuntimeCodexReconcileReportV1",
            "pub fenced_unresolved: usize",
        ),
        "ordered": (),
        "forbidden": ("operation_lock: Mutex<()>",),
    },
    "codex-rs/hepta-agentd/src/runtime_codex_supervisor.rs": {
        "required": (
            "RuntimeCodexScheduleReservationV1",
            "try_reserve_owned",
            "Semaphore::new",
            "JoinSet::new",
            "reconcile_pending",
            "archive_terminal_operations",
            "cancel_active",
            "fenced_unresolved == 0",
        ),
        "ordered": (),
        "forbidden": (),
    },
    "codex-rs/hepta-agentd/src/runtime_codex_executor_persistence.rs": {
        "required": (
            "RuntimeCodexTerminalWitnessV1",
            'const ARCHIVE_DIRECTORY: &str = ".terminal-archive"',
            'const WITNESS_DIRECTORY: &str = ".terminal-witnesses"',
            "pub(super) fn archive_terminal_operations",
            "terminal witness exists without its archived operation; refusing redispatch",
        ),
        "ordered": (),
        "forbidden": (),
    },
    "codex-rs/hepta-agentd/src/runtime_codex_executor_process_base.rs": {
        "required": (
            "mark_dispatch_fenced(paths, manifest)?",
            "let mut child = command.spawn()?",
        ),
        "ordered": (
            "mark_dispatch_fenced(paths, manifest)?",
            "let mut child = command.spawn()?",
        ),
        "forbidden": (),
    },
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs": {
        "required": (
            "run_mark_dispatched",
            "send_authorized_turn_start",
            "dispatch_native_with_pre_effect_abort",
            "verified_use.enter",
        ),
        "ordered": (
            "dispatch_native_with_pre_effect_abort",
            "run_mark_dispatched",
            "verified_use.enter",
            "send_authorized_turn_start",
        ),
        "forbidden": (),
    },
    "codex-rs/hepta-agentd/Cargo.toml": {
        "required": ("default = []", "production-cognitive-write = []"),
        "ordered": (),
        "forbidden": ('default = ["production-cognitive-write"]',),
    },
    "scripts/qualification/agentd_exact_head.py": {
        "required": (
            'OSES = ("ubuntu-latest", "macos-latest")',
            '"product-process"',
            '"strict-clippy"',
            '"read-only-profile"',
            '"missing required OS/suite receipt"',
        ),
        "ordered": (),
        "forbidden": (),
    },
    ".github/workflows/runtime-agentd-required.yml": {
        "required": (
            "name: Runtime Agentd required candidate",
            "Exact candidate lane: source-head or base-merge.",
            "source-head)",
            "base-merge)",
            "os: [ubuntu-latest, macos-latest]",
            "suite: [owner-libraries, native-library, native-process, daemon-process, product-process, strict-clippy, read-only-profile]",
            "fail-fast: false",
            "runtime.agentd ${{ inputs.lane }} required",
            "Reject missing stale skipped failed or tampered suites",
        ),
        "ordered": (),
        "forbidden": ("continue-on-error: true",),
    },
    ".github/workflows/blocking-ci.yml": {
        "required": (
            "runtime-agentd-source:",
            "runtime-agentd-merge:",
            "uses: ./.github/workflows/runtime-agentd-required.yml",
            "- runtime-agentd-source",
            "- runtime-agentd-merge",
            "name: CI required",
        ),
        "ordered": (),
        "forbidden": (),
    },
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_text(root: Path, relative: str) -> str:
    path = root / relative
    require(path.is_file(), f"missing required source file: {relative}")
    require(not path.is_symlink(), f"symlink source file is forbidden: {relative}")
    size = path.stat().st_size
    require(0 < size <= 2 * 1024 * 1024, f"invalid source file size: {relative}")
    text = path.read_text(encoding="utf-8")
    require("\x00" not in text, f"NUL byte in source file: {relative}")
    return text


def verify_source_files(root: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for relative, contract in SOURCE_REQUIREMENTS.items():
        text = read_text(root, relative)
        for needle in contract["required"]:
            require(needle in text, f"{relative} is missing required invariant: {needle}")
        for needle in contract["forbidden"]:
            require(needle not in text, f"{relative} contains forbidden legacy invariant: {needle}")
        cursor = -1
        for needle in contract["ordered"]:
            position = text.find(needle, cursor + 1)
            require(position >= 0, f"{relative} is missing ordered invariant: {needle}")
            require(position > cursor, f"{relative} has invalid invariant order at: {needle}")
            cursor = position
        results.append(
            {
                "path": relative,
                "required_count": len(contract["required"]),
                "ordered_count": len(contract["ordered"]),
                "forbidden_count": len(contract["forbidden"]),
                "result": "success",
            }
        )
    return results


def git_value(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def exact_implementation_map(
    root: Path,
    source_sha: str,
    source_tree: str,
    verified_files: list[dict[str, Any]],
) -> dict[str, Any]:
    source_objects: list[dict[str, Any]] = []
    paths = [item["path"] for item in verified_files]
    paths.append(STATIC_IMPLEMENTATION_MAP)
    for relative in sorted(set(paths)):
        path = root / relative
        require(path.is_file(), f"implementation-map source path is missing: {relative}")
        blob = git_value(root, "hash-object", "--", relative)
        require(SHA.fullmatch(blob) is not None, f"invalid Git blob identity for {relative}")
        source_objects.append(
            {
                "path": relative,
                "blob": blob,
                "bytes": path.stat().st_size,
            }
        )
    return {
        "schema": "hepta.runtime-agentd.current-implementation.v1",
        "module": "runtime.agentd",
        "source_sha": source_sha,
        "source_tree": source_tree,
        "static_map_path": STATIC_IMPLEMENTATION_MAP,
        "source_objects": source_objects,
        "generated_by_ci": True,
        "committed_dynamic_status": False,
    }


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def verify(root: Path, expected_sha: str, output: Path | None) -> dict[str, Any]:
    root = root.resolve(strict=True)
    require(SHA.fullmatch(expected_sha) is not None, "expected SHA must be exact")
    observed_sha = git_value(root, "rev-parse", "HEAD")
    require(observed_sha == expected_sha, "checkout differs from expected SHA")
    observed_tree = git_value(root, "rev-parse", "HEAD^{tree}")
    require(SHA.fullmatch(observed_tree) is not None, "observed tree identity is invalid")
    dirty = git_value(root, "status", "--porcelain", "--untracked-files=all")
    require(not dirty, "checkout is dirty before source-closure verification")

    files = verify_source_files(root)
    implementation_map = exact_implementation_map(root, observed_sha, observed_tree, files)
    dirty_after = git_value(root, "status", "--porcelain", "--untracked-files=all")
    require(not dirty_after, "source-closure verification changed the checkout")

    receipt = {
        "schema": SCHEMA,
        "module": "runtime.agentd",
        "source_sha": observed_sha,
        "source_tree": observed_tree,
        "repository_controlled_source_closure": True,
        "product_execution_claim": "candidate-tested-only",
        "production_activation": False,
        "files": files,
        "implementation_map": implementation_map,
        "unproven": [
            "target-host-capacity-and-soak",
            "hardware-power-loss-semantics",
            "independent-security-acceptance",
            "release-artifact-signing-and-provenance",
            "production-activation",
        ],
    }
    if output is not None:
        atomic_json(output.resolve(), receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    command = subcommands.add_parser("verify")
    command.add_argument("--root", type=Path, default=Path.cwd())
    command.add_argument("--expected-sha", required=True)
    command.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        receipt = verify(args.root, args.expected_sha, args.output)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"runtime.agentd closure verification failed: {error}", file=os.sys.stderr)
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
