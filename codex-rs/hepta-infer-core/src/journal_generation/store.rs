impl JournalGenerationStore {
    pub fn open(
        directory: impl AsRef<Path>,
        namespace: impl Into<String>,
    ) -> Result<Self, JournalGenerationError> {
        let namespace = namespace.into();
        if namespace.is_empty()
            || namespace.len() > 128
            || !namespace
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_'))
        {
            return Err(JournalGenerationError::InvalidConfiguration);
        }
        let directory = directory.as_ref().to_path_buf();
        fs::create_dir_all(&directory)?;
        ensure_private_directory(&directory)?;
        sync_directory(&directory)?;
        Ok(Self {
            directory,
            namespace,
        })
    }

    pub fn commit_generation(
        &self,
        generation: u64,
        previous_manifest_sha256: Option<JournalDigest32>,
        snapshot: &[u8],
        predecessor_archive: &[u8],
        created_at_unix_ms: u64,
        retain_checkpoints: usize,
        failpoints: &mut dyn JournalFailpointController,
    ) -> Result<CommittedJournalGeneration, JournalGenerationError> {
        if generation == 0
            || snapshot.len() as u64 > MAX_SNAPSHOT_BYTES
            || predecessor_archive.len() as u64 > MAX_ARCHIVE_BYTES
            || retain_checkpoints == 0
        {
            return Err(JournalGenerationError::InvalidGeneration);
        }
        match self.recover() {
            Ok(current) => {
                if generation != current.manifest.generation.saturating_add(1)
                    || previous_manifest_sha256 != Some(current.manifest_sha256)
                {
                    return Err(JournalGenerationError::PreviousGenerationMismatch);
                }
            }
            Err(JournalGenerationError::NotFound) => {
                if generation != 1 || previous_manifest_sha256.is_some() {
                    return Err(JournalGenerationError::PreviousGenerationMismatch);
                }
            }
            Err(error) => return Err(error),
        }

        failpoints.hit(JournalFailpoint::BeforeArchiveWrite)?;
        let archive_sha256 = digest_bytes(predecessor_archive);
        let archive_file = format!(
            "{}.archive-{}.journal",
            self.namespace,
            hex_digest(archive_sha256)
        );
        let archive_path = self.directory.join(&archive_file);
        if archive_path.exists() {
            verify_file(
                &archive_path,
                predecessor_archive.len() as u64,
                archive_sha256,
                MAX_ARCHIVE_BYTES,
                JournalGenerationError::CorruptArchive,
            )?;
        } else {
            write_atomic_file(
                &self.directory,
                &archive_file,
                predecessor_archive,
                "archive",
                failpoints,
                Some(JournalFailpoint::AfterArchiveFsync),
                Some(JournalFailpoint::AfterArchiveRename),
            )?;
        }

        let manifest = JournalGenerationManifestV1 {
            schema_version: GENERATION_SCHEMA_VERSION,
            generation,
            previous_manifest_sha256,
            snapshot_sha256: digest_bytes(snapshot),
            snapshot_bytes: snapshot.len() as u64,
            archive_sha256,
            archive_bytes: predecessor_archive.len() as u64,
            created_at_unix_ms,
        };
        let manifest_sha256 = manifest.digest()?;
        let manifest_json = serde_json::to_vec(&manifest)
            .map_err(|_| JournalGenerationError::Encoding)?;
        if manifest_json.len() > MAX_MANIFEST_BYTES {
            return Err(JournalGenerationError::CapacityExceeded);
        }
        let mut checkpoint = Vec::with_capacity(manifest_json.len() + 1 + snapshot.len());
        checkpoint.extend_from_slice(&manifest_json);
        checkpoint.push(b'\n');
        checkpoint.extend_from_slice(snapshot);
        let checkpoint_file = format!(
            "{}.checkpoint-{:020}-{}.bin",
            self.namespace,
            generation,
            hex_digest(manifest_sha256)
        );
        let checkpoint_path = self.directory.join(&checkpoint_file);
        write_atomic_file(
            &self.directory,
            &checkpoint_file,
            &checkpoint,
            "checkpoint",
            failpoints,
            Some(JournalFailpoint::AfterCheckpointFsync),
            Some(JournalFailpoint::AfterCheckpointRename),
        )?;

        let pointer = CurrentPointerV1 {
            schema_version: GENERATION_SCHEMA_VERSION,
            generation,
            checkpoint_file,
            manifest_sha256,
        };
        let pointer_bytes = serde_json::to_vec(&pointer)
            .map_err(|_| JournalGenerationError::Encoding)?;
        failpoints.hit(JournalFailpoint::BeforePointerRename)?;
        write_atomic_file(
            &self.directory,
            &self.current_file_name(),
            &pointer_bytes,
            "current",
            failpoints,
            None,
            Some(JournalFailpoint::AfterPointerRename),
        )?;
        sync_directory(&self.directory)?;
        failpoints.hit(JournalFailpoint::AfterDirectoryFsync)?;
        self.prune_checkpoints(retain_checkpoints, &checkpoint_path)?;
        sync_directory(&self.directory)?;

        Ok(CommittedJournalGeneration {
            manifest,
            manifest_sha256,
            checkpoint_path,
            archive_path,
        })
    }

    pub fn recover(&self) -> Result<RecoveredJournalGeneration, JournalGenerationError> {
        let pointer_path = self.directory.join(self.current_file_name());
        if !pointer_path.exists() {
            return Err(JournalGenerationError::NotFound);
        }
        let pointer_bytes = read_bounded(&pointer_path, MAX_POINTER_BYTES)?;
        let pointer: CurrentPointerV1 = serde_json::from_slice(&pointer_bytes)
            .map_err(|_| JournalGenerationError::InvalidPointer)?;
        if pointer.schema_version != GENERATION_SCHEMA_VERSION
            || pointer.generation == 0
            || pointer.manifest_sha256 == [0; 32]
            || !safe_file_name(&pointer.checkpoint_file)
        {
            return Err(JournalGenerationError::InvalidPointer);
        }
        let checkpoint_path = self.directory.join(&pointer.checkpoint_file);
        let checkpoint = read_bounded(
            &checkpoint_path,
            MAX_SNAPSHOT_BYTES + MAX_MANIFEST_BYTES as u64 + 1,
        )?;
        let newline = checkpoint
            .iter()
            .position(|byte| *byte == b'\n')
            .ok_or(JournalGenerationError::CorruptCheckpoint)?;
        if newline == 0 || newline > MAX_MANIFEST_BYTES {
            return Err(JournalGenerationError::CorruptCheckpoint);
        }
        let manifest: JournalGenerationManifestV1 = serde_json::from_slice(&checkpoint[..newline])
            .map_err(|_| JournalGenerationError::CorruptCheckpoint)?;
        manifest.validate()?;
        let manifest_sha256 = manifest.digest()?;
        if manifest.generation != pointer.generation
            || manifest_sha256 != pointer.manifest_sha256
            || pointer.checkpoint_file
                != format!(
                    "{}.checkpoint-{:020}-{}.bin",
                    self.namespace,
                    manifest.generation,
                    hex_digest(manifest_sha256)
                )
        {
            return Err(JournalGenerationError::CorruptCheckpoint);
        }
        let snapshot = checkpoint[newline + 1..].to_vec();
        if snapshot.len() as u64 != manifest.snapshot_bytes
            || digest_bytes(&snapshot) != manifest.snapshot_sha256
        {
            return Err(JournalGenerationError::CorruptCheckpoint);
        }
        let archive_path = self.directory.join(format!(
            "{}.archive-{}.journal",
            self.namespace,
            hex_digest(manifest.archive_sha256)
        ));
        verify_file(
            &archive_path,
            manifest.archive_bytes,
            manifest.archive_sha256,
            MAX_ARCHIVE_BYTES,
            JournalGenerationError::CorruptArchive,
        )?;
        Ok(RecoveredJournalGeneration {
            manifest,
            manifest_sha256,
            snapshot,
            archive_path,
        })
    }

    fn current_file_name(&self) -> String {
        format!("{}.CURRENT", self.namespace)
    }

    fn prune_checkpoints(
        &self,
        retain: usize,
        current: &Path,
    ) -> Result<(), JournalGenerationError> {
        let prefix = format!("{}.checkpoint-", self.namespace);
        let mut checkpoints = Vec::new();
        for entry in fs::read_dir(&self.directory)? {
            let entry = entry?;
            let name = entry.file_name();
            let name = name.to_string_lossy();
            if name.starts_with(&prefix) && name.ends_with(".bin") {
                checkpoints.push(entry.path());
            }
        }
        checkpoints.sort();
        let remove_count = checkpoints.len().saturating_sub(retain);
        for path in checkpoints.into_iter().take(remove_count) {
            if path != current {
                fs::remove_file(path)?;
            }
        }
        Ok(())
    }
}
