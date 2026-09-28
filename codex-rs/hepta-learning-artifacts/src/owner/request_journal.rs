//! Create-only request metadata beneath the retained owner writer fence.
//! A checksum detects corruption; head signatures and registry support bindings
//! establish semantic integrity. The embedding host still protects ancestors.

use std::collections::BTreeMap;
#[cfg(unix)]
use std::fs;
#[cfg(unix)]
use std::fs::File;
#[cfg(unix)]
use std::fs::OpenOptions;
#[cfg(unix)]
use std::io::Read;
#[cfg(unix)]
use std::io::Write;
#[cfg(unix)]
use std::os::unix::fs::DirBuilderExt;
#[cfg(unix)]
use std::os::unix::fs::MetadataExt;
#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::LearningArtifactOwnerServiceError as Error;
use super::request_identity::RequestIdentityVerifier;
#[cfg(unix)]
use super::request_record::MAX_REQUEST_RECORD_BYTES;
use super::request_record::RequestRecord;
use crate::ArtifactOwnerHostError;
use crate::MAX_DURABLE_ARTIFACT_RECORDS;

const MAX_JOURNAL_BYTES: usize = 64 * 1024 * 1024;

pub(super) struct RequestJournal {
    directory: PathBuf,
    records: BTreeMap<StableId, RequestRecord>,
    encoded_bytes: usize,
}

impl RequestJournal {
    pub(super) fn open(root: &Path, registry: &StableId, scope: Digest32, binding: Digest32,
        verifier: &RequestIdentityVerifier) -> Result<Self, Error>
    {
        #[cfg(not(unix))]
        {
            let _ = (root, registry, scope, binding, verifier);
            Err(Error::ControlIo(std::io::Error::new(std::io::ErrorKind::Unsupported,
                "request journal requires qualified directory synchronization")))
        }
        #[cfg(unix)]
        {
            let directory = root.join("writer/request-identities-v1");
            match fs::DirBuilder::new().mode(0o700).create(&directory) {
                Ok(()) => {}
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {}
                Err(error) => return Err(Error::ControlIo(error)),
            }
            if !fs::symlink_metadata(&directory).map_err(Error::ControlIo)?.is_dir() {
                return Err(Error::RequestBindingCorrupt);
            }
            let mut value = Self { directory, records: BTreeMap::new(), encoded_bytes: 0 };
            for entry in fs::read_dir(&value.directory).map_err(Error::ControlIo)? {
                if value.records.len() >= MAX_DURABLE_ARTIFACT_RECORDS { return Err(capacity()); }
                let entry = entry.map_err(Error::ControlIo)?;
                let (file, bytes) = read_record(&entry.path())?;
                value.encoded_bytes = value.encoded_bytes.checked_add(bytes.len()).ok_or_else(capacity)?;
                if value.encoded_bytes > MAX_JOURNAL_BYTES { return Err(capacity()); }
                let record = RequestRecord::decode(&bytes, verifier)?;
                if record.signed_head.witness.registry_id != *registry
                    || record.admission.withdrawal_scope_digest != scope
                    || record.signed_head.binding != binding
                    || entry.file_name().to_str() != Some(record_name(&record.operation_id).as_str())
                { return Err(Error::RequestBindingCorrupt); }
                // A complete record may precede an unknown sync outcome. Reuse
                // this validated handle, never reopen by path for reconciliation.
                file.sync_all().map_err(Error::ControlIo)?;
                if value.records.insert(record.operation_id.clone(), record).is_some() {
                    return Err(Error::RequestBindingCorrupt);
                }
            }
            value.sync_directories()?;
            Ok(value)
        }
    }

    pub(super) fn records(&self) -> impl Iterator<Item = &RequestRecord> { self.records.values() }
    pub(super) fn get(&self, operation: &StableId) -> Option<&RequestRecord> { self.records.get(operation) }
    pub(super) fn len(&self) -> usize { self.records.len() }
    pub(super) fn encoded_bytes(&self) -> usize { self.encoded_bytes }

