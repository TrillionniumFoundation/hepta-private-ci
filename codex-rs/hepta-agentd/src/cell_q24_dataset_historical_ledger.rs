//! A Dataset view backed only by the actual complete Root receipt and current
//! recipient trust. No Ledger writer or consumer-side file is reopened.

use std::io;

use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;

use super::*;
use crate::root_historical_ledger_data::RootHistoricalLedgerReadDataV1;
use crate::root_historical_task_read_client::OriginalHistoricalLearningTrustV1;
use crate::root_historical_task_read_client::OriginalHistoricalTaskReadReceiptV1;

impl HistoricalDatasetLedgerV1 {
    pub(crate) fn capture_original(
        receipt: Arc<OriginalHistoricalTaskReadReceiptV1>,
        trust: Arc<OriginalHistoricalLearningTrustV1>,
        tasks: Vec<CellQ24DatasetTaskV1>,
    ) -> Result<Arc<Self>, Error> {
        OriginalHistoricalLearningTrustV1::require_original_receipt(&trust, &receipt)?;
        if tasks.len() != 1 {
            return Err(Error::Binding("one complete Root historical task required"));
        }
        for task in &tasks {
            CellQ24DatasetTaskV1::require_historical_receipt(task, &receipt)?;
        }
        let ledger = Arc::new(Self {
            receipt,
            trust,
            tasks,
        });
        ledger.with_current(|data, _, _, _| {
            RootHistoricalLedgerReadDataV1::read_snapshot(data).map(|_| ())
        })?;
        Ok(ledger)
    }

    pub(crate) fn initial_snapshot(&self) -> &LearningIterationSnapshotV1 {
        self.trust.initial_snapshot()
    }

    pub(crate) fn tasks(&self) -> &[CellQ24DatasetTaskV1] {
        &self.tasks
    }

    /// Immutable data from tasks already checked against this exact receipt.
    /// Consumers use it only inside, or before, the mandatory current read.
    pub(crate) fn original_task_data(
        &self,
    ) -> Vec<(CircuitTaskSourcePublicationV1, CellDecisionReceiptV1)> {
        self.tasks
            .iter()
            .map(|task| (task.publication.clone(), task.decision.clone()))
            .collect()
    }

    pub(crate) fn with_current<T>(
        &self,
        action: impl FnOnce(
            &RootHistoricalLedgerReadDataV1,
            &LearningEvidenceVerifierV1,
            &TrustedLearningSignerV1,
            u64,
        ) -> io::Result<T>,
    ) -> io::Result<T> {
        OriginalHistoricalLearningTrustV1::require_original_receipt(&self.trust, &self.receipt)?;
        OriginalHistoricalLearningTrustV1::with_current_trust(&self.trust, action)
    }
}

impl CellQ24TrainingBatchV1 {
    pub(crate) fn from_original_historical_dataset(
        ledger: Arc<HistoricalDatasetLedgerV1>,
        frozen: LedgerSnapshot,
        receipt: DatasetSnapshotReceiptV3,
        evidence: SignedLearningEvidenceV1,
        projection: CellQ24DatasetProjectionV1,
    ) -> Result<Self, Error> {
        let source = Arc::new(OriginalDataset {
            tasks: ledger.tasks.clone(),
            ledger: OriginalDatasetLedgerV1::Historical(ledger),
            frozen,
            receipt,
            evidence,
            projection,
        });
        let mut batch = source.materialize()?;
        batch.source = Some(source);
        Ok(batch)
    }
}

impl OriginalDataset {
    fn materialize_historical(
        &self,
        ledger: &HistoricalDatasetLedgerV1,
    ) -> Result<CellQ24TrainingBatchV1, Error> {
        Ok(HistoricalDatasetLedgerV1::with_current(
            ledger,
            |data, verifier, evaluator, observed_at| {
                let current = RootHistoricalLedgerReadDataV1::read_snapshot(data)?;
                if current != self.frozen {
                    return Err(io::Error::other(
                        "historical Dataset cut differs from actual Root image",
                    ));
                }
                let plan = DatasetFreezePlanV2 {
                    snapshot_id: self.receipt.snapshot.snapshot_id.clone(),
                    objective_digest: self.receipt.snapshot.objective_digest,
                    inclusion_policy_digest: self
                        .projection
                        .inclusion_policy_digest()
                        .map_err(io::Error::other)?,
                };
                let payload =
                    dataset_freeze_signing_payload_v2(&current, &plan).map_err(io::Error::other)?;
                let verified = verifier
                    .verify(
                        LearningEvidenceRoleV1::Evaluator,
                        &self.evidence,
                        &payload,
                        observed_at,
                    )
                    .map_err(io::Error::other)?;
                if verified.principal() != &evaluator.principal
                    || verified.controller_id() != &evaluator.controller_id
                {
                    return Err(io::Error::other(
                        "Dataset freeze differs from fixed current Root Evaluator",
                    ));
                }
                if freeze_dataset_from_ledger(
                    &current,
                    plan,
                    verified.principal().clone(),
                    observed_at,
                )
                .map_err(io::Error::other)?
                    != self.receipt
                {
                    return Err(io::Error::other(
                        "current authenticated historical Dataset freeze differs",
                    ));
                }
                let records =
                    LedgerSnapshot::read_dataset_records(&current, &self.receipt, observed_at)
                        .map_err(io::Error::other)?;
                // These tasks were captured with this exact opaque receipt. Both
                // surrounding Root reads compare the full publication and Cell
                // data too; no independent cached success or second file IO is used.
                let tasks = self
                    .tasks
                    .iter()
                    .map(|task| (task.publication.clone(), task.decision.clone()))
                    .collect::<Vec<_>>();
                project_original_q24_dataset_v1(
                    &current,
                    &self.receipt,
                    &self.projection,
                    &records,
                    &tasks,
                    observed_at,
                )
                .map_err(io::Error::other)
            },
        )?)
    }
}
