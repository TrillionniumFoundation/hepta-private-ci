use super::*;

pub(super) async fn authenticate_packet(
    store: &CognitiveStore,
    owner: &AgentId,
    snapshot_digest: &str,
    read_digest: &str,
    items: &[CognitiveContextItem],
    retrieval_context_digest: Option<Digest32>,
) -> Result<AuthenticatedPacketV2, CognitiveContextError> {
    if items.len() > 4 {
        return Err(CognitiveStoreError::Invalid(
            "authenticated context accepts at most four items".to_string(),
        )
        .into());
    }
    let expected_snapshot = parse_digest(snapshot_digest, "snapshot digest")?;
    let expected_read = parse_digest(read_digest, "read digest")?;
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let cut = store
        .lane_c_snapshot(&access, &scope, legacy_now_seconds()?)
        .await?;
    if cut.snapshot().snapshot_digest != expected_snapshot {
        return Err(CognitiveStoreError::Conflict(
            "cognitive context snapshot changed before authentication".to_string(),
        )
        .into());
    }
    let read = read_selected_items(&cut, items)?;
    let actual_read = bind_selected_read(&cut, &read, retrieval_context_digest);
    if actual_read != expected_read
        || !read.missing_ids().is_empty()
        || read.records().len() != items.len()
    {
        return Err(CognitiveStoreError::Conflict(
            "cognitive context owner read changed before authentication".to_string(),
        )
        .into());
    }

    let records = read
        .records()
        .iter()
        .map(|record| (record.record_id.as_str(), record))
        .collect::<BTreeMap<_, _>>();
    let mut record_set = CONTEXT_RECORD_SET_DOMAIN.to_vec();
    for item in items {
        let text_digest = Sha256Digest::for_bytes(item.content.as_bytes());
        if text_digest.as_str() != item.content_sha256.as_str() {
            return Err(CognitiveStoreError::Invalid(
                "cognitive context content hash mismatch".to_string(),
            )
            .into());
        }
        let expected_content = parse_digest(&item.content_sha256, "content digest")?;
        let current = records.get(item.memory_id.as_str()).ok_or_else(|| {
            CognitiveStoreError::Conflict("cognitive context item disappeared".to_string())
        })?;
        if !current.is_live()
            || current.revision.get() != item.revision
            || current.content_digest != Some(expected_content)
        {
            return Err(CognitiveStoreError::Conflict(
                "cognitive context item changed before authentication".to_string(),
            )
            .into());
        }
        push_bytes(&mut record_set, item.memory_id.as_bytes());
        record_set.extend_from_slice(&item.revision.to_be_bytes());
        push_digest(&mut record_set, expected_content);
    }
    let record_count = u16::try_from(items.len()).map_err(|error| {
        CognitiveStoreError::Invalid(format!("invalid authenticated context count: {error}"))
    })?;
    Ok(AuthenticatedPacketV2 {
        snapshot_digest: expected_snapshot,
        read_binding_digest: actual_read,
        record_set_digest: Digest32::of_bytes(&record_set),
        record_count,
    })
}

fn read_selected_items(
    cut: &DurableCognitiveSnapshot,
    items: &[CognitiveContextItem],
) -> Result<ReadIdsResultV1, CognitiveContextError> {
    let record_ids = items
        .iter()
        .map(|item| {
            codex_hepta_types::StableId::new(item.memory_id.as_str())
                .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))
        })
        .collect::<Result<Vec<_>, _>>()?;
    cut.read_ids(ReadIdsRequestV1 {
        snapshot_digest: cut.snapshot().snapshot_digest,
        record_ids,
        fields: vec![ReadFieldV1::ContentDigest],
        maximum_encoded_bytes: MAX_ENCODED_READ_RESULT_BYTES_V2,
    })
    .map_err(map_read_ids_error)
}

