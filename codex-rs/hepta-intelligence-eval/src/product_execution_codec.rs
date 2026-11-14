//! Private bounded encoding of original execution bytes. Decoding the inner
//! receipt is allowed only after the runner authenticates the exact byte digest.
//! An integrity seal is not an authentication mechanism or a deserialization API.

use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use super::ProductEvaluationError;
use super::ProductFrozenEvaluationPlanV1;
use super::ProductTemporalEvaluationReceiptV1;
use crate::ClusterOpeEstimate;
use crate::FinalHoldoutJournalReceiptV1;
use crate::HoldoutUseDispositionV1;
use crate::MAX_PRODUCT_EVALUATION_EXECUTION_BYTES_V1 as LIMIT;
use crate::OpeEstimate;
use crate::OpeInterval;
use crate::TemporalEvaluationReceipt;

fn invalid() -> ProductEvaluationError {
    ProductEvaluationError::Integrity("execution encoding")
}

pub(super) fn encode_envelope(
    signed: &SignedLearningEvidenceV1,
    body: &[u8],
) -> Result<Vec<u8>, ProductEvaluationError> {
    if signed.role != LearningEvidenceRoleV1::Evaluator || body.len() > LIMIT {
        return Err(invalid());
    }
    let mut bytes = b"HPEXEV01".to_vec();
    put_id(&mut bytes, &signed.evidence_id);
    put_id(&mut bytes, &signed.principal_id);
    for digest in [
        signed.trust_digest,
        signed.scope_digest,
        signed.objective_digest,
        signed.payload_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    for value in [signed.authority_epoch, signed.issued_at, signed.expires_at] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    bytes.extend_from_slice(&signed.signature);
    bytes.extend_from_slice(&(body.len() as u32).to_be_bytes());
    bytes.extend_from_slice(body);
    if bytes.len() > LIMIT {
        return Err(invalid());
    }
    Ok(bytes)
}

pub(super) fn decode_envelope(
    bytes: &[u8],
) -> Result<(SignedLearningEvidenceV1, &[u8]), ProductEvaluationError> {
    let mut reader = Reader::new(bytes)?;
    if reader.take(/*count*/ 8)? != b"HPEXEV01" {
        return Err(invalid());
    }
    let signed = SignedLearningEvidenceV1 {
        evidence_id: reader.id()?,
        principal_id: reader.id()?,
        role: LearningEvidenceRoleV1::Evaluator,
        trust_digest: reader.digest()?,
        scope_digest: reader.digest()?,
        objective_digest: reader.digest()?,
        payload_digest: reader.digest()?,
        authority_epoch: reader.u64()?,
        issued_at: reader.u64()?,
        expires_at: reader.u64()?,
        signature: reader
            .take(/*count*/ 64)?
            .try_into()
            .map_err(|_| invalid())?,
    };
    let length = reader.u32()? as usize;
    let body = reader.take(length)?;
    reader.finish()?;
    Ok((signed, body))
}

pub(super) fn encode_execution(
    receipt: &ProductTemporalEvaluationReceiptV1,
) -> Result<Vec<u8>, ProductEvaluationError> {
    receipt.validate_integrity()?;
    if receipt.authority.grants_any()
        || receipt.holdout.authority.grants_any()
        || receipt.holdout.use_receipt.authority.grants_any()
        || receipt.holdout.disposition != HoldoutUseDispositionV1::Recorded
    {
        return Err(invalid());
    }
    let mut bytes = b"HPEXR001".to_vec();
    bytes.extend_from_slice(receipt.product_plan.receipt_seal.as_array());
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
    let mut reader = Reader::new(bytes)?;
    if reader.take(/*count*/ 8)? != b"HPEXR001"
        || reader.digest()? != plan.receipt_seal
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
    let metrics = super::derive_metric_gates(plan, &candidate.estimate, &baseline.estimate)?;
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
    };
    reader.finish()?;
    receipt.validate_integrity()?;
    // Require the unique encoding too; unsupported future encodings are refused.
    if encode_execution(&receipt)? != bytes {
        return Err(invalid());
    }
    Ok(receipt)
}

