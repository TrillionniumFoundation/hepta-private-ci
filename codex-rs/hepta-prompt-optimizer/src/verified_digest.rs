/// Compute the exact host trust scope required for generator/evaluator evidence.
#[must_use]
pub fn prompt_evidence_scope_digest_v2(
    value: &VerifiedEnumeratedPromptCandidatesV2,
) -> Digest32 {
    value.scope_digest
}

fn evidence_scope_digest(value: &EnumeratedPromptCandidatesV1) -> Digest32 {
    let mut bytes = EVIDENCE_SCOPE_DOMAIN.to_vec();
    for digest in [
        value.receipt.objective_digest,
        value.receipt.state_digest,
        value.registry_snapshot.snapshot_digest,
        value.generation_vector_digest,
        value.model_tuple.digest(),
        value.candidates_digest,
        value.canonical_order_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn digest_lineage(
    trust_digest: Digest32,
    authority_epoch: u64,
    payload_digests: &[Digest32],
) -> Digest32 {
    let mut bytes = EVIDENCE_LINEAGE_DOMAIN.to_vec();
    bytes.extend_from_slice(trust_digest.as_array());
    bytes.extend_from_slice(&authority_epoch.to_be_bytes());
    push_len(&mut bytes, payload_digests.len());
    for digest in payload_digests {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn graph_valid_until(graph: &KnowledgeGenerationV2) -> Result<u64, VerifiedPromptErrorV2> {
    let mut valid_until = u64::MAX;
    for support in graph
        .nodes
        .iter()
        .flat_map(|node| node.supports.iter())
        .chain(graph.edges.iter().flat_map(|edge| edge.supports.iter()))
    {
        if support.tombstoned {
            return Err(VerifiedPromptErrorV2::GraphExpired);
        }
        if let Some(seconds) = support.valid_to_unix_seconds {
            let seconds = u64::try_from(seconds).map_err(|_| {
                VerifiedPromptErrorV2::Corrupt("negative graph validity".to_owned())
            })?;
            valid_until = valid_until.min(seconds.saturating_mul(1_000));
        }
    }
    Ok(valid_until)
}

fn digest_candidates(value: &EnumeratedPromptCandidatesV1) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.candidates.v1".to_vec();
    push_len(&mut bytes, value.candidates.len());
    for candidate in &value.candidates {
        push_id(&mut bytes, &candidate.factor_id);
        push_id(&mut bytes, &candidate.realization.realization_id);
        bytes.extend_from_slice(candidate.binding_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn digest_candidate_order(value: &EnumeratedPromptCandidatesV1) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.candidate-order.v1".to_vec();
    for candidate in &value.candidates {
        push_id(&mut bytes, &candidate.factor_id);
        push_id(&mut bytes, &candidate.realization.realization_id);
    }
    Digest32::of_bytes(&bytes)
}

fn digest_candidate_receipt(
    value: &EnumeratedPromptCandidatesV1,
    candidates_digest: Digest32,
    order_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.candidate-set-receipt.v1".to_vec();
    push_id(&mut bytes, &value.receipt.set_id);
    for digest in [
        value.receipt.objective_digest,
        value.receipt.state_digest,
        value.receipt.registry_digest,
        value.registry_snapshot.snapshot_digest,
        value.model_tuple.digest(),
        value.receipt.selection_grammar_digest,
        candidates_digest,
        order_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_ids(&mut bytes, &value.receipt.candidate_factor_ids);
    bytes.extend_from_slice(&value.omitted_count.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn digest_pricing_receipt(
    priced: &PricedPromptCandidatesV1,
    row: &crate::canonical::PricedPromptCandidateV1,
) -> Digest32 {
    let pricing = &row.pricing;
    let confidence = &pricing.confidence_interval;
    let mut bytes = b"hepta.prompt-optimizer.pricing-receipt.v1".to_vec();
    push_id(&mut bytes, &pricing.factor_id);
    bytes.extend_from_slice(pricing.state_digest.as_array());
    bytes.extend_from_slice(&pricing.expected_utility_q32.raw().to_be_bytes());
    bytes.extend_from_slice(&pricing.downside_q32.raw().to_be_bytes());
    bytes.extend_from_slice(&pricing.token_cost.to_be_bytes());
    bytes.extend_from_slice(&pricing.latency_cost_micros.to_be_bytes());
    bytes.extend_from_slice(&pricing.interference_ppm.to_be_bytes());
    bytes.extend_from_slice(&confidence.lower_q32.raw().to_be_bytes());
    bytes.extend_from_slice(&confidence.upper_q32.raw().to_be_bytes());
    bytes.extend_from_slice(&confidence.support_count.to_be_bytes());
    bytes.extend_from_slice(confidence.support_audit_digest.as_array());
    bytes.extend_from_slice(priced.pricing_policy_digest.as_array());
    bytes.extend_from_slice(row.binding.binding_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn digest_pricing_set(priced: &PricedPromptCandidatesV1) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.pricing-set.v1".to_vec();
    bytes.extend_from_slice(priced.pricing_policy_digest.as_array());
    push_len(&mut bytes, priced.rows.len());
    for row in &priced.rows {
        push_id(&mut bytes, &row.binding.factor_id);
        bytes.extend_from_slice(row.pricing.receipt_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn digest_portfolio_receipt(value: &SelectedPromptPortfolioV1) -> Digest32 {
    let receipt = &value.receipt;
    let mut bytes = b"hepta.prompt-optimizer.portfolio-receipt.v1".to_vec();
    push_id(&mut bytes, &receipt.portfolio_id);
    for digest in [
        receipt.candidate_set_digest,
        receipt.interaction_digest,
        value.pricing_set_digest,
        value.graph_generation_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_ids(&mut bytes, &receipt.factor_ids);
    bytes.extend_from_slice(&receipt.expected_utility_q32.raw().to_be_bytes());
    bytes.extend_from_slice(&receipt.total_token_upper_bound.to_be_bytes());
    bytes.extend_from_slice(&receipt.valid_until_unix_ms.to_be_bytes());
    bytes.push(0);
    bytes.push(0);
    Digest32::of_bytes(&bytes)
}

fn canonical_pair(left: &StableId, right: &StableId) -> (StableId, StableId) {
    if left <= right {
        (left.clone(), right.clone())
    } else {
        (right.clone(), left.clone())
    }
}

fn require_digest(label: &'static str, digest: Digest32) -> Result<(), VerifiedPromptErrorV2> {
    if digest.is_zero() {
        Err(VerifiedPromptErrorV2::EmptyDigest(label))
    } else {
        Ok(())
    }
}

fn push_ids(bytes: &mut Vec<u8>, values: &[StableId]) {
    push_len(bytes, values.len());
    for value in values {
        push_id(bytes, value);
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len());
    bytes.extend_from_slice(raw);
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    bytes.extend_from_slice(&u64::try_from(value).unwrap_or(u64::MAX).to_be_bytes());
}

#[cfg(test)]
#[path = "verified_tests.rs"]
mod tests;
