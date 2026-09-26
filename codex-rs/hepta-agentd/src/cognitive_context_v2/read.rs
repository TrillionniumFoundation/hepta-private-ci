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
    let mut response = legacy::read_with_retrieval_context_and_learning(
        store,
        owner,
        body_generation,
        query,
        limit,
        ranker,
        current_retrieval,
        learning_sink,
        request_id,
    )
    .await?;

    let legacy_plan = response.plan.clone().ok_or_else(|| {
        CognitiveStoreError::Invalid("cognitive context read did not return a plan".to_string())
    })?;
    let evaluated_context_digest = helpers::parse_digest(
        &legacy_plan.evaluated_context_digest,
        "evaluated context digest",
    )?;
    let raw_plan_receipt_digest = helpers::parse_digest(
        &legacy_plan.plan_receipt_digest,
        "raw planner receipt digest",
    )?;
    let retrieval_context_digest =
        helpers::current_retrieval_digest(current_retrieval, owner, body_generation).await?;
    let ranker_policy_digest =
        helpers::current_ranker_policy_digest(ranker, owner, body_generation, query).await?;
    let authenticated = helpers::authenticate_packet(
        store,
        owner,
        &response.snapshot_digest,
        &response.read_digest,
        &response.items,
        retrieval_context_digest,
    )
    .await?;

    if legacy_plan.read_allowed {
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

    let issued_at_micros = helpers::monotonic_micros()?;
    let expires_at_micros = issued_at_micros
        .checked_add(CONTEXT_LEASE_MICROS)
        .ok_or_else(|| {
            CognitiveStoreError::Unavailable("context monotonic lease overflow".to_string())
        })?;
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
        issued_at_micros,
        expires_at_micros,
        read_allowed: legacy_plan.read_allowed,
        query: query.to_string(),
    };
    let seal_digest = helpers::register_issued_seal(seal)?;
    let plan = response.plan.as_mut().ok_or_else(|| {
        CognitiveStoreError::Invalid(
            "cognitive context plan disappeared before sealing".to_string(),
        )
    })?;
    plan.plan_receipt_digest =
        helpers::encode_plan_binding(raw_plan_receipt_digest, seal_digest);

    if serde_json::to_vec(&response)
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?
        .len()
        > MAX_CONTEXT_JSON_BYTES
    {
        return Err(CognitiveStoreError::Invalid(
            "sealed cognitive context exceeds response budget".to_string(),
        )
        .into());
    }
    Ok(response)
}
