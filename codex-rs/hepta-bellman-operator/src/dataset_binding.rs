//! Verified frozen-dataset binding for operator training.
//!
//! New qualification code consumes a self-verifying DatasetSnapshotReceiptV3,
//! then binds the exact source-record evidence set to the fitted rows. Legacy
//! fit functions remain available for compatibility, but cannot establish this
//! receipt-to-row relationship on their own.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_ledger::DatasetReceiptError;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_dataset_snapshot_receipt_v3;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::BellmanOperatorArtifact;
use crate::Error as TargetBuilderError;
use crate::LearnedOperatorError;
use crate::TabularOperatorArtifactV1;
use crate::TabularOperatorPlanV1;
use crate::TabularWorldModelV1;
use crate::TrainingRequest;
use crate::WorldModelError;
use crate::WorldModelSampleV1;
use crate::build_targets;
use crate::fit_tabular_operator;
use crate::fit_transition_model;

/// A verified, immutable dataset identity whose full V3 digest preimage has
/// already been checked. Fields are private so arbitrary callers cannot mint a
/// dataset binding from a detached digest.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedOperatorDatasetV2 {
    snapshot_id: StableId,
    objective_digest: Digest32,
    dataset_digest: Digest32,
    ledger_head_digest: Digest32,
    source_record_digests: Vec<Digest32>,
}

impl VerifiedOperatorDatasetV2 {
    /// Structural compatibility constructor. This proves the V3 receipt digest
    /// preimage is self-consistent but does not authenticate the dataset owner.
    /// Repository product source must use `from_authenticated_receipt`.
    pub fn from_receipt(
        receipt: &DatasetSnapshotReceiptV3,
        now: u64,
    ) -> Result<Self, OperatorDatasetBindingError> {
        verify_dataset_snapshot_receipt_v3(receipt, now)?;
        Ok(Self {
            snapshot_id: receipt.snapshot.snapshot_id.clone(),
            objective_digest: receipt.snapshot.objective_digest,
            dataset_digest: receipt.snapshot.dataset_digest,
            ledger_head_digest: receipt.snapshot.ledger_head_digest,
            source_record_digests: receipt.snapshot.source_record_digests.clone(),
        })
    }

    /// Verify both receipt integrity and host-trusted DatasetOwner provenance.
    ///
    /// The signed payload is domain-separated and binds the exact V3 dataset
    /// digest. The verified host principal must exactly equal the producer
    /// embedded in the receipt, so caller-constructed identity metadata cannot
    /// stand in for authoritative owner evidence.
    pub fn from_authenticated_receipt(
        receipt: &DatasetSnapshotReceiptV3,
        owner_evidence: &SignedLearningEvidenceV1,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
    ) -> Result<Self, OperatorDatasetBindingError> {
        let payload = operator_dataset_signing_payload_v2(receipt, now)?;
        let owner = verifier.verify(
            LearningEvidenceRoleV1::DatasetOwner,
            owner_evidence,
            &payload,
            now,
        )?;
        if owner.principal() != &receipt.producer {
            return Err(OperatorDatasetBindingError::OwnerIdentityBinding);
        }
        Self::from_receipt(receipt, now)
    }

    #[must_use]
    pub fn snapshot_id(&self) -> &StableId {
        &self.snapshot_id
    }

    #[must_use]
    pub fn objective_digest(&self) -> Digest32 {
        self.objective_digest
    }

    #[must_use]
    pub fn dataset_digest(&self) -> Digest32 {
        self.dataset_digest
    }

    #[must_use]
    pub fn ledger_head_digest(&self) -> Digest32 {
        self.ledger_head_digest
    }

    fn require_exact_evidence(
        &self,
        evidence: impl IntoIterator<Item = Digest32>,
    ) -> Result<(), OperatorDatasetBindingError> {
        let mut provided = evidence.into_iter().collect::<Vec<_>>();
        if provided.iter().any(|digest| digest.is_zero()) {
            return Err(OperatorDatasetBindingError::EvidenceSetMismatch);
        }
        provided.sort_unstable();
        if provided.windows(2).any(|pair| pair[0] == pair[1]) {
            return Err(OperatorDatasetBindingError::DuplicateEvidence);
        }
        if provided != self.source_record_digests {
            return Err(OperatorDatasetBindingError::EvidenceSetMismatch);
        }
        Ok(())
    }
}

