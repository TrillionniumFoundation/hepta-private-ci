//! Complete canonical planning projections retained behind the planner store.
//!
//! Five length-framed sections preserve snapshot, feasible candidate bodies,
//! prepared input, consumed NDU projection and the final receipt. Each section
//! must hash to the native kernel's own digest, not a second approximate digest.
//! A decoded archive proves framing/integrity only: execution still requires
//! fresh owner inputs, native finalization and independently issued authority.
//! Rejected source candidates and opaque owner profiles remain referenced by
//! their existing source/profile digests; they are not reconstructed as facts.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::FeasiblePlanReceiptV1;
use crate::GlobalStateSnapshotV1;
use crate::NduPlanEvaluationV1;
use crate::OwnerReadinessV1;
use crate::PlannerAxisValueV1;
use crate::PlanningEvaluationDispositionV1;
use crate::PreparedPlanInputV1;
use crate::SearchDisclosureV1;
use crate::finalize_plan;
use crate::planner_store::MAX_PLANNER_ENVELOPE_BYTES;
use crate::planner_store::PlannerStoreError;
use crate::planner_store::PlannerStoreV1;
use crate::planner_store::PlannerStoredReceiptV1;

const MAGIC: &[u8; 8] = b"HCPENV01";
const DOMAINS: [&[u8]; 5] = [
    b"hepta.control.global-state-snapshot.v1",
    b"hepta.control.plan-candidate-set.v1",
    b"hepta.control.prepared-plan.v1",
    b"hepta.control.ndu-plan-evaluation-binding.v1",
    b"hepta.control.feasible-plan-receipt.v1",
];

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerDecisionEnvelopeV1 {
    bytes: Vec<u8>,
    section_digests: [Digest32; 5],
}

impl PlannerDecisionEnvelopeV1 {
    /// Seal only the exact native finalization result over these projections.
    pub fn from_plan(
        snapshot: &GlobalStateSnapshotV1,
        prepared: &PreparedPlanInputV1,
        evaluation: &NduPlanEvaluationV1,
        receipt: &FeasiblePlanReceiptV1,
        now_micros: u64,
    ) -> Result<Self, PlannerStoreError> {
        let actual = finalize_plan(snapshot, prepared, evaluation, now_micros)
            .map_err(|_| invalid("native plan revalidation"))?;
        if &actual != receipt {
            return Err(invalid("receipt differs from native finalization"));
        }
        let section_digests = [
            snapshot.snapshot_digest(),
            prepared.candidate_set_digest(),
            prepared.prepared_digest(),
            evaluation.binding_digest(),
            receipt.receipt_digest(),
        ];
        let sections = [
            encode_snapshot(snapshot),
            encode_candidates(prepared),
            encode_prepared(prepared),
            encode_evaluation(evaluation),
            encode_receipt(receipt),
        ];
        let mut bytes = MAGIC.to_vec();
        for (section, expected) in sections.into_iter().zip(section_digests) {
            if Digest32::of_bytes(&section) != expected {
                return Err(invalid("canonical archive/native digest disagreement"));
            }
            if bytes.len() + 36 + section.len() > MAX_PLANNER_ENVELOPE_BYTES {
                return Err(PlannerStoreError::LimitExceeded);
            }
            bytes.extend_from_slice(expected.as_array());
            bytes.extend_from_slice(&(section.len() as u32).to_be_bytes());
            bytes.extend_from_slice(&section);
        }
        Ok(Self { bytes, section_digests })
    }

    /// Inspect a versioned archive. This never creates a FeasiblePlanReceiptV1,
    /// capability or execution token from persisted caller-controlled bytes.
    pub fn decode(bytes: &[u8]) -> Result<Self, PlannerStoreError> {
        if bytes.len() > MAX_PLANNER_ENVELOPE_BYTES {
            return Err(PlannerStoreError::LimitExceeded);
        }
        if bytes.get(..8) != Some(MAGIC.as_slice()) {
            return Err(invalid("planning envelope schema"));
        }
        let mut offset = 8_usize;
        let mut section_digests = [Digest32::ZERO; 5];
        for (index, domain) in DOMAINS.iter().enumerate() {
            let digest_bytes = take(bytes, &mut offset, 32)?;
            let digest = Digest32::from_array(digest_bytes.try_into()
                .map_err(|_| invalid("planning section digest"))?);
            let length = u32::from_be_bytes(take(bytes, &mut offset, 4)?.try_into()
                .map_err(|_| invalid("planning section length"))?) as usize;
            let section = take(bytes, &mut offset, length)?;
            if digest.is_zero() || !section.starts_with(domain)
                || Digest32::of_bytes(section) != digest
            {
                return Err(invalid("planning section identity or checksum"));
            }
            section_digests[index] = digest;
        }
        if offset != bytes.len() {
            return Err(invalid("unknown trailing planning envelope fields"));
        }
        Ok(Self { bytes: bytes.to_vec(), section_digests })
    }

