#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, found {count}: {old[:100]!r}")
    write(path, content.replace(old, new, 1))


# Planner input strictness: required-owner closure and duplicate payload rejection.
replace_once(
    "codex-rs/hepta-control-plane/src/planner.rs",
    "    DuplicateOwner(String),\n    DuplicateCandidate(String),\n",
    "    DuplicateOwner(String),\n    UnexpectedOwner(String),\n    DuplicateCandidate(String),\n    DuplicatePayloadDigest(String),\n",
)
replace_once(
    "codex-rs/hepta-control-plane/src/planner.rs",
    "            Self::DuplicateOwner(owner) => write!(formatter, \"duplicate owner summary: {owner}\"),\n            Self::DuplicateCandidate(candidate) => {\n",
    "            Self::DuplicateOwner(owner) => write!(formatter, \"duplicate owner summary: {owner}\"),\n            Self::UnexpectedOwner(owner) => {\n                write!(formatter, \"owner summary is outside the required owner set: {owner}\")\n            }\n            Self::DuplicateCandidate(candidate) => {\n",
)
replace_once(
    "codex-rs/hepta-control-plane/src/planner.rs",
    "            Self::DuplicateCandidate(candidate) => {\n                write!(formatter, \"duplicate plan candidate: {candidate}\")\n            }\n            Self::DuplicateResourceAxis(axis) => {\n",
    "            Self::DuplicateCandidate(candidate) => {\n                write!(formatter, \"duplicate plan candidate: {candidate}\")\n            }\n            Self::DuplicatePayloadDigest(candidate) => {\n                write!(formatter, \"candidate {candidate} repeats a final payload digest\")\n            }\n            Self::DuplicateResourceAxis(axis) => {\n",
)
replace_once(
    "codex-rs/hepta-control-plane/src/planner.rs",
    "    owner_summaries.sort_by(|left, right| left.owner_id.cmp(&right.owner_id));\n    for window in owner_summaries.windows(2) {\n        if window[0].owner_id == window[1].owner_id {\n            return Err(PlannerError::DuplicateOwner(window[0].owner_id.to_string()));\n        }\n    }\n\n    let mut stale_owner_ids = Vec::new();\n",
    "    owner_summaries.sort_by(|left, right| left.owner_id.cmp(&right.owner_id));\n    for window in owner_summaries.windows(2) {\n        if window[0].owner_id == window[1].owner_id {\n            return Err(PlannerError::DuplicateOwner(window[0].owner_id.to_string()));\n        }\n    }\n    let required_owners: BTreeSet<_> = request.required_owner_ids.iter().cloned().collect();\n    if let Some(summary) = owner_summaries\n        .iter()\n        .find(|summary| !required_owners.contains(&summary.owner_id))\n    {\n        return Err(PlannerError::UnexpectedOwner(summary.owner_id.to_string()));\n    }\n\n    let mut stale_owner_ids = Vec::new();\n",
)
replace_once(
    "codex-rs/hepta-control-plane/src/planner.rs",
    "        candidate.final_payload_digests.sort();\n        candidate.final_payload_digests.dedup();\n        candidate.resource_costs.sort();\n",
    "        candidate.final_payload_digests.sort();\n        if candidate\n            .final_payload_digests\n            .windows(2)\n            .any(|window| window[0] == window[1])\n        {\n            return Err(PlannerError::DuplicatePayloadDigest(\n                candidate.candidate_id.to_string(),\n            ));\n        }\n        candidate.resource_costs.sort();\n",
)

