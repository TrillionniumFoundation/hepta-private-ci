fn build_index(
    store_id: &str,
    identity: &EvidenceFrontierBackendIdentityV1,
    identity_sha256: &Sha256Digest,
    segment_count: u64,
    archived_records: u64,
    archived_bytes: u64,
    latest_segment: Option<EvidenceFrontierSegmentPointerV1>,
    active_journal_bytes: u64,
    active_journal_sha256: Sha256Digest,
    audit_sequence: u64,
    frontier: EvidenceRecoveryFrontierV2,
    frontier_sha256: Sha256Digest,
    record_sha256: Sha256Digest,
) -> Result<EvidenceFrontierLatestIndexV1, EvidenceFrontierBackendError> {
    let mut index = EvidenceFrontierLatestIndexV1 {
        schema_version: LATEST_INDEX_SCHEMA_VERSION,
        backend_id: identity.backend_id.clone(),
        backend_identity_sha256: identity_sha256.clone(),
        store_id: store_id.to_string(),
        segment_count,
        archived_records,
        archived_bytes,
        latest_segment,
        active_journal_bytes,
        active_journal_sha256,
        audit_sequence,
        frontier_generation: frontier.frontier_generation,
        frontier_sha256,
        record_sha256,
        frontier,
        index_sha256: Sha256Digest::for_bytes(b"pending"),
    };
    index.index_sha256 = latest_index_sha256(&index)?;
    Ok(index)
}

fn validate_index(
    index: &EvidenceFrontierLatestIndexV1,
    store_id: &str,
    identity: &EvidenceFrontierBackendIdentityV1,
    identity_sha256: &Sha256Digest,
) -> Result<(), EvidenceFrontierBackendError> {
    if index.schema_version != LATEST_INDEX_SCHEMA_VERSION
        || index.backend_id != identity.backend_id
        || &index.backend_identity_sha256 != identity_sha256
        || index.store_id != store_id
        || index.audit_sequence == 0
        || index.frontier_generation == 0
        || index.frontier_generation != index.audit_sequence
        || index.frontier.frontier_generation != index.frontier_generation
        || index.frontier.store_id != store_id
        || &index.frontier.backend_identity_sha256 != identity_sha256
        || index.frontier_sha256
            != evidence_recovery_frontier_v2_sha256(&index.frontier)
                .map_err(|error| corrupt(&format!("cannot hash indexed frontier: {error}")))?
        || index.index_sha256 != latest_index_sha256(index)?
        || index.archived_records > index.audit_sequence
        || index.segment_count == 0 && index.latest_segment.is_some()
        || index.segment_count > 0 && index.latest_segment.is_none()
    {
        return Err(corrupt(
            "frontier latest index identity or digest is inconsistent",
        ));
    }
    if let Some(pointer) = &index.latest_segment {
        validate_pointer(pointer)?;
        if pointer.last_audit_sequence != index.archived_records
            || pointer.last_generation != index.archived_records
            || pointer.last_audit_sequence > index.audit_sequence
        {
            return Err(corrupt(
                "frontier latest segment pointer conflicts with index bounds",
            ));
        }
    } else if index.archived_records != 0 || index.archived_bytes != 0 {
        return Err(corrupt(
            "frontier index has archive counters without a segment",
        ));
    }
    Ok(())
}

fn latest_index_sha256(
    index: &EvidenceFrontierLatestIndexV1,
) -> Result<Sha256Digest, EvidenceFrontierBackendError> {
    let payload = EvidenceFrontierLatestIndexPayloadV1 {
        schema_version: index.schema_version,
        backend_id: &index.backend_id,
        backend_identity_sha256: &index.backend_identity_sha256,
        store_id: &index.store_id,
        segment_count: index.segment_count,
        archived_records: index.archived_records,
        archived_bytes: index.archived_bytes,
        latest_segment: index.latest_segment.as_ref(),
        active_journal_bytes: index.active_journal_bytes,
        active_journal_sha256: &index.active_journal_sha256,
        audit_sequence: index.audit_sequence,
        frontier_generation: index.frontier_generation,
        frontier_sha256: &index.frontier_sha256,
        record_sha256: &index.record_sha256,
        frontier: &index.frontier,
    };
    let bytes = serde_json::to_vec(&payload)
        .map_err(|error| invalid(&format!("cannot hash frontier latest index: {error}")))?;
    Ok(Sha256Digest::for_bytes(&bytes))
}

