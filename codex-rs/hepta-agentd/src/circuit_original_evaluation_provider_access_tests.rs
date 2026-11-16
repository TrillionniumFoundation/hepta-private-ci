//! Test-only wall-clock fixture. All material and release methods below are
//! the same private methods used by the production SystemTime entry points.
use super::*;
use pretty_assertions::assert_eq;

pub(crate) struct CohortAt {
    pub(crate) original: OriginalCircuitEvaluationCohortV1,
    pub(crate) at: u64,
}
impl CohortAt {
    pub(crate) fn read(
        owners: OriginalCircuitEvaluationSourceOwnersV1,
        config: OriginalCircuitEvaluationCohortConfigV1,
        at: u64,
    ) -> Result<Self, Error> {
        Ok(Self {
            original: OriginalCircuitEvaluationCohortV1::read_original_with_clock(
                owners,
                config,
                || Ok(at),
            )?,
            at,
        })
    }

    pub(crate) fn current(&mut self) -> Result<Digest32, Error> {
        self.original
            .read_current_with_clock(|| Ok(self.at))
            .map(|data| data.manifest)
    }

    pub(crate) fn bytes(&mut self) -> anyhow::Result<[Vec<u8>; 2]> {
        Ok(self
            .original
            .owners
            .ledger
            .qualification_file_bytes(/*maximum_bytes*/ 8 * 1024 * 1024)?)
    }

    pub(crate) fn validate_signature(
        &self,
        signed: &SignedLearningEvidenceV1,
        freeze: bool,
    ) -> anyhow::Result<()> {
        let (role, payload) = if freeze {
            (
                codex_hepta_learning_ledger::LearningEvidenceRoleV1::Evaluator,
                codex_hepta_learning_ledger::dataset_freeze_signing_payload_v2(
                    &self.original.owners.ledger.snapshot()?,
                    &self.original.config.freeze_plan,
                )?,
            )
        } else {
            (
                codex_hepta_learning_ledger::LearningEvidenceRoleV1::Generator,
                codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1(
                    &self.original.config.training.receipts[2],
                )?,
            )
        };
        self.original
            .config
            .verifier
            .verify(role, signed, &payload, self.at)?;
        Ok(())
    }

    pub(crate) fn resign_freeze(&mut self, signature: SignedLearningEvidenceV1) {
        self.original.config.freeze_evidence = signature;
    }

    pub(crate) fn resign_training(&mut self, signature: SignedLearningEvidenceV1) {
        self.original.config.training_evidence = signature;
    }

    pub(crate) fn original_config(&self) -> &OriginalCircuitEvaluationCohortConfigV1 {
        &self.original.config
    }

    pub(crate) fn consume(self, plan: CellEvaluationPlanV1) -> Result<ProviderAt, Error> {
        let at = self.at;
        let original = self.original.into_final_holdout_provider(plan)?;
        assert_eq!(original.release_attempted, false);
        Ok(ProviderAt {
            original,
            at,
            manifest_calls: 0,
            releases: 0,
        })
    }

    pub(crate) fn readonly(
        self,
        plan: CellEvaluationPlanV1,
    ) -> Result<OriginalCircuitEvaluationCohortReadbackV1, Error> {
        OriginalCircuitEvaluationCohortReadbackV1::fixture_cold(self.original, plan, self.at)
    }
}

pub(crate) struct ProviderAt {
    original: OriginalCircuitFinalHoldoutProviderV1,
    at: u64,
    pub(crate) manifest_calls: usize,
    pub(crate) releases: usize,
}
impl ProviderAt {
    pub(crate) fn into_original_readback(
        self,
    ) -> Result<OriginalCircuitEvaluationCohortReadbackV1, Error> {
        Ok(self.original.into_original_readback()?.fixture_at(self.at))
    }
}
impl FinalHoldoutProviderV1 for ProviderAt {
    fn manifest_digest(&mut self) -> Result<Digest32, ProductProviderErrorV1> {
        self.manifest_calls += 1;
        self.original.manifest_with_clock(|| Ok(self.at))
    }
    fn release_after_consumption(
        &mut self,
        receipt: &FinalHoldoutJournalReceiptV1,
    ) -> Result<TemporalComparisonInputsV1, ProductProviderErrorV1> {
        self.releases += 1;
        self.original.release_with_clock(receipt, || Ok(self.at))
    }
}

use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