fn encode_temporal(
    bytes: &mut Vec<u8>,
    receipt: &TemporalEvaluationReceipt,
) -> Result<(), ProductEvaluationError> {
    let estimate = &receipt.estimate;
    if receipt.authority.grants_any()
        || estimate.authority.grants_any()
        || estimate.point.authority.grants_any()
    {
        return Err(invalid());
    }
    put_id(bytes, &receipt.evaluation_id);
    for digest in [
        receipt.plan_digest,
        receipt.model_digest,
        receipt.predictions_digest,
        receipt.evidence_digest,
        receipt.receipt_seal,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&(estimate.point.rows as u64).to_be_bytes());
    for value in [
        estimate.point.ips,
        estimate.point.snips,
        estimate.point.doubly_robust,
        estimate.point.effective_sample_size,
        estimate.point.maximum_observed_weight,
    ] {
        bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
    bytes.extend_from_slice(estimate.point.evidence_digest.as_array());
    bytes.extend_from_slice(&(estimate.cluster_count as u64).to_be_bytes());
    bytes.extend_from_slice(&(estimate.largest_cluster_rows as u64).to_be_bytes());
    for interval in [
        estimate.ips,
        estimate.snips,
        estimate.doubly_robust,
        estimate.weight_mean,
    ] {
        bytes.extend_from_slice(&interval.lower.raw().to_be_bytes());
        bytes.extend_from_slice(&interval.upper.raw().to_be_bytes());
    }
    bytes.extend_from_slice(estimate.evidence_digest.as_array());
    bytes.extend_from_slice(estimate.receipt_seal.as_array());
    Ok(())
}

fn decode_temporal(
    reader: &mut Reader<'_>,
) -> Result<TemporalEvaluationReceipt, ProductEvaluationError> {
    let evaluation_id = reader.id()?;
    let plan_digest = reader.digest()?;
    let model_digest = reader.digest()?;
    let predictions_digest = reader.digest()?;
    let evidence_digest = reader.digest()?;
    let receipt_seal = reader.digest()?;
    let point = OpeEstimate {
        rows: reader.count()?,
        ips: reader.fixed()?,
        snips: reader.fixed()?,
        doubly_robust: reader.fixed()?,
        effective_sample_size: reader.fixed()?,
        maximum_observed_weight: reader.fixed()?,
        evidence_digest: reader.digest()?,
        authority: AuthorityPosture::DENY_ALL,
    };
    let estimate = ClusterOpeEstimate {
        point,
        cluster_count: reader.count()?,
        largest_cluster_rows: reader.count()?,
        ips: reader.interval()?,
        snips: reader.interval()?,
        doubly_robust: reader.interval()?,
        weight_mean: reader.interval()?,
        evidence_digest: reader.digest()?,
        receipt_seal: reader.digest()?,
        authority: AuthorityPosture::DENY_ALL,
    };
    let receipt = TemporalEvaluationReceipt {
        evaluation_id,
        plan_digest,
        model_digest,
        predictions_digest,
        estimate,
        evidence_digest,
        receipt_seal,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.validate_integrity()?;
    Ok(receipt)
}

fn put_id(bytes: &mut Vec<u8>, id: &StableId) {
    bytes.extend_from_slice(&(id.as_str().len() as u16).to_be_bytes());
    bytes.extend_from_slice(id.as_str().as_bytes());
}

struct Reader<'a> {
    bytes: &'a [u8],
}

impl<'a> Reader<'a> {
    fn new(bytes: &'a [u8]) -> Result<Self, ProductEvaluationError> {
        if bytes.len() > LIMIT {
            return Err(invalid());
        }
        Ok(Self { bytes })
    }
    fn take(&mut self, count: usize) -> Result<&'a [u8], ProductEvaluationError> {
        let (head, tail) = self.bytes.split_at_checked(count).ok_or_else(invalid)?;
        self.bytes = tail;
        Ok(head)
    }
    fn u32(&mut self) -> Result<u32, ProductEvaluationError> {
        Ok(u32::from_be_bytes(
            self.take(/*count*/ 4)?.try_into().map_err(|_| invalid())?,
        ))
    }
    fn u64(&mut self) -> Result<u64, ProductEvaluationError> {
        Ok(u64::from_be_bytes(
            self.take(/*count*/ 8)?.try_into().map_err(|_| invalid())?,
        ))
    }
    fn count(&mut self) -> Result<usize, ProductEvaluationError> {
        let value = self.u64()?;
        if value > 1_000_000 {
            return Err(invalid());
        }
        usize::try_from(value).map_err(|_| invalid())
    }
    fn digest(&mut self) -> Result<Digest32, ProductEvaluationError> {
        Ok(Digest32::from_array(
            self.take(/*count*/ 32)?.try_into().map_err(|_| invalid())?,
        ))
    }
    fn fixed(&mut self) -> Result<FixedQ32, ProductEvaluationError> {
        Ok(FixedQ32::from_raw(i64::from_be_bytes(
            self.take(/*count*/ 8)?.try_into().map_err(|_| invalid())?,
        )))
    }
    fn interval(&mut self) -> Result<OpeInterval, ProductEvaluationError> {
        Ok(OpeInterval {
            lower: self.fixed()?,
            upper: self.fixed()?,
        })
    }
    fn id(&mut self) -> Result<StableId, ProductEvaluationError> {
        let size = usize::from(u16::from_be_bytes(
            self.take(/*count*/ 2)?.try_into().map_err(|_| invalid())?,
        ));
        if !(1..=128).contains(&size) {
            return Err(invalid());
        }
        StableId::new(std::str::from_utf8(self.take(size)?).map_err(|_| invalid())?)
            .map_err(|_| invalid())
    }
    fn ids(&mut self) -> Result<Vec<StableId>, ProductEvaluationError> {
        let count = self.u32()? as usize;
        if count > self.bytes.len() / 3 {
            return Err(invalid());
        }
        (0..count).map(|_| self.id()).collect()
    }
    fn finish(self) -> Result<(), ProductEvaluationError> {
        if self.bytes.is_empty() {
            Ok(())
        } else {
            Err(invalid())
        }
    }
}
