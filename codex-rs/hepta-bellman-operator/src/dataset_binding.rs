//! Cryptographically bound operator dataset admission.
//!
//! The legacy fitters remain deterministic helpers for already trusted in-process
//! data. Cross-owner qualification can instead authenticate a self-verifying
//! `DatasetSnapshotReceiptV3` with the host-owned learning-evidence verifier,
//! producing a private typed dataset that binds the exact source-record set used
//! by tabular and world-model fitting.

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

use crate::LearnedOperatorError;
use crate::TabularOperatorArtifactV1;
use crate::TabularOperatorPlanV1;
use crate::TabularWorldModelV1;
use crate::WorldModelError;
use crate::WorldModelSampleV1;

const DATASET_DOMAIN: &[u8] = b"hepta.bellman-operator.dataset-binding.v1";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedOperatorDatasetV1 {
    dataset_digest: Digest32,
    objective_digest: Digest32,
    source_record_digests: Vec<Digest32>,
    producer_id: StableId,
}

impl VerifiedOperatorDatasetV1 {
    #[must_use]
    pub fn dataset_digest(&self) -> Digest32 {
        self.dataset_digest
    }

    #[must_use]
    pub fn objective_digest(&self) -> Digest32 {
        self.objective_digest
    }

    #[must_use]
    pub fn producer_id(&self) -> &StableId {
        &self.producer_id
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OperatorDatasetError {
    Receipt(DatasetReceiptError),
    Signed(SignedEvidenceError),
    ProducerMismatch,
    DatasetDigestMismatch,
    ObjectiveDigestMismatch,
    RowSetMismatch,
    Learned(LearnedOperatorError),
    WorldModel(WorldModelError),
}

impl fmt::Display for OperatorDatasetError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for OperatorDatasetError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Receipt(error) => Some(error),
            Self::Signed(error) => Some(error),
            Self::Learned(error) => Some(error),
            Self::WorldModel(error) => Some(error),
            Self::ProducerMismatch
            | Self::DatasetDigestMismatch
            | Self::ObjectiveDigestMismatch
            | Self::RowSetMismatch => None,
        }
    }
}

impl From<DatasetReceiptError> for OperatorDatasetError {
    fn from(value: DatasetReceiptError) -> Self {
        Self::Receipt(value)
    }
}

impl From<SignedEvidenceError> for OperatorDatasetError {
    fn from(value: SignedEvidenceError) -> Self {
        Self::Signed(value)
    }
}

impl From<LearnedOperatorError> for OperatorDatasetError {
    fn from(value: LearnedOperatorError) -> Self {
        Self::Learned(value)
    }
}

impl From<WorldModelError> for OperatorDatasetError {
    fn from(value: WorldModelError) -> Self {
        Self::WorldModel(value)
    }
}

