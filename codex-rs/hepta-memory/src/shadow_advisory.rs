//! Read-only composition seam for the H5/H6 local-development shadows.
//!
//! This module deliberately consumes two already-typed shadow results without
//! turning either result into runtime authority.  It binds both decisions to
//! one immutable state/snapshot/policy epoch, recomputes them during
//! validation, and carries explicit negative flags for future callers.

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use thiserror::Error;

use crate::IntuitionShadowError;
use crate::IntuitionShadowInput;
use crate::IntuitionShadowReceipt;
use crate::NeuronParameter;
use crate::NeuronProposalDecision;
use crate::NeuronProposalError;
use crate::NeuronProposalInput;
use crate::framing::frame_part;
use crate::shadow_intuition_decide;
use crate::shadow_neuron_propose;

pub const SHADOW_ADVISORY_SCHEMA_VERSION: u32 = 1;
pub const SHADOW_ADVISORY_NAMESPACE: &str = "local_development_only";

/// One immutable read epoch shared by the H5 and H6 shadow inputs.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ShadowAdvisoryInput {
    pub state_digest: Sha256Digest,
    pub snapshot_digest: Sha256Digest,
    pub policy_digest: Sha256Digest,
    pub authority_epoch: u64,
    pub neuron: NeuronProposalInput,
    pub neuron_parameter: NeuronParameter,
    pub intuition: IntuitionShadowInput,
}

impl ShadowAdvisoryInput {
    pub fn validate(&self) -> Result<(), ShadowAdvisoryError> {
        validate_digest(&self.state_digest, "state digest")?;
        validate_digest(&self.snapshot_digest, "snapshot digest")?;
        validate_digest(&self.policy_digest, "policy digest")?;
        if self.authority_epoch == 0 {
            return Err(ShadowAdvisoryError::Invalid(
                "authority epoch must be non-zero".to_string(),
            ));
        }
        self.neuron.validate()?;
        self.intuition.validate()?;
        if self.neuron.state_digest != self.state_digest
            || self.neuron.policy_digest != self.policy_digest
            || self.neuron.authority_epoch != self.authority_epoch
        {
            return Err(ShadowAdvisoryError::BindingMismatch(
                "neuron input is not bound to the shared state/policy epoch".to_string(),
            ));
        }
        if self.intuition.snapshot_digest != self.snapshot_digest
            || self.intuition.policy_digest != self.policy_digest
            || self.intuition.authority_epoch != self.authority_epoch
        {
            return Err(ShadowAdvisoryError::BindingMismatch(
                "intuition input is not bound to the shared snapshot/policy epoch".to_string(),
            ));
        }
        // This is a pure validation call.  It never writes or authorizes the
        // proposal, but it ensures the position/parameter scope is checked at
        // the composition boundary as well as inside the H5 module.
        shadow_neuron_propose(&self.neuron, self.neuron_parameter)?;
        Ok(())
    }

    pub fn digest(&self) -> Result<Sha256Digest, ShadowAdvisoryError> {
        self.validate()?;
        let neuron_digest = self.neuron.digest()?;
        let intuition_digest = self.intuition.digest()?;
        let mut hasher = Sha256::new();
        frame_part(&mut hasher, b"hepta:h5-h6:shadow-advisory-input:v1");
        frame_part(&mut hasher, self.state_digest.as_str().as_bytes());
        frame_part(&mut hasher, self.snapshot_digest.as_str().as_bytes());
        frame_part(&mut hasher, self.policy_digest.as_str().as_bytes());
        frame_part(&mut hasher, &self.authority_epoch.to_be_bytes());
        frame_part(&mut hasher, self.neuron_parameter.as_str().as_bytes());
        frame_part(&mut hasher, neuron_digest.as_str().as_bytes());
        frame_part(&mut hasher, intuition_digest.as_str().as_bytes());
        Ok(Sha256Digest::from_sha256_output(hasher.finalize()))
    }
}

/// A read-only bundle of H5 and H6 decisions.  The nested values are
/// revalidated against their original inputs before this receipt is accepted.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ShadowAdvisoryReceipt {
    pub schema_version: u32,
    pub namespace: String,
    pub receipt_digest: Sha256Digest,
    pub input_digest: Sha256Digest,
    pub state_digest: Sha256Digest,
    pub snapshot_digest: Sha256Digest,
    pub policy_digest: Sha256Digest,
    pub authority_epoch: u64,
    pub neuron: NeuronProposalDecision,
    pub intuition: IntuitionShadowReceipt,
    pub production_effects: bool,
    pub execute_allowed: bool,
    pub kg_write_allowed: bool,
    pub online_routing: bool,
    pub runtime_consumer: bool,
}

