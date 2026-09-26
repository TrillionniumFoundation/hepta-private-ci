use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::EvidenceFrontierBackend;
use crate::EvidenceFrontierBackendError;
use crate::EvidenceFrontierBackendIdentityV1;
use crate::EvidenceFrontierDurableAckV1;
use crate::EvidenceFrontierHistoryRangeV1;
use crate::EvidenceRecoveryFrontierV2;
use crate::evidence_recovery_frontier_v2_sha256;
use crate::frontier_backend::EVIDENCE_FRONTIER_AUDIT_RECORD_SCHEMA_VERSION;
use crate::frontier_backend::EVIDENCE_FRONTIER_BACKEND_IDENTITY_FILENAME;
use crate::frontier_backend::EVIDENCE_FRONTIER_BACKEND_JOURNAL_DIRECTORY;
use crate::frontier_backend::EVIDENCE_FRONTIER_MAX_AUDIT_RECORD_BYTES;
use crate::frontier_backend::EVIDENCE_FRONTIER_MAX_AUDIT_RECORDS;
use crate::frontier_backend::EVIDENCE_FRONTIER_MAX_IDENTITY_BYTES;
use crate::frontier_backend::EVIDENCE_FRONTIER_MAX_JOURNAL_BYTES;

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EvidenceFrontierAuditRecordV1 {
    schema_version: u32,
    audit_sequence: u64,
    backend_id: String,
    backend_identity_sha256: Sha256Digest,
    store_id: String,
    expected_generation: Option<u64>,
    frontier: EvidenceRecoveryFrontierV2,
    frontier_sha256: Sha256Digest,
    previous_record_sha256: Option<Sha256Digest>,
    record_sha256: Sha256Digest,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct EvidenceFrontierAuditPayloadV1<'a> {
    schema_version: u32,
    audit_sequence: u64,
    backend_id: &'a str,
    backend_identity_sha256: &'a Sha256Digest,
    store_id: &'a str,
    expected_generation: Option<u64>,
    frontier: &'a EvidenceRecoveryFrontierV2,
    frontier_sha256: &'a Sha256Digest,
    previous_record_sha256: Option<&'a Sha256Digest>,
}

/// Locked append-only backend for a separately mounted rollback domain.
///
/// `open_external` requires the backend and local rollback roots to reside on
/// distinct Unix devices. The backend identity is digest-pinned. Each evidence
/// store has a private append-only hash-chained journal; an exclusive OS file
/// lock linearizes CAS operations on filesystems with coherent cross-host locks
/// and durable `fsync` semantics.
pub struct LockedFileEvidenceFrontierBackend {
    root: PathBuf,
    journals: PathBuf,
    owner_uid: u32,
    root_device: u64,
    root_inode: u64,
    journals_device: u64,
    journals_inode: u64,
    identity: EvidenceFrontierBackendIdentityV1,
    identity_sha256: Sha256Digest,
    poisoned: bool,
}

impl LockedFileEvidenceFrontierBackend {
    pub fn open_external(
        root: &Path,
        expected_identity_sha256: Sha256Digest,
        local_rollback_root: &Path,
    ) -> Result<Self, EvidenceFrontierBackendError> {
        Self::open(root, expected_identity_sha256, local_rollback_root, true)
    }

