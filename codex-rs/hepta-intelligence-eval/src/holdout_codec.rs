//! Owner-local journal encoding; not a canonical cross-owner protocol.
use super::*;

pub(crate) fn encode(plan: &CrossFoldPlanReceiptV1) -> Result<Vec<u8>, EvaluationClosureError> {
    validate_frozen_plan_receipt_integrity(plan)?;
    let mut bytes = Vec::new();
    for id in [
        &plan.plan_id,
        &plan.candidate_id,
        &plan.baseline_id,
        &plan.final_holdout_window_id,
    ] {
        bytes.extend_from_slice(&(id.as_str().len() as u16).to_be_bytes());
        bytes.extend_from_slice(id.as_str().as_bytes());
    }
    bytes.push(plan.claim_scope.tag());
    for digest in [
        plan.objective_digest,
        plan.dataset_digest,
        plan.estimand_digest,
        plan.metric_contract_digest,
        plan.final_holdout_digest,
        plan.plan_digest,
        plan.receipt_seal,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    for value in [
        plan.family_alpha_ppm,
        plan.simultaneous_comparisons,
        plan.fold_count,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    if plan.authority.grants_any() {
        return Err(EvaluationClosureError::FrozenPlanBindingMismatch(
            "authority",
        ));
    }
    Ok(bytes)
}

pub(crate) fn decode(mut bytes: &[u8]) -> Result<CrossFoldPlanReceiptV1, EvaluationClosureError> {
    fn take<'a>(bytes: &mut &'a [u8], count: usize) -> Result<&'a [u8], EvaluationClosureError> {
        let (head, tail) = bytes
            .split_at_checked(count)
            .ok_or(EvaluationClosureError::FrozenPlanReceiptIntegrity)?;
        *bytes = tail;
        Ok(head)
    }
    fn id(bytes: &mut &[u8]) -> Result<StableId, EvaluationClosureError> {
        let raw = take(bytes, 2)?;
        let size = usize::from(u16::from_be_bytes([raw[0], raw[1]]));
        if !(1..=128).contains(&size) {
            return Err(EvaluationClosureError::FrozenPlanReceiptIntegrity);
        }
        let text = std::str::from_utf8(take(bytes, size)?)
            .map_err(|_| EvaluationClosureError::FrozenPlanReceiptIntegrity)?;
        StableId::new(text).map_err(|_| EvaluationClosureError::FrozenPlanReceiptIntegrity)
    }
    let plan_id = id(&mut bytes)?;
    let candidate_id = id(&mut bytes)?;
    let baseline_id = id(&mut bytes)?;
    let final_holdout_window_id = id(&mut bytes)?;
    let claim_scope = match take(&mut bytes, 1)?[0] {
        0 => EvaluationClaimScopeV1::Qualification,
        1 => EvaluationClaimScopeV1::SystemLongitudinal,
        _ => return Err(EvaluationClosureError::FrozenPlanReceiptIntegrity),
    };
    let mut digests = [Digest32::ZERO; 7];
    for value in &mut digests {
        let mut raw = [0; 32];
        raw.copy_from_slice(take(&mut bytes, 32)?);
        *value = Digest32::from_array(raw);
    }
    let mut values = [0; 3];
    for value in &mut values {
        let mut raw = [0; 4];
        raw.copy_from_slice(take(&mut bytes, 4)?);
        *value = u32::from_be_bytes(raw);
    }
    if !bytes.is_empty() {
        return Err(EvaluationClosureError::FrozenPlanReceiptIntegrity);
    }
    let plan = CrossFoldPlanReceiptV1 {
        plan_id,
        candidate_id,
        baseline_id,
        final_holdout_window_id,
        claim_scope,
        objective_digest: digests[0],
        dataset_digest: digests[1],
        estimand_digest: digests[2],
        metric_contract_digest: digests[3],
        final_holdout_digest: digests[4],
        plan_digest: digests[5],
        receipt_seal: digests[6],
        family_alpha_ppm: values[0],
        simultaneous_comparisons: values[1],
        fold_count: values[2],
        authority: AuthorityPosture::DENY_ALL,
    };
    validate_frozen_plan_receipt_integrity(&plan)?;
    Ok(plan)
}