# The context planner accepts canonical record bindings and derives its own count.
planner_context = r'''//! Request-local planning over a completed, authenticated cognitive read.
//! The host supplies canonical record bindings and enforces its existing scope
//! and generation fence. These observations say nothing about model quality,
//! memory capacity, future utility, or permission to execute effects.

use std::collections::BTreeSet;

use codex_hepta_ndu::AxisDirection;
use codex_hepta_ndu::AxisLimit;
use codex_hepta_ndu::AxisValue;
use codex_hepta_ndu::ContributionSet;
use codex_hepta_ndu::FeasibilityPosture;
use codex_hepta_ndu::RequiredOrganSet;
use codex_hepta_ndu::UtilityContribution;
use codex_hepta_ndu::UtilityProfile;
use codex_hepta_ndu::legacy_evaluation_policy;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::EvaluatedPlanV1;
use crate::NduPlanningError;
use crate::NduPlanningInputV1;
use crate::OwnerReadinessV1;
use crate::OwnerSummaryV1;
use crate::PlanCandidateV1;
use crate::PlannerAxisValueV1;
use crate::PlannerError;
use crate::PlanningRequestV1;
use crate::ResourceReservationV1;
use crate::SnapshotRequestV1;
use crate::canonical_ndu_planning_policy_digest;
use crate::collect_snapshot;
use crate::evaluate_prepared_plan_with_ndu;
use crate::prepare_plan;

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct VerifiedContextRecordV1 {
    pub record_id: StableId,
    pub revision: Revision,
    pub content_digest: Digest32,
}

/// Host-only evidence after verifying the canonical read and local scope.
/// `encoded_context` excludes planning metadata to avoid self-reference.
pub struct ObservedContextV1<'a> {
    pub owner_id: StableId,
    pub body_generation: Generation,
    pub source_snapshot_digest: Digest32,
    pub read_digest: Digest32,
    pub request_binding_digest: Digest32,
    pub verified_records: &'a [VerifiedContextRecordV1],
    pub encoded_context: &'a [u8],
    pub maximum_context_bytes: u32,
    pub observed_at_micros: u64,
    pub expires_at_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObservedContextPlanV1 {
    pub read_allowed: bool,
    pub context_digest: Digest32,
    pub record_binding_digest: Digest32,
    pub evaluation: EvaluatedPlanV1,
}

/// Compute a two-candidate read/abstain plan using actual NDU and planner code.
/// Utility is derived from canonical record bindings; resource cost is the
/// encoded delivery size. Zero records, ties, and exceeded budgets abstain.
pub fn plan_observed_context(
    observed: ObservedContextV1<'_>,
) -> Result<ObservedContextPlanV1, NduPlanningError> {
    use NduPlanningError as E;
    if observed.verified_records.len() > 4
        || observed.encoded_context.len() > 24 * 1024
        || observed.maximum_context_bytes > 24 * 1024
    {
        return Err(E::Planner(PlannerError::LimitExceeded("observed_context")));
    }
    if observed.source_snapshot_digest.is_zero()
        || observed.read_digest.is_zero()
        || observed.request_binding_digest.is_zero()
        || observed
            .verified_records
            .iter()
            .any(|record| record.content_digest.is_zero())
    {
        return Err(E::Planner(PlannerError::EmptyDigest(
            "authenticated context observation",
        )));
    }
    let mut identities = BTreeSet::new();
    for record in observed.verified_records {
        if !identities.insert((record.record_id.clone(), record.revision)) {
            return Err(E::Planner(PlannerError::DuplicateCandidate(
                record.record_id.to_string(),
            )));
        }
    }

    let id = |name: &str| StableId::new(name).map_err(|_| E::Planner(PlannerError::Arithmetic));
    let count_axis = id("verified-context-items")?;
    let bytes_axis = id("context-bytes")?;
    let read_id = id("read-context")?;
    let context_digest = Digest32::of_bytes(observed.encoded_context);
    let record_binding_digest = digest_verified_records(observed.verified_records);
    let q32 = |value: u32| FixedQ32::from_raw(i64::from(value) << 32);
    let record_count = u32::try_from(observed.verified_records.len())
        .map_err(|_| E::Planner(PlannerError::Arithmetic))?;
    let budget = q32(observed.maximum_context_bytes);
    let bytes = q32(observed.encoded_context.len() as u32);
    let mut objective = b"hepta.control.deliver-verified-context.v2\0".to_vec();
    objective.extend_from_slice(&observed.maximum_context_bytes.to_be_bytes());
    objective.extend_from_slice(observed.request_binding_digest.as_array());
    objective.extend_from_slice(record_binding_digest.as_array());
    let objective_digest = Digest32::of_bytes(&objective);
    let profile = UtilityProfile {
        profile_id: id("verified-context-delivery-v2")?,
        axis_registry_digest: Digest32::of_bytes(
            b"hepta.control.verified-context-axis-registry.v1",
        ),
        normalization_manifest_digest: Digest32::of_bytes(
            b"hepta.control.verified-context-normalization.v1",
        ),
        dimensions: vec![(count_axis.clone(), AxisDirection::Maximize)],
        risk_ceilings: vec![],
        resource_ceilings: vec![AxisLimit {
            axis: bytes_axis.clone(),
            maximum: budget,
        }],
        required_organs: RequiredOrganSet {
            organ_ids: vec![observed.owner_id.clone()],
        },
    };
    let mut input = NduPlanningInputV1 {
        policy: legacy_evaluation_policy(&profile).map_err(E::Ndu)?,
        profile,
        scalarization: None,
        contributions: ContributionSet {
            objective_digest,
            generation: observed.body_generation,
            contributions: vec![],
        },
    };
    let configuration_digest = canonical_ndu_planning_policy_digest(&input).map_err(E::Ndu)?;
    let mut fence = b"hepta.control.context-read-generation.v2\0".to_vec();
    fence.extend_from_slice(observed.owner_id.as_str().as_bytes());
    fence.extend_from_slice(&observed.body_generation.get().to_be_bytes());
    fence.extend_from_slice(observed.request_binding_digest.as_array());
    let mut support = b"hepta.control.authenticated-context-support.v1\0".to_vec();
    support.extend_from_slice(observed.read_digest.as_array());
    support.extend_from_slice(record_binding_digest.as_array());
    support.extend_from_slice(observed.request_binding_digest.as_array());
    let snapshot = collect_snapshot(
        SnapshotRequestV1 {
            objective_digest,
            body_generation: observed.body_generation,
            configuration_digest,
            revocation_frontier_digest: Digest32::of_bytes(&fence),
            snapshot_policy_digest: Digest32::of_bytes(
                b"hepta.control.immutable-context-observation.v2",
            ),
            collected_at_micros: observed.observed_at_micros,
            maximum_owner_age_micros: 1,
            expires_at_micros: observed.expires_at_micros,
            required_owner_ids: vec![observed.owner_id.clone()],
        },
        vec![OwnerSummaryV1 {
            owner_id: observed.owner_id.clone(),
            revision: Revision::new(1)
                .map_err(|_| E::Planner(PlannerError::Arithmetic))?,
            objective_digest,
            body_generation: observed.body_generation,
            configuration_digest,
            observed_at_micros: observed.observed_at_micros,
            expires_at_micros: observed.expires_at_micros,
            readiness: OwnerReadinessV1::Ready,
            source_frontier_digest: observed.source_snapshot_digest,
            support_digest: Digest32::of_bytes(&support),
        }],
    )
    .map_err(E::Planner)?;
    let candidates = [id("abstain")?, read_id.clone()]
        .into_iter()
        .map(|candidate_id| {
            let is_read = candidate_id == read_id;
            PlanCandidateV1 {
                operation_id: candidate_id.clone(),
                candidate_id,
                plan_digest: if is_read {
                    context_digest
                } else {
                    Digest32::of_bytes(b"hepta.control.context-abstain.v2")
                },
                required_owner_ids: vec![observed.owner_id.clone()],
                final_payload_digests: vec![],
                resource_costs: vec![PlannerAxisValueV1 {
                    axis: bytes_axis.clone(),
                    value: if is_read { bytes } else { FixedQ32::ZERO },
                }],
            }
        })
        .collect();
    let prepared = prepare_plan(
        &snapshot,
        PlanningRequestV1 {
            plan_id: id("context-delivery")?,
            now_micros: observed.observed_at_micros,
            deadline_micros: observed.expires_at_micros,
            evaluation_policy_digest: configuration_digest,
            resource_profile_digest: objective_digest,
            candidates,
            resource_reservations: vec![ResourceReservationV1 {
                axis: bytes_axis.clone(),
                endowment: budget,
                essential_floor: FixedQ32::ZERO,
            }],
        },
    )
    .map_err(E::Planner)?;
    input.contributions.contributions = prepared
        .feasible_candidates()
        .iter()
        .map(|candidate| {
            let is_read = candidate.candidate_id == read_id;
            UtilityContribution {
                candidate_id: candidate.candidate_id.clone(),
                organ_id: observed.owner_id.clone(),
                objective_digest,
                generation: observed.body_generation,
                feasibility: FeasibilityPosture::Feasible,
                utility: vec![AxisValue {
                    axis: count_axis.clone(),
                    value: if is_read { q32(record_count) } else { FixedQ32::ZERO },
                }],
                risk: vec![],
                resource: vec![AxisValue {
                    axis: bytes_axis.clone(),
                    value: if is_read { bytes } else { FixedQ32::ZERO },
                }],
                uncertainty: vec![AxisValue {
                    axis: count_axis.clone(),
                    value: FixedQ32::ZERO,
                }],
                support_digest: Digest32::of_bytes(&support),
            }
        })
        .collect();
    let evaluation =
        evaluate_prepared_plan_with_ndu(&snapshot, &prepared, input, observed.observed_at_micros)?;
    Ok(ObservedContextPlanV1 {
        read_allowed: evaluation.plan.chosen_candidate_id() == Some(&read_id),
        context_digest,
        record_binding_digest,
        evaluation,
    })
}

fn digest_verified_records(records: &[VerifiedContextRecordV1]) -> Digest32 {
    let mut bytes = b"hepta.control.verified-context-records.v1\0".to_vec();
    bytes.extend_from_slice(&(records.len() as u64).to_be_bytes());
    for record in records {
        bytes.extend_from_slice(&(record.record_id.as_str().len() as u64).to_be_bytes());
        bytes.extend_from_slice(record.record_id.as_str().as_bytes());
        bytes.extend_from_slice(&record.revision.get().to_be_bytes());
        bytes.extend_from_slice(record.content_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
#[path = "planner_context_tests.rs"]
mod tests;
'''
write("codex-rs/hepta-control-plane/src/planner_context.rs", planner_context)

