impl SegmentedFileEvidenceFrontierBackend {
    fn fast_latest(
        &self,
        paths: &StorePaths,
        store_id: &str,
    ) -> Result<Option<EvidenceRecoveryFrontierV2>, EvidenceFrontierBackendError> {
        let _active_length = self.current_active_length(paths)?;
        let mut active = self.open_active_existing(paths)?;
        if let Some(file) = active.as_ref() {
            file.lock_shared().map_err(unavailable)?;
        }
        let state = self.load_state_from_active(paths, store_id, active.as_mut())?;
        Ok(state.latest_frontier())
    }

    fn archive_active(
        &mut self,
        paths: &StorePaths,
        store_id: &str,
        active: &mut File,
        state: &SegmentedState,
    ) -> Result<EvidenceFrontierLatestIndexV1, EvidenceFrontierBackendError> {
        let Some(first) = state.active_records.first() else {
            return Err(invalid("cannot archive an empty frontier journal tail"));
        };
        let last = state.active_records.last().expect("non-empty active records");
        let segment_bytes = encode_records(&state.active_records)?;
        if segment_bytes.is_empty()
            || u64::try_from(segment_bytes.len()).unwrap_or(u64::MAX)
                > EVIDENCE_FRONTIER_MAX_JOURNAL_BYTES
        {
            return Err(invalid("frontier segment exceeds the bounded segment size"));
        }
        let segment_file_name = format!(
            "{}.segment.{:020}-{:020}.jsonl",
            paths.token, first.audit_sequence, last.audit_sequence
        );
        let metadata_file_name = format!("{segment_file_name}.meta.json");
        validate_direct_file_name(&segment_file_name)?;
        validate_direct_file_name(&metadata_file_name)?;
        let segment_path = self.legacy.journals.join(&segment_file_name);
        if let Err(error) = write_immutable_private_file(
            &segment_path,
            &self.legacy.journals,
            self.legacy.owner_uid,
            &segment_bytes,
        ) {
            return Err(self.poison(error));
        }
        let segment_file_sha256 = Sha256Digest::for_bytes(&segment_bytes);

        let previous_segment = state.latest_segment().cloned();
        let mut ancestors = Vec::new();
        if let Some(previous) = &previous_segment {
            let mut jump = previous.clone();
            for level in 0..MAX_SEGMENT_ANCESTORS {
                ancestors.push(jump.clone());
                let jump_metadata = if level == 0 {
                    state
                        .latest_segment_metadata
                        .clone()
                        .ok_or_else(|| corrupt("latest segment pointer has no metadata"))?
                } else {
                    self.read_segment_metadata(&jump, store_id)?
                };
                let Some(next) = jump_metadata.ancestors.get(level).cloned() else {
                    break;
                };
                jump = next;
            }
        }
        let mut metadata = EvidenceFrontierSegmentMetadataV1 {
            schema_version: SEGMENT_METADATA_SCHEMA_VERSION,
            backend_id: self.legacy.identity.backend_id.clone(),
            backend_identity_sha256: self.legacy.identity_sha256.clone(),
            store_id: store_id.to_string(),
            segment_file_name: segment_file_name.clone(),
            segment_file_sha256,
            segment_bytes: u64::try_from(segment_bytes.len())
                .map_err(|_| invalid("frontier segment length overflow"))?,
            first_audit_sequence: first.audit_sequence,
            last_audit_sequence: last.audit_sequence,
            first_generation: first.frontier.frontier_generation,
            last_generation: last.frontier.frontier_generation,
            previous_record_sha256: first.previous_record_sha256.clone(),
            last_record_sha256: last.record_sha256.clone(),
            previous_segment,
            ancestors,
            metadata_sha256: Sha256Digest::for_bytes(b"pending"),
        };
        metadata.metadata_sha256 = segment_metadata_sha256(&metadata)?;
        let metadata_bytes = serde_json::to_vec(&metadata).map_err(|error| {
            invalid(&format!("cannot encode frontier segment metadata: {error}"))
        })?;
        if metadata_bytes.len() as u64 > MAX_SEGMENT_METADATA_BYTES {
            return Err(invalid("frontier segment metadata exceeds its bounded size"));
        }
        let metadata_path = self.legacy.journals.join(&metadata_file_name);
        if let Err(error) = write_immutable_private_file(
            &metadata_path,
            &self.legacy.journals,
            self.legacy.owner_uid,
            &metadata_bytes,
        ) {
            return Err(self.poison(error));
        }
        let metadata_file_sha256 = Sha256Digest::for_bytes(&metadata_bytes);
        let pointer = segment_pointer(&metadata, metadata_file_name, metadata_file_sha256);

        let directory = open_pinned_directory(
            &self.legacy.journals,
            self.legacy.owner_uid,
            self.legacy.journals_device,
            self.legacy.journals_inode,
        )?;
        directory.sync_all().map_err(|error| self.poison(error))?;

        let latest_frontier = last.frontier.clone();
        let frontier_sha256 = last.frontier_sha256.clone();
        let archived_bytes = state
            .archived_bytes()
            .checked_add(metadata.segment_bytes)
            .ok_or_else(|| invalid("archived frontier byte count overflow"))?;
        let archive_index = build_index(
            store_id,
            &self.legacy.identity,
            &self.legacy.identity_sha256,
            state
                .segment_count()
                .checked_add(1)
                .ok_or_else(|| invalid("frontier segment count overflow"))?,
            last.audit_sequence,
            archived_bytes,
            Some(pointer),
            state.active_bytes,
            state.active_sha256.clone(),
            last.audit_sequence,
            latest_frontier,
            frontier_sha256,
            last.record_sha256.clone(),
        )?;
        // Publish the immutable segment pointer before truncating the duplicate
        // active prefix. A crash here leaves two exact copies; reopening removes
        // the prefix only after validating its boundary digest and frontier.
        self.write_index_atomic(paths, &archive_index)?;
        active.set_len(0).map_err(|error| self.poison(error))?;
        active
            .seek(SeekFrom::Start(0))
            .map_err(|error| self.poison(error))?;
        active.sync_all().map_err(|error| self.poison(error))?;
        directory.sync_all().map_err(|error| self.poison(error))?;
        Ok(archive_index)
    }
}
