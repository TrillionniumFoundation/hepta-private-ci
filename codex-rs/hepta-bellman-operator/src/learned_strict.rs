//! Strict admission wrapper for the simplest-sufficient tabular operator.
//!
//! The original V1 functions remain available. This additive surface rejects
//! duplicate underlying evidence even when callers relabel samples, and uses
//! the artifact's canonical cell ordering for binary lookup after an O(n)
//! validation on every call. Use LoadedTabularOperatorV1 for once-validated
//! persisted candidates and O(log n) repeated lookups.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_ledger::DatasetReceiptError;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::verify_dataset_snapshot_receipt_v3;
use codex_hepta_types::StableId;

use crate::LearnedOperatorError;
use crate::TabularOperatorArtifactV1;
use crate::TabularOperatorPlanV1;
use crate::TabularOperatorPredictionV1;
use crate::fit_tabular_operator;

pub fn fit_tabular_operator_strict_v2(
    plan: TabularOperatorPlanV1,
) -> Result<TabularOperatorArtifactV1, StrictLearnedOperatorError> {
    let mut evidence = plan
        .samples
        .iter()
        .map(|sample| sample.evidence_digest)
        .collect::<Vec<_>>();
    evidence.sort_unstable();
    if evidence
        .windows(2)
        .any(|adjacent| adjacent[0] == adjacent[1])
    {
        return Err(StrictLearnedOperatorError::DuplicateEvidence);
    }
    Ok(fit_tabular_operator(plan)?)
}

/// Qualification entrypoint for a strict tabular fit. The frozen V3 dataset
/// receipt is independently recomputed before its identity is accepted, and
/// every training row must name evidence contained in that exact snapshot.
/// Callers cannot pair arbitrary rows with an unrelated dataset digest.
pub fn fit_tabular_operator_from_dataset_receipt_v3(
    mut plan: TabularOperatorPlanV1,
    dataset: &DatasetSnapshotReceiptV3,
    now: u64,
) -> Result<TabularOperatorArtifactV1, StrictLearnedOperatorError> {
    verify_dataset_snapshot_receipt_v3(dataset, now)?;
    if plan.objective_digest != dataset.snapshot.objective_digest {
        return Err(StrictLearnedOperatorError::DatasetBindingMismatch);
    }
    if plan.dataset_digest != dataset.snapshot.dataset_digest {
        return Err(StrictLearnedOperatorError::DatasetBindingMismatch);
    }
    let admitted = dataset
        .snapshot
        .source_record_digests
        .iter()
        .copied()
        .collect::<BTreeSet<_>>();
    if plan
        .samples
        .iter()
        .any(|sample| !admitted.contains(&sample.evidence_digest))
    {
        return Err(StrictLearnedOperatorError::EvidenceOutsideDataset);
    }
    // Freeze the already verified identity before handing the pure plan to the
    // compatibility core. This assignment is idempotent but makes the binding
    // explicit at the handoff boundary.
    plan.dataset_digest = dataset.snapshot.dataset_digest;
    fit_tabular_operator_strict_v2(plan)
}

pub fn predict_tabular_operator_indexed_v2(
    artifact: &TabularOperatorArtifactV1,
    sensor_id: &StableId,
    action_id: &StableId,
) -> Result<TabularOperatorPredictionV1, StrictLearnedOperatorError> {
    if artifact.cells.windows(2).any(|adjacent| {
        (&adjacent[0].sensor_id, &adjacent[0].action_id)
            >= (&adjacent[1].sensor_id, &adjacent[1].action_id)
    }) {
        return Err(StrictLearnedOperatorError::NonCanonicalArtifact);
    }
    let index = artifact
        .cells
        .binary_search_by(|cell| (&cell.sensor_id, &cell.action_id).cmp(&(sensor_id, action_id)))
        .map_err(|_| StrictLearnedOperatorError::UnsupportedCell)?;
    let cell = &artifact.cells[index];
    Ok(TabularOperatorPredictionV1 {
        artifact_id: artifact.artifact_id.clone(),
        sensor_id: cell.sensor_id.clone(),
        action_id: cell.action_id.clone(),
        value: cell.mean_target,
        cell_evidence_digest: cell.evidence_digest,
        learned: true,
        synthetic: true,
        authority: codex_hepta_types::AuthorityPosture::DENY_ALL,
    })
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum StrictLearnedOperatorError {
    Learned(LearnedOperatorError),
    DatasetReceipt(DatasetReceiptError),
    DuplicateEvidence,
    DatasetBindingMismatch,
    EvidenceOutsideDataset,
    NonCanonicalArtifact,
    UnsupportedCell,
}

impl fmt::Display for StrictLearnedOperatorError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for StrictLearnedOperatorError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Learned(error) => Some(error),
            Self::DatasetReceipt(error) => Some(error),
            Self::DuplicateEvidence
            | Self::DatasetBindingMismatch
            | Self::EvidenceOutsideDataset
            | Self::NonCanonicalArtifact
            | Self::UnsupportedCell => None,
        }
    }
}