planner_context_tests = r'''use pretty_assertions::assert_eq;

use super::*;

static RECORDS: std::sync::LazyLock<Vec<VerifiedContextRecordV1>> = std::sync::LazyLock::new(|| {
    vec![
        VerifiedContextRecordV1 {
            record_id: StableId::new("record-a").expect("record"),
            revision: Revision::new(1).expect("revision"),
            content_digest: Digest32::of_bytes(b"content-a"),
        },
        VerifiedContextRecordV1 {
            record_id: StableId::new("record-b").expect("record"),
            revision: Revision::new(2).expect("revision"),
            content_digest: Digest32::of_bytes(b"content-b"),
        },
    ]
});

fn observed() -> ObservedContextV1<'static> {
    ObservedContextV1 {
        owner_id: StableId::new("actual-state-owner").expect("owner id"),
        body_generation: Generation::new(7).expect("owner generation"),
        source_snapshot_digest: Digest32::of_bytes(b"canonical-read-cut"),
        read_digest: Digest32::of_bytes(b"verified-read"),
        request_binding_digest: Digest32::of_bytes(b"request-query-ranker-binding"),
        verified_records: &RECORDS,
        encoded_context: b"verified content",
        maximum_context_bytes: 128,
        observed_at_micros: 100,
        expires_at_micros: 200,
    }
}

#[test]
fn measured_context_is_selected_and_budget_excess_abstains() {
    let read = plan_observed_context(observed()).expect("read plan");
    assert!(read.read_allowed);
    assert_eq!(
        read.evaluation.plan.chosen_plan_digest(),
        Some(read.context_digest)
    );
    assert!(!read.evaluation.plan.authority().grants_any());
    let mut over_budget = observed();
    over_budget.maximum_context_bytes = 1;
    let abstain = plan_observed_context(over_budget).expect("bounded abstain plan");
    assert!(!abstain.read_allowed);
    assert_eq!(
        abstain.evaluation.plan.resource_rejected_candidate_ids(),
        &[StableId::new("read-context").expect("id")]
    );
}

#[test]
fn empty_context_never_becomes_a_utility_claim_and_invalid_observations_reject() {
    let mut empty = observed();
    empty.verified_records = &[];
    assert!(!plan_observed_context(empty).expect("empty plan").read_allowed);
    let mut invalid = observed();
    invalid.expires_at_micros = 100;
    assert!(matches!(
        plan_observed_context(invalid),
        Err(NduPlanningError::Planner(PlannerError::InvalidTime(_)))
    ));
    let mut oversized_records = RECORDS.clone();
    oversized_records.extend(RECORDS.iter().cloned());
    oversized_records.push(VerifiedContextRecordV1 {
        record_id: StableId::new("record-c").expect("record"),
        revision: Revision::new(1).expect("revision"),
        content_digest: Digest32::of_bytes(b"content-c"),
    });
    let mut oversized = observed();
    oversized.verified_records = &oversized_records;
    assert_eq!(
        plan_observed_context(oversized),
        Err(NduPlanningError::Planner(PlannerError::LimitExceeded(
            "observed_context"
        )))
    );
}

#[test]
fn receipt_binds_bytes_records_request_source_and_generation() {
    let original = plan_observed_context(observed()).expect("original plan");
    let mut bytes = observed();
    bytes.encoded_context = b"changed content";
    let mut request = observed();
    request.request_binding_digest = Digest32::of_bytes(b"other request");
    let mut records = RECORDS.clone();
    records[0].content_digest = Digest32::of_bytes(b"changed-record");
    let mut record_change = observed();
    record_change.verified_records = &records;
    let mut source = observed();
    source.source_snapshot_digest = Digest32::of_bytes(b"other-read-cut");
    let mut generation = observed();
    generation.body_generation = Generation::new(8).expect("next generation");
    for changed in [bytes, request, record_change, source, generation] {
        let changed = plan_observed_context(changed).expect("changed plan");
        assert_ne!(
            original.evaluation.plan.receipt_digest(),
            changed.evaluation.plan.receipt_digest()
        );
    }
    assert_eq!(
        original,
        plan_observed_context(observed()).expect("deterministic replay")
    );
}
'''
write("codex-rs/hepta-control-plane/src/planner_context_tests.rs", planner_context_tests)

