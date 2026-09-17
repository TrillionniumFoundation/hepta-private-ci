//! Safe observability surface for composed plasticity proposal generation.
//!
//! Events intentionally omit evidence bodies, credentials and raw parameter
//! values. Hosts may translate these bounded events into metrics/traces.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AppendDisposition;
use crate::ComposedParameterProposalRequestV1;
use crate::DurableProposalAppendReceiptV1;
use crate::DurableProposalRegistryError;
use crate::EvidenceVerifier;
use crate::IndependentEvaluatorVerifier;
use crate::ProductionProposalRegistry;
use crate::generate_authenticate_and_append_v1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlasticityOperationV1 {
    GenerateAuthenticateAppend,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlasticityFailureClassV1 {
    PolicyOrIntegrity,
    Trust,
    DurableStore,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlasticityOutcomeV1 {
    Started,
    Inserted,
    Unchanged,
    Rejected(PlasticityFailureClassV1),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityEventV1 {
    pub operation: PlasticityOperationV1,
    pub proposal_id: StableId,
    pub selected_artifact_digest: Digest32,
    pub window_id: StableId,
    pub input_signal_count: usize,
    pub maximum_update_candidates: usize,
    pub sequence: Option<u64>,
    pub outcome: PlasticityOutcomeV1,
}

pub trait PlasticityObserver {
    fn observe(&self, event: &PlasticityEventV1);
}

pub fn generate_authenticate_append_observed_v1(
    registry: &mut ProductionProposalRegistry,
    request: ComposedParameterProposalRequestV1,
    evidence_verifier: &impl EvidenceVerifier,
    evaluator_verifier: &impl IndependentEvaluatorVerifier,
    observer: &impl PlasticityObserver,
) -> Result<DurableProposalAppendReceiptV1, DurableProposalRegistryError> {
    let base = PlasticityEventV1 {
        operation: PlasticityOperationV1::GenerateAuthenticateAppend,
        proposal_id: request.request.proposal_id.clone(),
        selected_artifact_digest: request.request.selected_artifact_digest,
        window_id: request.request.window.window_id.clone(),
        input_signal_count: request.signals.len(),
        maximum_update_candidates: request.generator.maximum_update_candidates,
        sequence: None,
        outcome: PlasticityOutcomeV1::Started,
    };
    observer.observe(&base);

    match generate_authenticate_and_append_v1(
        registry,
        request,
        evidence_verifier,
        evaluator_verifier,
    ) {
        Ok(receipt) => {
            let mut event = base;
            event.sequence = Some(receipt.sequence);
            event.outcome = match receipt.disposition {
                AppendDisposition::Inserted => PlasticityOutcomeV1::Inserted,
                AppendDisposition::Unchanged => PlasticityOutcomeV1::Unchanged,
            };
            observer.observe(&event);
            Ok(receipt)
        }
        Err(error) => {
            let mut event = base;
            event.outcome = PlasticityOutcomeV1::Rejected(classify_failure(&error));
            observer.observe(&event);
            Err(error)
        }
    }
}

fn classify_failure(error: &DurableProposalRegistryError) -> PlasticityFailureClassV1 {
    match error {
        DurableProposalRegistryError::Proposal(proposal_error) => match proposal_error {
            crate::Error::MissingAuthenticatedEvidence(_)
            | crate::Error::DuplicateAuthenticatedEvidence(_)
            | crate::Error::StaleAuthenticatedEvidence(_)
            | crate::Error::AuthenticatedEvidenceScopeMismatch
            | crate::Error::InvalidAuthenticatedEvidenceProducer
            | crate::Error::InvalidAuthenticatedEvidenceWindow
            | crate::Error::EvaluatorAttestationMismatch
            | crate::Error::StaleIndependentEvaluator
            | crate::Error::EvidenceVerificationFailed(_)
            | crate::Error::IndependentEvaluatorVerificationFailed(_) => {
                PlasticityFailureClassV1::Trust
            }
            _ => PlasticityFailureClassV1::PolicyOrIntegrity,
        },
        _ => PlasticityFailureClassV1::DurableStore,
    }
}