/// Canonical target construction from an independently verified frozen dataset.
/// The legacy request fields must identify the exact frozen snapshot and every
/// transition must correspond one-to-one with the receipt's source records.
/// The returned artifact binds the V3 dataset digest, not a detached legacy hash.
pub fn build_targets_bound_v2(
    dataset: &VerifiedOperatorDatasetV2,
    request: TrainingRequest,
) -> Result<BellmanOperatorArtifact, OperatorDatasetBindingError> {
    if request.dataset.snapshot_id != dataset.snapshot_id {
        return Err(OperatorDatasetBindingError::SnapshotMismatch);
    }
    if request.dataset.objective_digest != dataset.objective_digest {
        return Err(OperatorDatasetBindingError::ObjectiveMismatch);
    }
    if request.dataset.source_head_digest != dataset.ledger_head_digest {
        return Err(OperatorDatasetBindingError::SourceHeadMismatch);
    }
    dataset.require_exact_evidence(
        request
            .dataset
            .transitions
            .iter()
            .map(|transition| transition.support_digest),
    )?;
    let mut artifact = build_targets(request.clone())?;
    artifact.dataset_digest = dataset.dataset_digest;
    artifact.artifact_digest = crate::digest_artifact(
        &request,
        dataset.dataset_digest,
        &artifact.targets,
        &artifact.regularity,
    );
    Ok(artifact)
}

/// Canonical complete-grid fit from an independently verified frozen dataset.
/// The plan may still carry its historical digests for encoding compatibility,
/// but they must match the verified receipt exactly.
pub fn fit_tabular_operator_bound_v2(
    dataset: &VerifiedOperatorDatasetV2,
    plan: TabularOperatorPlanV1,
) -> Result<TabularOperatorArtifactV1, OperatorDatasetBindingError> {
    if plan.objective_digest != dataset.objective_digest {
        return Err(OperatorDatasetBindingError::ObjectiveMismatch);
    }
    if plan.dataset_digest != dataset.dataset_digest {
        return Err(OperatorDatasetBindingError::DatasetMismatch);
    }
    dataset.require_exact_evidence(plan.samples.iter().map(|sample| sample.evidence_digest))?;
    Ok(fit_tabular_operator(plan)?)
}

/// Canonical world-model fit from an independently verified frozen dataset.
/// The dataset digest is taken from the verified binding rather than supplied
/// as a second caller-controlled identity.
pub fn fit_transition_model_bound_v2(
    dataset: &VerifiedOperatorDatasetV2,
    model_id: StableId,
    samples: Vec<WorldModelSampleV1>,
) -> Result<TabularWorldModelV1, OperatorDatasetBindingError> {
    dataset.require_exact_evidence(samples.iter().map(|sample| sample.evidence_digest))?;
    Ok(fit_transition_model(
        model_id,
        dataset.dataset_digest,
        samples,
    )?)
}

/// Canonical bytes signed by the host-trusted dataset owner.
///
/// V3 integrity verification proves that `dataset_digest` already commits to
/// snapshot identity, producer identity, ledger/objective frontiers, correction
/// and revocation cuts, inclusion policy and the complete canonical source set.
pub fn operator_dataset_signing_payload_v2(
    receipt: &DatasetSnapshotReceiptV3,
    now: u64,
) -> Result<Vec<u8>, OperatorDatasetBindingError> {
    verify_dataset_snapshot_receipt_v3(receipt, now)?;
    let mut bytes = b"hepta.bellman-operator.dataset-owner.v2".to_vec();
    bytes.extend_from_slice(receipt.snapshot.dataset_digest.as_array());
    Ok(bytes)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OperatorDatasetBindingError {
    DatasetReceipt(DatasetReceiptError),
    SignedEvidence(SignedEvidenceError),
    OwnerIdentityBinding,
    ObjectiveMismatch,
    DatasetMismatch,
    SnapshotMismatch,
    SourceHeadMismatch,
    DuplicateEvidence,
    EvidenceSetMismatch,
    TargetBuilder(TargetBuilderError),
    Learned(LearnedOperatorError),
    WorldModel(WorldModelError),
}

impl fmt::Display for OperatorDatasetBindingError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for OperatorDatasetBindingError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::DatasetReceipt(error) => Some(error),
            Self::SignedEvidence(error) => Some(error),
            Self::TargetBuilder(error) => Some(error),
            Self::Learned(error) => Some(error),
            Self::WorldModel(error) => Some(error),
            Self::OwnerIdentityBinding
            | Self::ObjectiveMismatch
            | Self::DatasetMismatch
            | Self::SnapshotMismatch
            | Self::SourceHeadMismatch
            | Self::DuplicateEvidence
            | Self::EvidenceSetMismatch => None,
        }
    }
}