fn map_read_ids_error(error: ReadIdsError) -> CognitiveContextError {
    let message = error.to_string();
    match error {
        ReadIdsError::Read(error) => {
            CognitiveContextError::Store(CognitiveStoreError::Corrupt(error.to_string()))
        }
        ReadIdsError::InvalidCanonicalEncoding => CognitiveContextError::Store(
            CognitiveStoreError::Corrupt("invalid canonical exact-id cognitive read".to_string()),
        ),
        ReadIdsError::TooManyRecordIds { .. }
        | ReadIdsError::DuplicateRecordId
        | ReadIdsError::DuplicateField
        | ReadIdsError::InvalidMaximumEncodedBytes { .. } => {
            CognitiveContextError::Store(CognitiveStoreError::Invalid(message))
        }
        ReadIdsError::EncodedResultTooLarge { .. } => {
            CognitiveContextError::ReadUnavailable(message)
        }
    }
}

fn bind_selected_read(
    cut: &DurableCognitiveSnapshot,
    read: &ReadIdsResultV1,
    retrieval_context: Option<Digest32>,
) -> Digest32 {
    let mut bytes = CONTEXT_READ_BINDING_DOMAIN.to_vec();
    bytes.extend_from_slice(cut.cut_digest().as_array());
    bytes.extend_from_slice(read.receipt_digest().as_array());
    if let Some(context) = retrieval_context {
        bytes.extend_from_slice(context.as_array());
    }
    Digest32::of_bytes(&bytes)
}

pub(super) async fn current_retrieval_digest(
    current: Option<&Arc<dyn CurrentMemoryRetrievalContext>>,
    owner: &AgentId,
    body_generation: u64,
) -> Result<Option<Digest32>, CognitiveContextError> {
    let Some(current) = current else {
        return Ok(None);
    };
    let current = Arc::clone(current);
    let owner = owner.clone();
    let context = tokio::task::spawn_blocking(move || current.current(&owner, body_generation))
        .await
        .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)?
        .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)?;
    context
        .validate()
        .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)?;
    Ok(Some(RetrievalExecutionContextV1::binding_digest(&context)))
}

pub(super) async fn current_ranker_policy_digest(
    ranker: Option<&Arc<PinnedCognitiveRanker>>,
    owner: &AgentId,
    body_generation: u64,
    query: &str,
) -> Result<Option<Digest32>, CognitiveContextError> {
    let Some(ranker) = ranker else {
        return Ok(None);
    };
    let ranker = Arc::clone(ranker);
    let owner = owner.clone();
    let query = query.to_string();
    let observation = tokio::task::spawn_blocking(move || {
        let mut empty = Vec::new();
        ranker.rank(&owner, body_generation, &query, &mut empty)
    })
    .await
    .map_err(|_| CognitiveContextError::RankerUnavailable)?
    .map_err(|_| CognitiveContextError::RankerUnavailable)?;
    Ok(Some(observation.policy_digest))
}

pub(super) fn request_binding_digest(
    owner: &AgentId,
    body_generation: u64,
    query: &str,
    limit: u16,
    request_id: Option<u64>,
    retrieval_context_digest: Option<Digest32>,
    ranker_policy_digest: Option<Digest32>,
) -> Digest32 {
    let mut bytes = CONTEXT_REQUEST_BINDING_DOMAIN.to_vec();
    push_bytes(&mut bytes, owner.as_str().as_bytes());
    bytes.extend_from_slice(&body_generation.to_be_bytes());
    push_bytes(&mut bytes, query.as_bytes());
    bytes.extend_from_slice(&limit.to_be_bytes());
    match request_id {
        Some(request_id) => {
            bytes.push(1);
            bytes.extend_from_slice(&request_id.to_be_bytes());
        }
        None => bytes.push(0),
    }
    push_optional_digest(&mut bytes, retrieval_context_digest);
    push_optional_digest(&mut bytes, ranker_policy_digest);
    Digest32::of_bytes(&bytes)
}

