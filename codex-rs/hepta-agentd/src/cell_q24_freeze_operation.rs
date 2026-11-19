//! One current operation around original freeze authorization. The borrowed
//! view cannot escape its callback or replace the original preparation owner.

use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use codex_hepta_neuron::AnchorWitnessStore;
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
    #[track_caller]
    pub(super) fn with_original_freeze_operation<T, E>(
        &self,
        action: impl for<'read> FnOnce(&OriginalFreezePreparationReadV1<'read>) -> Result<T, E>,
    ) -> Result<Result<T, E>, Error> {
        let caller = std::panic::Location::caller();
        let _ = std::io::Write::write_fmt(
            &mut std::io::stderr(),
            format_args!(
                "daemon_stage=historical.trace.freeze caller={}:{}\n",
                caller.file(),
                caller.line(),
            ),
        );
        let result =
            OriginalDatasetLedgerV1::with_original_ledger_operation(&self.ledger, |operation| {
                let read = OriginalFreezePreparationReadV1 {
                    preparation: self,
                    operation,
                };
                OriginalFreezePreparationReadV1::revalidate_source(&read)
                    .map_err(FreezeOperationError::Source)?;
                let result = action(&read).map_err(FreezeOperationError::Work);
                OriginalFreezePreparationReadV1::revalidate_source(&read)
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
        OriginalFreezePreparationReadV1::revalidate_source(self)
    }

    fn revalidate_source(&self) -> Result<(), Error> {
        match &self.preparation.ledger {
            OriginalDatasetLedgerV1::Live(_) => {
                CellQ24DatasetFreezePreparationV1::revalidate_source(self.preparation)
            }
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

impl CellQ24DatasetFreezePreparationV1 {
    /// The original descriptor/key checks and their Root postread have already
    /// completed. One synchronous original owner now opens its journal, signs
    /// or reads back once, and materializes that exact Dataset. The same actual
    /// ledger operation performs its final Root read even when this work fails.
    pub(crate) fn materialize_original_historical_owner<W: AnchorWitnessStore>(
        self,
        file: std::fs::File,
        witness: W,
        config: OriginalCellQ24DatasetFreezeSigningConfigV1,
        key: SigningKey,
        mode: crate::OriginalCellQ24LearningOpenV1,
    ) -> Result<CellQ24PreparedLearningV1, OriginalCellQ24DatasetFreezeErrorV1> {
        let OriginalDatasetLedgerV1::Historical(ledger) = &self.ledger else {
            return Err(Error::Binding("original historical freeze construction required").into());
        };
        let ledger = Arc::clone(ledger);
        let original = OriginalDatasetLedgerV1::Historical(Arc::clone(&ledger));
        original
            .with_original_ledger_operation(move |operation| {
                let frozen = {
                    let read = OriginalFreezePreparationReadV1 {
                        preparation: &self,
                        operation,
                    };
                    OriginalFreezePreparationReadV1::revalidate_source(&read)?;
                    let result: Result<
                        CellQ24FrozenDatasetV1,
                        OriginalCellQ24DatasetFreezeErrorV1,
                    > = (|| {
                        let mut owner = match mode {
                            crate::OriginalCellQ24LearningOpenV1::Create => {
                                OriginalCellQ24DatasetFreezeOwnerV1::create_in_operation(
                                    file, witness, &self, config, key, &read,
                                )
                            }
                            crate::OriginalCellQ24LearningOpenV1::Recover => {
                                OriginalCellQ24DatasetFreezeOwnerV1::recover_in_operation(
                                    file, witness, &self, config, key, &read,
                                )
                            }
                        }?;
                        let authorization =
                            OriginalCellQ24DatasetFreezeOwnerV1::authorize_in_operation(
                                &mut owner, &self, &read,
                            )?;
                        let frozen = read.validate_original_authorization(&authorization)?;
                        // Root's later independent freeze acknowledgement must
                        // still obtain the actual journal and witness locks.
                        drop(owner);
                        Ok(frozen)
                    })();
                    OriginalFreezePreparationReadV1::revalidate_source(&read)?;
                    result?
                };
                CellQ24PreparedLearningV1::from_historical(self.config, ledger, frozen, operation)
                    .map_err(OriginalCellQ24DatasetFreezeErrorV1::from)
            })
            .map_err(Error::from)?
    }
}