    /// Persist before Prepared. Failure is uncertainty, not permission to reuse
    /// an operation. Existing bytes must agree exactly and are never overwritten.
    pub(super) fn bind(&mut self, mut record: RequestRecord, verifier: &RequestIdentityVerifier) -> Result<(), Error> {
        if let Some(previous) = self.records.get(&record.operation_id) {
            return if previous.identity == record.identity { Ok(()) } else { Err(Error::RequestMismatch) };
        }
        let bytes = record.encode()?;
        let total = self.encoded_bytes.checked_add(bytes.len()).ok_or_else(capacity)?;
        if self.records.len() >= MAX_DURABLE_ARTIFACT_RECORDS || total > MAX_JOURNAL_BYTES {
            return Err(capacity());
        }
        #[cfg(not(unix))]
        {
            let _ = (&mut record, verifier, &self.directory, total);
            Err(Error::ControlIo(std::io::Error::new(std::io::ErrorKind::Unsupported,
                "request journal requires qualified directory synchronization")))
        }
        #[cfg(unix)]
        {
            let path = self.directory.join(record_name(&record.operation_id));
            match OpenOptions::new().write(true).create_new(true).mode(0o600).open(&path) {
                Ok(mut file) => { file.write_all(&bytes).map_err(Error::ControlIo)?;
                    file.sync_all().map_err(Error::ControlIo)?; }
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                    let (file, existing) = read_record(&path)?;
                    let previous = RequestRecord::decode(&existing, verifier)?;
                    if previous.identity != record.identity || previous.operation_id != record.operation_id {
                        return Err(Error::RequestMismatch);
                    }
                    record = previous;
                    file.sync_all().map_err(Error::ControlIo)?;
                }
                Err(error) => return Err(Error::ControlIo(error)),
            }
            self.sync_directories()?;
            self.encoded_bytes = total;
            self.records.insert(record.operation_id.clone(), record);
            Ok(())
        }
    }

    #[cfg(unix)]
    fn sync_directories(&self) -> Result<(), Error> {
        let writer = self.directory.parent().ok_or(Error::RequestBindingCorrupt)?;
        let root = writer.parent().ok_or(Error::RequestBindingCorrupt)?;
        for directory in [self.directory.as_path(), writer, root] {
            File::open(directory).and_then(|file| file.sync_all()).map_err(Error::ControlIo)?;
        }
        Ok(())
    }
}

fn capacity() -> Error { Error::Host(ArtifactOwnerHostError::Capacity) }
#[cfg(unix)]
fn record_name(operation: &StableId) -> String {
    format!("{}.request", Digest32::of_bytes(operation.as_str().as_bytes()))
}

#[cfg(unix)]
fn read_record(path: &Path) -> Result<(File, Vec<u8>), Error> {
    let before = fs::symlink_metadata(path).map_err(Error::ControlIo)?;
    if !before.is_file() || before.len() > MAX_REQUEST_RECORD_BYTES as u64 {
        return Err(Error::RequestBindingCorrupt);
    }
    let mut file = OpenOptions::new().read(true).write(true).open(path).map_err(Error::ControlIo)?;
    let after = file.metadata().map_err(Error::ControlIo)?;
    if !after.is_file() || after.len() != before.len() { return Err(Error::RequestBindingCorrupt); }
    #[cfg(unix)]
    if before.dev() != after.dev() || before.ino() != after.ino() || after.nlink() != 1 {
        return Err(Error::RequestBindingCorrupt);
    }
    let mut bytes = Vec::new();
    (&mut file).take(MAX_REQUEST_RECORD_BYTES as u64 + 1).read_to_end(&mut bytes)
        .map_err(Error::ControlIo)?;
    if bytes.len() > MAX_REQUEST_RECORD_BYTES { return Err(Error::RequestBindingCorrupt); }
    Ok((file, bytes))
}
