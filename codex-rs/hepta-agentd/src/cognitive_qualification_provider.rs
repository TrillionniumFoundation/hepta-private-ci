//! Read released outcomes only inside the original consume-before-release seam.
//! Acquisition is a separate durable reservation so independent custodians can
//! collect future outcomes before an observer/evaluator signs their statements.
use anyhow::{Result, ensure};
use codex_hepta_intelligence_eval as eval;
use codex_hepta_types::Digest32;

use crate::cognitive_materials_io::read_material;
use crate::cognitive_process_product::PinnedProductFileV1;
use crate::cognitive_qualification_wire::{CognitiveCollectedQualificationV1, CognitiveHoldoutReservationV1};

pub(super) struct CollectedInputsProviderV1 {
    pub material: PinnedProductFileV1,
    pub collection: PinnedProductFileV1,
    pub reservation: CognitiveHoldoutReservationV1,
    pub plan_digest: Digest32,
    pub frozen_plan: eval::CrossFoldPlanReceiptV1,
    pub not_before_unix_micros: u64,
    pub observed: Option<CollectedObservationV1>,
}

pub(super) struct CollectedObservationV1 {
    pub context: eval::ProductQualificationContextV1,
    pub windows: Vec<eval::ObservedFutureWindowV1>,
    pub offered_rows: usize,
    pub candidate_terminal_rows: usize,
    pub candidate_pending_rows: usize,
    pub baseline_terminal_rows: usize,
    pub baseline_pending_rows: usize,
    pub bootstrap_inputs: Vec<u8>,
}

impl eval::FinalHoldoutProviderV1 for CollectedInputsProviderV1 {
    fn manifest_digest(&mut self) -> Result<Digest32, eval::ProductProviderErrorV1> {
        read_pinned(&self.material, 4 * 1024 * 1024).map_err(|_| eval::ProductProviderErrorV1::Unavailable)?;
        Ok(self.material.digest.0)
    }

    fn release_after_consumption(
        &mut self,
        receipt: &eval::FinalHoldoutJournalReceiptV1,
    ) -> Result<eval::TemporalComparisonInputsV1, eval::ProductProviderErrorV1> {
        if self.observed.is_some()
            || receipt.disposition != eval::HoldoutUseDispositionV1::IdempotentReplay
            || receipt.use_receipt.plan_digest != self.plan_digest
            || receipt.use_receipt.holdout_digest != self.material.digest.0
            || receipt.sequence != self.reservation.sequence
            || receipt.record_digest != self.reservation.record_digest.0
            || receipt.use_receipt.use_digest != self.reservation.use_digest.0
            || receipt.authority.grants_any()
        {
            return Err(eval::ProductProviderErrorV1::Rejected);
        }
        let bytes = read_pinned(&self.collection, 32 * 1024 * 1024)
            .map_err(|_| eval::ProductProviderErrorV1::Unavailable)?;
        let raw: CognitiveCollectedQualificationV1 = serde_json::from_slice(&bytes)
            .map_err(|_| eval::ProductProviderErrorV1::Rejected)?;
        let inputs: eval::TemporalComparisonInputsV1 = raw.inputs.into();
        let bootstrap_inputs = serde_json::to_vec(&crate::cognitive_process_product_wire::TemporalComparisonInputsV1Raw::from(inputs.clone()))
            .map_err(|_| eval::ProductProviderErrorV1::Rejected)?;
        let windows: Vec<_> = raw.windows.into_iter().map(Into::into).collect();
        crate::cognitive_timed_cohort::validate(&inputs, &self.frozen_plan, &windows, self.not_before_unix_micros)
            .map_err(|_| eval::ProductProviderErrorV1::Rejected)?;
        self.observed = Some(CollectedObservationV1 {
            context: raw.context.into(), windows,
            offered_rows: inputs.targets.len(),
            candidate_terminal_rows: inputs.candidate_observations.iter().filter(|row| row.finalized_outcome.is_some()).count(),
            candidate_pending_rows: inputs.candidate_observations.iter().filter(|row| row.finalized_outcome.is_none()).count(),
            baseline_terminal_rows: inputs.baseline_observations.iter().filter(|row| row.finalized_outcome.is_some()).count(),
            baseline_pending_rows: inputs.baseline_observations.iter().filter(|row| row.finalized_outcome.is_none()).count(),
            bootstrap_inputs,
        });
        Ok(inputs)
    }
}

pub(super) fn read_pinned(input: &PinnedProductFileV1, maximum: u64) -> Result<Vec<u8>> {
    let bytes = read_material(&input.path, maximum)?;
    ensure!(!input.digest.0.is_zero() && Digest32::of_bytes(&bytes) == input.digest.0, "qualification material digest mismatch");
    Ok(bytes)
}
