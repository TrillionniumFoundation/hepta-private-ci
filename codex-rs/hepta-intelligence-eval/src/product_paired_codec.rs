//! Bounded paired execution encoding, accepted only after the original signed
//! envelope is authenticated. The legacy HPEXR001 encoding remains separate.

use codex_hepta_types::AuthorityPosture;

use super::LIMIT;
use super::Reader;
use super::decode_temporal;
use super::encode_temporal;
use super::invalid;
use super::put_id;
use super::super::ProductComparisonModeV1;
use super::super::ProductEvaluationError;
use super::super::ProductFrozenEvaluationPlanV1;
use super::super::ProductTemporalEvaluationReceiptV1;
use crate::FinalHoldoutJournalReceiptV1;
use crate::HoldoutUseDispositionV1;

pub(super) fn encode_execution(
    receipt: &ProductTemporalEvaluationReceiptV1,
) -> Result<Vec<u8>, ProductEvaluationError> {
    receipt.validate_integrity()?;
    if !matches!(receipt.product_plan.comparison_mode(), ProductComparisonModeV1::PairedOnPolicy(_))
        || receipt.authority.grants_any()
        || receipt.holdout.authority.grants_any()
        || receipt.holdout.use_receipt.authority.grants_any()
        || receipt.holdout.disposition != HoldoutUseDispositionV1::Recorded
    {
        return Err(invalid());
    }
    let paired_input = receipt.paired_input_digest.ok_or_else(invalid)?;
    let mut bytes = b"HPEXRP01".to_vec();
    bytes.extend_from_slice(receipt.product_plan.receipt_seal.as_array());
    bytes.extend_from_slice(paired_input.as_array());
    bytes.extend_from_slice(&receipt.holdout.sequence.to_be_bytes());
    for digest in [
        receipt.holdout.record_digest,
        receipt.holdout.head_digest,
        receipt.holdout.use_receipt.use_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    for temporal in [&receipt.candidate, &receipt.baseline] {
        encode_temporal(&mut bytes, temporal)?;
    }
    for ids in [&receipt.snapshot_ids, &receipt.future_window_ids] {
        if ids.len() > LIMIT / 3 {
            return Err(invalid());
        }
        bytes.extend_from_slice(&(ids.len() as u32).to_be_bytes());
        for id in ids {
            put_id(&mut bytes, id);
            if bytes.len() > LIMIT {
                return Err(invalid());
            }
        }
    }
    for digest in [
        receipt.estimate_receipt_digest,
        receipt.support_audit_digest,
        receipt.confidence_receipt_digest,
        receipt.execution_digest,
        receipt.receipt_seal,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    if bytes.len() > LIMIT {
        return Err(invalid());
    }
    Ok(bytes)
}

pub(super) fn decode_execution(
    bytes: &[u8],
    plan: &ProductFrozenEvaluationPlanV1,
    holdout: &FinalHoldoutJournalReceiptV1,
) -> Result<ProductTemporalEvaluationReceiptV1, ProductEvaluationError> {
    if !matches!(plan.comparison_mode(), ProductComparisonModeV1::PairedOnPolicy(_)) {
        return Err(invalid());
    }
    let mut reader = Reader::new(bytes)?;
    if reader.take(/*count*/ 8)? != b"HPEXRP01"
        || reader.digest()? != plan.receipt_seal
    {
        return Err(invalid());
    }
    let paired_input = reader.digest()?;
    if paired_input.is_zero()
        || reader.u64()? != holdout.sequence
        || reader.digest()? != holdout.record_digest
        || reader.digest()? != holdout.head_digest
        || reader.digest()? != holdout.use_receipt.use_digest
        || holdout.disposition != HoldoutUseDispositionV1::Recorded
        || holdout.authority.grants_any()
        || holdout.use_receipt.authority.grants_any()
    {
        return Err(invalid());
    }
    let candidate = decode_temporal(&mut reader)?;
    let baseline = decode_temporal(&mut reader)?;
    let metrics = super::super::derive_metric_gates(plan, &candidate.estimate, &baseline.estimate)?;
    let receipt = ProductTemporalEvaluationReceiptV1 {
        holdout: holdout.clone(),
        product_plan: plan.clone(),
        candidate,
        baseline,
        metrics,
        snapshot_ids: reader.ids()?,
        future_window_ids: reader.ids()?,
        estimate_receipt_digest: reader.digest()?,
        support_audit_digest: reader.digest()?,
        confidence_receipt_digest: reader.digest()?,
        execution_digest: reader.digest()?,
        receipt_seal: reader.digest()?,
        authority: AuthorityPosture::DENY_ALL,
        execution_evaluator: None,
        paired_input_digest: Some(paired_input),
    };
    reader.finish()?;
    receipt.validate_integrity()?;
    if encode_execution(&receipt)? != bytes {
        return Err(invalid());
    }
    Ok(receipt)
}
