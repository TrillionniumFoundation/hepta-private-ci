//! Preparation from an authenticated current-recipient Root receipt. Source
//! and Ledger images are immutable data; the held original route admits use.

use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;

use super::*;
use crate::root_historical_ledger_data::RootHistoricalLedgerReadDataV1;
use crate::root_historical_task_read_client::OriginalHistoricalLearningTrustV1;
use crate::root_historical_task_read_client::OriginalHistoricalTaskReadReceiptV1;

impl CellQ24DatasetFreezePreparationV1 {
    pub(crate) fn capture_historical(
        config: CellQ24LearningPreparationConfigV1,
        receipt: Arc<OriginalHistoricalTaskReadReceiptV1>,
        trust: Arc<OriginalHistoricalLearningTrustV1>,
        task: CellQ24DatasetTaskV1,
    ) -> Result<Self, Error> {
        let ledger = HistoricalDatasetLedgerV1::capture_original(receipt, trust, vec![task])?;
        let original = OriginalDatasetLedgerV1::Historical(Arc::clone(&ledger));
        original.with_original_ledger_operation(|operation| {
            Self::capture_historical_in_operation(config, ledger, operation)
        })?
    }

    /// Task capture, ledger binding and immutable preparation are one
    /// synchronous construction from the original current Root operation.
    pub(crate) fn capture_original_historical_task(
        config: CellQ24LearningPreparationConfigV1,
        receipt: Arc<OriginalHistoricalTaskReadReceiptV1>,
        trust: Arc<OriginalHistoricalLearningTrustV1>,
        client: &Arc<crate::root_historical_task_read_client::RootHistoricalTaskReadClientV1>,
        session: &crate::AgentdRootAuthoritySession,
    ) -> Result<Self, Error> {
        OriginalHistoricalLearningTrustV1::require_original_receipt(&trust, &receipt)?;
        OriginalHistoricalLearningTrustV1::with_original_operation(&trust, |read| {
            let ledger = HistoricalDatasetLedgerV1::capture_original_task_in_operation(
                receipt,
                Arc::clone(&trust),
                client,
                session,
                read,
            )?;
            let operation = OriginalDatasetOperationV1::borrow_original_historical(read);
            Self::capture_historical_in_operation(config, ledger, &operation)
        })?
    }

    fn capture_historical_in_operation(
        config: CellQ24LearningPreparationConfigV1,
        ledger: Arc<HistoricalDatasetLedgerV1>,
        operation: &OriginalDatasetOperationV1<'_>,
    ) -> Result<Self, Error> {
        let operation: &OriginalDatasetOperationV1<'_> = operation;
        let (snapshot, frontier) =
            operation.read_historical(&ledger, |data, _, _, observed_at| {
                require_historical_configuration(&config, &ledger).map_err(io::Error::other)?;
                if observed_at >= config.request.envelope.expiry_unix_seconds {
                    return Err(io::Error::other("new historical preparation deadline"));
                }
                Ok((
                    RootHistoricalLedgerReadDataV1::read_snapshot(data)?,
                    data.ledger_cut()?.frontier,
                ))
            })?;
        let preparation = Self {
            config,
            tasks: ledger.tasks().to_vec(),
            ledger: OriginalDatasetLedgerV1::Historical(Arc::clone(&ledger)),
            snapshot,
            frontier,
        };
        // Snapshot/configuration and the pure signing payload belong to
        // this one preparation. The actual Root post-read still precedes
        // returning it; no observation is retained for another operation.
        preparation.with_historical_cut_in_operation(
            &ledger,
            operation,
            |snapshot, _, _, _, _| {
                dataset_freeze_signing_payload_v2(snapshot, &preparation.plan()?)?;
                Ok(())
            },
        )?;
        Ok(preparation)
    }

    pub(super) fn with_historical_cut<T>(
        &self,
        ledger: &HistoricalDatasetLedgerV1,
        action: impl FnOnce(
            &LedgerSnapshot,
            Digest32,
            &LearningEvidenceVerifierV1,
            &TrustedLearningSignerV1,
            u64,
        ) -> Result<T, Error>,
    ) -> Result<T, Error> {
        OriginalDatasetLedgerV1::with_original_ledger_operation(&self.ledger, |operation| {
            self.with_historical_cut_in_operation(ledger, operation, action)
        })?
    }

    pub(super) fn with_historical_cut_in_operation<T>(
        &self,
        ledger: &HistoricalDatasetLedgerV1,
        operation: &OriginalDatasetOperationV1<'_>,
        action: impl FnOnce(
            &LedgerSnapshot,
            Digest32,
            &LearningEvidenceVerifierV1,
            &TrustedLearningSignerV1,
            u64,
        ) -> Result<T, Error>,
    ) -> Result<T, Error> {
        Ok(OriginalDatasetOperationV1::read_historical(
            operation,
            ledger,
            |data, verifier, evaluator, observed_at| {
                require_historical_configuration(&self.config, ledger).map_err(io::Error::other)?;
                let current = RootHistoricalLedgerReadDataV1::read_snapshot(data)?;
                let cut = data.ledger_cut()?;
                if current != self.snapshot || cut.frontier != self.frontier {
                    return Err(io::Error::other("original historical freeze cut changed"));
                }
                action(&current, cut.binding, verifier, evaluator, observed_at)
                    .map_err(io::Error::other)
            },
        )?)
    }

