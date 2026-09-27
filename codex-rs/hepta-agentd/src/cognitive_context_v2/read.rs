use super::*;

#[cfg(test)]
pub(crate) async fn read(
    store: &CognitiveStore,
    owner: &AgentId,
    body_generation: u64,
    query: &str,
    limit: u16,
    ranker: Option<&Arc<PinnedCognitiveRanker>>,
) -> Result<CognitiveContextSnapshot, CognitiveContextError> {
    read_with_retrieval_context_and_learning(
        store,
        owner,
        body_generation,
        query,
        limit,
        ranker,
        None,
        None,
        None,
    )
    .await
}

#[cfg(test)]
pub(crate) async fn read_with_retrieval_context(
    store: &CognitiveStore,
    owner: &AgentId,
    body_generation: u64,
    query: &str,
    limit: u16,
    ranker: Option<&Arc<PinnedCognitiveRanker>>,
    current_retrieval: Option<&Arc<dyn CurrentMemoryRetrievalContext>>,
) -> Result<CognitiveContextSnapshot, CognitiveContextError> {
    read_with_retrieval_context_and_learning(
        store,
        owner,
        body_generation,
        query,
        limit,
        ranker,
        current_retrieval,
        None,
        None,
    )
    .await
}

pub(crate) async fn read_with_retrieval_context_and_learning(
    store: &CognitiveStore,
    owner: &AgentId,
    body_generation: u64,
    query: &str,
    limit: u16,
    ranker: Option<&Arc<PinnedCognitiveRanker>>,
    current_retrieval: Option<&Arc<dyn CurrentMemoryRetrievalContext>>,
    learning_sink: Option<&Arc<crate::CognitiveRetrievalLearningSink>>,
    request_id: Option<u64>,
) -> Result<CognitiveContextSnapshot, CognitiveContextError> {
    if learning_sink.is_some() && request_id.is_none() {
        return Err(CognitiveContextError::RetrievalLearningUnavailable);
    }
    // Preparing the owner read must not append a learning-delivery record.
    // Its final response bytes are not known until the V2 seal is attached.
    let mut prepared = legacy::prepare_read(
        store,
        owner,
        body_generation,
        query,
        limit,
        ranker,
        current_retrieval,
        learning_sink.is_some(),
    )
    .await?;
    let response = &mut prepared.response;
    let raw_plan = response.plan.clone().ok_or_else(|| {
        CognitiveStoreError::Invalid("cognitive context read did not return a plan".to_string())
    })?;
    let evaluated_context_digest = helpers::parse_digest(
        &raw_plan.evaluated_context_digest,
        "evaluated context digest",
    )?;
    let raw_plan_receipt_digest =
        helpers::parse_digest(&raw_plan.plan_receipt_digest, "raw planner receipt digest")?;
    let retrieval_context_digest =
        helpers::current_retrieval_digest(current_retrieval, owner, body_generation).await?;
    if retrieval_context_digest != prepared.retrieval_context_digest {
        return Err(CognitiveContextError::RetrievalContextUnavailable);
    }
    let ranker_policy_digest =
        helpers::current_ranker_policy_digest(ranker, owner, body_generation, query).await?;
    if ranker_policy_digest != prepared.ranker_policy_digest {
        return Err(CognitiveContextError::RankerUnavailable);
    }
    let authenticated = helpers::authenticate_packet(
        store,
        owner,
        &response.snapshot_digest,
        &response.read_digest,
        &response.items,
        retrieval_context_digest,
    )
    .await?;

    if raw_plan.read_allowed {
        let pre_plan = CognitiveContextSnapshot {
            snapshot_digest: response.snapshot_digest.clone(),
            read_digest: response.read_digest.clone(),
            omitted_records: response.omitted_records,
            items: response.items.clone(),
            plan: None,
        };
        let encoded = serde_json::to_vec(&pre_plan)
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
        if Digest32::of_bytes(&encoded) != evaluated_context_digest {
            return Err(CognitiveStoreError::Conflict(
                "cognitive context changed before V2 delivery sealing".to_string(),
            )
            .into());
        }
    }

    let request_binding_digest = helpers::request_binding_digest(
        owner,
        body_generation,
        query,
        limit,
        request_id,
        retrieval_context_digest,
        ranker_policy_digest,
    );
    let seal = IssuedContextSealV2 {
        owner: owner.clone(),
        body_generation,
        snapshot_digest: authenticated.snapshot_digest,
        read_binding_digest: authenticated.read_binding_digest,
        evaluated_context_digest,
        raw_plan_receipt_digest,
        request_binding_digest,
        retrieval_context_digest,
        ranker_policy_digest,
        record_set_digest: authenticated.record_set_digest,
        visible_record_count: authenticated.record_count,
        // Preserve the planner's original deadline; sealing never renews TTL.
        issued_at_micros: prepared.issued_at_micros,
        expires_at_micros: prepared.expires_at_micros,
        read_allowed: raw_plan.read_allowed,
        query: query.to_string(),
    };
    let pending = publication::reserve(seal)?;
    let plan = response.plan.as_mut().ok_or_else(|| {
        CognitiveStoreError::Invalid("cognitive context plan disappeared before sealing".to_string())
    })?;
    plan.plan_receipt_digest =
        helpers::encode_plan_binding(raw_plan_receipt_digest, pending.digest());
    if serde_json::to_vec(response)
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?
        .len()
        > MAX_CONTEXT_JSON_BYTES
    {
        return Err(CognitiveStoreError::Invalid(
            "sealed cognitive context exceeds response budget".to_string(),
        )
        .into());
    }

    // The learning ledger hashes exactly these sealed bytes. A failed append
    // or dropped future abandons the reserved origin. Nothing after a
    // successful append may mutate the response or renew its lease.
    let response = prepared
        .record_delivery(owner, body_generation, learning_sink, request_id)
        .await?;
    pending.publish();
    Ok(response)
}