impl From<DatasetReceiptError> for OperatorDatasetBindingError {
    fn from(value: DatasetReceiptError) -> Self {
        Self::DatasetReceipt(value)
    }
}

impl From<SignedEvidenceError> for OperatorDatasetBindingError {
    fn from(value: SignedEvidenceError) -> Self {
        Self::SignedEvidence(value)
    }
}

impl From<TargetBuilderError> for OperatorDatasetBindingError {
    fn from(value: TargetBuilderError) -> Self {
        Self::TargetBuilder(value)
    }
}

impl From<LearnedOperatorError> for OperatorDatasetBindingError {
    fn from(value: LearnedOperatorError) -> Self {
        Self::Learned(value)
    }
}

impl From<WorldModelError> for OperatorDatasetBindingError {
    fn from(value: WorldModelError) -> Self {
        Self::WorldModel(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
    use codex_hepta_learning_ledger::DatasetFreezeRequestV1;
    use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
    use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
    use codex_hepta_learning_ledger::TrustedLearningSignerV1;
    use codex_hepta_learning_ledger::freeze_dataset_receipt_v3;
    use codex_hepta_types::FixedQ32;
    use codex_hepta_types::Generation;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    use crate::DatasetSnapshot;
    use crate::TabularOperatorSampleV1;
    use crate::TrainingRequest;
    use crate::Transition;

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned())
            .unwrap_or_else(|error| panic!("valid fixture id: {error:?}"))
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn receipt() -> DatasetSnapshotReceiptV3 {
        freeze_dataset_receipt_v3(
            DatasetFreezeRequestV1 {
                snapshot_id: id("operator-dataset"),
                producer: AuthenticatedPrincipalV1 {
                    principal_id: id("dataset-owner"),
                    credential_chain_digest: digest("credential"),
                    signing_key_digest: digest("key"),
                    scope_digest: digest("scope"),
                    authority_epoch: 7,
                    authenticated_at: 10,
                    expires_at: 100,
                },
                ledger_head_digest: digest("ledger-head"),
                objective_digest: digest("objective"),
                eligible_frontier: 3,
                outcome_watermark: 20,
                correction_cut_digest: digest("correction-cut"),
                revocation_cut_digest: digest("revocation-cut"),
                inclusion_policy_digest: digest("inclusion-policy"),
                source_record_digests: vec![digest("record-b"), digest("record-a")],
                pending_outcomes: 0,
                censored_outcomes: 0,
            },
            50,
        )
        .unwrap_or_else(|error| panic!("valid dataset receipt: {error:?}"))
    }

    fn sample(
        name: &str,
        action: &str,
        evidence: Digest32,
        target: i64,
    ) -> TabularOperatorSampleV1 {
        TabularOperatorSampleV1 {
            sample_id: id(name),
            sensor_id: id("sensor"),
            action_id: id(action),
            target: FixedQ32::from_raw(target),
            evidence_digest: evidence,
        }
    }

    fn target_request(receipt: &DatasetSnapshotReceiptV3) -> TrainingRequest {
        TrainingRequest {
            artifact_id: id("target-artifact"),
            producer_id: id("trainer"),
            generation: Generation::new(1).unwrap_or_else(|error| panic!("generation: {error:?}")),
            gamma: FixedQ32::from_raw(1_i64 << 31),
            dataset: DatasetSnapshot {
                snapshot_id: receipt.snapshot.snapshot_id.clone(),
                objective_digest: receipt.snapshot.objective_digest,
                source_head_digest: receipt.snapshot.ledger_head_digest,
                transitions: vec![
                    Transition {
                        sample_id: id("row-a"),
                        state_id: id("state-a"),
                        action_id: id("action-a"),
                        reward: FixedQ32::ZERO,
                        next_value: FixedQ32::ONE,
                        terminal: false,
                        support_digest: digest("record-a"),
                    },
                    Transition {
                        sample_id: id("row-b"),
                        state_id: id("state-b"),
                        action_id: id("action-b"),
                        reward: FixedQ32::ONE,
                        next_value: FixedQ32::ZERO,
                        terminal: true,
                        support_digest: digest("record-b"),
                    },
                ],
            },
        }
    }

    #[test]
    fn op_07_authenticated_dataset_requires_exact_trusted_owner() {
        let owner_key = SigningKey::from_bytes(&[41; 32]);
        let other_key = SigningKey::from_bytes(&[42; 32]);
        let principal = |name: &str, key: &SigningKey| AuthenticatedPrincipalV1 {
            principal_id: id(name),
            credential_chain_digest: digest(&format!("{name}-credential")),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            scope_digest: digest("scope"),
            authority_epoch: 7,
            authenticated_at: 10,
            expires_at: 100,
        };
        let owner = principal("dataset-owner", &owner_key);
        let other = principal("other-dataset-owner", &other_key);
        let receipt = freeze_dataset_receipt_v3(
            DatasetFreezeRequestV1 {
                snapshot_id: id("operator-dataset-authenticated"),
                producer: owner.clone(),
                ledger_head_digest: digest("ledger-head"),
                objective_digest: digest("objective"),
                eligible_frontier: 3,
                outcome_watermark: 20,
                correction_cut_digest: digest("correction-cut"),
                revocation_cut_digest: digest("revocation-cut"),
                inclusion_policy_digest: digest("inclusion-policy"),
                source_record_digests: vec![digest("record-b"), digest("record-a")],
                pending_outcomes: 0,
                censored_outcomes: 0,
            },
            50,
        )
        .unwrap_or_else(|error| panic!("valid receipt: {error:?}"));
        let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest: digest("scope"),
            objective_digest: digest("objective"),
            authority_epoch: 7,
            signers: vec![
                TrustedLearningSignerV1 {
                    principal: owner.clone(),
                    controller_id: id("dataset-controller"),
                    verifying_key: owner_key.verifying_key().to_bytes(),
                    roles: vec![LearningEvidenceRoleV1::DatasetOwner],
                    revoked_at: None,
                },
                TrustedLearningSignerV1 {
                    principal: other.clone(),
                    controller_id: id("other-dataset-controller"),
                    verifying_key: other_key.verifying_key().to_bytes(),
                    roles: vec![LearningEvidenceRoleV1::DatasetOwner],
                    revoked_at: None,
                },
            ],
        })
        .unwrap_or_else(|error| panic!("valid host trust: {error:?}"));
        let payload = operator_dataset_signing_payload_v2(&receipt, 50)
            .unwrap_or_else(|error| panic!("dataset payload: {error:?}"));
        let sign = |principal: &AuthenticatedPrincipalV1,
                    key: &SigningKey,
                    evidence_id: &str| {
            let mut evidence = SignedLearningEvidenceV1 {
                evidence_id: id(evidence_id),
                principal_id: principal.principal_id.clone(),
                role: LearningEvidenceRoleV1::DatasetOwner,
                trust_digest: verifier.trust_digest(),
                scope_digest: principal.scope_digest,
                objective_digest: receipt.snapshot.objective_digest,
                authority_epoch: principal.authority_epoch,
                issued_at: 20,
                expires_at: 90,
                payload_digest: Digest32::of_bytes(&payload),
                signature: [0; 64],
            };
            evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
            evidence
        };
        let owner_evidence = sign(&owner, &owner_key, "dataset-owner-proof");
        let verified = VerifiedOperatorDatasetV2::from_authenticated_receipt(
            &receipt,
            &owner_evidence,
            &verifier,
            50,
        )
        .unwrap_or_else(|error| panic!("trusted dataset owner: {error:?}"));
        assert_eq!(verified.dataset_digest(), receipt.snapshot.dataset_digest);

