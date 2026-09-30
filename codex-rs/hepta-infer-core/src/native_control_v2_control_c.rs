impl DurableInferenceControl {
    fn assert_native_plan_identity(
        &self,
        request_id: &str,
        plan: &VerifiedExecutionPlan,
    ) -> Result<(), Error> {
        let record = self
            .native
            .records
            .get(request_id)
            .ok_or(Error::RequestNotFound)?;
        let binding = record
            .execution_binding
            .as_ref()
            .ok_or(Error::InvalidIdentity("native execution binding"))?;
        if record.request.request_id != plan.request_id()
            || record.request.principal_id != plan.principal_id()
            || binding.execution_binding_digest != plan.execution_binding_digest()
            || binding.bundle_digest != plan.bundle_digest()
            || binding.authority_epoch != plan.authority_epoch()
        {
            return Err(Error::AssignmentMismatch);
        }
        Ok(())
    }

    fn assert_native_plan_binding(
        &self,
        request_id: &str,
        plan: &VerifiedExecutionPlan,
        now_unix_ms: u64,
    ) -> Result<(), Error> {
        plan.assert_valid_at(now_unix_ms)
            .map_err(|_| Error::InvalidTime)?;
        let record = self
            .native
            .records
            .get(request_id)
            .ok_or(Error::RequestNotFound)?;
        let binding = record
            .execution_binding
            .as_ref()
            .ok_or(Error::InvalidIdentity("native execution binding"))?;
        if record.request.request_id != plan.request_id()
            || record.request.principal_id != plan.principal_id()
            || binding.execution_binding_digest != plan.execution_binding_digest()
            || binding.bundle_digest != plan.bundle_digest()
            || binding.authority_epoch != plan.authority_epoch()
            || binding.valid_until_unix_ms <= now_unix_ms
        {
            return Err(Error::AssignmentMismatch);
        }
        Ok(())
    }

    fn ensure_native_dispatch_space(&mut self) -> Result<(), Error> {
        if self.journal_bytes
            > super::MAX_JOURNAL_BYTES.saturating_sub(COMPACTION_HEADROOM_BYTES)
        {
            self.compact_native_journal()?;
        }
        if self.journal_bytes
            > super::MAX_JOURNAL_BYTES.saturating_sub(COMPACTION_HEADROOM_BYTES)
        {
            return Err(Error::CapacityExceeded);
        }
        Ok(())
    }

    fn commit_native(&mut self, request_id: &str, event: Event) -> Result<NativeRunRecord, Error> {
        let mut next = self.native.clone();
        next.apply(event.clone())?;
        let json =
            serde_json::to_string(&event).map_err(|_| Error::CorruptJournal("native encode"))?;
        self.append(&format!("{JOURNAL_PREFIX}{json}\n"))?;
        self.native = next;
        self.native
            .records
            .get(request_id)
            .cloned()
            .ok_or(Error::RequestNotFound)
    }

    fn compact_native_journal_inner(
        &mut self,
        now_unix_ms: u64,
        failpoint: &mut dyn NativeMaintenanceFailpoint,
    ) -> Result<NativeMaintenanceReceipt, Error> {
        let current_bytes = read_bounded(&self.path, super::MAX_JOURNAL_BYTES).map_err(|error| {
            self.poisoned = true;
            error
        })?;
        if current_bytes.len() as u64 != self.journal_bytes {
            return Err(Error::CorruptJournal("journal metadata drift"));
        }
        let archive_segment_digest = sha256_hex(
            b"hepta.inference-control.archive-segment.v1\0",
            &current_bytes,
        );
        let archive_chain_digest = sha256_hex(
            b"hepta.inference-control.archive-chain.v1\0",
            format!(
                "{}:{}",
                self.native.archive_chain_digest.as_deref().unwrap_or("genesis"),
                archive_segment_digest
            )
            .as_bytes(),
        );
        let generation = self
            .native
            .checkpoint_generation
            .checked_add(1)
            .ok_or(Error::ArithmeticOverflow)?;

        let parent = absolute_parent(&self.path)?;
        let file_name = self
            .path
            .file_name()
            .ok_or(Error::InvalidIdentity("native journal path"))?;
        let absolute_journal = parent.join(file_name);
        let archive_dir = sibling_directory(&absolute_journal, "archive");
        let checkpoint_dir = sibling_directory(&absolute_journal, "checkpoints");
        fs::create_dir_all(&archive_dir)?;
        fs::create_dir_all(&checkpoint_dir)?;
        set_owner_only_directory(&archive_dir)?;
        set_owner_only_directory(&checkpoint_dir)?;

        failpoint.hit(NativeMaintenanceStage::BeforeArchiveWrite)?;
        let archive_path = archive_dir.join(format!("{archive_segment_digest}.journal"));
        write_content_addressed(&archive_path, &current_bytes)?;
        sync_directory(&archive_dir)?;
        failpoint.hit(NativeMaintenanceStage::AfterArchiveSync)?;

        // Expiry creates deletion work; it is not deletion evidence. Keep every
        // encrypted reference and key binding in the checkpoint until a
        // separately authenticated vault-deletion receipt is verified and
        // journaled. A maintenance receipt must never silently manufacture that
        // external side effect.
        let checkpoint_records = self.native.records.clone();
        let mut expired_encrypted_references = Vec::new();
        for record in checkpoint_records.values() {
            if let Some(protected) = &record.protected_output
                && protected.delete_after_unix_ms <= now_unix_ms
                && let Some(reference) = &protected.encrypted_reference
            {
                expired_encrypted_references.push(reference.clone());
            }
        }
        expired_encrypted_references.sort();
        expired_encrypted_references.dedup();

        let checkpoint = NativeCheckpoint {
            schema_version: CHECKPOINT_SCHEMA_VERSION,
            generation,
            maximum_in_flight: self.native.maximum_in_flight,
            records: checkpoint_records,
            archive_segment_digest: archive_segment_digest.clone(),
            archive_chain_digest: archive_chain_digest.clone(),
            created_at_unix_ms: now_unix_ms,
        };
        let checkpoint_bytes = serde_json::to_vec(&checkpoint)
            .map_err(|_| Error::CorruptJournal("native checkpoint encode"))?;
        if checkpoint_bytes.len() as u64 > MAX_CHECKPOINT_BYTES {
            return Err(Error::CapacityExceeded);
        }
        let checkpoint_digest = sha256_hex(
            b"hepta.inference-control.checkpoint.v1\0",
            &checkpoint_bytes,
        );
        failpoint.hit(NativeMaintenanceStage::BeforeCheckpointWrite)?;
        let checkpoint_path = checkpoint_dir.join(format!("{checkpoint_digest}.json"));
        write_content_addressed(&checkpoint_path, &checkpoint_bytes)?;
        sync_directory(&checkpoint_dir)?;
        failpoint.hit(NativeMaintenanceStage::AfterCheckpointSync)?;

        let reference = Event::CheckpointReference {
            generation,
            checkpoint_path: checkpoint_path
                .to_str()
                .ok_or(Error::InvalidIdentity("native checkpoint path"))?
                .to_string(),
            checkpoint_digest: checkpoint_digest.clone(),
            archive_segment_digest: archive_segment_digest.clone(),
            archive_chain_digest: archive_chain_digest.clone(),
        };
        let reference_json = serde_json::to_string(&reference)
            .map_err(|_| Error::CorruptJournal("native checkpoint reference encode"))?;
        let mut next_active = legacy_journal_lines(&current_bytes)?;
        next_active.extend_from_slice(JOURNAL_PREFIX.as_bytes());
        next_active.extend_from_slice(reference_json.as_bytes());
        next_active.push(b'\n');
        if next_active.len() as u64 > super::MAX_JOURNAL_BYTES {
            return Err(Error::CapacityExceeded);
        }

        failpoint.hit(NativeMaintenanceStage::BeforeGenerationWrite)?;
        let temp_path = temporary_generation_path(&self.path, generation, now_unix_ms);
        let mut options = OpenOptions::new();
        options.create_new(true).read(true).append(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut replacement = options.open(&temp_path)?;
        replacement
            .try_lock()
            .map_err(|_| Error::WriterUnavailable)?;
        replacement.write_all(&next_active)?;
        replacement.flush()?;
        replacement.sync_all()?;
        failpoint.hit(NativeMaintenanceStage::AfterGenerationSync)?;

        fs::rename(&temp_path, &self.path)?;
        // The active path now names another generation. Any failure until the
        // new descriptor and replayed state are installed fences this owner,
        // including validation errors beyond the I/O errors handled outside.
        self.poisoned = true;
        failpoint.hit(NativeMaintenanceStage::AfterGenerationRename)?;
        sync_directory(&parent)?;
        failpoint.hit(NativeMaintenanceStage::AfterParentSync)?;

        let mut next = NativeJournal::default();
        next.apply(reference)?;
        self.file = replacement;
        self.native = next;
        self.journal_bytes = next_active.len() as u64;
        self.poisoned = false;

        Ok(NativeMaintenanceReceipt {
            generation,
            archive_segment_digest,
            archive_chain_digest,
            checkpoint_digest,
            active_journal_bytes: self.journal_bytes,
            record_count: self.native.records.len(),
            expired_encrypted_references,
        })
    }
}
