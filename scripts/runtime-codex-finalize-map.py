#!/usr/bin/env python3
"""Finalize runtime.codex source maps after the source-only convergence commit.

The source commit/tree are supplied by the maintainer workflow. The following
map-only commit may safely describe that prior immutable source graph without
creating a self-referential commit hash.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE_COMMIT = os.environ.get("RUNTIME_CODEX_SOURCE_COMMIT", "")
SOURCE_TREE = os.environ.get("RUNTIME_CODEX_SOURCE_TREE", "")


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def load(path: str) -> dict[str, Any]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def write(path: str, value: dict[str, Any]) -> None:
    (ROOT / path).write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def update_observed_heads(value: Any) -> int:
    changed = 0
    if isinstance(value, dict):
        observed = value.get("observedAtHead")
        if isinstance(observed, dict) and {"commit", "tree"}.issubset(observed):
            observed["commit"] = SOURCE_COMMIT
            observed["tree"] = SOURCE_TREE
            changed += 1
        for child in value.values():
            changed += update_observed_heads(child)
    elif isinstance(value, list):
        for child in value:
            changed += update_observed_heads(child)
    return changed


def object_at(path: str) -> dict[str, str]:
    return {
        "path": path,
        "object": git("rev-parse", f"{SOURCE_COMMIT}:{path}"),
    }


def finalize_supervisor() -> None:
    path = "docs/modules/runtime.supervisor/IMPLEMENTATION_MAP.json"
    value = load(path)
    changed = update_observed_heads(value)
    if changed == 0:
        raise RuntimeError("runtime.supervisor has no observedAtHead source binding")
    write(path, value)


def finalize_codex() -> None:
    path = "docs/modules/runtime.codex/IMPLEMENTATION_MAP.json"
    value = load(path)
    value["sourceMaturity"] = "durable_bound_execution_candidate"
    value["declaredRoots"] = [
        "codex-rs/codex-app-server",
        "codex-rs/hepta-agent-protocol",
        "codex-rs/hepta-agentd",
        "codex-rs/hepta-codex-adapter",
        "codex-rs/hepta-infer-core",
        "codex-rs/hepta-infer-worker-host",
    ]
    value["resolvedRoots"] = [
        "codex-rs/app-server",
        "codex-rs/hepta-agent-protocol",
        "codex-rs/hepta-agentd",
        "codex-rs/hepta-codex-adapter",
        "codex-rs/hepta-infer-core",
        "codex-rs/hepta-infer-worker-host",
    ]
    value["sourceRoot"] = value["declaredRoots"]
    value["repositoryCandidate"] = {
        "sourceCommit": SOURCE_COMMIT,
        "sourceTree": SOURCE_TREE,
        "semantics": "immutable source-only convergence commit; the containing map commit is intentionally later and non-self-referential",
    }
    value["repositoryControlledGaps"] = [
        "exact-head and deterministic current-main synthetic-merge qualification receipts must pass at the final map head",
        "durable quarantine and cleanup recovery evidence must remain green under the product crash matrix",
    ]
    boundary = value.setdefault("claimBoundary", {})
    boundary.update(
        {
            "nativeSourceMappingComplete": True,
            "repositoryControlledDocumentationGapsClosed": True,
            "repositoryControlledMappingGapsClosed": True,
            "repositoryControlledSourceBoundaryGapsClosed": True,
            "productExecutionComplete": False,
            "deploymentQualificationComplete": False,
            "independentAcceptanceComplete": False,
            "sourceRootPresent": True,
            "productionImplementation": False,
            "productExecutionProved": False,
            "independentAcceptance": False,
            "activation": False,
            "release": False,
            "implementedOperationMappingComplete": True,
        }
    )
    value["productCallerState"] = "durable_bound_candidate_qualification_pending"
    provenance = value.setdefault("exactCandidateProvenance", {})
    provenance["sourceCommit"] = SOURCE_COMMIT
    provenance["sourceTree"] = SOURCE_TREE
    provenance["hardCodedInMap"] = False
    provenance["rationale"] = (
        "The map records the preceding immutable source-only commit/tree. Exact "
        "qualification identity is still derived from the checked-out final head, "
        "avoiding self-reference while retaining source provenance."
    )

    bindings = value.setdefault("productionCallerBindings", [])
    if not any(item.get("role") == "agentd_durable_run_owner" for item in bindings):
        bindings.append(
            {
                "role": "agentd_durable_run_owner",
                "path": "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
                "symbol": "pub fn open_durable(",
                "buildTarget": "codex-hepta-agentd",
                "semantics": "Loads and publishes the complete run/context/dispatch/abort-proof owner snapshot with fsync+rename durability, an advisory writer lock, exact composition binding, and monotonic store-revision stale-writer fencing before product RPC acknowledgement.",
            }
        )

    tests = value.setdefault("compositionTests", [])
    if not any(item.get("path") == "codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs" for item in tests):
        tests.append(
            {
                "path": "codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs",
                "command": "cargo test --locked -p codex-hepta-agentd --lib lane_b_runtime",
                "covers": [
                    "restart recovery of exact dispatch binding, abort commitment and proof",
                    "cross-process stale-writer revision fencing",
                    "crash-consistent owner snapshot publication",
                ],
            }
        )
    if not any(item.get("path") == "codex-rs/hepta-infer-worker-host/tests/runtime_codex_crash_matrix.rs" for item in tests):
        tests.append(
            {
                "path": "codex-rs/hepta-infer-worker-host/tests/runtime_codex_crash_matrix.rs",
                "command": "cargo test --locked -p codex-hepta-infer-worker-host --test runtime_codex_crash_matrix",
                "covers": [
                    "pre-effect abort crash boundaries",
                    "unknown outcome retention",
                    "terminal/rejection cleanup state",
                ],
            }
        )

    source_paths = [
        "codex-rs/app-server/src/request_processors/thread_processor.rs",
        "codex-rs/app-server/src/request_processors/turn_processor.rs",
        "codex-rs/core/src/tools/spec_plan.rs",
        "codex-rs/hepta-agent-protocol",
        "codex-rs/hepta-agentd",
        "codex-rs/hepta-codex-adapter",
        "codex-rs/hepta-infer-core",
        "codex-rs/hepta-infer-worker-host",
        "codex-rs/Cargo.lock",
        ".github/workflows/runtime-codex-qualification.yml",
        "scripts/runtime-codex-qualification.py",
    ]
    value["sourceObjects"] = [object_at(item) for item in source_paths]
    write(path, value)


def replace_section(path: str, title: str, body: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    begin = f"<!-- {title}:begin -->"
    end = f"<!-- {title}:end -->"
    section = f"{begin}\n{body.rstrip()}\n{end}"
    if begin in text and end in text:
        prefix, remainder = text.split(begin, 1)
        _, suffix = remainder.split(end, 1)
        text = prefix.rstrip() + "\n\n" + section + suffix
    else:
        text = text.rstrip() + "\n\n" + section + "\n"
    target.write_text(text, encoding="utf-8")


def finalize_docs() -> None:
    replace_section(
        "docs/modules/runtime.codex/TECHNICAL.md",
        "runtime-codex-durable-owner",
        f"""## Repository-controlled durable-owner candidate