# Public exports for the new store, execution closure, and record proof.
replace_once(
    "codex-rs/hepta-control-plane/src/lib.rs",
    "mod planner;\nmod planner_context;\nmod planner_journal;\nmod planner_ndu;\n",
    "mod planner;\nmod planner_context;\nmod planner_execution;\nmod planner_journal;\nmod planner_ndu;\nmod planner_store;\n",
)
replace_once(
    "codex-rs/hepta-control-plane/src/lib.rs",
    "pub use planner_context::ObservedContextPlanV1;\npub use planner_context::ObservedContextV1;\npub use planner_context::plan_observed_context;\n",
    "pub use planner_context::ObservedContextPlanV1;\npub use planner_context::ObservedContextV1;\npub use planner_context::VerifiedContextRecordV1;\npub use planner_context::plan_observed_context;\npub use planner_execution::ControlRuntimeExecutionConsumerV1;\npub use planner_execution::CurrentExecutionFenceV1;\npub use planner_execution::EffectTerminalDispositionV1;\npub use planner_execution::EffectTerminalReceiptV1;\npub use planner_execution::IndependentAuthorizationV1;\npub use planner_execution::ProductExecutionErrorV1;\npub use planner_execution::ProductExecutionPhaseV1;\npub use planner_execution::ProductExecutionRecordV1;\npub use planner_execution::validate_current_authorization;\n",
)
replace_once(
    "codex-rs/hepta-control-plane/src/lib.rs",
    "pub use planner_ndu::evaluate_prepared_plan_with_ndu;\n",
    "pub use planner_ndu::evaluate_prepared_plan_with_ndu;\npub use planner_store::CanonicalDecisionEnvelopeV1;\npub use planner_store::PlannerCheckpointV1;\npub use planner_store::PlannerStoreAppendReceiptV1;\npub use planner_store::PlannerStoreError;\npub use planner_store::PlannerStoreFailpointV1;\npub use planner_store::PlannerStoreRecordKindV1;\npub use planner_store::PlannerStoreRecordV1;\npub use planner_store::PlannerStoreV1;\n",
)