impl From<LearnedOperatorError> for StrictLearnedOperatorError {
    fn from(value: LearnedOperatorError) -> Self {
        Self::Learned(value)
    }
}

impl From<DatasetReceiptError> for StrictLearnedOperatorError {
    fn from(value: DatasetReceiptError) -> Self {
        Self::DatasetReceipt(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_types::Digest32;
    use codex_hepta_types::FixedQ32;
    use codex_hepta_types::Generation;

    use crate::TabularOperatorSampleV1;

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("valid test id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn plan() -> TabularOperatorPlanV1 {
        TabularOperatorPlanV1 {
            artifact_id: id("artifact"),
            producer_id: id("producer"),
            generation: Generation::new(1).expect("valid generation"),
            objective_digest: digest("objective"),
            dataset_digest: digest("dataset"),
            sensor_core_digest: digest("sensor-core"),
            training_profile_digest: digest("profile"),
            minimum_samples_per_cell: 1,
            sensor_ids: vec![id("sensor-b"), id("sensor-a")],
            action_ids: vec![id("action-b"), id("action-a")],
            samples: vec![
                sample("s-aa", "sensor-a", "action-a", 10, "e-aa"),
                sample("s-ab", "sensor-a", "action-b", 20, "e-ab"),
                sample("s-ba", "sensor-b", "action-a", 30, "e-ba"),
                sample("s-bb", "sensor-b", "action-b", 40, "e-bb"),
            ],
        }
    }

    fn sample(
        sample_id: &str,
        sensor_id: &str,
        action_id: &str,
        value: i64,
        evidence: &str,
    ) -> TabularOperatorSampleV1 {
        TabularOperatorSampleV1 {
            sample_id: id(sample_id),
            sensor_id: id(sensor_id),
            action_id: id(action_id),
            target: FixedQ32::from_raw(value),
            evidence_digest: digest(evidence),
        }
    }

    #[test]
    fn op_05_strict_fit_rejects_relabelled_duplicate_evidence() {
        let mut duplicate = plan();
        duplicate.samples[1].evidence_digest = duplicate.samples[0].evidence_digest;
        assert_eq!(
            fit_tabular_operator_strict_v2(duplicate),
            Err(StrictLearnedOperatorError::DuplicateEvidence)
        );
    }

    #[test]
    fn op_05_indexed_prediction_uses_canonical_grid() {
        let artifact = fit_tabular_operator_strict_v2(plan()).expect("strict fit succeeds");
        let prediction =
            predict_tabular_operator_indexed_v2(&artifact, &id("sensor-b"), &id("action-a"))
                .expect("supported cell");
        assert_eq!(prediction.value, FixedQ32::from_raw(30));
        assert!(prediction.synthetic);
        assert!(!prediction.authority.grants_any());
    }

    #[test]
    fn op_05_dataset_receipt_binds_strict_training_rows() {
        use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
        use codex_hepta_learning_ledger::DatasetFreezeRequestV1;
        use codex_hepta_learning_ledger::freeze_dataset_receipt_v3;

        let receipt = freeze_dataset_receipt_v3(
            DatasetFreezeRequestV1 {
                snapshot_id: id("snapshot"),
                producer: AuthenticatedPrincipalV1 {
                    principal_id: id("dataset-owner"),
                    credential_chain_digest: digest("dataset-credential"),
                    signing_key_digest: digest("dataset-key"),
                    scope_digest: digest("dataset-scope"),
                    authority_epoch: 3,
                    authenticated_at: 10,
                    expires_at: 100,
                },
                ledger_head_digest: digest("ledger-head"),
                objective_digest: digest("objective"),
                eligible_frontier: 4,
                outcome_watermark: 40,
                correction_cut_digest: digest("correction-cut"),
                revocation_cut_digest: digest("revocation-cut"),
                inclusion_policy_digest: digest("inclusion-policy"),
                source_record_digests: vec![
                    digest("e-aa"),
                    digest("e-ab"),
                    digest("e-ba"),
                    digest("e-bb"),
                ],
                pending_outcomes: 0,
                censored_outcomes: 0,
            },
            50,
        )
        .expect("frozen dataset");

        let mut bound = plan();
        bound.dataset_digest = receipt.snapshot.dataset_digest;
        fit_tabular_operator_from_dataset_receipt_v3(bound.clone(), &receipt, 50)
            .expect("bound strict fit");

        let mut detached = bound.clone();
        detached.samples[0].evidence_digest = digest("detached-evidence");
        assert_eq!(
            fit_tabular_operator_from_dataset_receipt_v3(detached, &receipt, 50),
            Err(StrictLearnedOperatorError::EvidenceOutsideDataset)
        );

        bound.dataset_digest = digest("detached-dataset");
        assert_eq!(
            fit_tabular_operator_from_dataset_receipt_v3(bound, &receipt, 50),
            Err(StrictLearnedOperatorError::DatasetBindingMismatch)
        );
    }

}
