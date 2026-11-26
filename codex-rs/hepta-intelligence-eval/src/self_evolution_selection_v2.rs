//! Selection from the original sealed paired execution and durable qualification.
//! V1 payload bytes remain historical facts; this is a separate signing domain.

use std::fmt;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LedgerSnapshot;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_dataset_snapshot_receipt_against_ledger_v3;
use codex_hepta_learning_ledger::verify_verified_role_separation;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AuthenticatedPairedRegistrationV1;
use crate::IndependentEvaluationDispositionV1;
use crate::ProductPairedEvaluationReceiptV1;
use crate::ProductPairedQualificationReceiptV1;
use crate::ProductQualificationContextV1;
use crate::SelfEvolutionSelectionError;
use crate::SelfEvolutionSelectionRequestV1;
use crate::SignedEvaluationEvidenceV1;
use crate::paired_evaluation_signing_payload_v1;
use crate::paired_observation_cut_signing_payload_v1;
use crate::paired_supervised_host_clock::PairedHostClockV1;

#[path = "self_evolution_rollback_v2.rs"]
mod rollback;
pub use rollback::VerifiedSelfEvolutionRollbackV2;
pub use rollback::admit_self_evolution_rollback_v2;
pub use rollback::rollback_signing_payload_v2;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelfEvolutionSelectionPolicyV2 {
    pub no_change_baseline_id: StableId,
    pub no_change_baseline_digest: Digest32,
    pub minimum_dataset_records: u32,
}

pub struct SelfEvolutionSelectionInputsV2<'a> {
    pub execution: &'a ProductPairedEvaluationReceiptV1,
    pub qualification: &'a ProductPairedQualificationReceiptV1,
    pub context: &'a ProductQualificationContextV1,
    pub evaluation_evidence: &'a SignedEvaluationEvidenceV1,
    pub dataset_receipt: &'a DatasetSnapshotReceiptV3,
    pub ledger_snapshot: &'a LedgerSnapshot,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelfEvolutionSelectionReceiptV2 {
    pub request: SelfEvolutionSelectionRequestV1,
    pub objective_digest: Digest32,
    pub dataset_digest: Digest32,
    pub ledger_head_digest: Digest32,
    pub qualification_digest: Digest32,
    pub publication_digest: Digest32,
    pub paired_execution_digest: Digest32,
    pub paired_profile_digest: Digest32,
    pub evaluation_evidence_digest: Digest32,
    pub evaluation_authentication_digest: Digest32,
    pub evaluation_trust_digest: Digest32,
    pub frozen_plan_digest: Digest32,
    pub registered_at_unix_micros: u64,
    pub minimum_dataset_records: u32,
    pub authority: AuthorityPosture,
}

#[derive(Clone)]
pub struct PreparedSelfEvolutionSelectionV2 {
    receipt: SelfEvolutionSelectionReceiptV2,
    participants: [VerifiedLearningEvidenceV1; 3],
    registration: AuthenticatedPairedRegistrationV1,
    clock: Arc<Mutex<PairedHostClockV1>>,
}

#[derive(Clone)]
pub struct VerifiedSelfEvolutionSelectionV2 {
    prepared: PreparedSelfEvolutionSelectionV2,
    selector: VerifiedLearningEvidenceV1,
    selector_evidence_digest: Digest32,
    selection_digest: Digest32,
}

impl fmt::Debug for PreparedSelfEvolutionSelectionV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PreparedSelfEvolutionSelectionV2")
            .field("receipt", &self.receipt)
            .finish_non_exhaustive()
    }
}

impl fmt::Debug for VerifiedSelfEvolutionSelectionV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("VerifiedSelfEvolutionSelectionV2")
            .field("receipt", self.receipt())
            .field("selection_digest", &self.selection_digest)
            .finish_non_exhaustive()
    }
}

impl PreparedSelfEvolutionSelectionV2 {
    pub fn receipt(&self) -> &SelfEvolutionSelectionReceiptV2 {
        &self.receipt
    }

