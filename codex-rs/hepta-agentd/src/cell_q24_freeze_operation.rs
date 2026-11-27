//! One current operation around original freeze authorization. The borrowed
//! view cannot escape its callback or replace the original preparation owner.

use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use ed25519_dalek::SigningKey;

use super::*;

pub(super) struct OriginalFreezePreparationReadV1<'read> {
    preparation: &'read CellQ24DatasetFreezePreparationV1,
    operation: &'read OriginalDatasetOperationV1<'read>,
}

enum FreezeOperationError<E> {
    Source(Error),
    Work(E),
}

impl CellQ24DatasetFreezePreparationV1 {
    pub(super) fn with_original_freeze_operation<T, E>(
        &self,
        action: impl for<'read> FnOnce(&OriginalFreezePreparationReadV1<'read>) -> Result<T, E>,
    ) -> Result<Result<T, E>, Error> {
        let result =
            OriginalDatasetLedgerV1::with_original_ledger_operation(&self.ledger, |operation| {
                let read = OriginalFreezePreparationReadV1 {
                    preparation: self,
                    operation,
                };
                read.revalidate_source()
                    .map_err(FreezeOperationError::Source)?;
                let result = action(&read).map_err(FreezeOperationError::Work);
                read.revalidate_source()
                    .map_err(FreezeOperationError::Source)?;
                result
            })?;
        match result {
            Ok(value) => Ok(Ok(value)),
            Err(FreezeOperationError::Work(error)) => Ok(Err(error)),
            Err(FreezeOperationError::Source(error)) => Err(error),
        }
    }
}

impl OriginalFreezePreparationReadV1<'_> {
    pub(super) fn require_original_preparation(
        &self,
        preparation: &CellQ24DatasetFreezePreparationV1,
    ) -> Result<(), Error> {
        if !std::ptr::eq(self.preparation, preparation) {
            return Err(Error::Binding(
                "freeze operation borrowed another preparation",
            ));
        }
        self.revalidate_source()
    }

    fn revalidate_source(&self) -> Result<(), Error> {
        match &self.preparation.ledger {
            OriginalDatasetLedgerV1::Live(_) => self.preparation.revalidate_source(),
            OriginalDatasetLedgerV1::Historical(ledger) => {
                CellQ24DatasetFreezePreparationV1::with_historical_cut_in_operation(
                    self.preparation,
                    ledger,
                    self.operation,
                    |_, _, _, _, _| Ok(()),
                )
            }
        }
    }

    pub(super) fn original_signing_payload(&self) -> Result<Vec<u8>, Error> {
        match &self.preparation.ledger {
            OriginalDatasetLedgerV1::Live(_) => self.preparation.signing_payload(),
            OriginalDatasetLedgerV1::Historical(ledger) => {
                CellQ24DatasetFreezePreparationV1::with_historical_cut_in_operation(
                    self.preparation,
                    ledger,
                    self.operation,
                    |snapshot, _, _, _, _| {
                        Ok(dataset_freeze_signing_payload_v2(
                            snapshot,
                            &self.preparation.plan()?,
                        )?)
                    },
                )
            }
        }
    }

    pub(super) fn validate_original_authorization(
        &self,
        authorization: &SignedLearningEvidenceV1,
    ) -> Result<CellQ24FrozenDatasetV1, Error> {
        match &self.preparation.ledger {
            OriginalDatasetLedgerV1::Live(_) => {
                self.preparation.validate_authorization(authorization)
            }
            OriginalDatasetLedgerV1::Historical(ledger) => {
                CellQ24DatasetFreezePreparationV1::validate_authorization_historical_in_operation(
                    self.preparation,
                    ledger,
                    authorization,
                    self.operation,
                )
            }
        }
    }

    pub(super) fn original_freezer_key(
        &self,
        config: &OriginalCellQ24DatasetFreezeSigningConfigV1,
        key: &SigningKey,
    ) -> Result<ProductEvaluationExecutionKeyV1, Error> {
        let OriginalDatasetLedgerV1::Historical(ledger) = &self.preparation.ledger else {
            return Err(Error::Binding("historical freeze operation required"));
        };
        CellQ24DatasetFreezePreparationV1::validate_historical_freezer(
            self.preparation,
            ledger,
            config,
            key,
            self.operation,
        )
    }
}
