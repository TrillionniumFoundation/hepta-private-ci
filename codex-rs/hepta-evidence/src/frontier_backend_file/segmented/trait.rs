impl EvidenceFrontierBackend for SegmentedFileEvidenceFrontierBackend {
    fn get_latest(
        &mut self,
        store_id: &str,
    ) -> Result<Option<EvidenceRecoveryFrontierV2>, EvidenceFrontierBackendError> {
        self.ensure_available()?;
        self.verify_backend_identity()?;
        let paths = self.paths(store_id)?;
        let lock = self.open_store_lock(&paths)?;
        lock.lock_shared().map_err(unavailable)?;
        if let Some(frontier) = self.fast_latest(&paths, store_id)? {
            return Ok(Some(frontier));
        }
        let mut active = self.open_active_existing(&paths)?;
        if let Some(file) = active.as_ref() {
            file.lock_shared().map_err(unavailable)?;
        }
        let state = self.load_state_from_active(&paths, store_id, active.as_mut())?;
        Ok(state.latest_frontier())
    }

    fn compare_and_swap(
        &mut self,
        store_id: &str,
        expected_generation: Option<u64>,
        new_frontier: &EvidenceRecoveryFrontierV2,
    ) -> Result<EvidenceFrontierDurableAckV1, EvidenceFrontierBackendError> {
        self.ensure_available()?;
        self.verify_backend_identity()?;
        new_frontier.validate_structure().map_err(|error| {
            invalid(&format!("invalid proposed frontier: {error}"))
        })?;
        if new_frontier.store_id != store_id
            || new_frontier.backend_identity_sha256 != self.legacy.identity_sha256
        {
            return Err(invalid(
                "proposed frontier is not bound to this store and backend",
            ));
        }
        let paths = self.paths(store_id)?;
        let lock = self.open_store_lock(&paths)?;
        lock.lock().map_err(unavailable)?;
        let mut active = self.open_active_writable(&paths)?;
        active.lock().map_err(unavailable)?;
        let mut state = self.load_state_from_active(&paths, store_id, Some(&mut active))?;
        let actual_generation = state.latest_generation();
        if actual_generation != expected_generation {
            return Err(EvidenceFrontierBackendError::Conflict {
                expected: expected_generation,
                actual: actual_generation,
            });
        }
        if let Some(current) = state.latest_frontier() {
            match crate::classify_frontier_merge(&current, new_frontier) {
                crate::FrontierMergeDecision::IncomingWins => {}
                crate::FrontierMergeDecision::ExactDuplicate => {
                    return Err(invalid(
                        "proposed frontier is an exact duplicate, not a new generation",
                    ));
                }
                crate::FrontierMergeDecision::IncomingStale => {
                    return Err(invalid("proposed frontier is stale"));
                }
                crate::FrontierMergeDecision::ConflictSameOrderDifferentIdentity => {
                    return Err(invalid(
                        "proposed frontier has a same-generation identity conflict",
                    ));
                }
                crate::FrontierMergeDecision::InvalidIncoming => {
                    return Err(invalid("proposed frontier is structurally invalid"));
                }
                crate::FrontierMergeDecision::InvalidCurrent => {
                    return Err(corrupt(
                        "accepted frontier is structurally invalid under the store lock",
                    ));
                }
                crate::FrontierMergeDecision::RepairRequired => {
                    return Err(invalid(
                        "proposed frontier requires an exact signed repair transition",
                    ));
                }
            }
        }
        let required_generation = actual_generation
            .unwrap_or(0)
            .checked_add(1)
            .ok_or_else(|| invalid("frontier generation exhausted its numeric domain"))?;
        if new_frontier.frontier_generation != required_generation {
            return Err(invalid(&format!(
                "frontier generation must advance exactly to {required_generation}"
            )));
        }
        let audit_sequence = state
            .latest_audit_sequence()
            .checked_add(1)
            .ok_or_else(|| invalid("frontier audit sequence exhausted its numeric domain"))?;
        let frontier_sha256 = evidence_recovery_frontier_v2_sha256(new_frontier).map_err(|error| {
            invalid(&format!("cannot hash proposed frontier: {error}"))
        })?;
        let mut record = EvidenceFrontierAuditRecordV1 {
            schema_version: EVIDENCE_FRONTIER_AUDIT_RECORD_SCHEMA_VERSION,
            audit_sequence,
            backend_id: self.legacy.identity.backend_id.clone(),
            backend_identity_sha256: self.legacy.identity_sha256.clone(),
            store_id: store_id.to_string(),
            expected_generation,
            frontier: new_frontier.clone(),
            frontier_sha256: frontier_sha256.clone(),
            previous_record_sha256: state.latest_record_sha256(),
            record_sha256: Sha256Digest::for_bytes(b"pending"),
        };
        record.record_sha256 = audit_record_sha256(&record)?;
        let encoded = encode_record(&record)?;
        let should_archive = !state.active_records.is_empty()
            && (state.active_records.len() >= ACTIVE_SEGMENT_MAX_RECORDS
                || state
                    .active_bytes
                    .checked_add(u64::try_from(encoded.len()).unwrap_or(u64::MAX))
                    .is_none_or(|length| length > ACTIVE_SEGMENT_MAX_BYTES));
        if should_archive {
            let archive_index = self.archive_active(&paths, store_id, &mut active, &state)?;
            state = SegmentedState {
                latest_segment_metadata: archive_index
                    .latest_segment
                    .as_ref()
                    .map(|pointer| self.read_segment_metadata(pointer, store_id))
                    .transpose()?,
                index: Some(archive_index),
                active_records: Vec::new(),
                active_bytes: 0,
                active_sha256: Sha256Digest::for_bytes(&[]),
            };
        }
        if encoded.len() as u64 > ACTIVE_SEGMENT_MAX_BYTES {
            return Err(invalid("one frontier audit record exceeds the active segment bound"));
        }
        let current_length = active.metadata().map_err(unavailable)?.len();
        if current_length != state.active_bytes {
            return Err(corrupt(
                "active frontier journal length changed under the store lock",
            ));
        }
        let expected_length = current_length
            .checked_add(u64::try_from(encoded.len()).map_err(|_| {
                invalid("frontier audit record length exceeds the numeric domain")
            })?)
            .ok_or_else(|| invalid("active frontier journal length overflow"))?;
        if expected_length > ACTIVE_SEGMENT_MAX_BYTES {
            return Err(invalid("active frontier segment reached its byte bound"));
        }
        let directory = open_pinned_directory(
            &self.legacy.journals,
            self.legacy.owner_uid,
            self.legacy.journals_device,
            self.legacy.journals_inode,
        )?;
        active.seek(SeekFrom::End(0)).map_err(unavailable)?;
        let write_result = active
            .write_all(&encoded)
            .and_then(|()| active.sync_all())
            .and_then(|()| directory.sync_all());
        if let Err(error) = write_result {
            return Err(self.poison(error));
        }
        let index = build_index(
            store_id,
            &self.legacy.identity,
            &self.legacy.identity_sha256,
            state.segment_count(),
            state.archived_records(),
            state.archived_bytes(),
            state.latest_segment().cloned(),
            expected_length,
            Sha256Digest::for_bytes(&read_locked_bytes(
                &mut active,
                ACTIVE_SEGMENT_MAX_BYTES,
            )?),
            audit_sequence,
            new_frontier.clone(),
            frontier_sha256.clone(),
            record.record_sha256.clone(),
        )?;
        self.write_index_atomic(&paths, &index)?;
        Ok(EvidenceFrontierDurableAckV1 {
            backend_id: self.legacy.identity.backend_id.clone(),
            backend_identity_sha256: self.legacy.identity_sha256.clone(),
            store_id: store_id.to_string(),
            frontier_generation: new_frontier.frontier_generation,
            frontier_sha256,
            audit_sequence,
        })
    }

    fn get_history(
        &mut self,
        store_id: &str,
        range: EvidenceFrontierHistoryRangeV1,
    ) -> Result<Vec<EvidenceRecoveryFrontierV2>, EvidenceFrontierBackendError> {
        self.ensure_available()?;
        self.verify_backend_identity()?;
        let paths = self.paths(store_id)?;
        let lock = self.open_store_lock(&paths)?;
        lock.lock_shared().map_err(unavailable)?;
        let mut active = self.open_active_existing(&paths)?;
        if let Some(file) = active.as_ref() {
            file.lock_shared().map_err(unavailable)?;
        }
        let state = self.load_state_from_active(&paths, store_id, active.as_mut())?;
        let mut result = Vec::new();
        let archived_last = state.archived_records();
        if archived_last > 0 && range.first_generation() <= archived_last {
            let requested_last = range.last_generation().min(archived_last);
            let latest = state
                .latest_segment()
                .cloned()
                .ok_or_else(|| corrupt("archived frontier history has no latest segment"))?;
            if let Some(mut metadata) = self.locate_segment(store_id, latest, requested_last)? {
                loop {
                    let records = self.read_segment_records(store_id, &metadata)?;
                    for record in records {
                        if (range.first_generation()..=range.last_generation())
                            .contains(&record.frontier.frontier_generation)
                        {
                            result.push(record.frontier);
                        }
                    }
                    if metadata.first_generation <= range.first_generation() {
                        break;
                    }
                    let Some(previous) = metadata.previous_segment.clone() else {
                        break;
                    };
                    metadata = self.read_segment_metadata(&previous, store_id)?;
                }
                result.sort_by_key(|frontier| frontier.frontier_generation);
            }
        }
        for record in state.active_records {
            if (range.first_generation()..=range.last_generation())
                .contains(&record.frontier.frontier_generation)
            {
                result.push(record.frontier);
            }
        }
        result.sort_by_key(|frontier| frontier.frontier_generation);
        result.dedup_by_key(|frontier| frontier.frontier_generation);
        Ok(result)
    }

    fn verify_backend_identity(
        &mut self,
    ) -> Result<EvidenceFrontierBackendIdentityV1, EvidenceFrontierBackendError> {
        self.legacy.verify_backend_identity()
    }
}