    fn current(
        &self,
        trust: &ActivatedLearningTrustV1,
    ) -> Result<u64, SelfEvolutionSelectionError> {
        if trust.verifier().trust_digest() != self.receipt.evaluation_trust_digest {
            return Err(SelfEvolutionSelectionError::BindingMismatch);
        }
        let now = self
            .clock
            .lock()
            .map_err(|_| SelfEvolutionSelectionError::BindingMismatch)?
            .sample_registered(trust, &self.registration)
            .map_err(|_| SelfEvolutionSelectionError::BindingMismatch)?;
        for participant in &self.participants {
            trust.verifier().revalidate(participant, now)?;
        }
        Ok(now)
    }
}

impl VerifiedSelfEvolutionSelectionV2 {
    pub fn receipt(&self) -> &SelfEvolutionSelectionReceiptV2 {
        self.prepared.receipt()
    }
    pub const fn selection_digest(&self) -> Digest32 {
        self.selection_digest
    }
    pub const fn selector_evidence_digest(&self) -> Digest32 {
        self.selector_evidence_digest
    }
    pub fn authority_epoch(&self) -> u64 {
        self.selector.principal().authority_epoch
    }

    /// Each consumer supplies its current root-activated trust. The token owns
    /// its clock and original registration; a caller cannot reuse an old date.
    pub fn revalidate_current(
        &self,
        trust: &ActivatedLearningTrustV1,
    ) -> Result<(), SelfEvolutionSelectionError> {
        let now = self.prepared.current(trust)?;
        trust.verifier().revalidate(&self.selector, now)?;
        for participant in &self.prepared.participants {
            verify_verified_role_separation(&self.selector, participant, now)?;
        }
        Ok(())
    }
}

pub fn prepare_self_evolution_selection_v2(
    policy: &SelfEvolutionSelectionPolicyV2,
    request: SelfEvolutionSelectionRequestV1,
    inputs: SelfEvolutionSelectionInputsV2<'_>,
    trust: &ActivatedLearningTrustV1,
) -> Result<PreparedSelfEvolutionSelectionV2, SelfEvolutionSelectionError> {
    prepare_with_clock(policy, request, inputs, trust, PairedHostClockV1::system())
}

