//! Borrow repeated Dataset checks within one actual current operation. Live
//! owners keep their existing physical checks; historical checks share only
//! the Root observation enclosed by this operation's real pre/post reads.

use super::*;
use crate::root_historical_task_read_client::OriginalHistoricalLearningTrustV1;
use crate::root_historical_task_read_client::OriginalHistoricalOperationV1;

enum DatasetOperationKind<'read> {
    Live,
    Historical(&'read OriginalHistoricalOperationV1<'read>),
}

pub(crate) struct OriginalDatasetOperationV1<'read> {
    kind: DatasetOperationKind<'read>,
}

enum OperationError<E> {
    Source(Error),
    Work(E),
}

impl OriginalDatasetLedgerV1 {
    pub(crate) fn with_original_ledger_operation<T, E>(
        &self,
        action: impl for<'read> FnOnce(&OriginalDatasetOperationV1<'read>) -> Result<T, E>,
    ) -> Result<Result<T, E>, Error> {
        match self {
            Self::Live(_) => Ok(action(&OriginalDatasetOperationV1 {
                kind: DatasetOperationKind::Live,
            })),
            Self::Historical(ledger) => {
                OriginalHistoricalLearningTrustV1::require_original_receipt(
                    &ledger.trust,
                    &ledger.receipt,
                )?;
                Ok(OriginalHistoricalLearningTrustV1::with_original_operation(
                    &ledger.trust,
                    |read| {
                        action(&OriginalDatasetOperationV1 {
                            kind: DatasetOperationKind::Historical(read),
                        })
                    },
                )?)
            }
        }
    }
}

impl OriginalDatasetOperationV1<'_> {
    pub(crate) fn read_historical<T>(
        &self,
        ledger: &HistoricalDatasetLedgerV1,
        action: impl FnOnce(
            &crate::root_historical_ledger_data::RootHistoricalLedgerReadDataV1,
            &codex_hepta_learning_ledger::LearningEvidenceVerifierV1,
            &codex_hepta_learning_ledger::TrustedLearningSignerV1,
            u64,
        ) -> std::io::Result<T>,
    ) -> std::io::Result<T> {
        let DatasetOperationKind::Historical(read) = &self.kind else {
            return Err(std::io::Error::other("historical operation borrow absent"));
        };
        OriginalHistoricalOperationV1::read_for(read, &ledger.trust, &ledger.receipt, action)
    }

    pub(crate) fn require_batch(&self, batch: &CellQ24TrainingBatchV1) -> Result<(), Error> {
        let source = batch
            .source
            .as_ref()
            .ok_or(Error::Binding("original Dataset capability absent"))?;
        let observed = match (&source.ledger, &self.kind) {
            (OriginalDatasetLedgerV1::Live(ledger), DatasetOperationKind::Live) => {
                source.materialize_live(ledger)?
            }
            (OriginalDatasetLedgerV1::Historical(ledger), DatasetOperationKind::Historical(_)) => {
                source.materialize_historical_in_operation(ledger, self)?
            }
            (OriginalDatasetLedgerV1::Live(_), DatasetOperationKind::Historical(_))
            | (OriginalDatasetLedgerV1::Historical(_), DatasetOperationKind::Live) => {
                return Err(Error::Binding("original Dataset operation owner differs"));
            }
        };
        if observed.encoded != batch.encoded || observed.digest != batch.digest {
            return Err(Error::Binding("original materialization changed"));
        }
        Ok(())
    }
}

impl CellQ24TrainingBatchV1 {
    pub(crate) fn with_original_dataset_operation<T, E>(
        &self,
        action: impl for<'read> FnOnce(&OriginalDatasetOperationV1<'read>) -> Result<T, E>,
    ) -> Result<Result<T, E>, Error> {
        let source = self
            .source
            .as_ref()
            .ok_or(Error::Binding("original Dataset capability absent"))?;
        let result = source.ledger.with_original_ledger_operation(|operation| {
            operation
                .require_batch(self)
                .map_err(OperationError::Source)?;
            let result = action(operation).map_err(OperationError::Work);
            operation
                .require_batch(self)
                .map_err(OperationError::Source)?;
            result
        })?;
        match result {
            Ok(value) => Ok(Ok(value)),
            Err(OperationError::Work(error)) => Ok(Err(error)),
            Err(OperationError::Source(error)) => Err(error),
        }
    }
}