    fn open(
        root: &Path,
        expected_identity_sha256: Sha256Digest,
        local_rollback_root: &Path,
        require_distinct_device: bool,
    ) -> Result<Self, EvidenceFrontierBackendError> {
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;

            let root = root.canonicalize().map_err(unavailable)?;
            let local_rollback_root = local_rollback_root.canonicalize().map_err(unavailable)?;
            let root_metadata = private_directory_metadata(&root, None, None)?;
            let local_metadata = std::fs::metadata(&local_rollback_root).map_err(unavailable)?;
            if root.starts_with(&local_rollback_root)
                || local_rollback_root.starts_with(&root)
                || (require_distinct_device && root_metadata.dev() == local_metadata.dev())
            {
                return Err(EvidenceFrontierBackendError::Invalid(
                    "external frontier backend is not outside the local rollback domain"
                        .to_string(),
                ));
            }

            let owner_uid = root_metadata.uid();
            let journals = root.join(EVIDENCE_FRONTIER_BACKEND_JOURNAL_DIRECTORY);
            let journals = journals.canonicalize().map_err(unavailable)?;
            let journals_metadata =
                private_directory_metadata(&journals, Some(&root), Some(owner_uid))?;

            let identity_path = root.join(EVIDENCE_FRONTIER_BACKEND_IDENTITY_FILENAME);
            let identity_bytes = read_private_regular_file(
                &identity_path,
                &root,
                owner_uid,
                EVIDENCE_FRONTIER_MAX_IDENTITY_BYTES,
            )?;
            let identity_sha256 = Sha256Digest::for_bytes(&identity_bytes);
            if identity_sha256 != expected_identity_sha256 {
                return Err(EvidenceFrontierBackendError::Invalid(
                    "external frontier backend identity digest does not match the pin".to_string(),
                ));
            }
            let identity: EvidenceFrontierBackendIdentityV1 =
                serde_json::from_slice(&identity_bytes).map_err(|error| {
                    EvidenceFrontierBackendError::Invalid(format!(
                        "invalid external frontier backend identity: {error}"
                    ))
                })?;
            identity.validate()?;
            Ok(Self {
                root,
                journals,
                owner_uid,
                root_device: root_metadata.dev(),
                root_inode: root_metadata.ino(),
                journals_device: journals_metadata.dev(),
                journals_inode: journals_metadata.ino(),
                identity,
                identity_sha256,
                poisoned: false,
            })
        }
        #[cfg(not(unix))]
        {
            let _ = (
                root,
                expected_identity_sha256,
                local_rollback_root,
                require_distinct_device,
            );
            Err(EvidenceFrontierBackendError::Unsupported)
        }
    }

    #[cfg(test)]
    pub(crate) fn open_same_filesystem_for_testing(
        root: &Path,
        expected_identity_sha256: Sha256Digest,
        local_rollback_root: &Path,
    ) -> Result<Self, EvidenceFrontierBackendError> {
        Self::open(
            root,
            expected_identity_sha256,
            local_rollback_root,
            false,
        )
    }

    fn ensure_available(&self) -> Result<(), EvidenceFrontierBackendError> {
        if self.poisoned {
            return Err(EvidenceFrontierBackendError::Indeterminate(
                "backend was fenced after an uncertain write".to_string(),
            ));
        }
        Ok(())
    }

    fn journal_path(&self, store_id: &str) -> Result<PathBuf, EvidenceFrontierBackendError> {
        StableId::new(store_id.to_string()).map_err(|error| {
            EvidenceFrontierBackendError::Invalid(format!("invalid recovery store id: {error}"))
        })?;
        let token = Sha256Digest::for_bytes(store_id.as_bytes());
        if !token.as_str().bytes().all(|byte| byte.is_ascii_hexdigit()) {
            return Err(EvidenceFrontierBackendError::Corrupt(
                "store journal filename digest is not canonical".to_string(),
            ));
        }
        Ok(self.journals.join(format!("{}.jsonl", token.as_str())))
    }

    fn read_records(
        &self,
        store_id: &str,
    ) -> Result<Vec<EvidenceFrontierAuditRecordV1>, EvidenceFrontierBackendError> {
        let path = self.journal_path(store_id)?;
        let Some(mut file) =
            open_existing_journal(&path, &self.journals, self.owner_uid)?
        else {
            return Ok(Vec::new());
        };
        file.lock_shared().map_err(unavailable)?;
        read_records_from_locked(
            &mut file,
            store_id,
            &self.identity,
            &self.identity_sha256,
        )
    }
}

