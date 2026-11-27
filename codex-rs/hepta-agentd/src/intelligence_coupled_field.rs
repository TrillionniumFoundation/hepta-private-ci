//! A host-installed, read-only source for coupled parameter evidence at ordinary evaluation.
use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_intelligence::coupled_field_admission::CoupledFieldCandidateBindingV1;
use codex_hepta_intelligence_eval::FinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::ProductEvaluationRunnerV1;
use codex_hepta_intelligence_eval::ProductQualificationReceiptV1;
use codex_hepta_intelligence_eval::SignedEvaluationDecisionV1;
use codex_hepta_learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_learning_artifacts::ParameterFamilyGuardV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::AgentdIntelligenceEvaluationError;

/// Point-in-time evidence. The registry witness binds the owner's current view.
/// The qualification digest identifies the published evaluation of these bytes.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdCoupledFieldReadbackV1 {
    pub binding: CoupledFieldCandidateBindingV1,
    pub registry_witness: Digest32,
    pub qualification_digest: Digest32,
}

impl AgentdCoupledFieldReadbackV1 {
    pub(super) fn digests(&self) -> [Digest32; 6] {
        [
            self.registry_witness,
            self.qualification_digest,
            self.binding.artifact_bytes_digest,
            self.binding.evaluation_dataset_digest,
            self.binding.plan_digest,
            self.binding.holdout_use_digest,
        ]
    }

    pub(super) fn extend_receipt(&self, receipt: &mut Vec<u8>) {
        receipt.extend_from_slice(b"hepta.agentd.coupled-parameter-readback.v1\0");
        for digest in self.digests() {
            receipt.extend_from_slice(digest.as_array());
        }
    }
}

/// Private type erasure for the concrete host store. Production callers can only
/// install the implementation backed by the actual registry and evaluator.
pub(super) trait CoupledReadback: Send + Sync {
    fn read(
        &self,
        decision: &SignedEvaluationDecisionV1,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
    ) -> Result<AgentdCoupledFieldReadbackV1, AgentdIntelligenceEvaluationError>;
}

/// Constructed by the host from its existing registry service, evaluation owner
/// and retained attestations. Ordinary requests cannot install or replace it.
pub struct AgentdCoupledFieldEvidenceOwnerV1<S> {
    service: Arc<Mutex<LearningArtifactOwnerService>>,
    family: Mutex<ParameterFamilyGuardV1>,
    runner: Arc<ProductEvaluationRunnerV1<S>>,
    qualifications: BTreeMap<StableId, (ProductQualificationReceiptV1, SignedLearningEvidenceV1)>,
}

impl<S> AgentdCoupledFieldEvidenceOwnerV1<S> {
    pub fn new(
        service: Arc<Mutex<LearningArtifactOwnerService>>,
        family: ParameterFamilyGuardV1,
        runner: Arc<ProductEvaluationRunnerV1<S>>,
        qualifications: Vec<(ProductQualificationReceiptV1, SignedLearningEvidenceV1)>,
    ) -> Result<Self, AgentdIntelligenceEvaluationError> {
        if qualifications.is_empty() || qualifications.len() > 31 {
            return Err(AgentdIntelligenceEvaluationError::Binding);
        }
        let mut records = BTreeMap::new();
        for (qualification, signature) in qualifications {
            qualification
                .validate_integrity()
                .map_err(|_| AgentdIntelligenceEvaluationError::Binding)?;
            let id = qualification.candidate_id.clone();
            if !id.as_str().starts_with("candidate:field:")
                || records.insert(id, (qualification, signature)).is_some()
            {
                return Err(AgentdIntelligenceEvaluationError::Binding);
            }
        }
        Ok(Self {
            service,
            family: Mutex::new(family),
            runner,
            qualifications: records,
        })
    }
}

impl<S: FinalHoldoutCasStoreV1> AgentdCoupledFieldEvidenceOwnerV1<S> {
    /// Obtain the same live material evidence checked during task execution.
    /// This lets an independent evaluator prepare the exact per-run signature.
    pub fn readback(
        &self,
        decision: &SignedEvaluationDecisionV1,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
    ) -> Result<AgentdCoupledFieldReadbackV1, AgentdIntelligenceEvaluationError> {
        use AgentdIntelligenceEvaluationError::Binding;
        let id = &decision.decision.candidate_id;
        let (qualification, signature) = self.qualifications.get(id).ok_or(Binding)?;
        if &qualification.decision != decision {
            return Err(Binding);
        }
        let service = self.service.try_lock().map_err(|_| Binding)?;
        let mut family = self.family.try_lock().map_err(|_| Binding)?;
        family
            .with_service(&service, now, |_, pins, registry_witness| {
                let pin = pins
                    .iter()
                    .find(|pin| &pin.spec().manifest.artifact_id == id)
                    .ok_or(Binding)?;
                let binding = CoupledFieldCandidateBindingV1::from_ordinary_qualification(
                    pin,
                    &self.runner,
                    qualification,
                    signature,
                    verifier,
                    now,
                )
                .map_err(|_| Binding)?;
                Ok(AgentdCoupledFieldReadbackV1 {
                    binding,
                    registry_witness,
                    qualification_digest: qualification.evidence_digest,
                })
            })
            .map_err(|_| Binding)?
    }
}

impl<S: FinalHoldoutCasStoreV1 + Send> CoupledReadback for AgentdCoupledFieldEvidenceOwnerV1<S> {
    fn read(
        &self,
        decision: &SignedEvaluationDecisionV1,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
    ) -> Result<AgentdCoupledFieldReadbackV1, AgentdIntelligenceEvaluationError> {
        self.readback(decision, verifier, now)
    }
}
