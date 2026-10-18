//! lease registry storage implementation.

use super::*;

impl DurableLeaseRegistryV1 {
    pub(crate) fn enter_consumption_execution(
        &self,
        id: &str,
    ) -> Result<crate::operation_execution::OperationExecutionGuard, LeaseRegistryErrorV1> {
        self.ensure_writable()?;
        self.executions.enter(id)
    }

    pub fn open(path: impl Into<PathBuf>) -> Result<Self, LeaseRegistryErrorV1> {
        Self::open_with_persistence(path, Arc::new(FsLeaseRegistryPersistenceV1))
    }

    pub(super) fn open_with_persistence(
        path: impl Into<PathBuf>,
        persistence: Arc<dyn LeaseRegistryPersistenceV1>,
    ) -> Result<Self, LeaseRegistryErrorV1> {
        if !cfg!(unix) {
            return Err(LeaseRegistryErrorV1::UnsupportedPlatform);
        }

        let path = path.into();
        let parent = parent_directory(&path);
        prepare_parent(parent)?;
        reject_existing_symlink(&path)?;

        let lock_path = sibling_with_suffix(&path, ".lock");
        reject_existing_symlink(&lock_path)?;
        let mut lock = private_file_options()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(&lock_path)
            .map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
        if !lock
            .metadata()
            .map_err(|_| LeaseRegistryErrorV1::Unavailable)?
            .is_file()
        {
            return Err(LeaseRegistryErrorV1::Unavailable);
        }
        match File::try_lock(&lock) {
            Ok(()) => {}
            Err(TryLockError::WouldBlock) => return Err(LeaseRegistryErrorV1::WriterBusy),
            Err(TryLockError::Error(_)) => return Err(LeaseRegistryErrorV1::Unavailable),
        }

        validate_private_file(&lock)?;
        let mut initialized = Vec::new();
        (&mut lock)
            .take(128)
            .read_to_end(&mut initialized)
            .map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
        if !initialized.is_empty() && initialized != INITIALIZED_MARKER {
            return Err(LeaseRegistryErrorV1::CorruptState);
        }
        let temp_path = sibling_with_suffix(&path, ".next");
        reject_existing_symlink(&temp_path)?;
        remove_if_present(&temp_path)?;

        let state = match private_file_options().read(true).open(&path) {
            Ok(file) => {
                validate_private_file(&file)?;
                if !file
                    .metadata()
                    .map_err(|_| LeaseRegistryErrorV1::Unavailable)?
                    .is_file()
                {
                    return Err(LeaseRegistryErrorV1::Unavailable);
                }
                let mut bytes = Vec::new();
                file.take((MAX_STORE_BYTES + 1) as u64)
                    .read_to_end(&mut bytes)
                    .map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
                if bytes.len() > MAX_STORE_BYTES {
                    return Err(LeaseRegistryErrorV1::CorruptState);
                }
                let decoded: StoredRegistryV1 = serde_json::from_slice(&bytes)
                    .map_err(|_| LeaseRegistryErrorV1::CorruptState)?;
                let migrated = migrate_state(decoded)?;
                validate_state(&migrated)?;
                migrated
            }
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                if !initialized.is_empty() {
                    return Err(LeaseRegistryErrorV1::CorruptState);
                }
                let initial = StoredRegistryV1 {
                    schema_version: SCHEMA_VERSION,
                    revision: 1,
                    time_frontier_unix_ms: 0,
                    operations: BTreeMap::new(),
                    leases: BTreeMap::new(),
                    consumptions: BTreeMap::new(),
                };
                validate_state(&initial)?;
                let bytes = encode_state(&initial, 0)?;
                match persist_bytes(&path, &bytes, persistence.as_ref()) {
                    Ok(()) => initial,
                    Err(PersistFailure::NotApplied) => {
                        return Err(LeaseRegistryErrorV1::Unavailable);
                    }
                    Err(PersistFailure::Indeterminate) => {
                        return Err(LeaseRegistryErrorV1::CommitIndeterminate);
                    }
                }
            }
            Err(_) => return Err(LeaseRegistryErrorV1::Unavailable),
        };