fn prepare_with_clock(
    policy: &SelfEvolutionSelectionPolicyV2,
    request: SelfEvolutionSelectionRequestV1,
    inputs: SelfEvolutionSelectionInputsV2<'_>,
    trust: &ActivatedLearningTrustV1,
    mut clock: PairedHostClockV1,
) -> Result<PreparedSelfEvolutionSelectionV2, SelfEvolutionSelectionError> {
    if policy.minimum_dataset_records == 0
        || policy.minimum_dataset_records > 1_000_000
        || policy.no_change_baseline_digest.is_zero()
    {
        return Err(SelfEvolutionSelectionError::InvalidPolicy);
    }
    if request.predecessor_generation.next().ok() != Some(request.candidate_generation) {
        return Err(SelfEvolutionSelectionError::GenerationMismatch);
    }
    let registration = &inputs.execution.registration;
    let plan = &registration.plan;
    let frozen = &plan.frozen;
    if request.predecessor_id != policy.no_change_baseline_id
        || request.predecessor_artifact_digest != policy.no_change_baseline_digest
        || request.predecessor_id == request.candidate_id
        || request.candidate_artifact_digest.is_zero()
        || request.predecessor_artifact_digest == request.candidate_artifact_digest
        || request.candidate_id != frozen.candidate_id
        || request.predecessor_id != frozen.baseline_id
        || request.candidate_artifact_digest != plan.runtime.candidate_artifact_digest
        || request.predecessor_artifact_digest != plan.runtime.deployed_baseline_digest
    {
        return Err(SelfEvolutionSelectionError::BindingMismatch);
    }
    let now = clock
        .sample_registered(trust, registration)
        .map_err(|_| SelfEvolutionSelectionError::BindingMismatch)?;
    inputs
        .execution
        .verify_current(trust.verifier(), now)
        .map_err(|_| SelfEvolutionSelectionError::BindingMismatch)?;
    inputs
        .qualification
        .validate_integrity()
        .map_err(|_| SelfEvolutionSelectionError::BindingMismatch)?;
    if inputs.qualification.paired_execution_digest != inputs.execution.execution_digest
        || inputs.qualification.paired_profile_digest != plan.profile_digest()
        || inputs.qualification.decision.trust_digest != trust.verifier().trust_digest()
        || inputs.qualification.decision.decision.candidate_id != request.candidate_id
        || inputs.qualification.decision.decision.baseline_id != request.predecessor_id
        || inputs.evaluation_evidence.generator_plan != registration.generator_evidence
    {
        return Err(SelfEvolutionSelectionError::BindingMismatch);
    }
    if inputs.qualification.decision.decision.disposition
        != IndependentEvaluationDispositionV1::EligibleForIndependentSelection
    {
        return Err(SelfEvolutionSelectionError::EvaluationRejected);
    }
    verify_dataset_snapshot_receipt_against_ledger_v3(
        inputs.dataset_receipt,
        inputs.ledger_snapshot,
        now,
    )?;
    if inputs.dataset_receipt.snapshot.objective_digest != frozen.objective_digest
        || inputs.dataset_receipt.snapshot.dataset_digest != frozen.dataset_digest
    {
        return Err(SelfEvolutionSelectionError::BindingMismatch);
    }
    if inputs.dataset_receipt.snapshot.source_record_digests.len()
        < policy.minimum_dataset_records as usize
    {
        return Err(SelfEvolutionSelectionError::DatasetTooSmall);
    }
    let verifier = trust.verifier();
    let bundle =
        crate::paired_supervised_qualification::paired_bundle(inputs.execution, inputs.context)
            .map_err(|_| SelfEvolutionSelectionError::BindingMismatch)?;
    let evaluator_payload = paired_evaluation_signing_payload_v1(inputs.execution, inputs.context)
        .map_err(|_| SelfEvolutionSelectionError::BindingMismatch)?;
    let authentication = crate::signed_evaluation::authenticate(
        &bundle,
        inputs.evaluation_evidence,
        verifier,
        &evaluator_payload,
        now,
    )?;
    if authentication != inputs.qualification.decision.authentication_digest {
        return Err(SelfEvolutionSelectionError::BindingMismatch);
    }
    let generator = verifier.verify(
        LearningEvidenceRoleV1::Generator,
        &registration.generator_evidence,
        frozen.plan_digest.as_array(),
        now,
    )?;
    let evaluator = verifier.verify(
        LearningEvidenceRoleV1::Evaluator,
        &inputs.evaluation_evidence.evaluator_bundle,
        &paired_evaluation_signing_payload_v1(inputs.execution, inputs.context)
            .map_err(|_| SelfEvolutionSelectionError::BindingMismatch)?,
        now,
    )?;
    let observer = verifier.verify(
        LearningEvidenceRoleV1::Observer,
        &inputs.execution.observations.observer_evidence,
        &paired_observation_cut_signing_payload_v1(&inputs.execution.observations.cut)
            .map_err(|_| SelfEvolutionSelectionError::BindingMismatch)?,
        now,
    )?;
    for (left, right) in [
        (&generator, &evaluator),
        (&generator, &observer),
        (&evaluator, &observer),
    ] {
        verify_verified_role_separation(left, right, now)?;
    }
    let receipt = SelfEvolutionSelectionReceiptV2 {
        request,
        objective_digest: frozen.objective_digest,
        dataset_digest: frozen.dataset_digest,
        ledger_head_digest: inputs.dataset_receipt.snapshot.ledger_head_digest,
        qualification_digest: inputs.qualification.evidence_digest,
        publication_digest: inputs.qualification.publication_digest,
        paired_execution_digest: inputs.execution.execution_digest,
        paired_profile_digest: plan.profile_digest(),
        evaluation_evidence_digest: inputs.qualification.decision.decision.evidence_digest,
        evaluation_authentication_digest: inputs.qualification.decision.authentication_digest,
        evaluation_trust_digest: verifier.trust_digest(),
        frozen_plan_digest: frozen.plan_digest,
        registered_at_unix_micros: registration.binding.registered_at_unix_micros,
        minimum_dataset_records: policy.minimum_dataset_records,
        authority: AuthorityPosture::DENY_ALL,
    };
    let prepared = PreparedSelfEvolutionSelectionV2 {
        receipt,
        participants: [generator, evaluator, observer],
        registration: registration.clone(),
        clock: Arc::new(Mutex::new(clock)),
    };
    // Dataset authentication and hashes can cross the original validity window.
    prepared.current(trust)?;
    Ok(prepared)
}

