use super::*;

#[cfg(test)]
pub(crate) async fn revalidate(
    store: &CognitiveStore,
    owner: &AgentId,
    snapshot_digest: &str,
    read_digest: &str,
    omitted_records: u64,
    items: &[CognitiveContextItem],
    plan: Option<&CognitiveContextPlan>,
    ranker: Option<&Arc<PinnedCognitiveRanker>>,
) -> Result<CognitiveContextRevalidation, CognitiveContextError> {
    revalidate_with_retrieval_context(
        store,
        owner,
        snapshot_digest,
        read_digest,
        omitted_records,
        items,
        plan,
        ranker,
        1,
        None,
    )
    .await
}

#[allow(clippy::too_many_arguments)]
pub(crate) async fn revalidate_with_retrieval_context(
    store: &CognitiveStore,
    owner: &AgentId,
    snapshot_digest: &str,
    read_digest: &str,
    omitted_records: u64,
    items: &[CognitiveContextItem],
    plan: Option<&CognitiveContextPlan>,
    ranker: Option<&Arc<PinnedCognitiveRanker>>,
    body_generation: u64,
    current_retrieval: Option<&Arc<dyn CurrentMemoryRetrievalContext>>,
) -> Result<CognitiveContextRevalidation, CognitiveContextError> {
    let plan = plan.ok_or_else(|| {
        CognitiveStoreError::Invalid("cognitive context final use requires a plan".to_string())
    })?;
    let (raw_plan_receipt_digest, seal_digest) =
        helpers::parse_plan_binding(&plan.plan_receipt_digest)?;
    let seal = helpers::issued_seal(seal_digest)?;
    let now_micros = helpers::monotonic_micros()?;
    if now_micros >= seal.expires_at_micros {
        return Err(CognitiveStoreError::Conflict(
            "cognitive context monotonic lease expired".to_string(),
        )
        .into());
    }
    let expected_snapshot = helpers::parse_digest(snapshot_digest, "snapshot digest")?;
    let expected_read = helpers::parse_digest(read_digest, "read digest")?;
    let evaluated_context_digest =
        helpers::parse_digest(&plan.evaluated_context_digest, "evaluated context digest")?;
    if seal.owner != *owner
        || seal.body_generation != body_generation
        || seal.snapshot_digest != expected_snapshot
        || seal.read_binding_digest != expected_read
        || seal.evaluated_context_digest != evaluated_context_digest
        || seal.raw_plan_receipt_digest != raw_plan_receipt_digest
        || seal.read_allowed != plan.read_allowed
        || usize::from(seal.visible_record_count) != items.len()
        || seal.digest() != seal_digest
    {
        return Err(CognitiveStoreError::Conflict(
            "cognitive context V2 delivery seal mismatch".to_string(),
        )
        .into());
    }

    let retrieval_context_digest =
        helpers::current_retrieval_digest(current_retrieval, owner, body_generation).await?;
    if retrieval_context_digest != seal.retrieval_context_digest {
        return Err(CognitiveContextError::RetrievalContextUnavailable);
    }
    let ranker_policy_digest = helpers::current_ranker_policy_digest(
        ranker,
        owner,
        body_generation,
        &seal.query,
    )
    .await?;
    if ranker_policy_digest != seal.ranker_policy_digest {
        return Err(CognitiveContextError::RankerUnavailable);
    }
    let authenticated = helpers::authenticate_packet(
        store,
        owner,
        snapshot_digest,
        read_digest,
        items,
        retrieval_context_digest,
    )
    .await?;
    if authenticated.record_set_digest != seal.record_set_digest
        || authenticated.record_count != seal.visible_record_count
    {
        return Err(CognitiveStoreError::Conflict(
            "cognitive context authenticated record set changed before final use".to_string(),
        )
        .into());
    }

    // The established final-use verifier still owns complete owner-cut,
    // text/content, ranker-currentness and retrieval-currentness checks.  The
    // V2 seal is an additional origin/request/lease fence, not a replacement.
    let result = legacy::revalidate_with_retrieval_context(
        store,
        owner,
        snapshot_digest,
        read_digest,
        omitted_records,
        items,
        Some(plan),
        ranker,
        body_generation,
        current_retrieval,
    )
    .await?;
    if helpers::monotonic_micros()? >= seal.expires_at_micros {
        return Err(CognitiveStoreError::Conflict(
            "cognitive context monotonic lease expired during final-use validation".to_string(),
        )
        .into());
    }
    Ok(result)
}
