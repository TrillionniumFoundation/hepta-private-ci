fn validate_pointer(
    pointer: &EvidenceFrontierSegmentPointerV1,
) -> Result<(), EvidenceFrontierBackendError> {
    validate_direct_file_name(&pointer.metadata_file_name)?;
    if pointer.first_audit_sequence == 0
        || pointer.first_audit_sequence > pointer.last_audit_sequence
        || pointer.first_generation == 0
        || pointer.first_generation > pointer.last_generation
        || pointer.first_audit_sequence != pointer.first_generation
        || pointer.last_audit_sequence != pointer.last_generation
    {
        return Err(corrupt("frontier segment pointer bounds are invalid"));
    }
    Ok(())
}

fn segment_pointer(
    metadata: &EvidenceFrontierSegmentMetadataV1,
    metadata_file_name: String,
    metadata_file_sha256: Sha256Digest,
) -> EvidenceFrontierSegmentPointerV1 {
    EvidenceFrontierSegmentPointerV1 {
        metadata_file_name,
        metadata_file_sha256,
        first_audit_sequence: metadata.first_audit_sequence,
        last_audit_sequence: metadata.last_audit_sequence,
        first_generation: metadata.first_generation,
        last_generation: metadata.last_generation,
        last_record_sha256: metadata.last_record_sha256.clone(),
    }
}

fn parse_active_records(
    bytes: &[u8],
    store_id: &str,
    identity: &EvidenceFrontierBackendIdentityV1,
    identity_sha256: &Sha256Digest,
    cursor: &ChainCursor,
) -> Result<Vec<EvidenceFrontierAuditRecordV1>, EvidenceFrontierBackendError> {
    if bytes.is_empty() {
        return Ok(Vec::new());
    }
    match parse_records(bytes, store_id, identity, identity_sha256, cursor.clone()) {
        Ok(records) => Ok(records),
        Err(primary_error) if cursor.next_audit_sequence > 1 => {
            let complete = parse_records(
                bytes,
                store_id,
                identity,
                identity_sha256,
                ChainCursor::initial(),
            )?;
            let boundary_sequence = cursor.next_audit_sequence - 1;
            let Some(boundary) = complete
                .iter()
                .find(|record| record.audit_sequence == boundary_sequence)
            else {
                return Err(primary_error);
            };
            if Some(boundary.frontier.frontier_generation) != cursor.previous_generation
                || Some(boundary.record_sha256.clone()) != cursor.previous_record_sha256
                || cursor
                    .previous_frontier
                    .as_ref()
                    .is_some_and(|frontier| frontier != &boundary.frontier)
            {
                return Err(corrupt(
                    "duplicate active prefix conflicts with the sealed segment boundary",
                ));
            }
            Ok(complete
                .into_iter()
                .filter(|record| record.audit_sequence >= cursor.next_audit_sequence)
                .collect())
        }
        Err(error) => Err(error),
    }
}

fn parse_records(
    bytes: &[u8],
    store_id: &str,
    identity: &EvidenceFrontierBackendIdentityV1,
    identity_sha256: &Sha256Digest,
    mut cursor: ChainCursor,
) -> Result<Vec<EvidenceFrontierAuditRecordV1>, EvidenceFrontierBackendError> {
    if bytes.is_empty() {
        return Ok(Vec::new());
    }
    if bytes.len() as u64 > EVIDENCE_FRONTIER_MAX_JOURNAL_BYTES {
        return Err(corrupt("frontier audit segment exceeds its bounded size"));
    }
    if bytes.last().copied() != Some(b'\n') {
        return Err(corrupt("frontier audit segment has a torn tail"));
    }
    let mut records = Vec::new();
    for line in bytes[..bytes.len() - 1].split(|byte| *byte == b'\n') {
        if line.is_empty() {
            return Err(corrupt("frontier audit segment contains an empty record"));
        }
        if line.len() > EVIDENCE_FRONTIER_MAX_AUDIT_RECORD_BYTES
            || records.len() >= EVIDENCE_FRONTIER_MAX_AUDIT_RECORDS
        {
            return Err(corrupt("frontier audit segment exceeds a bounded record limit"));
        }
        let record: EvidenceFrontierAuditRecordV1 = serde_json::from_slice(line).map_err(|error| {
            corrupt(&format!("cannot decode frontier audit record: {error}"))
        })?;
        if record.schema_version != EVIDENCE_FRONTIER_AUDIT_RECORD_SCHEMA_VERSION
            || record.audit_sequence != cursor.next_audit_sequence
            || record.backend_id != identity.backend_id
            || &record.backend_identity_sha256 != identity_sha256
            || record.store_id != store_id
            || record.expected_generation != cursor.previous_generation
            || record.previous_record_sha256 != cursor.previous_record_sha256
        {
            return Err(corrupt("frontier audit chain metadata is inconsistent"));
        }
        record.frontier.validate_structure().map_err(|error| {
            corrupt(&format!("stored frontier is invalid: {error}"))
        })?;
        let required_generation = cursor
            .previous_generation
            .unwrap_or(0)
            .checked_add(1)
            .ok_or_else(|| corrupt("stored frontier generation overflow"))?;
        if record.frontier.store_id != store_id
            || &record.frontier.backend_identity_sha256 != identity_sha256
            || record.frontier.frontier_generation != required_generation
            || record.frontier_sha256
                != evidence_recovery_frontier_v2_sha256(&record.frontier).map_err(|error| {
                    corrupt(&format!("cannot hash stored frontier: {error}"))
                })?
            || record.record_sha256 != audit_record_sha256(&record)?
        {
            return Err(corrupt(
                "frontier audit record digest or generation is inconsistent",
            ));
        }
        if let Some(previous) = cursor.previous_frontier.as_ref() {
            let decision = crate::classify_frontier_merge(previous, &record.frontier);
            if decision != crate::FrontierMergeDecision::IncomingWins {
                return Err(corrupt(&format!(
                    "frontier audit segment contains a non-automatic transition: {decision:?}"
                )));
            }
        }
        cursor.advance(&record)?;
        records.push(record);
    }
    Ok(records)
}

fn encode_record(
    record: &EvidenceFrontierAuditRecordV1,
) -> Result<Vec<u8>, EvidenceFrontierBackendError> {
    let mut bytes = serde_json::to_vec(record).map_err(|error| {
        invalid(&format!("cannot serialize frontier audit record: {error}"))
    })?;
    bytes.push(b'\n');
    if bytes.len() > EVIDENCE_FRONTIER_MAX_AUDIT_RECORD_BYTES {
        return Err(invalid("frontier audit record exceeds the bounded frame size"));
    }
    Ok(bytes)
}

fn encode_records(
    records: &[EvidenceFrontierAuditRecordV1],
) -> Result<Vec<u8>, EvidenceFrontierBackendError> {
    let mut bytes = Vec::new();
    for record in records {
        bytes.extend_from_slice(&encode_record(record)?);
    }
    Ok(bytes)
}