# Protocol makes the plan receipt part of an explicit final-use binding.
replace_once(
    "codex-rs/hepta-agent-protocol/src/lib.rs",
    "pub struct CognitiveContextPlan {\n    /// Binds the evaluated context with `plan: null`, before any abstention.\n    pub evaluated_context_digest: String,\n    pub plan_receipt_digest: String,\n    pub read_allowed: bool,\n}\n",
    "pub struct CognitiveContextPlan {\n    /// Binds the evaluated context with `plan: null`, before any abstention.\n    pub evaluated_context_digest: String,\n    pub plan_receipt_digest: String,\n    pub request_binding_digest: String,\n    pub final_use_binding_digest: String,\n    pub read_allowed: bool,\n}\n",
)

# Agentd builds canonical record evidence, a request/query/profile binding, and a
# request-local monotonic planning domain. It replays allowed plans at final use.
replace_once(
    "codex-rs/hepta-agentd/src/cognitive_context.rs",
    "use codex_hepta_control_plane::ObservedContextV1;\nuse codex_hepta_control_plane::plan_observed_context;\n",
    "use codex_hepta_control_plane::ObservedContextV1;\nuse codex_hepta_control_plane::VerifiedContextRecordV1;\nuse codex_hepta_control_plane::plan_observed_context;\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/cognitive_context.rs",
    "const CONTEXT_READ_BINDING_DOMAIN: &[u8] = b\"hepta.agentd.cognitive-context-read.v1\";\n",
    "const CONTEXT_READ_BINDING_DOMAIN: &[u8] = b\"hepta.agentd.cognitive-context-read.v1\";\nconst CONTEXT_PLAN_OBSERVED_AT_MICROS: u64 = 1;\nconst CONTEXT_PLAN_EXPIRES_AT_MICROS: u64 = 1_000_001;\n",
)
old_plan_block = '''    let encoded_context = serde_json::to_vec(&response)
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
    let now_micros = u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?
            .as_micros(),
    )
    .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?;
    let plan = plan_observed_context(ObservedContextV1 {
        owner_id: StableId::new(owner.as_str())
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?,
        body_generation: Generation::new(body_generation)
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?,
        source_snapshot_digest: selected_read.snapshot_digest(),
        read_digest: selected_read_binding,
        verified_item_count: response.items.len() as u32,
        encoded_context: &encoded_context,
        maximum_context_bytes: MAX_CONTEXT_JSON_BYTES as u32,
        observed_at_micros: now_micros,
        expires_at_micros: now_micros.checked_add(1_000_000).ok_or_else(|| {
            CognitiveStoreError::Invalid("context plan expiry overflow".to_string())
        })?,
    })
    .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?;
    if !plan.read_allowed {
        response.items.clear();
    }
    response.plan = Some(CognitiveContextPlan {
        evaluated_context_digest: plan.context_digest.to_string(),
        plan_receipt_digest: plan.evaluation.plan.receipt_digest().to_string(),
        read_allowed: plan.read_allowed,
    });
'''
new_plan_block = '''    let encoded_context = serde_json::to_vec(&response)
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
    let verified_records = verified_context_records(&response.items)?;
    let request_binding = context_request_binding(
        owner,
        body_generation,
        request_id,
        query,
        expected_retrieval_context_digest,
        downstream_policy_digest,
    );
    let plan = plan_observed_context(ObservedContextV1 {
        owner_id: StableId::new(owner.as_str())
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?,
        body_generation: Generation::new(body_generation)
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?,
        source_snapshot_digest: selected_read.snapshot_digest(),
        read_digest: selected_read_binding,
        request_binding_digest: request_binding,
        verified_records: &verified_records,
        encoded_context: &encoded_context,
        maximum_context_bytes: MAX_CONTEXT_JSON_BYTES as u32,
        observed_at_micros: CONTEXT_PLAN_OBSERVED_AT_MICROS,
        expires_at_micros: CONTEXT_PLAN_EXPIRES_AT_MICROS,
    })
    .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?;
    let receipt_digest = plan.evaluation.plan.receipt_digest();
    let final_use_binding = context_plan_final_use_binding(
        plan.context_digest,
        receipt_digest,
        request_binding,
        selected_read_binding,
        plan.read_allowed,
    );
    if !plan.read_allowed {
        response.items.clear();
    }
    response.plan = Some(CognitiveContextPlan {
        evaluated_context_digest: plan.context_digest.to_string(),
        plan_receipt_digest: receipt_digest.to_string(),
        request_binding_digest: request_binding.to_string(),
        final_use_binding_digest: final_use_binding.to_string(),
        read_allowed: plan.read_allowed,
    });
'''
replace_once("codex-rs/hepta-agentd/src/cognitive_context.rs", old_plan_block, new_plan_block)

