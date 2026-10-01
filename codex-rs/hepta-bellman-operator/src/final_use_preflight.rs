//! Reserve owner-admission inputs before cloning plans or canonicalizing rows.
//!
//! The live reservation covers retained request/plan data, bounded receipt and
//! attestation copies, row commitment buffers and admission indexing scratch.
//! It stays attached to the single-use capability during dispatch and fitting.
//! Backend ledger-history snapshots remain the ledger owner's capacity scope.

use std::mem::size_of;

use super::FinalUseErrorV1;
use super::TabularTrainingRequestV1;
use super::WorldModelTrainingRequestV1;
use crate::OperatorDatasetBindingError;
use crate::OperatorResourceBudgetV1;
use crate::OperatorWorkMeter;
use crate::checked_add;
use crate::checked_mul;
use crate::checked_u64;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::StableId;

pub(super) fn tabular(
    request: &TabularTrainingRequestV1,
    receipt: &DatasetSnapshotReceiptV3,
    freeze: &SignedLearningEvidenceV1,
    rows: &SignedLearningEvidenceV1,
) -> Result<OperatorWorkMeter, FinalUseErrorV1> {
    let grid = checked_add(
        checked_u64(request.sensor_ids.capacity())?,
        checked_u64(request.action_ids.capacity())?,
    )?;
    let mut input = checked_add(
        checked_u64(size_of::<TabularTrainingRequestV1>())?,
        checked_add(
            checked_mul(grid, checked_u64(size_of::<StableId>())?)?,
            checked_mul(
                checked_u64(request.samples.capacity())?,
                checked_u64(size_of::<crate::TabularOperatorSampleV1>())?,
            )?,
        )?,
    )?;
    for id in [&request.artifact_id, &request.producer_id]
        .into_iter()
        .chain(&request.sensor_ids)
        .chain(&request.action_ids)
        .chain(
            request
                .samples
                .iter()
                .flat_map(|sample| [&sample.sample_id, &sample.sensor_id, &sample.action_id]),
        )
    {
        input = checked_add(input, checked_u64(id.as_str().len())?)?;
    }
    reserve(
        input,
        request.samples.len(),
        grid,
        request.profile.runtime_limits(),
        receipt,
        freeze,
        rows,
    )
}

pub(super) fn world(
    request: &WorldModelTrainingRequestV1,
    receipt: &DatasetSnapshotReceiptV3,
    freeze: &SignedLearningEvidenceV1,
    rows: &SignedLearningEvidenceV1,
) -> Result<OperatorWorkMeter, FinalUseErrorV1> {
    let mut input = checked_add(
        checked_add(
            checked_u64(size_of::<WorldModelTrainingRequestV1>())?,
            checked_u64(request.model_id.as_str().len())?,
        )?,
        checked_mul(
            checked_u64(request.samples.capacity())?,
            checked_u64(size_of::<crate::WorldModelSampleV1>())?,
        )?,
    )?;
    for id in request.samples.iter().flat_map(|sample| {
        [
            &sample.sample_id,
            &sample.state_id,
            &sample.action_id,
            &sample.next_state_id,
        ]
    }) {
        input = checked_add(input, checked_u64(id.as_str().len())?)?;
    }
    reserve(
        input,
        request.samples.len(),
        /*grid*/ 0,
        request.profile.runtime_limits(),
        receipt,
        freeze,
        rows,
    )
}

fn reserve(
    input: u64,
    row_count: usize,
    grid: u64,
    budget: OperatorResourceBudgetV1,
    receipt: &DatasetSnapshotReceiptV3,
    freeze: &SignedLearningEvidenceV1,
    rows: &SignedLearningEvidenceV1,
) -> Result<OperatorWorkMeter, FinalUseErrorV1> {
    if receipt.snapshot.source_record_digests.len() > crate::MAX_SIGNED_OPERATOR_ROWS {
        return Err(OperatorDatasetBindingError::Bounds.into());
    }
    let mut receipt_bytes = checked_add(
        checked_u64(size_of::<DatasetSnapshotReceiptV3>())?,
        checked_mul(
            checked_u64(receipt.snapshot.source_record_digests.len())?,
            /*right*/ 32,
        )?,
    )?;
    for id in [
        &receipt.snapshot.snapshot_id,
        &receipt.producer.principal_id,
    ] {
        receipt_bytes = checked_add(receipt_bytes, checked_u64(id.as_str().len())?)?;
    }
    let mut evidence_bytes = 0;
    for evidence in [freeze, rows] {
        evidence_bytes = checked_add(
            evidence_bytes,
            checked_u64(size_of::<SignedLearningEvidenceV1>())?,
        )?;
        for id in [&evidence.evidence_id, &evidence.principal_id] {
            evidence_bytes = checked_add(evidence_bytes, checked_u64(id.as_str().len())?)?;
        }
    }
    // Four simultaneous input/canonical copies and generous per-row scratch
    // cover sorted references, evidence sets, ID indexes, preimages and bounded
    // owner record references. Count real known post-issue evidence checks,
    // rather than inventing operation costs for signature verification.
    let required = [
        checked_mul(input, /*right*/ 4)?,
        checked_mul(receipt_bytes, /*right*/ 4)?,
        checked_mul(evidence_bytes, /*right*/ 4)?,
        checked_mul(checked_u64(row_count)?, /*right*/ 1_024)?,
        checked_mul(grid, /*right*/ 256)?,
        16_384,
    ]
    .into_iter()
    .try_fold(0, checked_add)?;
    let mut meter = OperatorWorkMeter::new(budget)?;
    meter.preflight_operations(/*required*/ 2)?;
    meter.reserve_total_bytes(required)?;
    Ok(meter)
}