pub(super) fn register_issued_seal(
    seal: IssuedContextSealV2,
) -> Result<Digest32, CognitiveContextError> {
    let digest = seal.digest();
    let now = monotonic_micros()?;
    let mut issued = ISSUED_CONTEXT_SEALS
        .get_or_init(|| Mutex::new(BTreeMap::new()))
        .lock()
        .map_err(|_| {
            CognitiveStoreError::Unavailable("context delivery seal registry poisoned".to_string())
        })?;
    issued.retain(|_, existing| existing.expires_at_micros > now);
    if let Some(existing) = issued.get(&digest) {
        if existing == &seal {
            return Ok(digest);
        }
        return Err(CognitiveStoreError::Conflict(
            "context delivery seal digest collision".to_string(),
        )
        .into());
    }
    if issued.len() >= MAX_ISSUED_CONTEXT_SEALS {
        return Err(CognitiveStoreError::Unavailable(
            "context delivery seal registry is full".to_string(),
        )
        .into());
    }
    issued.insert(digest, seal);
    Ok(digest)
}

pub(super) fn issued_seal(
    digest: Digest32,
) -> Result<IssuedContextSealV2, CognitiveContextError> {
    let now = monotonic_micros()?;
    let mut issued = ISSUED_CONTEXT_SEALS
        .get_or_init(|| Mutex::new(BTreeMap::new()))
        .lock()
        .map_err(|_| {
            CognitiveStoreError::Unavailable("context delivery seal registry poisoned".to_string())
        })?;
    issued.retain(|_, existing| existing.expires_at_micros > now);
    issued.get(&digest).cloned().ok_or_else(|| {
        CognitiveStoreError::Conflict(
            "context delivery seal is unknown, expired or belongs to another process generation"
                .to_string(),
        )
        .into()
    })
}

pub(super) fn encode_plan_binding(raw: Digest32, seal: Digest32) -> String {
    format!("{CONTEXT_PLAN_PREFIX}:{raw}:{seal}")
}

pub(super) fn parse_plan_binding(
    value: &str,
) -> Result<(Digest32, Digest32), CognitiveContextError> {
    let mut fields = value.split(':');
    if fields.next() != Some(CONTEXT_PLAN_PREFIX) {
        return Err(CognitiveStoreError::Invalid(
            "cognitive context plan binding version is unsupported".to_string(),
        )
        .into());
    }
    let raw = fields.next().ok_or_else(|| {
        CognitiveStoreError::Invalid("cognitive context plan binding is truncated".to_string())
    })?;
    let seal = fields.next().ok_or_else(|| {
        CognitiveStoreError::Invalid("cognitive context plan binding is truncated".to_string())
    })?;
    if fields.next().is_some() {
        return Err(CognitiveStoreError::Invalid(
            "cognitive context plan binding has trailing fields".to_string(),
        )
        .into());
    }
    Ok((
        parse_digest(raw, "raw planner receipt digest")?,
        parse_digest(seal, "context delivery seal digest")?,
    ))
}

pub(super) fn parse_digest(
    value: &str,
    name: &'static str,
) -> Result<Digest32, CognitiveContextError> {
    value.parse().map_err(|error| {
        CognitiveStoreError::Invalid(format!("invalid {name}: {error}"))
            .into()
    })
}

pub(super) fn monotonic_micros() -> Result<u64, CognitiveContextError> {
    let origin = MONOTONIC_ORIGIN.get_or_init(Instant::now);
    u64::try_from(origin.elapsed().as_micros()).map_err(|error| {
        CognitiveStoreError::Unavailable(format!("context monotonic clock overflow: {error}"))
            .into()
    })
}

fn legacy_now_seconds() -> Result<i64, CognitiveContextError> {
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?
        .as_secs();
    i64::try_from(seconds)
        .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()).into())
}

pub(super) fn push_bytes(bytes: &mut Vec<u8>, value: &[u8]) {
    bytes.extend_from_slice(
        &u64::try_from(value.len())
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    );
    bytes.extend_from_slice(value);
}

pub(super) fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

pub(super) fn push_optional_digest(bytes: &mut Vec<u8>, value: Option<Digest32>) {
    match value {
        Some(value) => {
            bytes.push(1);
            push_digest(bytes, value);
        }
        None => bytes.push(0),
    }
}