impl EvidenceFrontierBackend for LockedFileEvidenceFrontierBackend {
    fn get_latest(
        &mut self,
        store_id: &str,
    ) -> Result<Option<EvidenceRecoveryFrontierV2>, EvidenceFrontierBackendError> {
        self.ensure_available()?;
        self.verify_backend_identity()?;
        Ok(self
            .read_records(store_id)?
            .last()
            .map(|record| record.frontier.clone()))
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
            EvidenceFrontierBackendError::Invalid(format!("invalid proposed frontier: {error}"))
        })?;
        if new_frontier.store_id != store_id
            || new_frontier.backend_identity_sha256 != self.identity_sha256
        {
            return Err(EvidenceFrontierBackendError::Invalid(
                "proposed frontier is not bound to this store and backend".to_string(),
            ));
        }

        let path = self.journal_path(store_id)?;
        let mut file = open_writable_journal(&path, &self.journals, self.owner_uid)?;
        file.lock().map_err(unavailable)?;
        let records = read_records_from_locked(
            &mut file,
            store_id,
            &self.identity,
            &self.identity_sha256,
        )?;
        let actual_generation = records
            .last()
            .map(|record| record.frontier.frontier_generation);
        if actual_generation != expected_generation {
            return Err(EvidenceFrontierBackendError::Conflict {
                expected: expected_generation,
                actual: actual_generation,
            });
        }
        let required_generation = actual_generation
            .unwrap_or(0)
            .checked_add(1)
            .ok_or_else(|| {
                EvidenceFrontierBackendError::Invalid(
                    "frontier generation exhausted its numeric domain".to_string(),
                )
            })?;
        if new_frontier.frontier_generation != required_generation {
            return Err(EvidenceFrontierBackendError::Invalid(format!(
                "frontier generation must advance exactly to {required_generation}"
            )));
        }

        let audit_sequence = u64::try_from(records.len())
            .ok()
            .and_then(|value| value.checked_add(1))
            .ok_or_else(|| {
                EvidenceFrontierBackendError::Invalid(
                    "frontier audit sequence exhausted its numeric domain".to_string(),
                )
            })?;
        let frontier_sha256 = evidence_recovery_frontier_v2_sha256(new_frontier).map_err(|error| {
            EvidenceFrontierBackendError::Invalid(format!("cannot hash proposed frontier: {error}"))
        })?;
        let previous_record_sha256 = records.last().map(|record| record.record_sha256.clone());
        let mut record = EvidenceFrontierAuditRecordV1 {
            schema_version: EVIDENCE_FRONTIER_AUDIT_RECORD_SCHEMA_VERSION,
            audit_sequence,
            backend_id: self.identity.backend_id.clone(),
            backend_identity_sha256: self.identity_sha256.clone(),
            store_id: store_id.to_string(),
            expected_generation,
            frontier: new_frontier.clone(),
            frontier_sha256: frontier_sha256.clone(),
            previous_record_sha256,
            record_sha256: Sha256Digest::for_bytes(b"pending"),
        };
        record.record_sha256 = audit_record_sha256(&record)?;
        let mut encoded = serde_json::to_vec(&record).map_err(|error| {
            EvidenceFrontierBackendError::Invalid(format!(
                "cannot serialize frontier audit record: {error}"
            ))
        })?;
        encoded.push(b'\n');
        if encoded.len() > EVIDENCE_FRONTIER_MAX_AUDIT_RECORD_BYTES {
            return Err(EvidenceFrontierBackendError::Invalid(
                "frontier audit record exceeds the bounded frame size".to_string(),
            ));
        }

        let current_length = file.metadata().map_err(unavailable)?.len();
        let expected_length = checked_journal_length_after_append(
            current_length,
            records.len(),
            encoded.len(),
        )?;
        let directory = open_pinned_directory(
            &self.journals,
            self.owner_uid,
            self.journals_device,
            self.journals_inode,
        )?;
        let end = file.seek(SeekFrom::End(0)).map_err(unavailable)?;
        if end != current_length {
            return Err(EvidenceFrontierBackendError::Corrupt(
                "frontier audit journal length changed under the exclusive lock".to_string(),
            ));
        }

        let write_result = file
            .write_all(&encoded)
            .and_then(|()| file.sync_all())
            .and_then(|()| {
                if file.metadata()?.len() != expected_length {
                    Err(io::Error::other(
                        "frontier audit journal did not reach the expected durable length",
                    ))
                } else {
                    Ok(())
                }
            })
            .and_then(|()| directory.sync_all());
        if let Err(error) = write_result {
            self.poisoned = true;
            return Err(EvidenceFrontierBackendError::Indeterminate(
                error.to_string(),
            ));
        }
        Ok(EvidenceFrontierDurableAckV1 {
            backend_id: self.identity.backend_id.clone(),
            backend_identity_sha256: self.identity_sha256.clone(),
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
        Ok(self
            .read_records(store_id)?
            .into_iter()
            .map(|record| record.frontier)
            .filter(|frontier| {
                (range.first_generation..=range.last_generation)
                    .contains(&frontier.frontier_generation)
            })
            .collect())
    }

    fn verify_backend_identity(
        &mut self,
    ) -> Result<EvidenceFrontierBackendIdentityV1, EvidenceFrontierBackendError> {
        self.ensure_available()?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;

            let root_metadata = private_directory_metadata(&self.root, None, None)?;
            let journals_metadata = private_directory_metadata(
                &self.journals,
                Some(&self.root),
                Some(self.owner_uid),
            )?;
            if root_metadata.uid() != self.owner_uid
                || root_metadata.dev() != self.root_device
                || root_metadata.ino() != self.root_inode
                || journals_metadata.dev() != self.journals_device
                || journals_metadata.ino() != self.journals_inode
            {
                return Err(EvidenceFrontierBackendError::Invalid(
                    "external frontier backend directory identity changed after bootstrap"
                        .to_string(),
                ));
            }
            let bytes = read_private_regular_file(
                &self.root.join(EVIDENCE_FRONTIER_BACKEND_IDENTITY_FILENAME),
                &self.root,
                self.owner_uid,
                EVIDENCE_FRONTIER_MAX_IDENTITY_BYTES,
            )?;
            if Sha256Digest::for_bytes(&bytes) != self.identity_sha256 {
                return Err(EvidenceFrontierBackendError::Invalid(
                    "external frontier backend identity changed after bootstrap".to_string(),
                ));
            }
            let identity: EvidenceFrontierBackendIdentityV1 =
                serde_json::from_slice(&bytes).map_err(|error| {
                    EvidenceFrontierBackendError::Corrupt(format!(
                        "cannot decode pinned backend identity: {error}"
                    ))
                })?;
            identity.validate()?;
            if identity != self.identity {
                return Err(EvidenceFrontierBackendError::Invalid(
                    "external frontier backend identity drifted after bootstrap".to_string(),
                ));
            }
            Ok(identity)
        }
        #[cfg(not(unix))]
        {
            Err(EvidenceFrontierBackendError::Unsupported)
        }
    }
}