The immutable source convergence point is `{SOURCE_COMMIT}` with tree
`{SOURCE_TREE}`. Agentd opens `runtime-codex-agent-runs-v1.json` below the
exact generation run root. The store publishes complete run, context, bound
dispatch, abort commitment, nonce-proof terminal, and admission state before a
product RPC is acknowledged. Publication uses an advisory single-writer lock,
monotonic store revision, full composition identity, file fsync, atomic rename,
and parent-directory fsync. A stale process therefore fails its next store CAS
rather than overwriting a newer owner.

This closes the repository implementation boundary only. Exact-head and
current-main synthetic-merge receipts must still be green, and target-host,
real-provider, trusted-time, signer-custody, canary, rollback and independent
acceptance gates remain external and false until independently supplied.""",
    )
    replace_section(
        "docs/modules/runtime.codex/STATE_MACHINE.md",
        "runtime-codex-restart-store",
        """## Durable restart projection

Every externally acknowledged mutation is followed by one transactional owner
snapshot. Restart restores the exact phase and all dispatch/abort bindings; it
does not collapse a bound dispatch or an `AbortedBeforeEffect` proof into an
information-poor generic indeterminate state. The store revision is a writer
fence, not merely an audit counter: a process that loaded an older revision
cannot publish after another process advances the store.""",
    )
    replace_section(
        "docs/modules/runtime.codex/OPERATIONS.md",
        "runtime-codex-run-store",
        """## Agentd run-owner store

The owner store is `<agent run root>/runtime-codex-agent-runs-v1.json`; its lock
is the adjacent `.lock` path. Back up the store only after admission is closed
and the Agentd process has stopped. Do not copy a live file as a release or
recovery receipt. On composition mismatch, decode failure, invalid bounds, or a
stale writer revision, Agentd fails closed and must not delete or regenerate the
store automatically. Preserve the file and its filesystem metadata for incident
analysis.""",
    )


def main() -> None:
    if len(SOURCE_COMMIT) != 40 or len(SOURCE_TREE) != 40:
        raise SystemExit("source commit/tree environment binding is missing")
    if git("rev-parse", f"{SOURCE_COMMIT}^{{tree}}") != SOURCE_TREE:
        raise SystemExit("source commit does not resolve to supplied tree")
    finalize_supervisor()
    finalize_codex()
    finalize_docs()


if __name__ == "__main__":
    main()