replace_once(
    "codex-rs/hepta-agentd/src/cognitive_context.rs",
    '''    if plan.read_allowed {
        let pre_plan = CognitiveContextSnapshot {
            snapshot_digest: snapshot_digest.to_string(),
            read_digest: read_digest.to_string(),
            omitted_records,
            items: items.to_vec(),
            plan: None,
        };
        let encoded = serde_json::to_vec(&pre_plan)
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
        if Digest32::of_bytes(&encoded).to_string() != plan.evaluated_context_digest {
            return Err(CognitiveStoreError::Conflict(
                "cognitive context ordered payload changed before final use".to_string(),
            )
            .into());
        }
    }
''',
    '''    let pre_plan = CognitiveContextSnapshot {
        snapshot_digest: snapshot_digest.to_string(),
        read_digest: read_digest.to_string(),
        omitted_records,
        items: items.to_vec(),
        plan: None,
    };
    let encoded = serde_json::to_vec(&pre_plan)
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
    if plan.read_allowed
        && Digest32::of_bytes(&encoded).to_string() != plan.evaluated_context_digest
    {
        return Err(CognitiveStoreError::Conflict(
            "cognitive context ordered payload changed before final use".to_string(),
        )
        .into());
    }
''',
)

replay_insert = '''
    let evaluated_context_digest: Digest32 = plan.evaluated_context_digest.parse().map_err(|error| {
        CognitiveStoreError::Invalid(format!("invalid evaluated context digest: {error}"))
    })?;
    let plan_receipt_digest: Digest32 = plan.plan_receipt_digest.parse().map_err(|error| {
        CognitiveStoreError::Invalid(format!("invalid plan receipt digest: {error}"))
    })?;
    let request_binding_digest: Digest32 = plan.request_binding_digest.parse().map_err(|error| {
        CognitiveStoreError::Invalid(format!("invalid request binding digest: {error}"))
    })?;
    let expected_final_use_binding: Digest32 = plan
        .final_use_binding_digest
        .parse()
        .map_err(|error| {
            CognitiveStoreError::Invalid(format!("invalid final-use binding digest: {error}"))
        })?;
    let actual_final_use_binding = context_plan_final_use_binding(
        evaluated_context_digest,
        plan_receipt_digest,
        request_binding_digest,
        current_read_binding,
        plan.read_allowed,
    );
    if actual_final_use_binding != expected_final_use_binding {
        return Err(CognitiveStoreError::Conflict(
            "cognitive context plan receipt binding changed before final use".to_string(),
        )
        .into());
    }
    if plan.read_allowed {
        let verified_records = verified_context_records(items)?;
        let replay = plan_observed_context(ObservedContextV1 {
            owner_id: StableId::new(owner.as_str())
                .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?,
            body_generation: Generation::new(body_generation)
                .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?,
            source_snapshot_digest: expected_snapshot,
            read_digest: current_read_binding,
            request_binding_digest,
            verified_records: &verified_records,
            encoded_context: &encoded,
            maximum_context_bytes: MAX_CONTEXT_JSON_BYTES as u32,
            observed_at_micros: CONTEXT_PLAN_OBSERVED_AT_MICROS,
            expires_at_micros: CONTEXT_PLAN_EXPIRES_AT_MICROS,
        })
        .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?;
        if !replay.read_allowed
            || replay.context_digest != evaluated_context_digest
            || replay.evaluation.plan.receipt_digest() != plan_receipt_digest
        {
            return Err(CognitiveStoreError::Conflict(
                "cognitive context planner receipt does not replay at final use".to_string(),
            )
            .into());
        }
    }
'''
replace_once(
    "codex-rs/hepta-agentd/src/cognitive_context.rs",
    "\n    // Ranking is part of the selected context semantics. A registry/model\n",
    replay_insert + "\n    // Ranking is part of the selected context semantics. A registry/model\n",
)