pub fn selection_signing_payload_v2(
    receipt: &SelfEvolutionSelectionReceiptV2,
) -> Result<Vec<u8>, SelfEvolutionSelectionError> {
    if receipt.authority != AuthorityPosture::DENY_ALL
        || receipt.registered_at_unix_micros == 0
        || receipt.minimum_dataset_records == 0
        || receipt.minimum_dataset_records > 1_000_000
    {
        return Err(SelfEvolutionSelectionError::BindingMismatch);
    }
    let mut bytes = b"hepta.intelligence-eval.self-evolution-selection.v2\0".to_vec();
    for id in [
        &receipt.request.selection_id,
        &receipt.request.predecessor_id,
        &receipt.request.candidate_id,
    ] {
        bytes.extend_from_slice(&(id.as_str().len() as u64).to_be_bytes());
        bytes.extend_from_slice(id.as_str().as_bytes());
    }
    bytes.extend_from_slice(&receipt.request.predecessor_generation.get().to_be_bytes());
    bytes.extend_from_slice(&receipt.request.candidate_generation.get().to_be_bytes());
    for digest in [
        receipt.request.predecessor_artifact_digest,
        receipt.request.candidate_artifact_digest,
        receipt.objective_digest,
        receipt.dataset_digest,
        receipt.ledger_head_digest,
        receipt.qualification_digest,
        receipt.publication_digest,
        receipt.paired_execution_digest,
        receipt.paired_profile_digest,
        receipt.evaluation_evidence_digest,
        receipt.evaluation_authentication_digest,
        receipt.evaluation_trust_digest,
        receipt.frozen_plan_digest,
    ] {
        if digest.is_zero() {
            return Err(SelfEvolutionSelectionError::EmptyDigest);
        }
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&receipt.registered_at_unix_micros.to_be_bytes());
    bytes.extend_from_slice(&receipt.minimum_dataset_records.to_be_bytes());
    Ok(bytes)
}

pub fn admit_self_evolution_selection_v2(
    prepared: PreparedSelfEvolutionSelectionV2,
    evidence: &SignedLearningEvidenceV1,
    trust: &ActivatedLearningTrustV1,
) -> Result<VerifiedSelfEvolutionSelectionV2, SelfEvolutionSelectionError> {
    let now = prepared.current(trust)?;
    let payload = selection_signing_payload_v2(prepared.receipt())?;
    let selector =
        trust
            .verifier()
            .verify(LearningEvidenceRoleV1::Selector, evidence, &payload, now)?;
    for participant in &prepared.participants {
        verify_verified_role_separation(&selector, participant, now)?;
    }
    let selector_evidence_digest = Digest32::of_bytes(&evidence.signing_bytes());
    let mut bytes = b"hepta.intelligence-eval.verified-self-evolution-selection.v2\0".to_vec();
    bytes.extend_from_slice(&payload);
    bytes.extend_from_slice(selector_evidence_digest.as_array());
    bytes.extend_from_slice(&evidence.signature);
    let token = VerifiedSelfEvolutionSelectionV2 {
        prepared,
        selector,
        selector_evidence_digest,
        selection_digest: Digest32::of_bytes(&bytes),
    };
    token.revalidate_current(trust)?;
    Ok(token)
}

#[cfg(test)]
#[path = "self_evolution_selection_v2_tests.rs"]
mod tests;
