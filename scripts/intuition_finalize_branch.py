#!/usr/bin/env python3
"""Apply the one-time intuition.policy product-composition patch deterministically.

This script is intentionally idempotent. It exists only to keep the temporary
GitHub Actions workflow small and auditable; it grants no runtime, acceptance,
promotion or release authority.
"""

from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def replace_one(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count == 0 and new in text:
        return
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement anchor, found {count}")
    write(path, text.replace(old, new, 1))


def compose_agentd() -> None:
    lib = "codex-rs/hepta-agentd/src/lib.rs"
    if "mod intuition_policy_serving;" not in read(lib):
        replace_one(
            lib,
            "mod intuition_policy_service;\n",
            "mod intuition_policy_service;\nmod intuition_policy_serving;\n",
        )
    if "pub use intelligence_ingress::AgentdIntuitionProductInvocationV1;" not in read(lib):
        replace_one(
            lib,
            "pub use intelligence_ingress::AgentdIntelligenceInvocationV1;\n",
            "pub use intelligence_ingress::AgentdIntelligenceInvocationV1;\n"
            "pub use intelligence_ingress::AgentdIntuitionProductInvocationV1;\n",
        )

    state = "codex-rs/hepta-agentd/src/state.rs"
    if "crate::intuition_policy_serving::authenticate_canonical_intuition(" not in read(state):
        replace_one(
            state,
            "        let invocation = provider.build(&self.identity, record)?;\n"
            "        invocation.validate(&self.identity, record)?;\n\n"
            "        // Freeze only the small immutable composition while holding the run\n",
            "        let invocation = provider.build(&self.identity, record)?;\n"
            "        invocation.validate(&self.identity, record)?;\n"
            "        let crate::AgentdIntelligenceInvocationV1 {\n"
            "            request,\n"
            "            inputs,\n"
            "            intuition_product,\n"
            "        } = invocation;\n"
            "        let episode_id = request.run_id.clone();\n"
            "        let run_snapshot_digest = request.snapshot.digest();\n"
            "        let intuition_request = inputs.intuition_request.clone();\n\n"
            "        // Freeze only the small immutable composition while holding the run\n",
        )
        replace_one(
            state,
            "            .prepare_for_composition(&composition, invocation.request, invocation.inputs)\n",
            "            .prepare_for_composition(&composition, request, inputs)\n",
        )
        replace_one(
            state,
            "            })?;\n\n"
            "        match outcome {\n",
            "            })?;\n\n"
            "        // The compatibility advisory stage is not a product decision. A\n"
            "        // configured product host must independently authenticate the\n"
            "        // current profile/runtime evidence and commit any selected Decision\n"
            "        // before the outcome can cross run admission.\n"
            "        let policy_now = self.require_current_run_start(record)?;\n"
            "        let _authenticated_intuition =\n"
            "            crate::intuition_policy_serving::authenticate_canonical_intuition(\n"
            "                self,\n"
            "                intuition_product,\n"
            "                intuition_request,\n"
            "                episode_id,\n"
            "                run_snapshot_digest,\n"
            "                &outcome,\n"
            "                policy_now,\n"
            "            )?;\n\n"
            "        match outcome {\n",
        )

    replace_one(
        "codex-rs/hepta-agentd/src/intelligence_product.rs",
        "use codex_hepta_intuition::decide_calibrated_v2;\n",
        "use codex_hepta_intuition::calibrated::decide_calibrated_v2;\n",
    )
    replace_one(
        "codex-rs/hepta-intuition/Cargo.toml",
        'default = ["legacy-intuition-api"]\n',
        "default = []\n",
    )


def fix_compile_edges() -> None:
    replace_one(
        "codex-rs/hepta-agentd/src/intuition_policy.rs",
        "        match writer.append_decision(expected_predecessor, request, evidence, now) {\n",
        "        match writer.append_decision(expected_predecessor, request, &evidence, now) {\n",
    )
    replace_one(
        "codex-rs/hepta-agentd/tests/intuition_policy_product_v3.rs",
        '    assert_eq!(reopened.snapshot().expect("snapshot").records, 1);\n',
        "    assert_eq!(\n"
        "        reopened.snapshot().expect(\"snapshot\").head_digest,\n"
        "        first_append.chain_digest,\n"
        "    );\n",
    )


def upgrade_authenticated_fast_gate() -> None:
    path = "codex-rs/hepta-intelligence/examples/intuition_authenticated_fast_gate.rs"
    text = read(path)
    if "decide_authenticated_intuition_v2" not in text:
        return
    for old, new in [
        ("decide_authenticated_intuition_v2", "decide_authenticated_intuition_v3"),
        ("AssignmentCommitmentV1", "AssignmentCommitmentV2"),
        ("ScoringCommitmentV1", "ScoringCommitmentV2"),
        ("canonical_runtime_commitment_payload_v1", "canonical_runtime_commitment_payload_v2"),
        ("canonical_scored_outputs_digest_v1", "canonical_scored_outputs_digest_v2"),
    ]:
        text = text.replace(old, new)
    text = text.replace(
        "use codex_hepta_intuition::OodArtifactV1;\n",
        "use codex_hepta_intuition::OodArtifactV1;\n"
        "use codex_hepta_intuition::PolicyGeneration;\n",
        1,
    )
    text = text.replace(
        "use codex_hepta_intuition::canonical_candidate_order_digest_v1;\n",
        "use codex_hepta_intuition::canonical_assignment_distribution_digest_v2;\n"
        "use codex_hepta_intuition::canonical_candidate_identity_digest_v2;\n"
        "use codex_hepta_intuition::canonical_candidate_order_digest_v1;\n",
        1,
    )
    old = """        candidate_set_digest,
        scored_outputs_digest: canonical_scored_outputs_digest_v2(&request).expect("scores"),
        policy_digest,
        policy_generation: 1,
    };
    let assignment = AssignmentCommitmentV2::Deterministic;
"""
    new = """        candidate_identity_digest: canonical_candidate_identity_digest_v2(
            &request.candidates,
        )
        .expect("identity"),
        scored_outputs_digest: canonical_scored_outputs_digest_v2(&request).expect("scores"),
        policy_digest,
        policy_generation: PolicyGeneration::new(1).expect("generation"),
    };
    let assignment = AssignmentCommitmentV2::Deterministic {
        distribution_digest: canonical_assignment_distribution_digest_v2(&request)
            .expect("distribution"),
    };
"""
    if old not in text:
        raise SystemExit("authenticated fast gate scoring anchor missing")
    write(path, text.replace(old, new, 1))


def update_technical_guide() -> None:
    path = "docs/modules/intuition.policy/TECHNICAL.md"
    text = read(path)
    heading = "## Current production qualification candidate (2026-09-26)"
    if heading in text:
        return
    marker = "<!-- BEGIN GENERATED EXACT REGISTRY PROJECTION -->"
    if text.count(marker) != 1:
        raise SystemExit("TECHNICAL.md generated projection marker missing or duplicated")
    section = """
## Current production qualification candidate (2026-09-26)

The current native contract is a source-integrated qualification candidate, not an activated or released policy. `codex-hepta-intuition` owns a pure, authority-free selector. Candidate generation, scoring, calibration-artifact production, OOD-artifact production, evaluation, random-stream ownership and durable learning remain with their registered owners.

### Product contract and commitment ownership

Product selection uses `decide_calibrated_v4`. `Ppm` bounds probability-quality fields to `[0, 1_000_000]`, `PolicyGeneration` rejects zero, and profile-forced routing preserves the original request risk while emitting an explicit slow-path reason. Candidate identity, scorer outputs and assignment/RNG facts have separate canonical V2 digests; the final runtime payload combines them with the exact request and profile to prevent substitution without mixing owner responsibilities.

Historical `decide_calibrated` and `decide_calibrated_v2` remain behind the non-default `legacy-intuition-api` feature for replay and migration. The canonical intelligence pipeline may compute the V2 result only as a compatibility advisory. It cannot cross product admission unless the independently authenticated V3 result agrees on disposition, selected candidate and propensity.

### Three-party authentication and complete Agentd pins

`codex-hepta-intelligence::decide_authenticated_intuition_v3` requires independent Generator, Evaluator and Observer evidence over, respectively, candidate completeness, profile/calibration/OOD qualification, and exact scorer/assignment commitments. Stable error codes are returned at module and Agentd boundaries.

`AgentdIntuitionPolicyPinsV2` fixes the policy-profile digest, policy digest, nonzero generation, objective class, model artifact, scorer contract, calibration artifact, OOD artifact, risk rule and optional RNG owner. A trusted evaluator signature therefore cannot silently replace host-selected policy semantics.

### Actual serving sequence

```text
signed ObjectiveStart and durable RunStart
  -> host-owned AgentdIntelligenceInvocationV1
  -> seven-owner canonical advisory pipeline
  -> authenticated V3 Generator/Evaluator/Observer verification
  -> V4 disposition and complete Agentd pin validation
  -> canonical/authenticated parity check
  -> selected-only durable ProductionDecisionV2 append
  -> final generation/current-run fence
  -> run and context admission
```

`AgentdState::start_canonical_intelligence` is the product composition point. A configured policy host without authenticated product material, or product material without a configured host, fails closed. Abstain and slow-path append no selected Decision and never become effect authority. Every receipt retains `AuthorityPosture::DENY_ALL`.

### Durability, retry and recovery

`IntuitionPolicyLearningSink` owns the sole `LedgerWriter` used by this composition. A selected result cannot return success without a witnessed append. Ordinary append rejection returns a stable failure code. The only uncertain state is `IndeterminateAfterLedgerCommit`, meaning the ledger commit succeeded while the independent witness did not advance. Agentd returns that state without dispatch authority and does not retry through a poisoned in-process handle. The owner must reopen the ledger and witness against the externally retained anchor, then replay the exact same deterministic record, signed evidence and original predecessor. The recovered writer admits only a one-event-lag idempotent replay and rejects record, evidence or predecessor drift. Generation is checked before preparation, before commit and after commit; a post-commit generation change yields an indeterminate service result rather than execution authority.

### Qualification and claim boundary

The dedicated `.github/workflows/hepta-intuition-qualification.yml` independently runs exact-source and deterministic synthetic-merge formatting, all-target compilation, strict Clippy, policy/intelligence tests, Agentd product tests, kernel and authenticated V3 p50/p95/p99 gates, learning-ledger append/reopen measurements, patch hygiene, and an exact-SHA command record. Property-style mutation tests, canonical Rust/JSON golden vectors and a standard `cargo-fuzz` target cover the digest boundary.

A green workflow proves repository qualification only. `qualification/intuition.policy/ACCEPTANCE_TEMPLATE.json` deliberately leaves independent evaluator acceptance, operator target-host acceptance, canary authorization, promotion and release unsigned and pending. This branch cannot self-issue those authorities.

"""
    write(path, text.replace(marker, section + marker, 1))


def main() -> None:
    compose_agentd()
    fix_compile_edges()
    upgrade_authenticated_fast_gate()
    update_technical_guide()


if __name__ == "__main__":
    main()