fn checked_journal_length_after_append(
    current_length: u64,
    current_records: usize,
    append_bytes: usize,
) -> Result<u64, EvidenceFrontierBackendError> {
    if current_records >= EVIDENCE_FRONTIER_MAX_AUDIT_RECORDS {
        return Err(EvidenceFrontierBackendError::Invalid(
            "frontier audit journal reached the bounded record capacity".to_string(),
        ));
    }
    let append_bytes = u64::try_from(append_bytes).map_err(|_| {
        EvidenceFrontierBackendError::Invalid(
            "frontier audit record length exceeds the numeric domain".to_string(),
        )
    })?;
    let expected_length = current_length.checked_add(append_bytes).ok_or_else(|| {
        EvidenceFrontierBackendError::Invalid(
            "frontier audit journal length exceeds the numeric domain".to_string(),
        )
    })?;
    if expected_length > EVIDENCE_FRONTIER_MAX_JOURNAL_BYTES {
        return Err(EvidenceFrontierBackendError::Invalid(
            "frontier audit journal reached the bounded byte capacity".to_string(),
        ));
    }
    Ok(expected_length)
}

fn read_records_from_locked(
    file: &mut File,
    store_id: &str,
    identity: &EvidenceFrontierBackendIdentityV1,
    identity_sha256: &Sha256Digest,
) -> Result<Vec<EvidenceFrontierAuditRecordV1>, EvidenceFrontierBackendError> {
    let length = file.metadata().map_err(unavailable)?.len();
    if length > EVIDENCE_FRONTIER_MAX_JOURNAL_BYTES {
        return Err(EvidenceFrontierBackendError::Corrupt(
            "frontier audit journal exceeds the bounded size".to_string(),
        ));
    }
    file.seek(SeekFrom::Start(0)).map_err(unavailable)?;
    let mut bytes = Vec::new();
    (&mut *file)
        .take(EVIDENCE_FRONTIER_MAX_JOURNAL_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(unavailable)?;
    if bytes.len() as u64 != length {
        return Err(EvidenceFrontierBackendError::Corrupt(
            "frontier audit journal changed during locked read".to_string(),
        ));
    }
    if bytes.is_empty() {
        return Ok(Vec::new());
    }
    if bytes.last().copied() != Some(b'\n') {
        return Err(EvidenceFrontierBackendError::Corrupt(
            "frontier audit journal has a torn tail".to_string(),
        ));
    }

    let mut records = Vec::new();
    let mut previous_generation = None;
    let mut previous_record_sha256: Option<Sha256Digest> = None;
    for line in bytes[..bytes.len() - 1].split(|byte| *byte == b'\n') {
        if line.is_empty() {
            return Err(EvidenceFrontierBackendError::Corrupt(
                "frontier audit journal contains an empty record".to_string(),
            ));
        }
        if line.len() > EVIDENCE_FRONTIER_MAX_AUDIT_RECORD_BYTES
            || records.len() >= EVIDENCE_FRONTIER_MAX_AUDIT_RECORDS
        {
            return Err(EvidenceFrontierBackendError::Corrupt(
                "frontier audit journal exceeds a bounded record limit".to_string(),
            ));
        }
        let record: EvidenceFrontierAuditRecordV1 = serde_json::from_slice(line).map_err(|error| {
            EvidenceFrontierBackendError::Corrupt(format!(
                "cannot decode frontier audit record: {error}"
            ))
        })?;
        let expected_sequence = u64::try_from(records.len())
            .ok()
            .and_then(|value| value.checked_add(1))
            .ok_or_else(|| {
                EvidenceFrontierBackendError::Corrupt(
                    "frontier audit sequence overflow".to_string(),
                )
            })?;
        if record.schema_version != EVIDENCE_FRONTIER_AUDIT_RECORD_SCHEMA_VERSION
            || record.audit_sequence != expected_sequence
            || record.backend_id != identity.backend_id
            || &record.backend_identity_sha256 != identity_sha256
            || record.store_id != store_id
            || record.expected_generation != previous_generation
            || record.previous_record_sha256 != previous_record_sha256
        {
            return Err(EvidenceFrontierBackendError::Corrupt(
                "frontier audit chain metadata is inconsistent".to_string(),
            ));
        }
        record.frontier.validate_structure().map_err(|error| {
            EvidenceFrontierBackendError::Corrupt(format!(
                "stored frontier is invalid: {error}"
            ))
        })?;
        let required_generation = previous_generation
            .unwrap_or(0_u64)
            .checked_add(1)
            .ok_or_else(|| {
                EvidenceFrontierBackendError::Corrupt(
                    "stored frontier generation overflow".to_string(),
                )
            })?;
        if record.frontier.store_id != store_id
            || &record.frontier.backend_identity_sha256 != identity_sha256
            || record.frontier.frontier_generation != required_generation
            || record.frontier_sha256
                != evidence_recovery_frontier_v2_sha256(&record.frontier).map_err(|error| {
                    EvidenceFrontierBackendError::Corrupt(format!(
                        "cannot hash stored frontier: {error}"
                    ))
                })?
            || record.record_sha256 != audit_record_sha256(&record)?
        {
            return Err(EvidenceFrontierBackendError::Corrupt(
                "frontier audit record digest or generation is inconsistent".to_string(),
            ));
        }
        previous_generation = Some(record.frontier.frontier_generation);
        previous_record_sha256 = Some(record.record_sha256.clone());
        records.push(record);
    }
    Ok(records)
}

fn audit_record_sha256(
    record: &EvidenceFrontierAuditRecordV1,
) -> Result<Sha256Digest, EvidenceFrontierBackendError> {
    let payload = EvidenceFrontierAuditPayloadV1 {
        schema_version: record.schema_version,
        audit_sequence: record.audit_sequence,
        backend_id: &record.backend_id,
        backend_identity_sha256: &record.backend_identity_sha256,
        store_id: &record.store_id,
        expected_generation: record.expected_generation,
        frontier: &record.frontier,
        frontier_sha256: &record.frontier_sha256,
        previous_record_sha256: record.previous_record_sha256.as_ref(),
    };
    let bytes = serde_json::to_vec(&payload).map_err(|error| {
        EvidenceFrontierBackendError::Invalid(format!(
            "cannot serialize frontier audit digest payload: {error}"
        ))
    })?;
    Ok(Sha256Digest::for_bytes(&bytes))
}

#[cfg(unix)]
fn private_directory_metadata(
    path: &Path,
    expected_parent: Option<&Path>,
    expected_uid: Option<u32>,
) -> Result<std::fs::Metadata, EvidenceFrontierBackendError> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;

    let canonical = path.canonicalize().map_err(unavailable)?;
    if canonical != path
        || expected_parent.is_some_and(|parent| canonical.parent() != Some(parent))
    {
        return Err(EvidenceFrontierBackendError::Invalid(
            "frontier backend directory is not a canonical direct child".to_string(),
        ));
    }
    let directory = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_CLOEXEC | libc::O_DIRECTORY | libc::O_NOFOLLOW)
        .open(path)
        .map_err(unavailable)?;
    let metadata = directory.metadata().map_err(unavailable)?;
    if !metadata.is_dir()
        || metadata.mode() & 0o077 != 0
        || expected_uid.is_some_and(|uid| metadata.uid() != uid)
    {
        return Err(EvidenceFrontierBackendError::Invalid(
            "frontier backend directory is not private and owner-bound".to_string(),
        ));
    }
    Ok(metadata)
}