helpers = r'''
fn verified_context_records(
    items: &[CognitiveContextItem],
) -> Result<Vec<VerifiedContextRecordV1>, CognitiveContextError> {
    items
        .iter()
        .map(|item| {
            Ok(VerifiedContextRecordV1 {
                record_id: StableId::new(item.memory_id.as_str())
                    .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?,
                revision: codex_hepta_types::Revision::new(item.revision)
                    .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?,
                content_digest: item.content_sha256.parse().map_err(|error| {
                    CognitiveStoreError::Invalid(format!("invalid cognitive content digest: {error}"))
                })?,
            })
        })
        .collect()
}

fn context_request_binding(
    owner: &AgentId,
    body_generation: u64,
    request_id: Option<u64>,
    query: &str,
    retrieval_context_digest: Option<Digest32>,
    ranker_policy_digest: Option<Digest32>,
) -> Digest32 {
    let mut bytes = b"hepta.agentd.cognitive-context-request.v1\0".to_vec();
    bytes.extend_from_slice(owner.as_str().as_bytes());
    bytes.extend_from_slice(&body_generation.to_be_bytes());
    bytes.push(u8::from(request_id.is_some()));
    bytes.extend_from_slice(&request_id.unwrap_or_default().to_be_bytes());
    bytes.extend_from_slice(Digest32::of_bytes(query.as_bytes()).as_array());
    bytes.extend_from_slice(
        retrieval_context_digest.unwrap_or(Digest32::ZERO).as_array(),
    );
    bytes.extend_from_slice(ranker_policy_digest.unwrap_or(Digest32::ZERO).as_array());
    Digest32::of_bytes(&bytes)
}

fn context_plan_final_use_binding(
    evaluated_context_digest: Digest32,
    plan_receipt_digest: Digest32,
    request_binding_digest: Digest32,
    read_binding_digest: Digest32,
    read_allowed: bool,
) -> Digest32 {
    let mut bytes = b"hepta.agentd.cognitive-context-final-use.v1\0".to_vec();
    bytes.extend_from_slice(evaluated_context_digest.as_array());
    bytes.extend_from_slice(plan_receipt_digest.as_array());
    bytes.extend_from_slice(request_binding_digest.as_array());
    bytes.extend_from_slice(read_binding_digest.as_array());
    bytes.push(u8::from(read_allowed));
    Digest32::of_bytes(&bytes)
}

'''
replace_once(
    "codex-rs/hepta-agentd/src/cognitive_context.rs",
    "/// Bind the selected exact-ID receipt to the complete durable owner cut.\n",
    helpers + "/// Bind the selected exact-ID receipt to the complete durable owner cut.\n",
)

# Add targeted planner regressions without depending on private fixture helpers.
planner_tests_path = "codex-rs/hepta-control-plane/src/planner_tests.rs"
planner_tests = read(planner_tests_path)
planner_tests += r'''

#[test]
fn extra_owner_summary_is_rejected_instead_of_poisoning_required_snapshot() {
    let mut request = snapshot_request();
    let required = request.required_owner_ids[0].clone();
    let mut summaries = vec![owner_summary(required)];
    summaries.push(owner_summary(StableId::new("unexpected-owner").expect("owner")));
    assert!(matches!(
        collect_snapshot(request, summaries),
        Err(PlannerError::UnexpectedOwner(owner)) if owner == "unexpected-owner"
    ));
}

#[test]
fn duplicate_final_payload_digest_is_rejected_not_silently_normalized() {
    let snapshot = coherent_snapshot();
    let mut request = planning_request();
    let payload = Digest32::of_bytes(b"duplicate-payload");
    request.candidates[0].final_payload_digests = vec![payload, payload];
    assert!(matches!(
        prepare_plan(&snapshot, request),
        Err(PlannerError::DuplicatePayloadDigest(_))
    ));
}
'''
write(planner_tests_path, planner_tests)