        if initialized.is_empty() {
            lock.write_all(INITIALIZED_MARKER)
                .and_then(|()| lock.sync_all())
                .map_err(|_| LeaseRegistryErrorV1::CommitIndeterminate)?;
            persistence
                .sync_parent(parent)
                .map_err(|_| LeaseRegistryErrorV1::CommitIndeterminate)?;
        }
        Ok(Self {
            executions: Default::default(),
            path,
            lock,
            state,
            persistence,
            fenced: false,
            runtime_metrics: Default::default(),
        })
    }

    #[must_use]
    pub const fn is_fenced(&self) -> bool {
        self.fenced
    }

    pub(super) fn ensure_writable(&self) -> Result<(), LeaseRegistryErrorV1> {
        if self.fenced {
            return Err(LeaseRegistryErrorV1::Fenced);
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            let held = self
                .lock
                .metadata()
                .map_err(|_| LeaseRegistryErrorV1::Fenced)?;
            let current = fs::symlink_metadata(sibling_with_suffix(&self.path, ".lock"))
                .map_err(|_| LeaseRegistryErrorV1::Fenced)?;
            if held.dev() != current.dev() || held.ino() != current.ino() || held.nlink() != 1 {
                return Err(LeaseRegistryErrorV1::Fenced);
            }
        }
        Ok(())
    }

    pub(super) fn commit(
        &mut self,
        mut next: StoredRegistryV1,
        required_reserve: usize,
    ) -> Result<(), LeaseRegistryErrorV1> {
        let started = Instant::now();
        self.runtime_metrics.attempts = self.runtime_metrics.attempts.saturating_add(1);
        if let Err(error) = self.ensure_writable() {
            self.runtime_metrics.unavailable_commits =
                self.runtime_metrics.unavailable_commits.saturating_add(1);
            self.runtime_metrics.record_duration(started);
            return Err(error);
        }
        next.schema_version = SCHEMA_VERSION;
        next.revision = match self.state.revision.checked_add(1) {
            Some(revision) => revision,
            None => {
                self.runtime_metrics.rejected_commits =
                    self.runtime_metrics.rejected_commits.saturating_add(1);
                self.runtime_metrics.record_duration(started);
                return Err(LeaseRegistryErrorV1::InvalidTransition);
            }
        };
        stamp_consumption_revisions(&self.state, &mut next);
        if let Err(error) = validate_state(&next) {
            self.runtime_metrics.rejected_commits =
                self.runtime_metrics.rejected_commits.saturating_add(1);
            self.runtime_metrics.record_duration(started);
            return Err(error);
        }
        let bytes = match encode_state(&next, required_reserve) {
            Ok(bytes) => bytes,
            Err(error) => {
                self.runtime_metrics.rejected_commits =
                    self.runtime_metrics.rejected_commits.saturating_add(1);
                self.runtime_metrics.record_duration(started);
                return Err(error);
            }
        };
        let attempted_bytes = u64::try_from(bytes.len()).unwrap_or(u64::MAX);
        self.runtime_metrics.attempted_bytes = self
            .runtime_metrics
            .attempted_bytes
            .saturating_add(attempted_bytes);
        match persist_bytes(&self.path, &bytes, self.persistence.as_ref()) {
            Ok(()) => {
                self.state = next;
                self.runtime_metrics.confirmed_commits =
                    self.runtime_metrics.confirmed_commits.saturating_add(1);
                self.runtime_metrics.confirmed_bytes = self
                    .runtime_metrics
                    .confirmed_bytes
                    .saturating_add(attempted_bytes);
                self.runtime_metrics.record_duration(started);
                Ok(())
            }
            Err(PersistFailure::NotApplied) => {
                self.runtime_metrics.unavailable_commits =
                    self.runtime_metrics.unavailable_commits.saturating_add(1);
                self.runtime_metrics.record_duration(started);
                Err(LeaseRegistryErrorV1::Unavailable)
            }
            Err(PersistFailure::Indeterminate) => {
                self.state = next;
                self.fenced = true;
                self.runtime_metrics.indeterminate_commits =
                    self.runtime_metrics.indeterminate_commits.saturating_add(1);
                self.runtime_metrics.writer_fence_events =
                    self.runtime_metrics.writer_fence_events.saturating_add(1);
                self.runtime_metrics.record_duration(started);
                Err(LeaseRegistryErrorV1::CommitIndeterminate)
            }
        }
    }
}