/// Authenticate the exact V3 dataset receipt through an observer key from the
/// host-owned trust snapshot. The returned value cannot be caller-constructed.
pub fn verify_operator_dataset_v1(
    receipt: &DatasetSnapshotReceiptV3,
    signed_observer: &SignedLearningEvidenceV1,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<VerifiedOperatorDatasetV1, OperatorDatasetError> {
    verify_dataset_snapshot_receipt_v3(receipt, now)?;
    let statement = dataset_statement(receipt.snapshot.dataset_digest);
    let observer = verifier.verify(
        LearningEvidenceRoleV1::Observer,
        signed_observer,
        &statement,
        now,
    )?;
    if observer.principal() != &receipt.producer {
        return Err(OperatorDatasetError::ProducerMismatch);
    }

    Ok(VerifiedOperatorDatasetV1 {
        dataset_digest: receipt.snapshot.dataset_digest,
        objective_digest: receipt.snapshot.objective_digest,
        source_record_digests: receipt.snapshot.source_record_digests.clone(),
        producer_id: observer.principal().principal_id.clone(),
    })
}

/// Fit a tabular operator only when its dataset/objective identities and exact
/// evidence-row set match the authenticated frozen dataset.
pub fn fit_tabular_operator_verified_v1(
    plan: TabularOperatorPlanV1,
    dataset: &VerifiedOperatorDatasetV1,
) -> Result<TabularOperatorArtifactV1, OperatorDatasetError> {
    if plan.dataset_digest != dataset.dataset_digest {
        return Err(OperatorDatasetError::DatasetDigestMismatch);
    }
    if plan.objective_digest != dataset.objective_digest {
        return Err(OperatorDatasetError::ObjectiveDigestMismatch);
    }
    require_exact_rows(
        plan.samples.iter().map(|sample| sample.evidence_digest),
        dataset,
    )?;
    Ok(crate::admitted::fit_tabular_operator(plan)?)
}

/// Fit a world model only when the exact sample evidence set matches the
/// authenticated frozen dataset. A detached caller-provided dataset digest is
/// therefore insufficient on this qualification path.
pub fn fit_transition_model_verified_v1(
    model_id: StableId,
    dataset_digest: Digest32,
    samples: Vec<WorldModelSampleV1>,
    dataset: &VerifiedOperatorDatasetV1,
) -> Result<TabularWorldModelV1, OperatorDatasetError> {
    if dataset_digest != dataset.dataset_digest {
        return Err(OperatorDatasetError::DatasetDigestMismatch);
    }
    require_exact_rows(
        samples.iter().map(|sample| sample.evidence_digest),
        dataset,
    )?;
    Ok(crate::admitted::fit_transition_model(
        model_id,
        dataset_digest,
        samples,
    )?)
}

fn require_exact_rows(
    digests: impl IntoIterator<Item = Digest32>,
    dataset: &VerifiedOperatorDatasetV1,
) -> Result<(), OperatorDatasetError> {
    let mut actual = digests.into_iter().collect::<Vec<_>>();
    actual.sort_unstable();
    if actual.windows(2).any(|pair| pair[0] == pair[1])
        || actual != dataset.source_record_digests
    {
        return Err(OperatorDatasetError::RowSetMismatch);
    }
    Ok(())
}

fn dataset_statement(dataset_digest: Digest32) -> Vec<u8> {
    let mut bytes = Vec::with_capacity(DATASET_DOMAIN.len() + 32);
    bytes.extend_from_slice(DATASET_DOMAIN);
    bytes.extend_from_slice(dataset_digest.as_array());
    bytes
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
    use codex_hepta_learning_ledger::DatasetFreezeRequestV1;
    use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
    use codex_hepta_learning_ledger::TrustedLearningSignerV1;
    use codex_hepta_learning_ledger::freeze_dataset_receipt_v3;
    use codex_hepta_types::FixedQ32;
    use codex_hepta_types::Generation;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    use crate::TabularOperatorSampleV1;

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("valid id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn observer_signer() -> TrustedLearningSignerV1 {
        let key = SigningKey::from_bytes(&[3; 32])
            .verifying_key()
            .to_bytes();
        TrustedLearningSignerV1 {
            principal: AuthenticatedPrincipalV1 {
                principal_id: id("dataset-owner"),
                credential_chain_digest: digest("dataset-owner-credential"),
                signing_key_digest: Digest32::of_bytes(&key),
                scope_digest: digest("scope"),
                authority_epoch: 7,
                authenticated_at: 10,
                expires_at: 100,
            },
            controller_id: id("dataset-controller"),
            verifying_key: key,
            roles: vec![LearningEvidenceRoleV1::Observer],
            revoked_at: None,
        }
    }

    fn verifier() -> LearningEvidenceVerifierV1 {
        LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest: digest("scope"),
            objective_digest: digest("objective"),
            authority_epoch: 7,
            signers: vec![observer_signer()],
        })
        .expect("host trust")
    }

    fn receipt() -> DatasetSnapshotReceiptV3 {
        freeze_dataset_receipt_v3(
            DatasetFreezeRequestV1 {
                snapshot_id: id("dataset"),
                producer: observer_signer().principal,
                ledger_head_digest: digest("ledger-head"),
                objective_digest: digest("objective"),
                eligible_frontier: 7,
                outcome_watermark: 40,
                correction_cut_digest: digest("correction"),
                revocation_cut_digest: digest("revocation"),
                inclusion_policy_digest: digest("policy"),
                source_record_digests: vec![digest("row-b"), digest("row-a")],
                pending_outcomes: 0,
                censored_outcomes: 0,
            },
            50,
        )
        .expect("frozen dataset")
    }

    fn signed_dataset(
        verifier: &LearningEvidenceVerifierV1,
        receipt: &DatasetSnapshotReceiptV3,
    ) -> SignedLearningEvidenceV1 {
        let statement = dataset_statement(receipt.snapshot.dataset_digest);
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: id("dataset-evidence"),
            principal_id: id("dataset-owner"),
            role: LearningEvidenceRoleV1::Observer,
            trust_digest: verifier.trust_digest(),
            scope_digest: digest("scope"),
            objective_digest: digest("objective"),
            authority_epoch: 7,
            issued_at: 20,
            expires_at: 90,
            payload_digest: Digest32::of_bytes(&statement),
            signature: [0; 64],
        };
        evidence.signature = SigningKey::from_bytes(&[3; 32])
            .sign(&evidence.signing_bytes())
            .to_bytes();
        evidence
    }

    fn tabular_plan(dataset: &VerifiedOperatorDatasetV1) -> TabularOperatorPlanV1 {
        TabularOperatorPlanV1 {
            artifact_id: id("artifact"),
            producer_id: id("trainer"),
            generation: Generation::new(1).expect("generation"),
            objective_digest: dataset.objective_digest(),
            dataset_digest: dataset.dataset_digest(),
            sensor_core_digest: digest("sensor-core"),
            training_profile_digest: digest("profile"),
            minimum_samples_per_cell: 1,
            sensor_ids: vec![id("sensor")],
            action_ids: vec![id("action-a"), id("action-b")],
            samples: vec![
                TabularOperatorSampleV1 {
                    sample_id: id("sample-a"),
                    sensor_id: id("sensor"),
                    action_id: id("action-a"),
                    target: FixedQ32::from_raw(10),
                    evidence_digest: digest("row-a"),
                },
                TabularOperatorSampleV1 {
                    sample_id: id("sample-b"),
                    sensor_id: id("sensor"),
                    action_id: id("action-b"),
                    target: FixedQ32::from_raw(20),
                    evidence_digest: digest("row-b"),
                },
            ],
        }
    }

    #[test]
    fn op_05_verified_dataset_binds_exact_tabular_rows() {
        let verifier = verifier();
        let receipt = receipt();
        let signed = signed_dataset(&verifier, &receipt);
        let dataset =
            verify_operator_dataset_v1(&receipt, &signed, &verifier, 50).expect("verified dataset");
        let artifact =
            fit_tabular_operator_verified_v1(tabular_plan(&dataset), &dataset).expect("verified fit");
        assert_eq!(artifact.dataset_digest, dataset.dataset_digest());

        let mut altered = tabular_plan(&dataset);
        altered.samples[0].evidence_digest = digest("other-row");
        assert_eq!(
            fit_tabular_operator_verified_v1(altered, &dataset),
            Err(OperatorDatasetError::RowSetMismatch)
        );
    }

    #[test]
    fn op_05_verified_dataset_binds_exact_world_model_rows() {
        let verifier = verifier();
        let receipt = receipt();
        let signed = signed_dataset(&verifier, &receipt);
        let dataset =
            verify_operator_dataset_v1(&receipt, &signed, &verifier, 50).expect("verified dataset");
        let samples = vec![
            WorldModelSampleV1 {
                sample_id: id("sample-a"),
                state_id: id("state"),
                action_id: id("action"),
                next_state_id: id("next-a"),
                outcome: FixedQ32::from_raw(10),
                evidence_digest: digest("row-a"),
            },
            WorldModelSampleV1 {
                sample_id: id("sample-b"),
                state_id: id("state"),
                action_id: id("action"),
                next_state_id: id("next-b"),
                outcome: FixedQ32::from_raw(20),
                evidence_digest: digest("row-b"),
            },
        ];
        let model = fit_transition_model_verified_v1(
            id("world-model"),
            dataset.dataset_digest(),
            samples.clone(),
            &dataset,
        )
        .expect("verified world-model fit");
        assert_eq!(model.dataset_digest, dataset.dataset_digest());

        assert_eq!(
            fit_transition_model_verified_v1(
                id("world-model"),
                digest("detached-dataset"),
                samples,
                &dataset,
            ),
            Err(OperatorDatasetError::DatasetDigestMismatch)
        );
    }
}
