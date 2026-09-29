impl SegmentedFileEvidenceFrontierBackend {
    fn read_segment_records(
        &self,
        store_id: &str,
        metadata: &EvidenceFrontierSegmentMetadataV1,
    ) -> Result<Vec<EvidenceFrontierAuditRecordV1>, EvidenceFrontierBackendError> {
        validate_segment_metadata(
            metadata,
            store_id,
            &self.legacy.identity,
            &self.legacy.identity_sha256,
        )?;
        let path = self.legacy.journals.join(&metadata.segment_file_name);
        let bytes = read_private_regular_file(
            &path,
            &self.legacy.journals,
            self.legacy.owner_uid,
            EVIDENCE_FRONTIER_MAX_JOURNAL_BYTES,
        )?;
        if bytes.len() as u64 != metadata.segment_bytes
            || Sha256Digest::for_bytes(&bytes) != metadata.segment_file_sha256
        {
            return Err(corrupt("frontier segment bytes differ from immutable metadata"));
        }
        let cursor = ChainCursor {
            next_audit_sequence: metadata.first_audit_sequence,
            previous_generation: metadata
                .first_generation
                .checked_sub(1)
                .filter(|generation| *generation > 0),
            previous_record_sha256: metadata.previous_record_sha256.clone(),
        };
        let records = parse_records(
            &bytes,
            store_id,
            &self.legacy.identity,
            &self.legacy.identity_sha256,
            cursor,
        )?;
        let Some(first) = records.first() else {
            return Err(corrupt("frontier segment is empty"));
        };
        let last = records.last().expect("non-empty segment records");
        if first.audit_sequence != metadata.first_audit_sequence
            || last.audit_sequence != metadata.last_audit_sequence
            || first.frontier.frontier_generation != metadata.first_generation
            || last.frontier.frontier_generation != metadata.last_generation
            || first.previous_record_sha256 != metadata.previous_record_sha256
            || last.record_sha256 != metadata.last_record_sha256
        {
            return Err(corrupt("frontier segment boundaries differ from metadata"));
        }
        Ok(records)
    }

    pub fn capacity_status(
        &mut self,
        store_id: &str,
    ) -> Result<EvidenceFrontierCapacityV1, EvidenceFrontierBackendError> {
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
        let active_records = u64::try_from(state.active_records.len())
            .map_err(|_| corrupt("active frontier record count overflow"))?;
        let record_limit = u64::try_from(ACTIVE_SEGMENT_MAX_RECORDS)
            .map_err(|_| invalid("active frontier record limit overflow"))?;
        let record_headroom = record_limit.saturating_sub(active_records);
        let byte_headroom = ACTIVE_SEGMENT_MAX_BYTES.saturating_sub(state.active_bytes);
        let alert = if state.segment_count() >= MAX_SEGMENT_COUNT_ALERT {
            EvidenceFrontierCapacityAlertV1::SegmentCountElevated
        } else if active_records.saturating_mul(5) >= record_limit.saturating_mul(4)
            || state.active_bytes.saturating_mul(5)
                >= ACTIVE_SEGMENT_MAX_BYTES.saturating_mul(4)
        {
            EvidenceFrontierCapacityAlertV1::ActiveNearRollover
        } else {
            EvidenceFrontierCapacityAlertV1::Healthy
        };
        Ok(EvidenceFrontierCapacityV1 {
            schema_version: 1,
            store_id: store_id.to_string(),
            latest_generation: state.latest_generation(),
            segment_count: state.segment_count(),
            archived_records: state.archived_records(),
            archived_bytes: state.archived_bytes(),
            active_records,
            active_bytes: state.active_bytes,
            active_record_limit: record_limit,
            active_byte_limit: ACTIVE_SEGMENT_MAX_BYTES,
            active_record_headroom: record_headroom,
            active_byte_headroom: byte_headroom,
            alert,
        })
    }

    pub fn recover_durable_acknowledgement(
        &mut self,
        store_id: &str,
        frontier_generation: u64,
        expected_frontier_sha256: &Sha256Digest,
    ) -> Result<Option<EvidenceFrontierDurableAckV1>, EvidenceFrontierBackendError> {
        self.ensure_available()?;
        if frontier_generation == 0 {
            return Err(invalid(
                "acknowledgement recovery requires a positive generation",
            ));
        }
        self.verify_backend_identity()?;
        let paths = self.paths(store_id)?;
        let lock = self.open_store_lock(&paths)?;
        lock.try_lock().map_err(|error| {
            EvidenceFrontierBackendError::Unavailable(format!(
                "publication acknowledgement recovery lock unavailable: {error}"
            ))
        })?;
        let mut active = self.open_active_writable(&paths)?;
        active.try_lock().map_err(|error| {
            EvidenceFrontierBackendError::Unavailable(format!(
                "active frontier journal recovery lock unavailable: {error}"
            ))
        })?;
        let state = self.load_state_from_active(&paths, store_id, Some(&mut active))?;
        let Some(publication) =
            self.record_for_generation(store_id, &state, frontier_generation)?
        else {
            return Ok(None);
        };
        if &publication.frontier_sha256 != expected_frontier_sha256 {
            return Err(invalid(
                "historical publication digest differs from the durable dispatch pin",
            ));
        }
        let latest_index = self
            .reconstruct_index(store_id, &state, state.active_bytes)?
            .ok_or_else(|| corrupt("published frontier has no recoverable latest index"))?;
        self.write_index_atomic(&paths, &latest_index)?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;

            let durable_file = OpenOptions::new()
                .read(true)
                .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
                .open(&publication.durable_path)
                .map_err(unavailable)?;
            validate_journal_metadata(&durable_file, self.legacy.owner_uid)?;
            let directory = open_pinned_directory(
                &self.legacy.journals,
                self.legacy.owner_uid,
                self.legacy.journals_device,
                self.legacy.journals_inode,
            )?;
            let index_file = OpenOptions::new()
                .read(true)
                .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
                .open(&paths.index)
                .map_err(unavailable)?;
            let sync_result = durable_file
                .sync_all()
                .and_then(|()| active.sync_all())
                .and_then(|()| index_file.sync_all())
                .and_then(|()| directory.sync_all());
            if let Err(error) = sync_result {
                return Err(self.poison(error));
            }
            Ok(Some(EvidenceFrontierDurableAckV1 {
                backend_id: self.legacy.identity.backend_id.clone(),
                backend_identity_sha256: self.legacy.identity_sha256.clone(),
                store_id: store_id.to_string(),
                frontier_generation,
                frontier_sha256: publication.frontier_sha256,
                audit_sequence: publication.audit_sequence,
            }))
        }
        #[cfg(not(unix))]
        {
            let _ = publication;
            Err(EvidenceFrontierBackendError::Unsupported)
        }
    }
}
