use std::collections::BTreeMap;
use std::fs::File;
use std::io::Read;
use std::io::Write;
use std::path::Path;

use serde::Deserialize;
use serde::Serialize;

use crate::lease_lifecycle::BaoLeaseMetadata;
use crate::lease_lifecycle::BaoLeaseOperationKind;
use crate::lease_lifecycle::BaoLeaseReconciliationObservation;
use crate::lease_lifecycle::BaoReconciliationOutcome;

const MAX_STATE_BYTES: u64 = 8 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
enum OperationState {
    Prepared,
    Dispatched,
    Succeeded,
    Rejected,
    Indeterminate,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct OperationRecord {
    request_sha256: [u8; 32],
    kind: BaoLeaseOperationKind,
    state: OperationState,
    lease_id: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Stored {
    schema: u32,
    operations: BTreeMap<String, OperationRecord>,
    leases: BTreeMap<String, BaoLeaseMetadata>,
}

pub(crate) struct BaoLeaseStore {
    root: File,
}

pub(crate) enum PrepareDisposition {
    Dispatch,
    Indeterminate,
    AlreadyCompleted,
    Rejected,
}

impl BaoLeaseStore {
    pub(crate) fn open(root: &Path) -> Result<Self, LeaseStoreError> {
        let root = prepare_directory(root)?;
        let store = Self { root };
        let (_guard, created_marker) = store.lock_initialization()?;
        let has_state = entry_exists(&store.root, "leases.json")?;
        if created_marker && has_state {
            // Never recreate a missing lock beside an existing registry; an
            // older process could still be fencing on the unlinked inode.
            return Err(LeaseStoreError::InvalidState);
        }
        if !has_state {
            if !created_marker {
                return Err(LeaseStoreError::InvalidState);
            }
            store.persist(&Stored {
                schema: 1,
                operations: BTreeMap::new(),
                leases: BTreeMap::new(),
            })?;
        } else {
            let _ = store.load()?;
        }
        Ok(store)
    }

    pub(crate) fn prepare(
        &self,
        operation_id: &str,
        request_sha256: [u8; 32],
        kind: BaoLeaseOperationKind,
        lease_id: Option<&str>,
    ) -> Result<PrepareDisposition, LeaseStoreError> {
        let _guard = self.lock()?;
        let mut stored = self.load()?;
        if let Some(existing) = stored.operations.get(operation_id) {
            if existing.request_sha256 != request_sha256
                || existing.kind != kind
                || existing.lease_id.as_deref() != lease_id
            {
                return Err(LeaseStoreError::Conflict);
            }
            let existing_state = existing.state;
            return Ok(match existing_state {
                OperationState::Prepared => PrepareDisposition::Dispatch,
                OperationState::Dispatched | OperationState::Indeterminate => {
                    if existing_state == OperationState::Dispatched {
                        stored
                            .operations
                            .get_mut(operation_id)
                            .ok_or(LeaseStoreError::InvalidState)?
                            .state = OperationState::Indeterminate;
                        self.persist(&stored)?;
                    }
                    PrepareDisposition::Indeterminate
                }
                OperationState::Succeeded => PrepareDisposition::AlreadyCompleted,
                OperationState::Rejected => PrepareDisposition::Rejected,
            });
        }
        stored.operations.insert(
            operation_id.to_owned(),
            OperationRecord {
                request_sha256,
                kind,
                state: OperationState::Prepared,
                lease_id: lease_id.map(str::to_owned),
            },
        );
        self.persist(&stored)?;
        Ok(PrepareDisposition::Dispatch)
    }

    pub(crate) fn mark_dispatched(
        &self,
        operation_id: &str,
        request_sha256: [u8; 32],
    ) -> Result<(), LeaseStoreError> {
        self.transition(operation_id, request_sha256, OperationState::Prepared, |record, _| {
            record.state = OperationState::Dispatched;
            Ok(())
        })
    }

    pub(crate) fn mark_indeterminate(
        &self,
        operation_id: &str,
        request_sha256: [u8; 32],
    ) -> Result<(), LeaseStoreError> {
        self.transition(
            operation_id,
            request_sha256,
            OperationState::Dispatched,
            |record, _| {
                record.state = OperationState::Indeterminate;
                Ok(())
            },
        )
    }

    pub(crate) fn mark_rejected(
        &self,
        operation_id: &str,
        request_sha256: [u8; 32],
    ) -> Result<(), LeaseStoreError> {
        self.transition(
            operation_id,
            request_sha256,
            OperationState::Dispatched,
            |record, _| {
                record.state = OperationState::Rejected;
                Ok(())
            },
        )
    }

    pub(crate) fn complete(
        &self,
        operation_id: &str,
        request_sha256: [u8; 32],
        metadata: BaoLeaseMetadata,
    ) -> Result<(), LeaseStoreError> {
        self.transition(
            operation_id,
            request_sha256,
            OperationState::Dispatched,
            |record, stored| {
                record.state = OperationState::Succeeded;
                record.lease_id = Some(metadata.lease_id.clone());
                stored.leases.insert(metadata.lease_id.clone(), metadata);
                Ok(())
            },
        )
    }

    pub(crate) fn reconcile_lease(
        &self,
        metadata: BaoLeaseMetadata,
    ) -> Result<(), LeaseStoreError> {
        let _guard = self.lock()?;
        let mut stored = self.load()?;
        stored.leases.insert(metadata.lease_id.clone(), metadata);
        self.persist(&stored)
    }

    pub(crate) fn resolve_indeterminate(
        &self,
        observation: &BaoLeaseReconciliationObservation,
    ) -> Result<(), LeaseStoreError> {
        let _guard = self.lock()?;
        let mut stored = self.load()?;
        let mut record = stored
            .operations
            .remove(&observation.operation_id)
            .ok_or(LeaseStoreError::InvalidState)?;
        if record.request_sha256 != observation.original_request_sha256
            || record.state != OperationState::Indeterminate
        {
            stored
                .operations
                .insert(observation.operation_id.clone(), record);
            return Err(LeaseStoreError::Conflict);
        }
        match observation.outcome {
            BaoReconciliationOutcome::NotApplied => {
                record.state = OperationState::Prepared;
            }
            BaoReconciliationOutcome::Rejected => {
                record.state = OperationState::Rejected;
            }
            BaoReconciliationOutcome::Applied => {
                let metadata = observation
                    .metadata
                    .clone()
                    .ok_or(LeaseStoreError::InvalidState)?;
                if record.kind != BaoLeaseOperationKind::Issue
                    && record.lease_id.as_deref() != Some(metadata.lease_id.as_str())
                {
                    return Err(LeaseStoreError::Conflict);
                }
                match record.kind {
                    BaoLeaseOperationKind::Issue | BaoLeaseOperationKind::Renew
                        if metadata.state != crate::lease_lifecycle::BaoLeaseState::Active =>
                    {
                        return Err(LeaseStoreError::Conflict);
                    }
                    BaoLeaseOperationKind::Revoke
                        if !matches!(
                            metadata.state,
                            crate::lease_lifecycle::BaoLeaseState::Revoked
                                | crate::lease_lifecycle::BaoLeaseState::Missing
                        ) =>
                    {
                        return Err(LeaseStoreError::Conflict);
                    }
                    _ => {}
                }
                record.state = OperationState::Succeeded;
                record.lease_id = Some(metadata.lease_id.clone());
                stored.leases.insert(metadata.lease_id.clone(), metadata);
            }
        }
        stored
            .operations
            .insert(observation.operation_id.clone(), record);
        self.persist(&stored)
    }

    pub(crate) fn lease(&self, lease_id: &str) -> Result<Option<BaoLeaseMetadata>, LeaseStoreError> {
        let _guard = self.lock()?;
        Ok(self.load()?.leases.get(lease_id).cloned())
    }

    fn transition(
        &self,
        operation_id: &str,
        request_sha256: [u8; 32],
        required: OperationState,
        update: impl FnOnce(&mut OperationRecord, &mut Stored) -> Result<(), LeaseStoreError>,
    ) -> Result<(), LeaseStoreError> {
        let _guard = self.lock()?;
        let mut stored = self.load()?;
        let mut record = stored
            .operations
            .remove(operation_id)
            .ok_or(LeaseStoreError::InvalidState)?;
        if record.request_sha256 != request_sha256 || record.state != required {
            stored.operations.insert(operation_id.to_owned(), record);
            return Err(LeaseStoreError::Conflict);
        }
        update(&mut record, &mut stored)?;
        stored.operations.insert(operation_id.to_owned(), record);
        self.persist(&stored)
    }

    fn lock(&self) -> Result<File, LeaseStoreError> {
        let file = open_private(&self.root, "leases.lock", Access::ReadWrite)?;
        file.lock().map_err(|_| LeaseStoreError::Unavailable)?;
        Ok(file)
    }

    fn lock_initialization(&self) -> Result<(File, bool), LeaseStoreError> {
        let (file, created) = create_or_open_lock(&self.root, "leases.lock")?;
        file.lock().map_err(|_| LeaseStoreError::Unavailable)?;
        Ok((file, created))
    }

    fn load(&self) -> Result<Stored, LeaseStoreError> {
        let mut bytes = Vec::new();
        open_private(&self.root, "leases.json", Access::Read)?
            .take(MAX_STATE_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| LeaseStoreError::Unavailable)?;
        if bytes.len() as u64 > MAX_STATE_BYTES {
            return Err(LeaseStoreError::InvalidState);
        }
        let stored: Stored =
            serde_json::from_slice(&bytes).map_err(|_| LeaseStoreError::InvalidState)?;
        if stored.schema != 1 {
            return Err(LeaseStoreError::InvalidState);
        }
        Ok(stored)
    }

    fn persist(&self, stored: &Stored) -> Result<(), LeaseStoreError> {
        let bytes = serde_json::to_vec(stored).map_err(|_| LeaseStoreError::Unavailable)?;
        if bytes.len() as u64 > MAX_STATE_BYTES {
            return Err(LeaseStoreError::CapacityExceeded);
        }
        let mut file = open_private(&self.root, "leases.next", Access::Create)?;
        file.set_len(0).map_err(|_| LeaseStoreError::Unavailable)?;
        file.write_all(&bytes)
            .and_then(|()| file.sync_all())
            .map_err(|_| LeaseStoreError::Unavailable)?;
        replace_entry(&self.root, "leases.next", "leases.json")?;
        self.root.sync_all().map_err(|_| LeaseStoreError::Unavailable)
    }
}

enum Access {
    Read,
    ReadWrite,
    Create,
}

#[cfg(unix)]
fn create_or_open_lock(
    directory: &File,
    name: &str,
) -> Result<(File, bool), LeaseStoreError> {
    use rustix::fs::Mode;
    use rustix::fs::OFlags;
    use std::os::unix::fs::MetadataExt;

    let flags = OFlags::RDWR
        | OFlags::CREATE
        | OFlags::EXCL
        | OFlags::NOFOLLOW
        | OFlags::CLOEXEC;
    let (file, created): (File, bool) = match rustix::fs::openat(
        directory,
        name,
        flags,
        Mode::RUSR | Mode::WUSR,
    ) {
        Ok(fd) => (fd.into(), true),
        Err(rustix::io::Errno::EXIST) => (
            open_private(directory, name, Access::ReadWrite)?,
            false,
        ),
        Err(_) => return Err(LeaseStoreError::Unavailable),
    };
    let metadata = file.metadata().map_err(|_| LeaseStoreError::Unavailable)?;
    if !metadata.is_file()
        || metadata.mode() & 0o077 != 0
        || metadata.nlink() != 1
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(LeaseStoreError::UnsafeStateDirectory);
    }
    if created {
        file.sync_all().map_err(|_| LeaseStoreError::Unavailable)?;
        directory.sync_all().map_err(|_| LeaseStoreError::Unavailable)?;
    }
    Ok((file, created))
}

#[cfg(not(unix))]
fn create_or_open_lock(
    _directory: &File,
    _name: &str,
) -> Result<(File, bool), LeaseStoreError> {
    Err(LeaseStoreError::UnsafeStateDirectory)
}

#[cfg(unix)]
fn prepare_directory(root: &Path) -> Result<File, LeaseStoreError> {
    use std::os::unix::fs::DirBuilderExt;
    use std::os::unix::fs::MetadataExt;
    if let Err(error) = std::fs::DirBuilder::new().mode(0o700).create(root)
        && error.kind() != std::io::ErrorKind::AlreadyExists
    {
        return Err(LeaseStoreError::Unavailable);
    }
    let directory: File = rustix::fs::open(
        root,
        rustix::fs::OFlags::RDONLY
            | rustix::fs::OFlags::DIRECTORY
            | rustix::fs::OFlags::NOFOLLOW
            | rustix::fs::OFlags::CLOEXEC,
        rustix::fs::Mode::empty(),
    )
    .map_err(|_| LeaseStoreError::UnsafeStateDirectory)?
    .into();
    let metadata = directory
        .metadata()
        .map_err(|_| LeaseStoreError::Unavailable)?;
    if !metadata.is_dir()
        || metadata.mode() & 0o077 != 0
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(LeaseStoreError::UnsafeStateDirectory);
    }
    Ok(directory)
}

