//! Bind the existing once-only freeze owner to the current Root Evaluator.
//! Only its supplied original key may sign; no root key or issuer is minted.

use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use ed25519_dalek::SigningKey;

use super::*;

impl CellQ24DatasetFreezePreparationV1 {
    pub(crate) fn original_historical_freeze_config(
        &self,
        maximum_signature_lifetime_seconds: u64,
    ) -> Result<OriginalCellQ24DatasetFreezeSigningConfigV1, Error> {
        let OriginalDatasetLedgerV1::Historical(ledger) = &self.ledger else {
            return Err(Error::Binding(
                "current historical freeze authority required",
            ));
        };
        self.with_historical_cut(ledger, |_, _, verifier, evaluator, _| {
            if !(1..=86_400).contains(&maximum_signature_lifetime_seconds) {
                return Err(Error::Binding("original freeze signature lifetime"));
            }
            Ok(OriginalCellQ24DatasetFreezeSigningConfigV1 {
                signer: evaluator.clone(),
                verifier: verifier.clone(),
                maximum_signature_lifetime_seconds,
            })
        })
    }

    pub(super) fn observed_unix_seconds(&self) -> Result<u64, Error> {
        match &self.ledger {
            OriginalDatasetLedgerV1::Live(_) => now(),
            OriginalDatasetLedgerV1::Historical(ledger) => {
                Ok(HistoricalDatasetLedgerV1::original_unix_seconds(ledger)?)
            }
        }
    }

    pub(super) fn validate_historical_freezer(
        &self,
        ledger: &HistoricalDatasetLedgerV1,
        config: &OriginalCellQ24DatasetFreezeSigningConfigV1,
        key: &SigningKey,
        operation: &OriginalDatasetOperationV1<'_>,
    ) -> Result<ProductEvaluationExecutionKeyV1, Error> {
        CellQ24DatasetFreezePreparationV1::with_historical_cut_in_operation(
            self,
            ledger,
            operation,
            |snapshot, binding, verifier, evaluator, observed_at| {
                if config.signer != *evaluator
                    || config.verifier.trust_digest() != verifier.trust_digest()
                    || config.verifier.scope_digest() != verifier.scope_digest()
                    || config.verifier.objective_digest()
                        != self.config.request.envelope.objective_digest
                    || key.verifying_key().to_bytes() != evaluator.verifying_key
                    || !(1..=86_400).contains(&config.maximum_signature_lifetime_seconds)
                {
                    return Err(Error::Binding(
                        "original current Root freeze signing configuration",
                    ));
                }
                verifier.require_signer_binding(
                    LearningEvidenceRoleV1::Evaluator,
                    evaluator,
                    observed_at,
                )?;
                config.verifier.require_signer_binding(
                    LearningEvidenceRoleV1::Evaluator,
                    &config.signer,
                    observed_at,
                )?;
                let payload = dataset_freeze_signing_payload_v2(snapshot, &self.plan()?)?;
                let identity = crate::original_q24_dataset_preparation_identity_v1(
                    ledger.initial_snapshot().head_digest,
                    binding,
                    &payload,
                    self.config.baseline.effective_weights_digest(),
                    self.config.head,
                    self.config.rule,
                );
                Ok(crate::original_q24_dataset_freeze_execution_key_v1(
                    &self.config.request.operation_id,
                    identity,
                    verifier.trust_digest(),
                    evaluator,
                    config.maximum_signature_lifetime_seconds,
                ))
            },
        )
    }
}
