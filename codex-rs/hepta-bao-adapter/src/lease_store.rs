use super::SecretLeaseMetadata;
use super::SecretLeaseState;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use std::collections::BTreeMap;
use std::fs::File;
use std::io::BufRead;
use std::io::BufReader;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::sync::Arc;
use std::sync::Mutex;

const META_MAX_BYTES: u64 = 16 * 1024;
const EVENT_MAX_BYTES: usize = 32 * 1024;
const EVENT_LOG_MAX_BYTES: u64 = 512 * 1024 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) enum StoreError {
    Invalid,
    UnsafeDirectory,
    Locked,
    Unavailable,
    OperationConflict,
    AlreadyCompleted,
    ReconciliationRequired,
    LeaseNotFound,
    LeaseNotActive,
    LeaseNotRenewable,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoreMeta {
    schema: u32,
    destination_id: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct LeaseRecord {
    issue_request_sha256: [u8; 32],
    metadata: SecretLeaseMetadata,
    prior_state: Option<SecretLeaseState>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct MutationIdentity {
    operation_id: String,
    request_sha256: [u8; 32],
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct JournalEvent {
    schema: u32,
    sequence: u64,
    record: LeaseRecord,
    mutation: Option<MutationIdentity>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct JournalLine {
    event: JournalEvent,
    event_sha256: [u8; 32],
}

struct RegistryState {
    next_sequence: u64,
    records: BTreeMap<String, LeaseRecord>,
    lease_to_issue: BTreeMap<String, String>,
    mutations: BTreeMap<String, (String, [u8; 32])>,
    failed: bool,
}

struct Store {
    root: File,
    _lock: File,
    events: File,
}

struct Inner {
    destination_id: String,
    state: Mutex<RegistryState>,
    store: Store,
}

#[derive(Clone)]
pub(super) struct LeaseRegistry(Arc<Inner>);

impl LeaseRegistry {
    pub(super) fn open(root: &Path, destination_id: &str) -> Result<Self, StoreError> {
        let root = prepare_directory(root)?;
        let initialized = entry_exists(&root, "leases.lock")?;
        let lock = open_private(&root, "leases.lock", Access::Create)?;
        lock.try_lock().map_err(|_| StoreError::Locked)?;
        let events = open_private(&root, "leases.events", Access::Append)?;
        let store = Store {
            root,
            _lock: lock,
            events,
        };
        let has_meta = entry_exists(&store.root, "leases.meta.json")?;
        if has_meta {
            validate_meta(&store.root, destination_id)?;
        } else {
            if initialized {
                return Err(StoreError::Invalid);
            }
            persist_meta(&store.root, destination_id)?;
        }
        let state = load_events(&store.root, destination_id)?;
        Ok(Self(Arc::new(Inner {
            destination_id: destination_id.to_owned(),
            state: Mutex::new(state),
            store,
        })))
    }

    pub(super) fn begin_issue(
        &self,
        metadata: SecretLeaseMetadata,
        request_sha256: [u8; 32],
    ) -> Result<(), StoreError> {
        let mut state = self.lock()?;
        if let Some(existing) = state.records.get(&metadata.operation_id) {
            if existing.issue_request_sha256 != request_sha256 {
                return Err(StoreError::OperationConflict);
            }
            return match existing.metadata.state {
                SecretLeaseState::Active
                | SecretLeaseState::Orphaned
                | SecretLeaseState::Revoked
                | SecretLeaseState::Expired
                | SecretLeaseState::Rejected => Err(StoreError::AlreadyCompleted),
                _ => Err(StoreError::ReconciliationRequired),
            };
        }
        let record = LeaseRecord {
            issue_request_sha256: request_sha256,
            metadata,
            prior_state: None,
        };
        self.append_locked(&mut state, record, None)
    }

    pub(super) fn reject_issue(&self, operation_id: &str) -> Result<(), StoreError> {
        self.transition_issue(operation_id, |record| {
            record.metadata.state = SecretLeaseState::Rejected;
        })
    }

    pub(super) fn mark_issue_indeterminate(&self, operation_id: &str) -> Result<(), StoreError> {
        self.transition_issue(operation_id, |record| {
            record.metadata.state = SecretLeaseState::IndeterminateIssue;
        })
    }

    pub(super) fn commit_issue(
        &self,
        operation_id: &str,
        lease_id: String,
        expires_at_unix_ms: u64,
        renewable: bool,
    ) -> Result<SecretLeaseMetadata, StoreError> {
        let mut state = self.lock()?;
        if let Some(owner) = state.lease_to_issue.get(&lease_id)
            && owner != operation_id
        {
            return Err(StoreError::OperationConflict);
        }
        let mut record = state
            .records
            .get(operation_id)
            .cloned()
            .ok_or(StoreError::LeaseNotFound)?;
        if !matches!(
            record.metadata.state,
            SecretLeaseState::IssuePending | SecretLeaseState::IndeterminateIssue
        ) {
            return Err(StoreError::OperationConflict);
        }
        record.metadata.lease_id = Some(lease_id);
        record.metadata.expires_at_unix_ms = Some(expires_at_unix_ms);
        record.metadata.renewable = renewable;
        record.metadata.generation = 1;
        record.metadata.state = SecretLeaseState::Active;
        record.prior_state = None;
        self.append_locked(&mut state, record.clone(), None)?;
        Ok(record.metadata)
    }

    pub(super) fn commit_orphaned_issue(
        &self,
        operation_id: &str,
        lease_id: String,
        expires_at_unix_ms: u64,
        renewable: bool,
    ) -> Result<SecretLeaseMetadata, StoreError> {
        let mut state = self.lock()?;
        if let Some(owner) = state.lease_to_issue.get(&lease_id)
            && owner != operation_id
        {
            return Err(StoreError::OperationConflict);
        }
        let mut record = state
            .records
            .get(operation_id)
            .cloned()
            .ok_or(StoreError::LeaseNotFound)?;
        if record.metadata.state != SecretLeaseState::IndeterminateIssue {
            return Err(StoreError::OperationConflict);
        }
        record.metadata.lease_id = Some(lease_id);
        record.metadata.expires_at_unix_ms = Some(expires_at_unix_ms);
        record.metadata.renewable = renewable;
        record.metadata.generation = 1;
        record.metadata.state = SecretLeaseState::Orphaned;
        record.prior_state = None;
        self.append_locked(&mut state, record.clone(), None)?;
        Ok(record.metadata)
    }

    pub(super) fn begin_renew(
        &self,
        lease_id: &str,
        mutation_id: &str,
        request_sha256: [u8; 32],
    ) -> Result<SecretLeaseMetadata, StoreError> {
        self.begin_mutation(
            lease_id,
            mutation_id,
            request_sha256,
            SecretLeaseState::RenewPending,
            true,
        )
    }

    pub(super) fn begin_revoke(
        &self,
        lease_id: &str,
        mutation_id: &str,
        request_sha256: [u8; 32],
    ) -> Result<SecretLeaseMetadata, StoreError> {
        self.begin_mutation(
            lease_id,
            mutation_id,
            request_sha256,
            SecretLeaseState::RevokePending,
            false,
        )
    }

    fn begin_mutation(
        &self,
        lease_id: &str,
        mutation_id: &str,
        request_sha256: [u8; 32],
        pending_state: SecretLeaseState,
        require_renewable: bool,
    ) -> Result<SecretLeaseMetadata, StoreError> {
        let mut state = self.lock()?;
        if let Some((owner, digest)) = state.mutations.get(mutation_id) {
            if digest != &request_sha256 {
                return Err(StoreError::OperationConflict);
            }
            let record = state.records.get(owner).ok_or(StoreError::Invalid)?;
            return match record.metadata.state {
                SecretLeaseState::IndeterminateRenew
                | SecretLeaseState::IndeterminateRevoke
                | SecretLeaseState::RenewPending
                | SecretLeaseState::RevokePending => Err(StoreError::ReconciliationRequired),
                _ => Err(StoreError::AlreadyCompleted),
            };
        }
        let issue_id = state
            .lease_to_issue
            .get(lease_id)
            .cloned()
            .ok_or(StoreError::LeaseNotFound)?;
        let mut record = state
            .records
            .get(&issue_id)
            .cloned()
            .ok_or(StoreError::Invalid)?;
        if !matches!(record.metadata.state, SecretLeaseState::Active | SecretLeaseState::Orphaned) {
            return Err(StoreError::LeaseNotActive);
        }
        if require_renewable && !record.metadata.renewable {
            return Err(StoreError::LeaseNotRenewable);
        }
        let prior = record.metadata.state;
        record.prior_state = Some(prior);
        record.metadata.state = pending_state;
        let mutation = MutationIdentity {
            operation_id: mutation_id.to_owned(),
            request_sha256,
        };
        self.append_locked(&mut state, record.clone(), Some(mutation))?;
        Ok(record.metadata)
    }

    pub(super) fn restore_after_definite_failure(
        &self,
        lease_id: &str,
    ) -> Result<SecretLeaseMetadata, StoreError> {
        let mut state = self.lock()?;
        let issue_id = state
            .lease_to_issue
            .get(lease_id)
            .cloned()
            .ok_or(StoreError::LeaseNotFound)?;
        let mut record = state
            .records
            .get(&issue_id)
            .cloned()
            .ok_or(StoreError::Invalid)?;
        let prior = record.prior_state.take().ok_or(StoreError::OperationConflict)?;
        record.metadata.state = prior;
        self.append_locked(&mut state, record.clone(), None)?;
        Ok(record.metadata)
    }

    pub(super) fn mark_renew_indeterminate(
        &self,
        lease_id: &str,
    ) -> Result<SecretLeaseMetadata, StoreError> {
        self.mark_mutation_indeterminate(lease_id, SecretLeaseState::IndeterminateRenew)
    }

    pub(super) fn mark_revoke_indeterminate(
        &self,
        lease_id: &str,
    ) -> Result<SecretLeaseMetadata, StoreError> {
        self.mark_mutation_indeterminate(lease_id, SecretLeaseState::IndeterminateRevoke)
    }

    fn mark_mutation_indeterminate(
        &self,
        lease_id: &str,
        next: SecretLeaseState,
    ) -> Result<SecretLeaseMetadata, StoreError> {
        let mut state = self.lock()?;
        let issue_id = state
            .lease_to_issue
            .get(lease_id)
            .cloned()
            .ok_or(StoreError::LeaseNotFound)?;
        let mut record = state
            .records
            .get(&issue_id)
            .cloned()
            .ok_or(StoreError::Invalid)?;
        record.metadata.state = next;
        self.append_locked(&mut state, record.clone(), None)?;
        Ok(record.metadata)
    }

    pub(super) fn commit_renew(
        &self,
        lease_id: &str,
        expires_at_unix_ms: u64,
        renewable: bool,
    ) -> Result<SecretLeaseMetadata, StoreError> {
        let mut state = self.lock()?;
        let issue_id = state
            .lease_to_issue
            .get(lease_id)
            .cloned()
            .ok_or(StoreError::LeaseNotFound)?;
        let mut record = state
            .records
            .get(&issue_id)
            .cloned()
            .ok_or(StoreError::Invalid)?;
        if !matches!(
            record.metadata.state,
            SecretLeaseState::RenewPending | SecretLeaseState::IndeterminateRenew
        ) {
            return Err(StoreError::OperationConflict);
        }
        record.metadata.expires_at_unix_ms = Some(expires_at_unix_ms);
        record.metadata.renewable = renewable;
        record.metadata.generation = record.metadata.generation.saturating_add(1);
        record.metadata.state = SecretLeaseState::Active;
        record.prior_state = None;
        self.append_locked(&mut state, record.clone(), None)?;
        Ok(record.metadata)
    }

    pub(super) fn commit_revoked(
        &self,
        lease_id: &str,
    ) -> Result<SecretLeaseMetadata, StoreError> {
        let mut state = self.lock()?;
        let issue_id = state
            .lease_to_issue
            .get(lease_id)
            .cloned()
            .ok_or(StoreError::LeaseNotFound)?;
        let mut record = state
            .records
            .get(&issue_id)
            .cloned()
            .ok_or(StoreError::Invalid)?;
        record.metadata.state = SecretLeaseState::Revoked;
        record.metadata.renewable = false;
        record.metadata.expires_at_unix_ms = None;
        record.prior_state = None;
        self.append_locked(&mut state, record.clone(), None)?;
        Ok(record.metadata)
    }

    pub(super) fn reconcile_present(
        &self,
        lease_id: &str,
        expires_at_unix_ms: u64,
        renewable: bool,
    ) -> Result<SecretLeaseMetadata, StoreError> {
        let mut state = self.lock()?;
        let issue_id = state
            .lease_to_issue
            .get(lease_id)
            .cloned()
            .ok_or(StoreError::LeaseNotFound)?;
        let mut record = state
            .records
            .get(&issue_id)
            .cloned()
            .ok_or(StoreError::Invalid)?;
        if matches!(record.metadata.state, SecretLeaseState::IndeterminateRenew) {
            record.metadata.generation = record.metadata.generation.saturating_add(1);
        }
        record.metadata.expires_at_unix_ms = Some(expires_at_unix_ms);
        record.metadata.renewable = renewable;
        record.metadata.state = record
            .prior_state
            .take()
            .unwrap_or(SecretLeaseState::Active);
        if !matches!(record.metadata.state, SecretLeaseState::Active | SecretLeaseState::Orphaned) {
            record.metadata.state = SecretLeaseState::Active;
        }
        self.append_locked(&mut state, record.clone(), None)?;
        Ok(record.metadata)
    }

    pub(super) fn metadata_by_operation(
        &self,
        operation_id: &str,
    ) -> Result<SecretLeaseMetadata, StoreError> {
        let state = self.lock()?;
        let mut metadata = state
            .records
            .get(operation_id)
            .map(|record| record.metadata.clone())
            .ok_or(StoreError::LeaseNotFound)?;
        mark_expired(&mut metadata);
        Ok(metadata)
    }

    pub(super) fn metadata_by_lease(
        &self,
        lease_id: &str,
    ) -> Result<SecretLeaseMetadata, StoreError> {
        let state = self.lock()?;
        let issue_id = state
            .lease_to_issue
            .get(lease_id)
            .ok_or(StoreError::LeaseNotFound)?;
        let mut metadata = state
            .records
            .get(issue_id)
            .map(|record| record.metadata.clone())
            .ok_or(StoreError::Invalid)?;
        mark_expired(&mut metadata);
        Ok(metadata)
    }

    fn transition_issue(
        &self,
        operation_id: &str,
        change: impl FnOnce(&mut LeaseRecord),
    ) -> Result<(), StoreError> {
        let mut state = self.lock()?;
        let mut record = state
            .records
            .get(operation_id)
            .cloned()
            .ok_or(StoreError::LeaseNotFound)?;
        change(&mut record);
        self.append_locked(&mut state, record, None)
    }

    fn lock(&self) -> Result<std::sync::MutexGuard<'_, RegistryState>, StoreError> {
        let state = self.0.state.lock().map_err(|_| StoreError::Unavailable)?;
        if state.failed {
            return Err(StoreError::Unavailable);
        }
        Ok(state)
    }

    fn append_locked(
        &self,
        state: &mut RegistryState,
        record: LeaseRecord,
        mutation: Option<MutationIdentity>,
    ) -> Result<(), StoreError> {
        let event = JournalEvent {
            schema: 1,
            sequence: state.next_sequence,
            record: record.clone(),
            mutation: mutation.clone(),
        };
        if self.0.store.append(&event).is_err() {
            state.failed = true;
            return Err(StoreError::Unavailable);
        }
        state.next_sequence = state.next_sequence.saturating_add(1);
        if let Some(lease_id) = record.metadata.lease_id.as_ref() {
            if let Some(owner) = state.lease_to_issue.get(lease_id)
                && owner != &record.metadata.operation_id
            {
                state.failed = true;
                return Err(StoreError::Invalid);
            }
            state
                .lease_to_issue
                .insert(lease_id.clone(), record.metadata.operation_id.clone());
        }
        if let Some(mutation) = mutation {
            state.mutations.insert(
                mutation.operation_id,
                (record.metadata.operation_id.clone(), mutation.request_sha256),
            );
        }
        state.records.insert(record.metadata.operation_id.clone(), record);
        Ok(())
    }

    pub(super) fn destination_id(&self) -> &str {
        &self.0.destination_id
    }
}

impl Store {
    fn append(&self, event: &JournalEvent) -> Result<(), StoreError> {
        let event_bytes = serde_json::to_vec(event).map_err(|_| StoreError::Unavailable)?;
        let line = JournalLine {
            event: event.clone(),
            event_sha256: Digest32::of_bytes(&event_bytes).into_array(),
        };
        let mut bytes = serde_json::to_vec(&line).map_err(|_| StoreError::Unavailable)?;
        if bytes.len() > EVENT_MAX_BYTES {
            return Err(StoreError::Invalid);
        }
        bytes.push(b'\n');
        let length = self
            .events
            .metadata()
            .map_err(|_| StoreError::Unavailable)?
            .len();
        if length > EVENT_LOG_MAX_BYTES.saturating_sub(bytes.len() as u64) {
            return Err(StoreError::Unavailable);
        }
        (&self.events)
            .write_all(&bytes)
            .and_then(|()| self.events.sync_data())
            .map_err(|_| StoreError::Unavailable)
    }
}

fn load_events(directory: &File, destination_id: &str) -> Result<RegistryState, StoreError> {
    let mut state = RegistryState {
        next_sequence: 1,
        records: BTreeMap::new(),
        lease_to_issue: BTreeMap::new(),
        mutations: BTreeMap::new(),
        failed: false,
    };
    if !entry_exists(directory, "leases.events")? {
        return Ok(state);
    }
    let file = open_private(directory, "leases.events", Access::Read)?;
    let length = file.metadata().map_err(|_| StoreError::Unavailable)?.len();
    if length > EVENT_LOG_MAX_BYTES {
        return Err(StoreError::Invalid);
    }
    if length == 0 {
        return Ok(state);
    }
    let mut reader = BufReader::new(file);
    let mut line = Vec::new();
    loop {
        line.clear();
        let read = reader
            .read_until(b'\n', &mut line)
            .map_err(|_| StoreError::Unavailable)?;
        if read == 0 {
            break;
        }
        if line.len() > EVENT_MAX_BYTES + 1 || line.last() != Some(&b'\n') {
            return Err(StoreError::Invalid);
        }
        line.pop();
        let wrapped: JournalLine =
            serde_json::from_slice(&line).map_err(|_| StoreError::Invalid)?;
        if wrapped.event.schema != 1 || wrapped.event.sequence != state.next_sequence {
            return Err(StoreError::Invalid);
        }
        let canonical = serde_json::to_vec(&wrapped.event).map_err(|_| StoreError::Invalid)?;
        if Digest32::of_bytes(&canonical).into_array() != wrapped.event_sha256
            || wrapped.event.record.metadata.destination_id != destination_id
        {
            return Err(StoreError::Invalid);
        }
        let record = wrapped.event.record;
        if let Some(lease_id) = record.metadata.lease_id.as_ref() {
            if let Some(owner) = state.lease_to_issue.get(lease_id)
                && owner != &record.metadata.operation_id
            {
                return Err(StoreError::Invalid);
            }
            state
                .lease_to_issue
                .insert(lease_id.clone(), record.metadata.operation_id.clone());
        }
        if let Some(mutation) = wrapped.event.mutation {
            if let Some(existing) = state.mutations.get(&mutation.operation_id)
                && existing != &(record.metadata.operation_id.clone(), mutation.request_sha256)
            {
                return Err(StoreError::Invalid);
            }
            state.mutations.insert(
                mutation.operation_id,
                (record.metadata.operation_id.clone(), mutation.request_sha256),
            );
        }
        state.records.insert(record.metadata.operation_id.clone(), record);
        state.next_sequence = state.next_sequence.saturating_add(1);
    }
    Ok(state)
}

fn mark_expired(metadata: &mut SecretLeaseMetadata) {
    if matches!(metadata.state, SecretLeaseState::Active | SecretLeaseState::Orphaned)
        && metadata
            .expires_at_unix_ms
            .is_some_and(|expires| now_ms().is_some_and(|now| now >= expires))
    {
        metadata.state = SecretLeaseState::Expired;
        metadata.renewable = false;
    }
}

fn now_ms() -> Option<u64> {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .ok()
        .and_then(|duration| u64::try_from(duration.as_millis()).ok())
}

fn validate_meta(directory: &File, destination_id: &str) -> Result<(), StoreError> {
    let mut bytes = Vec::new();
    open_private(directory, "leases.meta.json", Access::Read)?
        .take(META_MAX_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| StoreError::Unavailable)?;
    if bytes.len() as u64 > META_MAX_BYTES {
        return Err(StoreError::Invalid);
    }
    let meta: StoreMeta = serde_json::from_slice(&bytes).map_err(|_| StoreError::Invalid)?;
    if meta.schema != 1 || meta.destination_id != destination_id {
        return Err(StoreError::Invalid);
    }
    Ok(())
}

fn persist_meta(directory: &File, destination_id: &str) -> Result<(), StoreError> {
    let bytes = serde_json::to_vec(&StoreMeta {
        schema: 1,
        destination_id: destination_id.to_owned(),
    })
    .map_err(|_| StoreError::Unavailable)?;
    let mut next = open_private(directory, "leases.meta.next", Access::Create)?;
    next.set_len(0).map_err(|_| StoreError::Unavailable)?;
    next.write_all(&bytes)
        .and_then(|()| next.sync_all())
        .map_err(|_| StoreError::Unavailable)?;
    rustix::fs::renameat(
        directory,
        "leases.meta.next",
        directory,
        "leases.meta.json",
    )
    .map_err(|_| StoreError::Unavailable)?;
    directory.sync_all().map_err(|_| StoreError::Unavailable)
}

enum Access {
    Read,
    Create,
    Append,
}

#[cfg(unix)]
fn prepare_directory(root: &Path) -> Result<File, StoreError> {
    use std::os::unix::fs::DirBuilderExt;
    use std::os::unix::fs::MetadataExt;
    if let Err(error) = std::fs::DirBuilder::new().mode(0o700).create(root)
        && error.kind() != std::io::ErrorKind::AlreadyExists
    {
        return Err(StoreError::Unavailable);
    }
    let directory: File = rustix::fs::open(
        root,
        rustix::fs::OFlags::RDONLY
            | rustix::fs::OFlags::DIRECTORY
            | rustix::fs::OFlags::NOFOLLOW
            | rustix::fs::OFlags::CLOEXEC,
        rustix::fs::Mode::empty(),
    )
    .map_err(|_| StoreError::UnsafeDirectory)?
    .into();
    let metadata = directory.metadata().map_err(|_| StoreError::Unavailable)?;
    if !metadata.is_dir()
        || metadata.mode() & 0o077 != 0
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(StoreError::UnsafeDirectory);
    }
    Ok(directory)
}

#[cfg(not(unix))]
fn prepare_directory(_root: &Path) -> Result<File, StoreError> {
    Err(StoreError::UnsafeDirectory)
}

#[cfg(unix)]
fn open_private(directory: &File, name: &str, access: Access) -> Result<File, StoreError> {
    use rustix::fs::Mode;
    use rustix::fs::OFlags;
    use std::os::unix::fs::MetadataExt;
    let flags = match access {
        Access::Read => OFlags::RDONLY,
        Access::Create => OFlags::RDWR | OFlags::CREATE,
        Access::Append => OFlags::WRONLY | OFlags::CREATE | OFlags::APPEND,
    } | OFlags::NOFOLLOW
        | OFlags::CLOEXEC;
    let file: File = rustix::fs::openat(directory, name, flags, Mode::RUSR | Mode::WUSR)
        .map_err(|_| StoreError::Unavailable)?
        .into();
    let metadata = file.metadata().map_err(|_| StoreError::Unavailable)?;
    if !metadata.is_file()
        || metadata.mode() & 0o077 != 0
        || metadata.nlink() != 1
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(StoreError::UnsafeDirectory);
    }
    Ok(file)
}

#[cfg(not(unix))]
fn open_private(_directory: &File, _name: &str, _access: Access) -> Result<File, StoreError> {
    Err(StoreError::UnsafeDirectory)
}

#[cfg(unix)]
fn entry_exists(directory: &File, name: &str) -> Result<bool, StoreError> {
    match rustix::fs::statat(directory, name, rustix::fs::AtFlags::SYMLINK_NOFOLLOW) {
        Ok(_) => Ok(true),
        Err(rustix::io::Errno::NOENT) => Ok(false),
        Err(_) => Err(StoreError::Unavailable),
    }
}

#[cfg(not(unix))]
fn entry_exists(_directory: &File, _name: &str) -> Result<bool, StoreError> {
    Err(StoreError::UnsafeDirectory)
}
