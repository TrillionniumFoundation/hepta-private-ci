//! Canonical owner-local archival bodies, not a new external wire protocol.
//! Reopening these bytes never reconstructs an executable grant. A new dispatch
//! must revalidate the live snapshot and use the independent authority owner.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::FeasiblePlanReceiptV1;
use crate::GlobalStateSnapshotV1;
use crate::NduPlanEvaluationV1;
use crate::OwnerReadinessV1;
use crate::PlannerAxisValueV1;
use crate::PlannerError;
use crate::PlanningEvaluationDispositionV1;
use crate::PreparedPlanInputV1;
use crate::SearchDisclosureV1;

const MAGIC: &[u8; 8] = b"HCPENV01";
pub const MAX_PLANNER_ENVELOPE_BYTES: usize = 2 * 1024 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerDecisionEnvelopeV1 {
    receipt_digest: Digest32,
    envelope_digest: Digest32,
    bytes: Vec<u8>,
}

impl PlannerDecisionEnvelopeV1 {
    /// Only a coherent, currently valid sealed decision can enter the writer.
    /// All planner-owned fields are retained, including candidate payloads and
    /// resource costs; upstream utility facts remain referenced by owner digest.
    pub fn from_sealed_plan(
        snapshot: &GlobalStateSnapshotV1,
        prepared: &PreparedPlanInputV1,
        evaluation: &NduPlanEvaluationV1,
        receipt: &FeasiblePlanReceiptV1,
        now_micros: u64,
    ) -> Result<Self, PlannerError> {
        if &crate::finalize_plan(snapshot, prepared, evaluation, now_micros)? != receipt {
            return Err(PlannerError::PreparedPlanMismatch);
        }
        let mut bytes = MAGIC.to_vec();
        put_digest(&mut bytes, receipt.receipt_digest());
        put_u64(&mut bytes, now_micros);
        for section in [
            encode_snapshot(snapshot)?,
            encode_prepared(prepared)?,
            encode_evaluation(evaluation)?,
            encode_receipt(receipt)?,
        ] {
            put_bytes(&mut bytes, &section)?;
        }
        if bytes.len() > MAX_PLANNER_ENVELOPE_BYTES {
            return Err(PlannerError::LimitExceeded("decision envelope"));
        }
        Ok(Self {
            receipt_digest: receipt.receipt_digest(),
            envelope_digest: Digest32::of_bytes(&bytes),
            bytes,
        })
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    #[must_use]
    pub const fn envelope_digest(&self) -> Digest32 {
        self.envelope_digest
    }

    #[must_use]
    pub fn canonical_bytes(&self) -> &[u8] {
        &self.bytes
    }

    /// Structural validation is used only after the store's authenticated
    /// checkpoint has verified these exact bytes. It grants no live semantics.
    pub(crate) fn validate_archive(bytes: &[u8], receipt: Digest32) -> bool {
        if bytes.len() < 48 || bytes.len() > MAX_PLANNER_ENVELOPE_BYTES {
            return false;
        }
        if &bytes[..8] != MAGIC || &bytes[8..40] != receipt.as_array() {
            return false;
        }
        let mut offset = 48_usize;
        for _ in 0..4 {
            let Some(length_bytes) = bytes.get(offset..offset + 4) else {
                return false;
            };
            let Ok(length_bytes) = <[u8; 4]>::try_from(length_bytes) else {
                return false;
            };
            let length = u32::from_be_bytes(length_bytes) as usize;
            if length == 0 || length > MAX_PLANNER_ENVELOPE_BYTES {
                return false;
            }
            offset += 4;
            let Some(end) = offset.checked_add(length) else {
                return false;
            };
            if end > bytes.len() {
                return false;
            }
            offset = end;
        }
        offset == bytes.len()
    }
}

fn encode_snapshot(value: &GlobalStateSnapshotV1) -> Result<Vec<u8>, PlannerError> {
    let mut out = Vec::new();
    put_digest(&mut out, value.objective_digest());
    put_u64(&mut out, value.body_generation().get());
    put_digest(&mut out, value.configuration_digest());
    put_digest(&mut out, value.revocation_frontier_digest());
    put_digest(&mut out, value.snapshot_policy_digest());
    put_u64(&mut out, value.maximum_owner_age_micros());
    put_digest(&mut out, value.required_owner_set_digest());
    put_u64(&mut out, value.collected_at_micros());
    put_u64(&mut out, value.expires_at_micros());
    put_len(&mut out, value.owner_summaries().len())?;
    for owner in value.owner_summaries() {
        put_id(&mut out, &owner.owner_id)?;
        put_u64(&mut out, owner.revision.get());
        put_digest(&mut out, owner.objective_digest);
        put_u64(&mut out, owner.body_generation.get());
        put_digest(&mut out, owner.configuration_digest);
        put_u64(&mut out, owner.observed_at_micros);
        put_u64(&mut out, owner.expires_at_micros);
        out.push(match owner.readiness {
            OwnerReadinessV1::Ready => 0,
            OwnerReadinessV1::Degraded => 1,
            OwnerReadinessV1::Unavailable => 2,
        });
        put_digest(&mut out, owner.source_frontier_digest);
        put_digest(&mut out, owner.support_digest);
    }
    put_ids(&mut out, value.missing_owner_ids())?;
    put_ids(&mut out, value.stale_owner_ids())?;
    put_ids(&mut out, value.unavailable_owner_ids())?;
    put_digest(&mut out, value.snapshot_digest());
    Ok(out)
}

fn encode_prepared(value: &PreparedPlanInputV1) -> Result<Vec<u8>, PlannerError> {
    let mut out = Vec::new();
    put_id(&mut out, value.plan_id())?;
    put_digest(&mut out, value.objective_digest());
    put_u64(&mut out, value.body_generation().get());
    for digest in [
        value.configuration_digest(),
        value.revocation_frontier_digest(),
        value.snapshot_digest(),
        value.evaluation_policy_digest(),
        value.resource_profile_digest(),
        value.source_candidate_set_digest(),
        value.candidate_set_digest(),
    ] {
        put_digest(&mut out, digest);
    }
    put_len(&mut out, value.feasible_candidates().len())?;
    for candidate in value.feasible_candidates() {
        put_id(&mut out, &candidate.candidate_id)?;
        put_id(&mut out, &candidate.operation_id)?;
        put_digest(&mut out, candidate.plan_digest);
        put_ids(&mut out, &candidate.required_owner_ids)?;
        put_len(&mut out, candidate.final_payload_digests.len())?;
        for digest in &candidate.final_payload_digests {
            put_digest(&mut out, *digest);
        }
        put_axes(&mut out, &candidate.resource_costs)?;
    }
    put_ids(&mut out, value.resource_rejected_candidate_ids())?;
    put_u64(&mut out, value.expires_at_micros());
    put_digest(&mut out, value.prepared_digest());
    out.push(u8::from(value.authority().grants_any()));
    Ok(out)
}

fn encode_evaluation(value: &NduPlanEvaluationV1) -> Result<Vec<u8>, PlannerError> {
    let mut out = Vec::new();
    put_digest(&mut out, value.objective_digest());
    put_u64(&mut out, value.body_generation().get());
    put_digest(&mut out, value.evaluation_policy_digest());
    put_digest(&mut out, value.evaluation_digest());
    put_ids(&mut out, value.evaluated_candidate_ids())?;
    put_ids(&mut out, value.rejected_candidate_ids())?;
    put_ids(&mut out, value.pareto_candidate_ids())?;
    put_optional_id(&mut out, value.advisory_candidate_id())?;
    put_digest(&mut out, value.uncertainty_digest());
    out.push(disposition_tag(value.disposition()));
    put_digest(&mut out, value.binding_digest());
    out.push(u8::from(value.authority().grants_any()));
    Ok(out)
}

fn encode_receipt(value: &FeasiblePlanReceiptV1) -> Result<Vec<u8>, PlannerError> {
    let mut out = Vec::new();
    put_id(&mut out, value.plan_id())?;
    put_digest(&mut out, value.objective_digest());
    put_u64(&mut out, value.body_generation().get());
    for digest in [
        value.configuration_digest(),
        value.revocation_frontier_digest(),
        value.snapshot_digest(),
        value.source_candidate_set_digest(),
        value.candidate_set_digest(),
        value.prepared_digest(),
        value.resource_profile_digest(),
    ] {
        put_digest(&mut out, digest);
    }
    put_ids(&mut out, value.resource_rejected_candidate_ids())?;
    put_digest(&mut out, value.evaluation_policy_digest());
    put_digest(&mut out, value.ndu_evaluation_digest());
    put_digest(&mut out, value.ndu_binding_digest());
    out.push(disposition_tag(value.evaluation_disposition()));
    put_optional_id(&mut out, value.chosen_candidate_id())?;
    match value.chosen_plan_digest() {
        Some(digest) => {
            out.push(1);
            put_digest(&mut out, digest);
        }
        None => out.push(0),
    }
    put_digest(&mut out, value.uncertainty_digest());
    put_u64(&mut out, value.expires_at_micros());
    out.push(match value.search_disclosure() {
        SearchDisclosureV1::BoundedCandidateSetOnly => 0,
        SearchDisclosureV1::UniqueParetoOnBoundedSet => 1,
        SearchDisclosureV1::ScalarizedBoundedSet => 2,
        SearchDisclosureV1::UnresolvedParetoFrontier => 3,
    });
    put_digest(&mut out, value.receipt_digest());
    out.push(u8::from(value.authority().grants_any()));
    Ok(out)
}

fn disposition_tag(value: PlanningEvaluationDispositionV1) -> u8 {
    match value {
        PlanningEvaluationDispositionV1::InfeasibleExplicitAbstain => 0,
        PlanningEvaluationDispositionV1::UniqueParetoRecommendation => 1,
        PlanningEvaluationDispositionV1::ParetoSetRequiresSlowPath => 2,
        PlanningEvaluationDispositionV1::ScalarizedRecommendation => 3,
        PlanningEvaluationDispositionV1::ScalarizationTieRequiresSlowPath => 4,
    }
}

fn put_len(out: &mut Vec<u8>, length: usize) -> Result<(), PlannerError> {
    let length = u32::try_from(length).map_err(|_| PlannerError::Arithmetic)?;
    out.extend_from_slice(&length.to_be_bytes());
    Ok(())
}

fn put_bytes(out: &mut Vec<u8>, bytes: &[u8]) -> Result<(), PlannerError> {
    put_len(out, bytes.len())?;
    out.extend_from_slice(bytes);
    Ok(())
}

fn put_id(out: &mut Vec<u8>, id: &StableId) -> Result<(), PlannerError> {
    put_bytes(out, id.as_str().as_bytes())
}

fn put_ids(out: &mut Vec<u8>, ids: &[StableId]) -> Result<(), PlannerError> {
    put_len(out, ids.len())?;
    for id in ids {
        put_id(out, id)?;
    }
    Ok(())
}

fn put_optional_id(out: &mut Vec<u8>, id: Option<&StableId>) -> Result<(), PlannerError> {
    match id {
        Some(id) => {
            out.push(1);
            put_id(out, id)?;
        }
        None => out.push(0),
    }
    Ok(())
}

fn put_axes(out: &mut Vec<u8>, axes: &[PlannerAxisValueV1]) -> Result<(), PlannerError> {
    put_len(out, axes.len())?;
    for axis in axes {
        put_id(out, &axis.axis)?;
        out.extend_from_slice(&axis.value.raw().to_be_bytes());
    }
    Ok(())
}

fn put_u64(out: &mut Vec<u8>, value: u64) {
    out.extend_from_slice(&value.to_be_bytes());
}

fn put_digest(out: &mut Vec<u8>, digest: Digest32) {
    out.extend_from_slice(digest.as_array());
}