fn segment_metadata_sha256(
    metadata: &EvidenceFrontierSegmentMetadataV1,
) -> Result<Sha256Digest, EvidenceFrontierBackendError> {
    let payload = EvidenceFrontierSegmentMetadataPayloadV1 {
        schema_version: metadata.schema_version,
        backend_id: &metadata.backend_id,
        backend_identity_sha256: &metadata.backend_identity_sha256,
        store_id: &metadata.store_id,
        segment_file_name: &metadata.segment_file_name,
        segment_file_sha256: &metadata.segment_file_sha256,
        segment_bytes: metadata.segment_bytes,
        first_audit_sequence: metadata.first_audit_sequence,
        last_audit_sequence: metadata.last_audit_sequence,
        first_generation: metadata.first_generation,
        last_generation: metadata.last_generation,
        previous_record_sha256: metadata.previous_record_sha256.as_ref(),
        last_record_sha256: &metadata.last_record_sha256,
        previous_segment: metadata.previous_segment.as_ref(),
        ancestors: &metadata.ancestors,
    };
    let bytes = serde_json::to_vec(&payload)
        .map_err(|error| invalid(&format!("cannot hash frontier segment metadata: {error}")))?;
    Ok(Sha256Digest::for_bytes(&bytes))
}

fn validate_segment_metadata(
    metadata: &EvidenceFrontierSegmentMetadataV1,
    store_id: &str,
    identity: &EvidenceFrontierBackendIdentityV1,
    identity_sha256: &Sha256Digest,
) -> Result<(), EvidenceFrontierBackendError> {
    validate_direct_file_name(&metadata.segment_file_name)?;
    if metadata.schema_version != SEGMENT_METADATA_SCHEMA_VERSION
        || metadata.backend_id != identity.backend_id
        || &metadata.backend_identity_sha256 != identity_sha256
        || metadata.store_id != store_id
        || metadata.segment_bytes == 0
        || metadata.segment_bytes > EVIDENCE_FRONTIER_MAX_JOURNAL_BYTES
        || metadata.first_audit_sequence == 0
        || metadata.first_audit_sequence > metadata.last_audit_sequence
        || metadata.first_generation == 0
        || metadata.first_generation > metadata.last_generation
        || metadata.first_audit_sequence != metadata.first_generation
        || metadata.last_audit_sequence != metadata.last_generation
        || metadata.metadata_sha256 != segment_metadata_sha256(metadata)?
        || metadata.ancestors.len() > MAX_SEGMENT_ANCESTORS
    {
        return Err(corrupt(
            "frontier segment metadata identity or bounds are invalid",
        ));
    }
    match (&metadata.previous_segment, metadata.ancestors.first()) {
        (Some(previous), Some(first)) if previous == first => {
            validate_pointer(previous)?;
            if previous.last_audit_sequence.checked_add(1) != Some(metadata.first_audit_sequence)
                || previous.last_generation.checked_add(1) != Some(metadata.first_generation)
                || metadata.previous_record_sha256.as_ref() != Some(&previous.last_record_sha256)
            {
                return Err(corrupt("frontier segment predecessor is not contiguous"));
            }
        }
        (None, None)
            if metadata.first_audit_sequence == 1
                && metadata.first_generation == 1
                && metadata.previous_record_sha256.is_none() => {}
        _ => return Err(corrupt("frontier segment ancestor chain is inconsistent")),
    }
    let mut seen = BTreeSet::new();
    for ancestor in &metadata.ancestors {
        validate_pointer(ancestor)?;
        if !seen.insert(ancestor.metadata_file_name.clone()) {
            return Err(corrupt(
                "frontier segment ancestor chain contains a duplicate",
            ));
        }
    }
    Ok(())
}