    #[must_use]
    pub fn receipt_digest(&self) -> Digest32 {
        self.section_digests[4]
    }

    #[must_use]
    pub fn canonical_bytes(&self) -> &[u8] {
        &self.bytes
    }

    pub fn persist(&self, store: &mut PlannerStoreV1) -> Result<PlannerStoredReceiptV1, PlannerStoreError> {
        store.append(self.receipt_digest(), &self.bytes)
    }

    pub fn load(store: &PlannerStoreV1, receipt: Digest32) -> Result<Option<Self>, PlannerStoreError> {
        let Some(bytes) = store.get(receipt)? else { return Ok(None) };
        let archive = Self::decode(bytes)?;
        if archive.receipt_digest() != receipt {
            return Err(invalid("planning envelope/store identity mismatch"));
        }
        Ok(Some(archive))
    }

    /// An archived record is admissible only with the exact fresh native
    /// projections. Old signatures or a readable backup cannot replace this.
    pub fn revalidate(
        &self,
        snapshot: &GlobalStateSnapshotV1,
        prepared: &PreparedPlanInputV1,
        evaluation: &NduPlanEvaluationV1,
        receipt: &FeasiblePlanReceiptV1,
        now_micros: u64,
    ) -> Result<(), PlannerStoreError> {
        if Self::from_plan(snapshot, prepared, evaluation, receipt, now_micros)? != *self {
            return Err(invalid("planning envelope/current projection mismatch"));
        }
        Ok(())
    }
}

struct Encoder(Vec<u8>);

impl Encoder {
    fn new(section: usize) -> Self { Self(DOMAINS[section].to_vec()) }
    fn digest(&mut self, value: Digest32) { self.0.extend_from_slice(value.as_array()); }
    fn u64(&mut self, value: u64) { self.0.extend_from_slice(&value.to_be_bytes()); }
    fn count(&mut self, value: usize) { self.0.extend_from_slice(&(value as u32).to_be_bytes()); }
    fn id(&mut self, value: &StableId) {
        self.count(value.as_str().len());
        self.0.extend_from_slice(value.as_str().as_bytes());
    }
    fn ids(&mut self, values: &[StableId]) {
        self.count(values.len());
        for value in values { self.id(value); }
    }
    fn optional_id(&mut self, value: Option<&StableId>) {
        self.0.push(u8::from(value.is_some()));
        if let Some(value) = value { self.id(value); }
    }
    fn optional_digest(&mut self, value: Option<Digest32>) {
        self.0.push(u8::from(value.is_some()));
        if let Some(value) = value { self.digest(value); }
    }
    fn axes(&mut self, values: &[PlannerAxisValueV1]) {
        self.count(values.len());
        for value in values {
            self.id(&value.axis);
            self.0.extend_from_slice(&value.value.raw().to_be_bytes());
        }
    }
}

fn encode_snapshot(s: &GlobalStateSnapshotV1) -> Vec<u8> {
    let mut e = Encoder::new(0);
    e.digest(s.objective_digest());
    e.u64(s.body_generation().get());
    e.digest(s.configuration_digest());
    e.digest(s.revocation_frontier_digest());
    e.digest(s.snapshot_policy_digest());
    e.u64(s.maximum_owner_age_micros());
    e.digest(s.required_owner_set_digest());
    e.u64(s.collected_at_micros());
    e.u64(s.expires_at_micros());
    e.count(s.owner_summaries().len());
    for owner in s.owner_summaries() {
        e.id(&owner.owner_id);
        e.u64(owner.revision.get());
        e.digest(owner.objective_digest);
        e.u64(owner.body_generation.get());
        e.digest(owner.configuration_digest);
        e.u64(owner.observed_at_micros);
        e.u64(owner.expires_at_micros);
        e.0.push(match owner.readiness {
            OwnerReadinessV1::Ready => 0,
            OwnerReadinessV1::Degraded => 1,
            OwnerReadinessV1::Unavailable => 2,
        });
        e.digest(owner.source_frontier_digest);
        e.digest(owner.support_digest);
    }
    e.ids(s.missing_owner_ids());
    e.ids(s.stale_owner_ids());
    e.ids(s.unavailable_owner_ids());
    e.0
}