#[cfg(unix)]
fn read_private_regular_file(
    path: &Path,
    expected_parent: &Path,
    expected_uid: u32,
    maximum: u64,
) -> Result<Vec<u8>, EvidenceFrontierBackendError> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;

    let link_metadata = std::fs::symlink_metadata(path).map_err(unavailable)?;
    if link_metadata.file_type().is_symlink() || path.parent() != Some(expected_parent) {
        return Err(EvidenceFrontierBackendError::Invalid(
            "frontier backend file is not a direct regular file".to_string(),
        ));
    }
    let mut file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
        .open(path)
        .map_err(unavailable)?;
    let before = file.metadata().map_err(unavailable)?;
    if !before.is_file()
        || before.uid() != expected_uid
        || before.nlink() != 1
        || before.mode() & 0o077 != 0
        || before.len() == 0
        || before.len() > maximum
    {
        return Err(EvidenceFrontierBackendError::Invalid(
            "frontier backend file metadata is not private and bounded".to_string(),
        ));
    }
    let mut bytes = Vec::new();
    (&mut file)
        .take(maximum + 1)
        .read_to_end(&mut bytes)
        .map_err(unavailable)?;
    let after = file.metadata().map_err(unavailable)?;
    if before.dev() != after.dev()
        || before.ino() != after.ino()
        || before.len() != after.len()
        || bytes.len() as u64 != before.len()
    {
        return Err(EvidenceFrontierBackendError::Unavailable(
            "frontier backend file changed during read".to_string(),
        ));
    }
    Ok(bytes)
}