impl ShadowAdvisoryReceipt {
    pub fn validate(&self) -> Result<(), ShadowAdvisoryError> {
        if self.schema_version != SHADOW_ADVISORY_SCHEMA_VERSION
            || self.namespace != SHADOW_ADVISORY_NAMESPACE
        {
            return Err(ShadowAdvisoryError::SchemaMismatch);
        }
        validate_digest(&self.receipt_digest, "receipt digest")?;
        validate_digest(&self.input_digest, "input digest")?;
        validate_digest(&self.state_digest, "state digest")?;
        validate_digest(&self.snapshot_digest, "snapshot digest")?;
        validate_digest(&self.policy_digest, "policy digest")?;
        if self.authority_epoch == 0 {
            return Err(ShadowAdvisoryError::Invalid(
                "authority epoch must be non-zero".to_string(),
            ));
        }
        if self.production_effects
            || self.execute_allowed
            || self.kg_write_allowed
            || self.online_routing
            || self.runtime_consumer
        {
            return Err(ShadowAdvisoryError::AuthorityBoundary);
        }
        // A receipt can be deserialized and consumed without the original
        // input.  Validate both nested shadows here as well as in
        // `validate_against`; otherwise a caller could mutate a nested
        // authority bit, recompute only the outer digest, and make a receipt
        // that appears valid while carrying an executable neuron or runtime
        // intuition result.
        validate_neuron_decision(&self.neuron)?;
        self.intuition.validate()?;
        if self.receipt_digest != receipt_digest(self) {
            return Err(ShadowAdvisoryError::DigestMismatch);
        }
        Ok(())
    }

    pub fn validate_against(&self, input: &ShadowAdvisoryInput) -> Result<(), ShadowAdvisoryError> {
        input.validate()?;
        self.validate()?;
        if self.input_digest != input.digest()?
            || self.state_digest != input.state_digest
            || self.snapshot_digest != input.snapshot_digest
            || self.policy_digest != input.policy_digest
            || self.authority_epoch != input.authority_epoch
        {
            return Err(ShadowAdvisoryError::BindingMismatch(
                "advisory receipt is not bound to its input epoch".to_string(),
            ));
        }
        let expected_neuron = shadow_neuron_propose(&input.neuron, input.neuron_parameter)?;
        if self.neuron != expected_neuron {
            return Err(ShadowAdvisoryError::BindingMismatch(
                "neuron decision differs from deterministic recomputation".to_string(),
            ));
        }
        let expected_intuition = shadow_intuition_decide(&input.intuition)?;
        if self.intuition != expected_intuition {
            return Err(ShadowAdvisoryError::BindingMismatch(
                "intuition receipt differs from deterministic recomputation".to_string(),
            ));
        }
        Ok(())
    }

    pub fn is_shadow_only(&self) -> bool {
        self.namespace == SHADOW_ADVISORY_NAMESPACE
            && !self.production_effects
            && !self.execute_allowed
            && !self.kg_write_allowed
            && !self.online_routing
            && !self.runtime_consumer
    }
}