#[cfg(not(unix))]
fn prepare_directory(_root: &Path) -> Result<File, LeaseStoreError> {
    Err(LeaseStoreError::UnsafeStateDirectory)
}

#[cfg(unix)]
fn open_private(directory: &File, name: &str, access: Access) -> Result<File, LeaseStoreError> {
    use rustix::fs::Mode;
    use rustix::fs::OFlags;
    use std::os::unix::fs::MetadataExt;
    let flags = match access {
        Access::Read => OFlags::RDONLY,
        Access::ReadWrite => OFlags::RDWR,
        Access::Create => OFlags::RDWR | OFlags::CREATE,
    } | OFlags::NOFOLLOW
        | OFlags::CLOEXEC;
    let file: File = rustix::fs::openat(directory, name, flags, Mode::RUSR | Mode::WUSR)
        .map_err(|_| LeaseStoreError::Unavailable)?
        .into();
    let metadata = file.metadata().map_err(|_| LeaseStoreError::Unavailable)?;
    if !metadata.is_file()
        || metadata.mode() & 0o077 != 0
        || metadata.nlink() != 1
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(LeaseStoreError::UnsafeStateDirectory);
    }
    Ok(file)
}

#[cfg(not(unix))]
fn open_private(_directory: &File, _name: &str, _access: Access) -> Result<File, LeaseStoreError> {
    Err(LeaseStoreError::UnsafeStateDirectory)
}

#[cfg(unix)]
fn entry_exists(directory: &File, name: &str) -> Result<bool, LeaseStoreError> {
    match rustix::fs::statat(directory, name, rustix::fs::AtFlags::SYMLINK_NOFOLLOW) {
        Ok(_) => Ok(true),
        Err(rustix::io::Errno::NOENT) => Ok(false),
        Err(_) => Err(LeaseStoreError::Unavailable),
    }
}

#[cfg(not(unix))]
fn entry_exists(_directory: &File, _name: &str) -> Result<bool, LeaseStoreError> {
    Err(LeaseStoreError::UnsafeStateDirectory)
}

#[cfg(unix)]
fn replace_entry(directory: &File, from: &str, to: &str) -> Result<(), LeaseStoreError> {
    rustix::fs::renameat(directory, from, directory, to).map_err(|_| LeaseStoreError::Unavailable)
}

#[cfg(not(unix))]
fn replace_entry(_directory: &File, _from: &str, _to: &str) -> Result<(), LeaseStoreError> {
    Err(LeaseStoreError::UnsafeStateDirectory)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum LeaseStoreError {
    Conflict,
    InvalidState,
    CapacityExceeded,
    Unavailable,
    UnsafeStateDirectory,
}