#[cfg(unix)]
fn open_existing_journal(
    path: &Path,
    expected_parent: &Path,
    expected_uid: u32,
) -> Result<Option<File>, EvidenceFrontierBackendError> {
    use std::os::unix::fs::OpenOptionsExt;

    match std::fs::symlink_metadata(path) {
        Ok(metadata) => {
            if metadata.file_type().is_symlink() || path.parent() != Some(expected_parent) {
                return Err(EvidenceFrontierBackendError::Invalid(
                    "frontier journal is not a direct regular file".to_string(),
                ));
            }
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(unavailable(error)),
    }
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
        .open(path)
        .map_err(unavailable)?;
    validate_journal_metadata(&file, expected_uid)?;
    Ok(Some(file))
}

#[cfg(not(unix))]
fn open_existing_journal(
    _path: &Path,
    _expected_parent: &Path,
    _expected_uid: u32,
) -> Result<Option<File>, EvidenceFrontierBackendError> {
    Err(EvidenceFrontierBackendError::Unsupported)
}

#[cfg(unix)]
fn open_writable_journal(
    path: &Path,
    expected_parent: &Path,
    expected_uid: u32,
) -> Result<File, EvidenceFrontierBackendError> {
    use std::os::unix::fs::OpenOptionsExt;

    let file = match OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
        .open(path)
    {
        Ok(file) => file,
        Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
            let metadata = std::fs::symlink_metadata(path).map_err(unavailable)?;
            if metadata.file_type().is_symlink() || path.parent() != Some(expected_parent) {
                return Err(EvidenceFrontierBackendError::Invalid(
                    "frontier journal is not a direct regular file".to_string(),
                ));
            }
            OpenOptions::new()
                .read(true)
                .write(true)
                .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
                .open(path)
                .map_err(unavailable)?
        }
        Err(error) => return Err(unavailable(error)),
    };
    validate_journal_metadata(&file, expected_uid)?;
    Ok(file)
}