#[derive(Debug, Error, Eq, PartialEq)]
pub enum ShadowAdvisoryError {
    #[error("invalid shadow advisory input: {0}")]
    Invalid(String),
    #[error("shadow advisory schema is not supported")]
    SchemaMismatch,
    #[error("shadow advisory digest does not match its contents")]
    DigestMismatch,
    #[error("shadow advisory binding mismatch: {0}")]
    BindingMismatch(String),
    #[error("shadow advisory crosses the authority boundary")]
    AuthorityBoundary,
    #[error("neuron proposal error: {0}")]
    Neuron(#[from] NeuronProposalError),
    #[error("intuition shadow error: {0}")]
    Intuition(#[from] IntuitionShadowError),
}

/// Evaluate both local shadows against one immutable read epoch.
pub fn shadow_advisory_evaluate(
    input: &ShadowAdvisoryInput,
) -> Result<ShadowAdvisoryReceipt, ShadowAdvisoryError> {
    input.validate()?;
    let input_digest = input.digest()?;
    let neuron = shadow_neuron_propose(&input.neuron, input.neuron_parameter)?;
    let intuition = shadow_intuition_decide(&input.intuition)?;
    let mut receipt = ShadowAdvisoryReceipt {
        schema_version: SHADOW_ADVISORY_SCHEMA_VERSION,
        namespace: SHADOW_ADVISORY_NAMESPACE.to_string(),
        receipt_digest: Sha256Digest::for_bytes(b"pending"),
        input_digest,
        state_digest: input.state_digest.clone(),
        snapshot_digest: input.snapshot_digest.clone(),
        policy_digest: input.policy_digest.clone(),
        authority_epoch: input.authority_epoch,
        neuron,
        intuition,
        production_effects: false,
        execute_allowed: false,
        kg_write_allowed: false,
        online_routing: false,
        runtime_consumer: false,
    };
    receipt.receipt_digest = receipt_digest(&receipt);
    receipt.validate_against(input)?;
    Ok(receipt)
}

fn receipt_digest(receipt: &ShadowAdvisoryReceipt) -> Sha256Digest {
    let mut hasher = Sha256::new();
    frame_part(&mut hasher, b"hepta:h5-h6:shadow-advisory-receipt:v1");
    frame_part(&mut hasher, &receipt.schema_version.to_be_bytes());
    frame_part(&mut hasher, receipt.namespace.as_bytes());
    frame_part(&mut hasher, receipt.input_digest.as_str().as_bytes());
    frame_part(&mut hasher, receipt.state_digest.as_str().as_bytes());
    frame_part(&mut hasher, receipt.snapshot_digest.as_str().as_bytes());
    frame_part(&mut hasher, receipt.policy_digest.as_str().as_bytes());
    frame_part(&mut hasher, &receipt.authority_epoch.to_be_bytes());
    frame_part(
        &mut hasher,
        neuron_decision_digest(&receipt.neuron).as_str().as_bytes(),
    );
    frame_part(
        &mut hasher,
        receipt.intuition.receipt_digest.as_str().as_bytes(),
    );
    frame_part(&mut hasher, &[0, 0, 0, 0, 0]);
    Sha256Digest::from_sha256_output(hasher.finalize())
}

fn neuron_decision_digest(decision: &NeuronProposalDecision) -> Sha256Digest {
    let mut hasher = Sha256::new();
    frame_part(&mut hasher, b"hepta:h5:neuron-decision:v1");
    match decision {
        NeuronProposalDecision::Proposed(proposal) => {
            frame_part(&mut hasher, b"proposed");
            frame_part(&mut hasher, proposal.proposal_id.as_str().as_bytes());
            frame_part(&mut hasher, proposal.input_digest.as_str().as_bytes());
            frame_part(&mut hasher, proposal.position.as_str().as_bytes());
            frame_part(&mut hasher, proposal.parameter.as_str().as_bytes());
            frame_part(&mut hasher, &proposal.delta_bps.to_be_bytes());
            frame_part(&mut hasher, &proposal.confidence_bps.to_be_bytes());
        }
        NeuronProposalDecision::Abstained {
            input_digest,
            reason,
        } => {
            frame_part(&mut hasher, b"abstained");
            frame_part(&mut hasher, input_digest.as_str().as_bytes());
            frame_part(
                &mut hasher,
                match reason {
                    crate::NeuronAbstainReason::NoChange => b"no_change",
                },
            );
        }
    }
    Sha256Digest::from_sha256_output(hasher.finalize())
}

fn validate_neuron_decision(decision: &NeuronProposalDecision) -> Result<(), ShadowAdvisoryError> {
    match decision {
        NeuronProposalDecision::Proposed(proposal) => proposal.validate().map_err(Into::into),
        NeuronProposalDecision::Abstained { input_digest, .. } => {
            validate_digest(input_digest, "abstained neuron input digest")
        }
    }
}

fn validate_digest(digest: &Sha256Digest, label: &str) -> Result<(), ShadowAdvisoryError> {
    if Sha256Digest::parse(digest.as_str().to_string()).is_err() {
        return Err(ShadowAdvisoryError::Invalid(format!(
            "{label} must be a lowercase SHA-256 digest"
        )));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::ShadowAdvisoryError;
    use super::ShadowAdvisoryInput;
    use super::shadow_advisory_evaluate;
    use crate::IntuitionCandidate;
    use crate::IntuitionDecision;
    use crate::IntuitionMode;
    use crate::NeuronFeature;
    use crate::NeuronParameter;
    use crate::NeuronPosition;
    use crate::NeuronProposalDecision;
    use crate::intuition_schema_digest;
    use codex_hepta_contracts::Sha256Digest;

    fn input() -> ShadowAdvisoryInput {
        let state_digest = Sha256Digest::for_bytes(b"state:v1");
        let snapshot_digest = Sha256Digest::for_bytes(b"snapshot:v1");
        let policy_digest = Sha256Digest::for_bytes(b"policy:v1");
        ShadowAdvisoryInput {
            state_digest: state_digest.clone(),
            snapshot_digest: snapshot_digest.clone(),
            policy_digest: policy_digest.clone(),
            authority_epoch: 9,
            neuron: crate::NeuronProposalInput {
                position: NeuronPosition::MemoryRetrievalRank,
                state_digest,
                policy_digest: policy_digest.clone(),
                authority_epoch: 9,
                sample_count: 12,
                baseline_bps: 7_000,
                features: vec![NeuronFeature::new("success", 9_000).expect("feature")],
            },
            neuron_parameter: NeuronParameter::RetrievalWeightBps,
            intuition: crate::IntuitionShadowInput {
                snapshot_digest,
                schema_digest: intuition_schema_digest(),
                policy_digest,
                authority_epoch: 9,
                mode: IntuitionMode::SuggestOnly,
                max_risk_bps: 6_000,
                min_confidence_bps: 5_000,
                require_evidence: true,
                candidates: vec![
                    IntuitionCandidate::new(
                        "candidate-a",
                        8_000,
                        1_000,
                        vec![IntuitionMode::SuggestOnly],
                        true,
                    )
                    .expect("candidate"),
                ],
            },
        }
    }

    #[test]
    fn bundle_is_deterministic_and_shadow_only() {
        let first = shadow_advisory_evaluate(&input()).expect("bundle");
        let second = shadow_advisory_evaluate(&input()).expect("bundle");
        assert_eq!(first, second);
        assert!(first.is_shadow_only());
        assert!(matches!(first.neuron, NeuronProposalDecision::Proposed(_)));
        assert!(matches!(
            first.intuition.decision,
            IntuitionDecision::Suggested { .. }
        ));
    }

    #[test]
    fn shared_epoch_binding_rejects_cross_plane_input() {
        let mut input = input();
        input.intuition.authority_epoch = 10;
        assert!(matches!(
            shadow_advisory_evaluate(&input),
            Err(ShadowAdvisoryError::BindingMismatch(_))
        ));
    }

    #[test]
    fn policy_and_snapshot_binding_rejects_cross_plane_input() {
        let mut policy_input = input();
        policy_input.intuition.policy_digest = Sha256Digest::for_bytes(b"other-policy");
        assert!(matches!(
            shadow_advisory_evaluate(&policy_input),
            Err(ShadowAdvisoryError::BindingMismatch(_))
        ));
        let mut snapshot_input = input();
        snapshot_input.intuition.snapshot_digest = Sha256Digest::for_bytes(b"other-snapshot");
        assert!(matches!(
            shadow_advisory_evaluate(&snapshot_input),
            Err(ShadowAdvisoryError::BindingMismatch(_))
        ));
    }

    #[test]
    fn recomputation_rejects_tampered_nested_decisions() {
        let input = input();
        let mut receipt = shadow_advisory_evaluate(&input).expect("bundle");
        receipt.neuron = NeuronProposalDecision::Abstained {
            input_digest: input.neuron.digest().expect("digest"),
            reason: crate::NeuronAbstainReason::NoChange,
        };
        receipt.receipt_digest = super::receipt_digest(&receipt);
        assert!(matches!(
            receipt.validate_against(&input),
            Err(ShadowAdvisoryError::BindingMismatch(_))
        ));
    }

    #[test]
    fn negative_authority_flags_are_fail_closed() {
        let input = input();
        let mut receipt = shadow_advisory_evaluate(&input).expect("bundle");
        receipt.runtime_consumer = true;
        assert_eq!(
            receipt.validate(),
            Err(ShadowAdvisoryError::AuthorityBoundary)
        );
    }

    #[test]
    fn standalone_validation_rejects_tampered_nested_authority() {
        let input = input();
        let mut neuron_tampered = shadow_advisory_evaluate(&input).expect("bundle");
        let NeuronProposalDecision::Proposed(mut proposal) = neuron_tampered.neuron else {
            panic!("expected proposal");
        };
        proposal.execute_allowed = true;
        neuron_tampered.neuron = NeuronProposalDecision::Proposed(proposal);
        // The outer digest intentionally commits to the decision identity,
        // not mutable authority metadata.  Standalone validation must still
        // inspect the nested proposal before accepting this value.
        neuron_tampered.receipt_digest = super::receipt_digest(&neuron_tampered);
        assert!(matches!(
            neuron_tampered.validate(),
            Err(ShadowAdvisoryError::Neuron(
                crate::NeuronProposalError::AuthorityBoundary
            ))
        ));

        let mut intuition_tampered = shadow_advisory_evaluate(&input).expect("bundle");
        intuition_tampered.intuition.runtime_consumer = true;
        intuition_tampered.receipt_digest = super::receipt_digest(&intuition_tampered);
        assert!(matches!(
            intuition_tampered.validate(),
            Err(ShadowAdvisoryError::Intuition(
                crate::IntuitionShadowError::AuthorityBoundary
            ))
        ));
    }
}