fn encode_candidates(p: &PreparedPlanInputV1) -> Vec<u8> {
    let mut e = Encoder::new(1);
    let mut candidates = p.feasible_candidates().to_vec();
    candidates.sort_by(|a, b| a.candidate_id.cmp(&b.candidate_id));
    e.count(candidates.len());
    for mut c in candidates {
        e.id(&c.candidate_id);
        e.id(&c.operation_id);
        e.digest(c.plan_digest);
        c.required_owner_ids.sort();
        e.ids(&c.required_owner_ids);
        c.final_payload_digests.sort();
        e.count(c.final_payload_digests.len());
        for payload in c.final_payload_digests { e.digest(payload); }
        c.resource_costs.sort();
        e.axes(&c.resource_costs);
    }
    e.0
}

fn encode_prepared(p: &PreparedPlanInputV1) -> Vec<u8> {
    let mut e = Encoder::new(2);
    e.id(p.plan_id());
    e.digest(p.objective_digest());
    e.u64(p.body_generation().get());
    for digest in [p.configuration_digest(), p.revocation_frontier_digest(),
        p.snapshot_digest(), p.evaluation_policy_digest(), p.resource_profile_digest(),
        p.source_candidate_set_digest(), p.candidate_set_digest()] {
        e.digest(digest);
    }
    e.ids(p.resource_rejected_candidate_ids());
    e.u64(p.expires_at_micros());
    e.0
}

fn encode_evaluation(n: &NduPlanEvaluationV1) -> Vec<u8> {
    let mut e = Encoder::new(3);
    e.digest(n.objective_digest());
    e.u64(n.body_generation().get());
    e.digest(n.evaluation_policy_digest());
    e.digest(n.evaluation_digest());
    e.ids(n.evaluated_candidate_ids());
    e.ids(n.rejected_candidate_ids());
    e.ids(n.pareto_candidate_ids());
    e.optional_id(n.advisory_candidate_id());
    e.digest(n.uncertainty_digest());
    e.0.push(disposition(n.disposition()));
    e.0
}

fn encode_receipt(r: &FeasiblePlanReceiptV1) -> Vec<u8> {
    let mut e = Encoder::new(4);
    e.id(r.plan_id());
    e.digest(r.objective_digest());
    e.u64(r.body_generation().get());
    for digest in [r.configuration_digest(), r.revocation_frontier_digest(),
        r.snapshot_digest(), r.source_candidate_set_digest(), r.candidate_set_digest(),
        r.prepared_digest(), r.resource_profile_digest()] {
        e.digest(digest);
    }
    e.ids(r.resource_rejected_candidate_ids());
    e.digest(r.evaluation_policy_digest());
    e.digest(r.ndu_evaluation_digest());
    e.digest(r.ndu_binding_digest());
    e.0.push(disposition(r.evaluation_disposition()));
    e.optional_id(r.chosen_candidate_id());
    e.optional_digest(r.chosen_plan_digest());
    e.digest(r.uncertainty_digest());
    e.u64(r.expires_at_micros());
    e.0.push(match r.search_disclosure() {
        SearchDisclosureV1::BoundedCandidateSetOnly => 0,
        SearchDisclosureV1::UniqueParetoOnBoundedSet => 1,
        SearchDisclosureV1::ScalarizedBoundedSet => 2,
        SearchDisclosureV1::UnresolvedParetoFrontier => 3,
    });
    e.0
}

fn disposition(value: PlanningEvaluationDispositionV1) -> u8 {
    match value {
        PlanningEvaluationDispositionV1::InfeasibleExplicitAbstain => 0,
        PlanningEvaluationDispositionV1::UniqueParetoRecommendation => 1,
        PlanningEvaluationDispositionV1::ParetoSetRequiresSlowPath => 2,
        PlanningEvaluationDispositionV1::ScalarizedRecommendation => 3,
        PlanningEvaluationDispositionV1::ScalarizationTieRequiresSlowPath => 4,
    }
}

fn take<'a>(bytes: &'a [u8], offset: &mut usize, length: usize) -> Result<&'a [u8], PlannerStoreError> {
    let end = offset.checked_add(length).ok_or_else(|| invalid("planning length overflow"))?;
    let slice = bytes.get(*offset..end).ok_or_else(|| invalid("truncated planning envelope"))?;
    *offset = end;
    Ok(slice)
}

fn invalid(message: &'static str) -> PlannerStoreError { PlannerStoreError::Invalid(message) }

#[cfg(test)]
#[path = "planner_envelope_tests.rs"]
mod tests;
