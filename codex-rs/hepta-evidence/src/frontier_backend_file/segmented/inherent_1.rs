impl SegmentedFileEvidenceFrontierBackend {
    pub fn open_external(
        root: &Path,
        expected_identity_sha256: Sha256Digest,
        local_rollback_root: &Path,
    ) -> Result<Self, EvidenceFrontierBackendError> {
        Ok(Self {
            legacy: LegacyLockedFileEvidenceFrontierBackend::open_external(
                root,
                expected_identity_sha256,
                local_rollback_root,
            )?,
        })
    }

    #[cfg(test)]
    pub(crate) fn open_same_filesystem_for_testing(
        root: &Path,
        expected_identity_sha256: Sha256Digest,
        local_rollback_root: &Path,
    ) -> Result<Self, EvidenceFrontierBackendError> {
        Ok(Self {
            legacy: LegacyLockedFileEvidenceFrontierBackend::open_same_filesystem_for_testing(
                root,
                expected_identity_sha256,
                local_rollback_root,
            )?,
        })
    }

    fn ensure_available(&self) -> Result<(), EvidenceFrontierBackendError> {
        self.legacy.ensure_available()
    }

    fn poison(&mut self, error: impl std::fmt::Display) -> EvidenceFrontierBackendError {
        self.legacy.poisoned = true;
        EvidenceFrontierBackendError::Indeterminate(error.to_string())
    }

    fn paths(&self, store_id: &str) -> Result<StorePaths, EvidenceFrontierBackendError> {
        StableId::new(store_id.to_string()).map_err(|error| {
            invalid(&format!("invalid recovery store id: {error}"))
        })?;
        let token = Sha256Digest::for_bytes(store_id.as_bytes())
            .as_str()
            .to_string();
        if !token.bytes().all(|byte| byte.is_ascii_hexdigit()) {
            return Err(corrupt("store journal filename digest is not canonical"));
        }
        Ok(StorePaths {
            active: self.legacy.journals.join(format!("{token}.jsonl")),
            lock: self.legacy.journals.join(format!("{token}.lock")),
            index: self.legacy.journals.join(format!("{token}.latest.json")),
            token,
        })
    }

    fn open_store_lock(&self, paths: &StorePaths) -> Result<File, EvidenceFrontierBackendError> {
        open_writable_journal(&paths.lock, &self.legacy.journals, self.legacy.owner_uid)
    }

    fn open_active_writable(&self, paths: &StorePaths) -> Result<File, EvidenceFrontierBackendError> {
        open_writable_journal(&paths.active, &self.legacy.journals, self.legacy.owner_uid)
    }

    fn open_active_existing(&self, paths: &StorePaths) -> Result<Option<File>, EvidenceFrontierBackendError> {
        open_existing_journal(&paths.active, &self.legacy.journals, self.legacy.owner_uid)
    }

    fn current_active_length(&self, paths: &StorePaths) -> Result<u64, EvidenceFrontierBackendError> {
        match std::fs::symlink_metadata(&paths.active) {
            Ok(metadata) => {
                if !metadata.is_file() || metadata.file_type().is_symlink() {
                    return Err(invalid("active frontier journal is not a regular file"));
                }
                Ok(metadata.len())
            }
            Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(0),
            Err(error) => Err(unavailable(error)),
        }
    }

    fn read_index(
        &self,
        paths: &StorePaths,
        store_id: &str,
    ) -> Result<Option<EvidenceFrontierLatestIndexV1>, EvidenceFrontierBackendError> {
        let Some(bytes) = read_optional_private_file(
            &paths.index,
            &self.legacy.journals,
            self.legacy.owner_uid,
            MAX_INDEX_BYTES,
        )? else {
            return Ok(None);
        };
        let index: EvidenceFrontierLatestIndexV1 = serde_json::from_slice(&bytes).map_err(|error| {
            corrupt(&format!("cannot decode frontier latest index: {error}"))
        })?;
        validate_index(
            &index,
            store_id,
            &self.legacy.identity,
            &self.legacy.identity_sha256,
        )?;
        Ok(Some(index))
    }

    fn read_segment_metadata(
        &self,
        pointer: &EvidenceFrontierSegmentPointerV1,
        store_id: &str,
    ) -> Result<EvidenceFrontierSegmentMetadataV1, EvidenceFrontierBackendError> {
        validate_direct_file_name(&pointer.metadata_file_name)?;
        let path = self.legacy.journals.join(&pointer.metadata_file_name);
        let bytes = read_private_regular_file(
            &path,
            &self.legacy.journals,
            self.legacy.owner_uid,
            MAX_SEGMENT_METADATA_BYTES,
        )?;
        if Sha256Digest::for_bytes(&bytes) != pointer.metadata_file_sha256 {
            return Err(corrupt("frontier segment metadata file digest differs from its pointer"));
        }
        let metadata: EvidenceFrontierSegmentMetadataV1 =
            serde_json::from_slice(&bytes).map_err(|error| {
                corrupt(&format!("cannot decode frontier segment metadata: {error}"))
            })?;
        validate_segment_metadata(
            &metadata,
            store_id,
            &self.legacy.identity,
            &self.legacy.identity_sha256,
        )?;
        if segment_pointer(
            &metadata,
            pointer.metadata_file_name.clone(),
            pointer.metadata_file_sha256.clone(),
        ) != pointer.clone()
        {
            return Err(corrupt("frontier segment pointer does not match its metadata"));
        }
        Ok(metadata)
    }

    fn load_state_from_active(
        &self,
        paths: &StorePaths,
        store_id: &str,
        active: Option<&mut File>,
    ) -> Result<SegmentedState, EvidenceFrontierBackendError> {
        let index = self.read_index(paths, store_id)?;
        let archived = index
            .as_ref()
            .and_then(|index| index.latest_segment.as_ref())
            .map(|pointer| self.verify_archived_history(store_id, pointer))
            .transpose()?;
        if let Some(index) = &index {
            match &archived {
                Some(history)
                    if history.segment_count == index.segment_count
                        && history.archived_records == index.archived_records
                        && history.archived_bytes == index.archived_bytes
                        && history.latest_record.record_sha256 == index
                            .latest_segment
                            .as_ref()
                            .expect("verified archive has a pointer")
                            .last_record_sha256 => {}
                Some(_) => {
                    return Err(corrupt(
                        "verified frontier archive counters differ from the latest index",
                    ));
                }
                None
                    if index.segment_count == 0
                        && index.archived_records == 0
                        && index.archived_bytes == 0 => {}
                None => {
                    return Err(corrupt(
                        "frontier latest index declares an archive without a segment chain",
                    ));
                }
            }
        }
        let (latest_segment_metadata, archived_latest_record) = match archived {
            Some(history) => (Some(history.latest_metadata), Some(history.latest_record)),
            None => (None, None),
        };
        let cursor = archived_latest_record
            .as_ref()
            .map(ChainCursor::after_record)
            .transpose()?
            .unwrap_or_else(ChainCursor::initial);
        let (active_records, active_bytes, active_sha256) = match active {
            Some(file) => {
                let bytes = read_locked_bytes(file, EVIDENCE_FRONTIER_MAX_JOURNAL_BYTES)?;
                let length = u64::try_from(bytes.len())
                    .map_err(|_| corrupt("active frontier journal length overflow"))?;
                let digest = Sha256Digest::for_bytes(&bytes);
                let records = parse_active_records(
                    &bytes,
                    store_id,
                    &self.legacy.identity,
                    &self.legacy.identity_sha256,
                    &cursor,
                )?;
                (records, length, digest)
            }
            None => (Vec::new(), 0, Sha256Digest::for_bytes(&[])),
        };
        let derived_latest = active_records
            .last()
            .or(archived_latest_record.as_ref());
        if let Some(index) = &index {
            let derived_sequence = derived_latest.map_or(0, |record| record.audit_sequence);
            if derived_sequence < index.audit_sequence {
                return Err(corrupt("frontier latest index is ahead of durable history"));
            }
            if index.audit_sequence < index.archived_records {
                return Err(corrupt("frontier latest index sequence precedes archived history"));
            }
            if derived_sequence == index.audit_sequence {
                let record = derived_latest
                    .ok_or_else(|| corrupt("frontier latest index has no durable record"))?;
                if record.frontier != index.frontier
                    || record.frontier_sha256 != index.frontier_sha256
                    || record.record_sha256 != index.record_sha256
                {
                    return Err(corrupt(
                        "frontier latest index differs from the replayed durable record",
                    ));
                }
            }
        }
        Ok(SegmentedState {
            index,
            latest_segment_metadata,
            active_records,
            active_bytes,
            active_sha256,
        })
    }
}