    pub(super) fn identity_historical(
        &self,
        ledger: &HistoricalDatasetLedgerV1,
    ) -> Result<Digest32, Error> {
        self.with_historical_cut(ledger, |snapshot, binding, _, _, _| {
            let payload = dataset_freeze_signing_payload_v2(snapshot, &self.plan()?)?;
            Ok(crate::original_q24_dataset_preparation_identity_v1(
                ledger.initial_snapshot().head_digest,
                binding,
                &payload,
                self.config.baseline.effective_weights_digest(),
                self.config.head,
                self.config.rule,
            ))
        })
    }

    pub(super) fn signing_payload_historical(
        &self,
        ledger: &HistoricalDatasetLedgerV1,
    ) -> Result<Vec<u8>, Error> {
        self.with_historical_cut(ledger, |snapshot, _, _, _, _| {
            Ok(dataset_freeze_signing_payload_v2(snapshot, &self.plan()?)?)
        })
    }

    pub(super) fn validate_authorization_historical(
        &self,
        ledger: &HistoricalDatasetLedgerV1,
        authorization: &SignedLearningEvidenceV1,
    ) -> Result<CellQ24FrozenDatasetV1, Error> {
        OriginalDatasetLedgerV1::with_original_ledger_operation(&self.ledger, |operation| {
            self.validate_authorization_historical_in_operation(ledger, authorization, operation)
        })?
    }

    pub(super) fn validate_authorization_historical_in_operation(
        &self,
        ledger: &HistoricalDatasetLedgerV1,
        authorization: &SignedLearningEvidenceV1,
        operation: &OriginalDatasetOperationV1<'_>,
    ) -> Result<CellQ24FrozenDatasetV1, Error> {
        self.with_historical_cut_in_operation(
            ledger,
            operation,
            |snapshot, _, verifier, evaluator, observed_at| {
                let plan = self.plan()?;
                let payload = dataset_freeze_signing_payload_v2(snapshot, &plan)?;
                let verified = verifier.verify(
                    LearningEvidenceRoleV1::Evaluator,
                    authorization,
                    &payload,
                    observed_at,
                )?;
                if verified.principal() != &evaluator.principal
                    || verified.controller_id() != &evaluator.controller_id
                {
                    return Err(Error::Binding(
                        "freeze is not signed by the fixed current Root Evaluator",
                    ));
                }
                let receipt = freeze_dataset_from_ledger(
                    snapshot,
                    plan,
                    verified.principal().clone(),
                    observed_at,
                )?;
                let records =
                    LedgerSnapshot::read_dataset_records(snapshot, &receipt, observed_at)?;
                // Validation needs the shared data algorithm, not a temporary
                // source capability or another network/physical observation.
                crate::project_original_q24_dataset_v1(
                    snapshot,
                    &receipt,
                    &self.config.projection,
                    &records,
                    &ledger.original_task_data(),
                    observed_at,
                )?;
                Ok(CellQ24FrozenDatasetV1 {
                    snapshot: snapshot.clone(),
                    receipt,
                    authorization: authorization.clone(),
                })
            },
        )
    }

    pub(super) fn materialize_historical(
        self,
        authorization: SignedLearningEvidenceV1,
    ) -> Result<CellQ24PreparedLearningV1, Error> {
        let OriginalDatasetLedgerV1::Historical(ledger) = &self.ledger else {
            return Err(Error::Binding("original historical Dataset required"));
        };
        let ledger = Arc::clone(ledger);
        let original = OriginalDatasetLedgerV1::Historical(Arc::clone(&ledger));
        original.with_original_ledger_operation(|operation| {
            let frozen = self.validate_authorization_historical_in_operation(
                &ledger,
                &authorization,
                operation,
            )?;
            // Authorization, projection and immutable prepared facts are one
            // synchronous construction. Each checks the exact same borrowed
            // receipt; the enclosing operation performs both physical reads.
            CellQ24PreparedLearningV1::from_historical(
                self.config,
                Arc::clone(&ledger),
                frozen,
                operation,
            )
        })?
    }
}

pub(super) fn require_historical_configuration(
    config: &CellQ24LearningPreparationConfigV1,
    ledger: &HistoricalDatasetLedgerV1,
) -> Result<CircuitTaskSourcePublicationV1, Error> {
    let initial =
        LearningIterationCoordinatorV1::new(config.request.clone(), config.owners.clone())?;
    if initial.snapshot() != ledger.initial_snapshot() {
        return Err(Error::Binding(
            "preparation differs from actual current Root recipient",
        ));
    }
    let publications = ledger
        .original_task_data()
        .into_iter()
        .map(|(publication, _)| publication)
        .collect::<Vec<_>>();
    require_configuration_data(config, &publications)
}
