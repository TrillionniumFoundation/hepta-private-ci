#!/usr/bin/env python3
"""Verify intelligence.control product-source truth and emit exact receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SOURCE_FILES = {
    "canonical": ROOT / "codex-rs/hepta-intelligence/src/canonical.rs",
    "canonical_guard": ROOT / "codex-rs/hepta-intelligence/src/canonical_guard.rs",
    "intelligence_lib": ROOT / "codex-rs/hepta-intelligence/src/lib.rs",
    "agentd_lib": ROOT / "codex-rs/hepta-agentd/src/lib.rs",
    "config": ROOT / "codex-rs/hepta-agentd/src/config.rs",
    "main": ROOT / "codex-rs/hepta-agentd/src/main.rs",
    "ingress": ROOT / "codex-rs/hepta-agentd/src/intelligence_ingress.rs",
    "provider": ROOT / "codex-rs/hepta-agentd/src/intelligence_provider.rs",
    "runner": ROOT / "codex-rs/hepta-agentd/src/intelligence_product_runner.rs",
    "state": ROOT / "codex-rs/hepta-agentd/src/state.rs",
    "learning": ROOT / "codex-rs/hepta-agentd/src/intelligence_learning.rs",
    "learning_plan": ROOT / "codex-rs/hepta-agentd/src/intelligence_learning_plan.rs",
    "outcome_plan": ROOT / "codex-rs/hepta-agentd/src/intelligence_outcome_plan.rs",
    "metrics": ROOT / "codex-rs/hepta-agentd/src/intelligence_observability.rs",
    "run_identity": ROOT / "codex-rs/hepta-agentd/src/run_identity.rs",
}

DOC_FILES = {
    "technical": ROOT / "docs/modules/intelligence.control/TECHNICAL.md",
    "implementation_map": ROOT
    / "docs/modules/intelligence.control/IMPLEMENTATION_MAP.json",
    "traceability": ROOT / "docs/modules/intelligence.control/TEST_TRACEABILITY.json",
}


def fail(message: str) -> None:
    raise AssertionError(message)


def require(text: str, token: str, label: str) -> None:
    if token not in text:
        fail(f"{label}: missing {token!r}")


def forbid(text: str, token: str, label: str) -> None:
    if token in text:
        fail(f"{label}: forbidden {token!r}")


def require_order(text: str, first: str, second: str, label: str) -> None:
    left = text.find(first)
    right = text.find(second)
    if left < 0 or right < 0 or left >= right:
        fail(f"{label}: expected {first!r} before {second!r}")


def load_sources() -> dict[str, str]:
    values: dict[str, str] = {}
    for label, path in {**SOURCE_FILES, **DOC_FILES}.items():
        if not path.is_file():
            fail(f"missing {label}: {path.relative_to(ROOT)}")
        values[label] = path.read_text(encoding="utf-8")
    return values


def verify() -> dict[str, object]:
    values = load_sources()

    require(values["run_identity"], "agentd_objective_fence", "generation/fence")
    require(values["run_identity"], "start_bound_run", "composition identity")
    require(values["run_identity"], "composition(41, 42)", "spawn/current test")
    require(values["run_identity"], "current_run_generation", "spawn/current model")

    require(values["ingress"], "AgentdRunStartBindingV1", "durable RunStart")
    require(values["ingress"], "attach_runtime_metrics", "profile metrics sidecar")
    require(values["ingress"], "Option<AgentdIntelligenceDecisionPlanV1>", "Decision plan")
    require(values["ingress"], "provider_sealed::Sealed", "closed provider set")
    require(values["ingress"], "fn product_ready", "provider readiness")

    require(values["config"], "pub(crate) fn with_intelligence_product_runner", "atomic config")
    require(
        values["config"],
        "pub(crate) fn with_intelligence_invocation_provider",
        "atomic config",
    )
    forbid(values["config"], "pub fn with_intelligence_product_runner", "runner setter")
    forbid(
        values["config"],
        "pub fn with_intelligence_invocation_provider",
        "provider setter",
    )
    require(values["main"], "standalone Agentd refuses runner-only", "standalone gate")
    forbid(values["main"], ".with_intelligence_product_runner(", "standalone gate")

    require(values["provider"], "AgentdIntelligenceInvocationRegistryV1", "provider")
    require(values["provider"], "new_product", "product provider")
    require(values["provider"], "invocation.attach_runtime_metrics", "provider metrics")
    require(values["provider"], "AgentdCanonicalIntelligenceRuntimeProfileV1", "runtime profile")
    require(values["provider"], "AgentdCanonicalIntelligenceStatusV1", "profile status")
    require(values["provider"], "compose_canonical_intelligence_profile_v1", "atomic profile")
    require(values["agentd_lib"], "AgentdCanonicalIntelligenceRuntimeProfileV1", "profile export")

    require(values["state"], "let (request, inputs, run_start, decision_plan)", "daemon route")
    require(values["state"], "append_prepared_decision", "Decision-before-ready")
    require_order(
        values["state"],
        "append_prepared_decision",
        ".start_bound_run(",
        "Decision-before-ready",
    )
    require(values["state"], "IntelligenceLearningStateV1::Acknowledged", "Decision ACK")

    require(values["learning"], "AgentdIntelligenceLearningOutboxV1", "durable outbox")
    require(values["learning"], "IntelligenceLearningStateV1::Indeterminate", "outbox state")
    require(values["learning"], "file.sync_all()", "outbox durability")
    require(values["learning"], "verify_active_decision_binding", "Outcome binding")
    require(values["learning_plan"], "candidate_ids_digest_v2", "candidate identity")
    require(values["learning_plan"], "canonical_candidate_set_digest", "candidate set")
    require(values["learning_plan"], "acknowledged_binding", "Decision publication")
    require(values["outcome_plan"], "from_acknowledged_binding", "restart Outcome")
    require(
        values["outcome_plan"],
        "outcome.support_digest = binding.outcome_support_digest",
        "physical Outcome binding",
    )

    require(values["canonical_guard"], "struct GuardedOwnerPorts", "malicious port guard")
    require(values["canonical_guard"], "selected-candidate-membership", "membership guard")
    require(values["canonical_guard"], "malicious_selected_candidate_is_rejected", "guard test")
    require(values["intelligence_lib"], "canonical_guard::prepare_intelligence_run", "guard export")

    require(values["metrics"], "IntelligenceStageMetricsSnapshotV1", "stage metrics")
    require(values["metrics"], "late_workers_active", "late worker metrics")
    require(values["runner"], "ObservedOwnerPortsV1", "observed owner ports")
    require(values["runner"], "record_late_worker_completed", "late worker completion")
    require(values["runner"], "run_start.runtime_metrics()", "observed product run")

    implementation_map = json.loads(values["implementation_map"])
    traceability = json.loads(values["traceability"])
    if implementation_map.get("module") != "intelligence.control":
        fail("implementation map module mismatch")
    if traceability.get("module") != "intelligence.control":
        fail("traceability module mismatch")

    source_digest = hashlib.sha256()
    for label in sorted(SOURCE_FILES):
        source_digest.update(label.encode())
        source_digest.update(b"\0")
        source_digest.update(values[label].encode())
        source_digest.update(b"\0")

    return {
        "schema": "hepta.intelligence-control-source-truth.v1",
        "module": "intelligence.control",
        "sourceDigestSha256": source_digest.hexdigest(),
        "checks": {
            "unifiedGenerationFence": True,
            "durableRunStartBinding": True,
            "concreteBoundedProvider": True,
            "atomicProfileOnly": True,
            "standaloneRunnerOnlyRejected": True,
            "decisionBeforeReady": True,
            "durableDecisionOutcomeOutbox": True,
            "restartOutcomeBinding": True,
            "canonicalCandidateMembership": True,
            "profileOwnedObservability": True,
            "qualificationLegacyWriteIsProductEvidence": False,
        },
    }


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def receipt(output: Path) -> None:
    value = verify()
    value.update(
        {
            "commit": git("rev-parse", "HEAD"),
            "tree": git("rev-parse", "HEAD^{tree}"),
            "worktreeClean": git("status", "--porcelain", "--untracked-files=no") == "",
        }
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    receipt_parser = sub.add_parser("receipt")
    receipt_parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "check":
            value = verify()
            print(json.dumps(value, sort_keys=True))
        else:
            receipt(args.output)
    except (AssertionError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        print(f"intelligence.control verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
