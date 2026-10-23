impl SegmentedFileEvidenceFrontierBackend {
    fn write_index_atomic(
        &mut self,
        paths: &StorePaths,
        index: &EvidenceFrontierLatestIndexV1,
    ) -> Result<(), EvidenceFrontierBackendError> {
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            use std::time::SystemTime;
            use std::time::UNIX_EPOCH;

            let bytes = serde_json::to_vec(index).map_err(|error| {
                invalid(&format!("cannot encode frontier latest index: {error}"))
            })?;
            if bytes.is_empty() || bytes.len() as u64 > MAX_INDEX_BYTES {
                return Err(invalid("frontier latest index exceeds its bounded size"));
            }
            let nonce = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map(|duration| duration.as_nanos())
                .unwrap_or_default();
            let temporary = self.legacy.journals.join(format!(
                "{}.tmp.{}.{}.{}",
                paths
                    .index
                    .file_name()
                    .and_then(|name| name.to_str())
                    .ok_or_else(|| invalid("frontier latest index filename is invalid"))?,
                std::process::id(),
                index.audit_sequence,
                nonce
            ));
            validate_direct_path(&temporary, &self.legacy.journals)?;
            let write_result = (|| -> io::Result<()> {
                let mut file = OpenOptions::new()
                    .write(true)
                    .create_new(true)
                    .mode(0o600)
                    .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
                    .open(&temporary)?;
                file.write_all(&bytes)?;
                file.sync_all()?;
                std::fs::rename(&temporary, &paths.index)?;
                let directory = open_pinned_directory(
                    &self.legacy.journals,
                    self.legacy.owner_uid,
                    self.legacy.journals_device,
                    self.legacy.journals_inode,
                )
                .map_err(backend_error_to_io)?;
                directory.sync_all()
            })();
            if let Err(error) = write_result {
                return Err(self.poison(error));
            }
            Ok(())
        }
        #[cfg(not(unix))]
        {
            let _ = (paths, index);
            Err(EvidenceFrontierBackendError::Unsupported)
        }
    }

    fn reconstruct_index(
        &self,
        store_id: &str,
        state: &SegmentedState,
        active_bytes: u64,
    ) -> Result<Option<EvidenceFrontierLatestIndexV1>, EvidenceFrontierBackendError> {
        let Some(frontier) = state.latest_frontier() else {
            return Ok(None);
        };
        let audit_sequence = state.latest_audit_sequence();
        let record_sha256 = state
            .latest_record_sha256()
            .ok_or_else(|| corrupt("latest frontier has no audit record digest"))?;
        let frontier_sha256 = evidence_recovery_frontier_v2_sha256(&frontier).map_err(|error| {
            corrupt(&format!("cannot hash latest frontier: {error}"))
        })?;
        build_index(
            store_id,
            &self.legacy.identity,
            &self.legacy.identity_sha256,
            state.segment_count(),
            state.archived_records(),
            state.archived_bytes(),
            state.latest_segment().cloned(),
            active_bytes,
            state.active_sha256.clone(),
            audit_sequence,
            frontier,
            frontier_sha256,
            record_sha256,
        )
        .map(Some)
    }

    fn record_for_generation(
        &self,
        store_id: &str,
        state: &SegmentedState,
        generation: u64,
    ) -> Result<Option<RecoveredPublication>, EvidenceFrontierBackendError> {
        if let Some(record) = state
            .active_records
            .iter()
            .find(|record| record.frontier.frontier_generation == generation)
        {
            return Ok(Some(RecoveredPublication {
                frontier_sha256: record.frontier_sha256.clone(),
                audit_sequence: record.audit_sequence,
                durable_path: self.paths(store_id)?.active,
            }));
        }
        let Some(latest_pointer) = state.latest_segment().cloned() else {
            return Ok(None);
        };
        let Some(metadata) = self.locate_segment(store_id, latest_pointer, generation)? else {
            return Ok(None);
        };
        let records = self.read_segment_records(store_id, &metadata)?;
        let record = records
            .into_iter()
            .find(|record| record.frontier.frontier_generation == generation);
        let path = self.legacy.journals.join(&metadata.segment_file_name);
        Ok(record.map(|record| RecoveredPublication {
            frontier_sha256: record.frontier_sha256,
            audit_sequence: record.audit_sequence,
            durable_path: path,
        }))
    }

    fn locate_segment(
        &self,
        store_id: &str,
        mut pointer: EvidenceFrontierSegmentPointerV1,
        generation: u64,
    ) -> Result<Option<EvidenceFrontierSegmentMetadataV1>, EvidenceFrontierBackendError> {
        loop {
            if generation > pointer.last_generation {
                return Ok(None);
            }
            let metadata = self.read_segment_metadata(&pointer, store_id)?;
            if (metadata.first_generation..=metadata.last_generation).contains(&generation) {
                return Ok(Some(metadata));
            }
            if generation >= metadata.first_generation {
                return Ok(None);
            }
            let jump = metadata
                .ancestors
                .iter()
                .rev()
                .find(|ancestor| ancestor.first_generation > generation)
                .cloned()
                .or_else(|| metadata.previous_segment.clone());
            let Some(next) = jump else {
                return Ok(None);
            };
            pointer = next;
        }
    }

}