        let wrong_owner = sign(&other, &other_key, "other-dataset-owner-proof");
        assert_eq!(
            VerifiedOperatorDatasetV2::from_authenticated_receipt(
                &receipt,
                &wrong_owner,
                &verifier,
                50,
            ),
            Err(OperatorDatasetBindingError::OwnerIdentityBinding)
        );
    }

    #[test]
    fn op_07_bound_target_builder_consumes_exact_v3_dataset_rows() {
        let receipt = receipt();
        let bound = VerifiedOperatorDatasetV2::from_receipt(&receipt, 50)
            .unwrap_or_else(|error| panic!("verified dataset: {error:?}"));
        let artifact = build_targets_bound_v2(&bound, target_request(&receipt))
            .unwrap_or_else(|error| panic!("bound target build: {error:?}"));
        assert_eq!(artifact.dataset_digest, receipt.snapshot.dataset_digest);
        assert_eq!(artifact.objective_digest, receipt.snapshot.objective_digest);
    }

    #[test]
    fn op_07_bound_target_builder_rejects_detached_head_or_relabelled_evidence() {
        let receipt = receipt();
        let bound = VerifiedOperatorDatasetV2::from_receipt(&receipt, 50)
            .unwrap_or_else(|error| panic!("verified dataset: {error:?}"));

        let mut detached = target_request(&receipt);
        detached.dataset.source_head_digest = digest("detached-head");
        assert_eq!(
            build_targets_bound_v2(&bound, detached),
            Err(OperatorDatasetBindingError::SourceHeadMismatch)
        );

        let mut replayed = target_request(&receipt);
        replayed.dataset.transitions[1].sample_id = id("row-b-relabelled");
        replayed.dataset.transitions[1].support_digest =
            replayed.dataset.transitions[0].support_digest;
        assert_eq!(
            build_targets_bound_v2(&bound, replayed),
            Err(OperatorDatasetBindingError::DuplicateEvidence)
        );
    }

    #[test]
    fn op_07_bound_tabular_fit_consumes_exact_v3_dataset_rows() {
        let receipt = receipt();
        let bound = VerifiedOperatorDatasetV2::from_receipt(&receipt, 50)
            .unwrap_or_else(|error| panic!("verified: {error:?}"));
        let artifact = fit_tabular_operator_bound_v2(
            &bound,
            TabularOperatorPlanV1 {
                artifact_id: id("artifact"),
                producer_id: id("trainer"),
                generation: Generation::new(1)
                    .unwrap_or_else(|error| panic!("generation: {error:?}")),
                objective_digest: receipt.snapshot.objective_digest,
                dataset_digest: receipt.snapshot.dataset_digest,
                sensor_core_digest: digest("sensor-core"),
                training_profile_digest: digest("profile"),
                minimum_samples_per_cell: 1,
                sensor_ids: vec![id("sensor")],
                action_ids: vec![id("a"), id("b")],
                samples: vec![
                    sample("row-a", "a", digest("record-a"), 10),
                    sample("row-b", "b", digest("record-b"), 20),
                ],
            },
        )
        .unwrap_or_else(|error| panic!("bound fit: {error:?}"));
        assert_eq!(artifact.dataset_digest, receipt.snapshot.dataset_digest);
    }

    #[test]
    fn op_07_bound_fit_rejects_detached_digest_or_row_set() {
        let receipt = receipt();
        let bound = VerifiedOperatorDatasetV2::from_receipt(&receipt, 50)
            .unwrap_or_else(|error| panic!("verified: {error:?}"));
        let mut plan = TabularOperatorPlanV1 {
            artifact_id: id("artifact"),
            producer_id: id("trainer"),
            generation: Generation::new(1).unwrap_or_else(|error| panic!("generation: {error:?}")),
            objective_digest: receipt.snapshot.objective_digest,
            dataset_digest: digest("detached-dataset"),
            sensor_core_digest: digest("sensor-core"),
            training_profile_digest: digest("profile"),
            minimum_samples_per_cell: 1,
            sensor_ids: vec![id("sensor")],
            action_ids: vec![id("a"), id("b")],
            samples: vec![
                sample("row-a", "a", digest("record-a"), 10),
                sample("row-b", "b", digest("record-b"), 20),
            ],
        };
        assert_eq!(
            fit_tabular_operator_bound_v2(&bound, plan.clone()),
            Err(OperatorDatasetBindingError::DatasetMismatch)
        );
        plan.dataset_digest = receipt.snapshot.dataset_digest;
        plan.samples[1].evidence_digest = digest("foreign-record");
        assert_eq!(
            fit_tabular_operator_bound_v2(&bound, plan),
            Err(OperatorDatasetBindingError::EvidenceSetMismatch)
        );
    }

    #[test]
    fn op_07_bound_world_model_takes_dataset_identity_from_receipt() {
        let receipt = receipt();
        let bound = VerifiedOperatorDatasetV2::from_receipt(&receipt, 50)
            .unwrap_or_else(|error| panic!("verified: {error:?}"));
        let model = fit_transition_model_bound_v2(
            &bound,
            id("world-model"),
            vec![
                WorldModelSampleV1 {
                    sample_id: id("row-a"),
                    state_id: id("state"),
                    action_id: id("a"),
                    next_state_id: id("next-a"),
                    outcome: FixedQ32::from_raw(10),
                    evidence_digest: digest("record-a"),
                },
                WorldModelSampleV1 {
                    sample_id: id("row-b"),
                    state_id: id("state"),
                    action_id: id("b"),
                    next_state_id: id("next-b"),
                    outcome: FixedQ32::from_raw(20),
                    evidence_digest: digest("record-b"),
                },
            ],
        )
        .unwrap_or_else(|error| panic!("bound world model: {error:?}"));
        assert_eq!(model.dataset_digest, receipt.snapshot.dataset_digest);
    }
}