#[cfg(not(unix))]
fn open_writable_journal(
    _path: &Path,
    _expected_parent: &Path,
    _expected_uid: u32,
) -> Result<File, EvidenceFrontierBackendError> {
    Err(EvidenceFrontierBackendError::Unsupported)
}

#[cfg(unix)]
fn open_pinned_directory(
    path: &Path,
    expected_uid: u32,
    expected_device: u64,
    expected_inode: u64,
) -> Result<File, EvidenceFrontierBackendError> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;

    let directory = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_CLOEXEC | libc::O_DIRECTORY | libc::O_NOFOLLOW)
        .open(path)
        .map_err(unavailable)?;
    let metadata = directory.metadata().map_err(unavailable)?;
    if !metadata.is_dir()
        || metadata.uid() != expected_uid
        || metadata.mode() & 0o077 != 0
        || metadata.dev() != expected_device
        || metadata.ino() != expected_inode
    {
        return Err(EvidenceFrontierBackendError::Invalid(
            "frontier backend directory identity changed after bootstrap".to_string(),
        ));
    }
    Ok(directory)
}

#[cfg(not(unix))]
fn open_pinned_directory(
    _path: &Path,
    _expected_uid: u32,
    _expected_device: u64,
    _expected_inode: u64,
) -> Result<File, EvidenceFrontierBackendError> {
    Err(EvidenceFrontierBackendError::Unsupported)
}

#[cfg(unix)]
fn validate_journal_metadata(
    file: &File,
    expected_uid: u32,
) -> Result<(), EvidenceFrontierBackendError> {
    use std::os::unix::fs::MetadataExt;

    let metadata = file.metadata().map_err(unavailable)?;
    if !metadata.is_file()
        || metadata.uid() != expected_uid
        || metadata.nlink() != 1
        || metadata.mode() & 0o077 != 0
        || metadata.len() > EVIDENCE_FRONTIER_MAX_JOURNAL_BYTES
    {
        return Err(EvidenceFrontierBackendError::Invalid(
            "frontier journal metadata is not private, owner-bound, and bounded".to_string(),
        ));
    }
    Ok(())
}

fn unavailable(error: io::Error) -> EvidenceFrontierBackendError {
    EvidenceFrontierBackendError::Unavailable(error.to_string())
}

#[cfg(test)]
#[path = "frontier_backend_file_tests.rs"]
mod tests;
