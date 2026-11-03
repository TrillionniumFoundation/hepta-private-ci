//! Validate a retained request/receipt without running context selection.
//! A valid pair is correlation only; this API never returns a new receipt or
//! proves that bytes came from a durable owner.

use super::*;

pub fn validate_retained_compilation_v1(request: &CompilationRequest, receipt: &ContextCompilationReceipt)
    -> Result<(), Error> {
    if request.items.len() > MAX_ITEMS { return Err(Error::ItemLimitExceeded); }
    if request.token_budget == 0 || request.token_budget > MAX_TOKENS { return Err(Error::InvalidTokenBudget); }
    if request.run_snapshot_digest.is_zero() || request.objective_digest.is_zero()
        || receipt.context_digest.is_zero() || receipt.compilation_id != request.compilation_id
        || receipt.authority.grants_any() {
        return Err(Error::RetainedReceiptMismatch);
    }
    let mut items = request.items.iter().collect::<Vec<_>>();
    items.sort_by(|left, right| left.role.cmp(&right.role).then_with(|| left.item_id.cmp(&right.item_id)));
    let mut seen = BTreeSet::new();
    for item in &items {
        if !seen.insert(item.item_id.clone()) { return Err(Error::DuplicateItem(item.item_id.to_string())); }
        if item.content_digest.is_zero() || item.source_digest.is_zero() { return Err(Error::EmptyDigest("retained item")); }
        if item.token_count == 0 { return Err(Error::ZeroTokenItem(item.item_id.to_string())); }
        if item.contains_secret { return Err(Error::SecretRejected(item.item_id.to_string())); }
    }
    let trusted = receipt.trusted_instruction_ids.iter().cloned().collect::<BTreeSet<_>>();
    let evidence = receipt.untrusted_evidence_ids.iter().cloned().collect::<BTreeSet<_>>();
    let omitted = receipt.omitted_ids.iter().cloned().collect::<BTreeSet<_>>();
    if trusted.len() != receipt.trusted_instruction_ids.len() || evidence.len() != receipt.untrusted_evidence_ids.len()
        || omitted.len() != receipt.omitted_ids.len() || !trusted.is_disjoint(&evidence)
        || !trusted.is_disjoint(&omitted) || !evidence.is_disjoint(&omitted)
        || trusted.len() + evidence.len() + omitted.len() != items.len()
        || trusted.iter().chain(&evidence).chain(&omitted).any(|id| !seen.contains(id)) {
        return Err(Error::RetainedReceiptMismatch);
    }
    let mut ordered_trusted = Vec::new();
    let mut ordered_evidence = Vec::new();
    let mut ordered_omitted = Vec::new();
    let mut tokens = 0_u64;
    let mut bytes = b"hepta.context.compilation.v1".to_vec();
    push_id(&mut bytes, &request.compilation_id);
    bytes.extend_from_slice(request.run_snapshot_digest.as_array());
    bytes.extend_from_slice(request.objective_digest.as_array());
    bytes.extend_from_slice(&request.token_budget.to_be_bytes());
    for item in items {
        if omitted.contains(&item.item_id) {
            if item.role == ContextRole::TrustedInstruction { return Err(Error::RetainedReceiptMismatch); }
            ordered_omitted.push(item.item_id.clone());
            continue;
        }
        match item.role {
            ContextRole::TrustedInstruction if trusted.contains(&item.item_id) => {
                ordered_trusted.push(item.item_id.clone()); bytes.push(0);
            }
            ContextRole::UntrustedEvidence if evidence.contains(&item.item_id) => {
                ordered_evidence.push(item.item_id.clone()); bytes.push(1);
            }
            ContextRole::TrustedInstruction | ContextRole::UntrustedEvidence => return Err(Error::RetainedReceiptMismatch),
        }
        tokens = tokens.checked_add(item.token_count).ok_or(Error::Arithmetic)?;
        push_id(&mut bytes, &item.item_id);
        bytes.extend_from_slice(item.content_digest.as_array());
        bytes.extend_from_slice(item.source_digest.as_array());
        bytes.extend_from_slice(&item.token_count.to_be_bytes());
    }
    if ordered_trusted != receipt.trusted_instruction_ids || ordered_evidence != receipt.untrusted_evidence_ids
        || ordered_omitted != receipt.omitted_ids || tokens != receipt.used_tokens || tokens > request.token_budget
        || Digest32::of_bytes(&bytes) != receipt.context_digest {
        return Err(Error::RetainedReceiptMismatch);
    }
    Ok(())
}

#[cfg(test)]
#[path = "retained_tests.rs"]
mod tests;