# Update maturity map and add one machine-readable truth source.
implementation_path = ROOT / "docs/modules/control.runtime/IMPLEMENTATION_MAP.json"
implementation = json.loads(implementation_path.read_text(encoding="utf-8"))
implementation["productCallerState"] = "read_only_source_composed_candidate"
implementation["globalPlannerCallerState"] = "not_composed"
implementation["productionWriterState"] = "durable_store_source_candidate_not_product_composed"
implementation["subsystemMaturity"] = {
    "planner": {
        "source": "candidate_implemented",
        "namedCaller": "agentd_read_only_context_adapter",
        "productionGlobalCaller": "not_established",
    },
    "organHost": {
        "source": "read_only_candidate_implemented",
        "productionComposition": "not_established",
    },
    "embodimentReference": {
        "source": "synthetic_reference_implemented",
        "hardwareActivation": "not_established",
    },
    "plannerStore": {
        "source": "candidate_implemented",
        "productComposition": "not_established",
    },
    "executionClosure": {
        "source": "authority_separated_candidate_implemented",
        "namedConsumer": "ControlRuntimeExecutionConsumerV1",
        "externalAuthorityAndExecutorComposition": "not_established",
    },
}
implementation["completion"]["productionCaller"] = "read_only_candidate_only"
implementation["completion"]["productionWriter"] = "source_candidate_not_composed"
implementation["completion"]["exactHeadQualification"] = "required_after_this_change"
implementation["completion"]["activationState"] = "not_established"
implementation_path.write_text(json.dumps(implementation, indent=2) + "\n", encoding="utf-8")

maturity = {
    "schema": "hepta.control-runtime-maturity.v1",
    "module": "control.runtime",
    "claimBoundary": "source candidate only",
    "readOnlyAgentdCaller": "source_composed_candidate",
    "globalPlannerCaller": "not_composed",
    "productionWriter": "durable_store_source_candidate_not_composed",
    "independentAuthorityConsumer": "source_contract_candidate_not_composed",
    "effectExecutor": "not_composed",
    "activation": False,
    "independentAcceptance": False,
    "release": False,
    "subsystems": implementation["subsystemMaturity"],
    "requiredEvidence": [
        "source-head regression",
        "synthetic-merge regression",
        "control NDU caller regression",
        "strict clippy",
        "formatting",
        "package tests",
        "named-host qualification",
        "independent semantic review",
        "canary and rollback rehearsal",
    ],
}
write("docs/modules/control.runtime/MATURITY.json", json.dumps(maturity, indent=2) + "\n")

technical = read("docs/modules/control.runtime/TECHNICAL.md")
technical += r'''

## 18. As-built subsystem maturity and production closure

`docs/modules/control.runtime/MATURITY.json` is the machine-readable as-built
maturity source. The module is split operationally into planner, read-only organ
host, embodiment reference, durable planner store and authority-separated
execution closure. Agentd's bounded cognitive-context caller is a source-composed
read-only candidate. The global planner caller, external authority service,
effect executor, activated production writer, independent acceptance, canary,
promotion and release remain unestablished.

`PlannerStoreV1` stores the complete canonical decision envelope, not only its
digest. It uses a versioned file header, exclusive writer lock, bounded framed
records, payload and frame checksums, file and directory synchronization,
partial-tail recovery, atomic compaction/backup/restore, deterministic legacy
migration and externally supplied checkpoint receipts. `ControlRuntimeExecutionConsumerV1`
requires a durable decision before an authority request, consumes a separately
issued current-state authorization, records dispatch and terminal outcomes, and
requires explicit reconciliation of indeterminate effects. Neither type issues
a capability or activates an effect boundary by itself.
'''
write("docs/modules/control.runtime/TECHNICAL.md", technical)

readiness = read("docs/readiness/CONTROL_RUNTIME_EXECUTION.md")
readiness += r'''

## Production-closure source candidate

The request-local Agentd adapter now derives utility count from canonical
record-id/revision/content-digest bindings. Its request binding covers caller,
body generation, request identity, query digest, retrieval context and applied
ranker policy. Planning uses a request-local monotonic logical clock rather than
Unix wall time. Final use always validates a binding that includes the exact plan
receipt digest; an allowed read additionally replays the planner against the
current owner cut and exact record bindings.

The repository also contains a durable `PlannerStoreV1` and the named
`ControlRuntimeExecutionConsumerV1` source candidate. These close the source-level
sequence from durable decision through independent authorization, dispatch,
terminal receipt and reconciliation. They do not establish an activated product
writer, external authority service, effect executor, independent acceptance,
canary, promotion or release.
'''
write("docs/readiness/CONTROL_RUNTIME_EXECUTION.md", readiness)

print("control.runtime closure patch applied")
