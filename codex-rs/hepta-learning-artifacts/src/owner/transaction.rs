use std::error::Error as StdError;
use std::fmt;
use std::fs;
use std::fs::File;
use std::io::Read;
#[cfg(unix)]
use std::os::unix::fs::DirBuilderExt;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;
use std::str::FromStr;
use std::sync::Arc;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::HostDurabilityError;
use crate::durable_write_new_v1;
use crate::provision_private_root_v1;
use crate::sync_directory_v1;

const MAX_REQUEST_RECORD_BYTES: usize = 64 * 1024;
const MAX_RESULT_BYTES: usize = 2 * 1024 * 1024;
const PREPARED_MAGIC: &str = "HEPTA-ARTIFACT-OWNER-PREPARED-V1";
const RESULT_MAGIC: &str = "HEPTA-ARTIFACT-OWNER-RESULT-V1";
const AUDIT_MAGIC: &str = "HEPTA-ARTIFACT-OWNER-AUDIT-V1";

pub trait OwnerDurableStoreV1: Send + Sync {
    fn root(&self) -> &Path;
    fn ensure_directory(&self, relative: &Path) -> Result<(), OwnerJournalError>;
    fn write_new(&self, relative: &Path, bytes: &[u8]) -> Result<(), OwnerJournalError>;
    fn read_optional(
        &self,
        relative: &Path,
        maximum_bytes: usize,
    ) -> Result<Option<Vec<u8>>, OwnerJournalError>;
}

#[derive(Debug)]
pub struct FsOwnerDurableStoreV1 {
    root: PathBuf,
}

impl FsOwnerDurableStoreV1 {
    pub fn open(root: impl AsRef<Path>) -> Result<Self, OwnerJournalError> {
        let root = provision_private_root_v1(root).map_err(OwnerJournalError::Durability)?;
        let value = Self { root };
        for relative in [
            "host",
            "host/requests",
            "host/results",
            "host/audit",
            "host/status",
            "host/backups",
        ] {
            value.ensure_directory(Path::new(relative))?;
        }
        Ok(value)
    }

    fn resolve(&self, relative: &Path) -> Result<PathBuf, OwnerJournalError> {
        validate_relative(relative)?;
        let mut current = self.root.clone();
        let components: Vec<_> = relative.components().collect();
        for (index, component) in components.iter().enumerate() {
            let Component::Normal(name) = component else {
                return Err(OwnerJournalError::InvalidPath);
            };
            current.push(name);
            if index + 1 < components.len() && current.exists() {
                let metadata = fs::symlink_metadata(&current)?;
                if metadata.file_type().is_symlink() || !metadata.is_dir() {
                    return Err(OwnerJournalError::InvalidPath);
                }
            }
        }
        Ok(current)
    }
}

impl OwnerDurableStoreV1 for FsOwnerDurableStoreV1 {
    fn root(&self) -> &Path {
        &self.root
    }

    fn ensure_directory(&self, relative: &Path) -> Result<(), OwnerJournalError> {
        let path = self.resolve(relative)?;
        if path.exists() {
            let metadata = fs::symlink_metadata(&path)?;
            if metadata.file_type().is_symlink() || !metadata.is_dir() {
                return Err(OwnerJournalError::InvalidPath);
            }
            return Ok(());
        }
        let parent = path.parent().ok_or(OwnerJournalError::InvalidPath)?;
        let parent_metadata = fs::symlink_metadata(parent)?;
        if parent_metadata.file_type().is_symlink() || !parent_metadata.is_dir() {
            return Err(OwnerJournalError::InvalidPath);
        }
        let mut builder = fs::DirBuilder::new();
        #[cfg(unix)]
        builder.mode(0o700);
        builder.create(&path)?;
        sync_directory_v1(parent).map_err(OwnerJournalError::Durability)?;
        Ok(())
    }

    fn write_new(&self, relative: &Path, bytes: &[u8]) -> Result<(), OwnerJournalError> {
        let path = self.resolve(relative)?;
        durable_write_new_v1(path, bytes).map_err(OwnerJournalError::Durability)
    }

    fn read_optional(
        &self,
        relative: &Path,
        maximum_bytes: usize,
    ) -> Result<Option<Vec<u8>>, OwnerJournalError> {
        let path = self.resolve(relative)?;
        let metadata = match fs::symlink_metadata(&path) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(error.into()),
        };
        if metadata.file_type().is_symlink()
            || !metadata.is_file()
            || metadata.len() > maximum_bytes as u64
        {
            return Err(OwnerJournalError::Corrupt);
        }
        let mut bytes = Vec::with_capacity(metadata.len() as usize);
        File::open(path)?
            .take(maximum_bytes as u64 + 1)
            .read_to_end(&mut bytes)?;
        if bytes.len() > maximum_bytes {
            return Err(OwnerJournalError::Corrupt);
        }
        Ok(Some(bytes))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OwnerRequestDispositionV1 {
    Execute,
    ReturnStored(Vec<u8>),
}

pub struct OwnerRequestJournalV1 {
    store: Arc<dyn OwnerDurableStoreV1>,
}

impl fmt::Debug for OwnerRequestJournalV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("OwnerRequestJournalV1")
            .field("root", &self.store.root())
            .finish()
    }
}

impl OwnerRequestJournalV1 {
    #[must_use]
    pub fn new(store: Arc<dyn OwnerDurableStoreV1>) -> Self {
        Self { store }
    }

    pub fn prepare(
        &self,
        request_id: &StableId,
        request_digest: Digest32,
        client_id: &StableId,
        action: &str,
    ) -> Result<OwnerRequestDispositionV1, OwnerJournalError> {
        let prepared = prepared_path(request_id);
        let result = result_path(request_id);
        if let Some(bytes) = self.store.read_optional(&result, MAX_RESULT_BYTES)? {
            let (record_digest, response) = decode_result(&bytes)?;
            if record_digest != request_digest {
                return Err(OwnerJournalError::ReplayConflict);
            }
            return Ok(OwnerRequestDispositionV1::ReturnStored(response));
        }
        if let Some(bytes) = self
            .store
            .read_optional(&prepared, MAX_REQUEST_RECORD_BYTES)?
        {
            let record = decode_prepared(&bytes)?;
            if record.request_id != *request_id
                || record.request_digest != request_digest
                || record.client_id != *client_id
                || record.action != action
            {
                return Err(OwnerJournalError::ReplayConflict);
            }
            return Ok(OwnerRequestDispositionV1::Execute);
        }
        let bytes = encode_prepared(request_id, request_digest, client_id, action)?;
        match self.store.write_new(&prepared, &bytes) {
            Ok(()) => Ok(OwnerRequestDispositionV1::Execute),
            Err(OwnerJournalError::Durability(HostDurabilityError::ExistingTarget)) => {
                self.prepare(request_id, request_digest, client_id, action)
            }
            Err(error) => Err(error),
        }
    }

    pub fn complete(
        &self,
        request_id: &StableId,
        request_digest: Digest32,
        response: &[u8],
    ) -> Result<Vec<u8>, OwnerJournalError> {
        if response.len() > MAX_RESULT_BYTES / 2 {
            return Err(OwnerJournalError::Capacity);
        }
        let path = result_path(request_id);
        let bytes = encode_result(request_digest, response);
        match self.store.write_new(&path, &bytes) {
            Ok(()) => Ok(response.to_vec()),
            Err(OwnerJournalError::Durability(HostDurabilityError::ExistingTarget)) => {
                let existing = self
                    .store
                    .read_optional(&path, MAX_RESULT_BYTES)?
                    .ok_or(OwnerJournalError::Corrupt)?;
                let (existing_digest, existing_response) = decode_result(&existing)?;
                if existing_digest != request_digest || existing_response != response {
                    return Err(OwnerJournalError::ReplayConflict);
                }
                Ok(existing_response)
            }
            Err(error) => Err(error),
        }
    }

    pub fn record_audit(
        &self,
        request_id: &StableId,
        request_digest: Digest32,
        client_id: &StableId,
        action: &str,
        outcome: &str,
        occurred_at: u64,
        response: &[u8],
    ) -> Result<(), OwnerJournalError> {
        let response_digest = Digest32::of_bytes(response);
        let bytes = encode_audit(
            request_id,
            request_digest,
            client_id,
            action,
            outcome,
            occurred_at,
            response_digest,
        )?;
        let path = audit_path(request_id);
        match self.store.write_new(&path, &bytes) {
            Ok(()) => Ok(()),
            Err(OwnerJournalError::Durability(HostDurabilityError::ExistingTarget)) => {
                let existing = self
                    .store
                    .read_optional(&path, MAX_REQUEST_RECORD_BYTES)?
                    .ok_or(OwnerJournalError::Corrupt)?;
                if existing == bytes {
                    Ok(())
                } else {
                    Err(OwnerJournalError::ReplayConflict)
                }
            }
            Err(error) => Err(error),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct PreparedRecordV1 {
    request_id: StableId,
    request_digest: Digest32,
    client_id: StableId,
    action: String,
}

fn encode_prepared(
    request_id: &StableId,
    request_digest: Digest32,
    client_id: &StableId,
    action: &str,
) -> Result<Vec<u8>, OwnerJournalError> {
    validate_atom(action)?;
    Ok(format!(
        "{PREPARED_MAGIC}\n{request_id}\n{request_digest}\n{client_id}\n{action}\n"
    )
    .into_bytes())
}

fn decode_prepared(bytes: &[u8]) -> Result<PreparedRecordV1, OwnerJournalError> {
    let text = std::str::from_utf8(bytes).map_err(|_| OwnerJournalError::Corrupt)?;
    let lines: Vec<_> = text.lines().collect();
    if lines.len() != 5 || lines[0] != PREPARED_MAGIC || !text.ends_with('\n') {
        return Err(OwnerJournalError::Corrupt);
    }
    validate_atom(lines[4])?;
    Ok(PreparedRecordV1 {
        request_id: StableId::new(lines[1].to_owned()).map_err(|_| OwnerJournalError::Corrupt)?,
        request_digest: Digest32::from_str(lines[2]).map_err(|_| OwnerJournalError::Corrupt)?,
        client_id: StableId::new(lines[3].to_owned()).map_err(|_| OwnerJournalError::Corrupt)?,
        action: lines[4].to_owned(),
    })
}

fn encode_result(request_digest: Digest32, response: &[u8]) -> Vec<u8> {
    format!(
        "{RESULT_MAGIC}\n{request_digest}\n{}\n{}\n",
        response.len(),
        encode_hex(response)
    )
    .into_bytes()
}

fn decode_result(bytes: &[u8]) -> Result<(Digest32, Vec<u8>), OwnerJournalError> {
    let text = std::str::from_utf8(bytes).map_err(|_| OwnerJournalError::Corrupt)?;
    let lines: Vec<_> = text.lines().collect();
    if lines.len() != 4 || lines[0] != RESULT_MAGIC || !text.ends_with('\n') {
        return Err(OwnerJournalError::Corrupt);
    }
    let digest = Digest32::from_str(lines[1]).map_err(|_| OwnerJournalError::Corrupt)?;
    let length = lines[2]
        .parse::<usize>()
        .map_err(|_| OwnerJournalError::Corrupt)?;
    let response = decode_hex(lines[3])?;
    if response.len() != length {
        return Err(OwnerJournalError::Corrupt);
    }
    Ok((digest, response))
}

fn encode_audit(
    request_id: &StableId,
    request_digest: Digest32,
    client_id: &StableId,
    action: &str,
    outcome: &str,
    occurred_at: u64,
    response_digest: Digest32,
) -> Result<Vec<u8>, OwnerJournalError> {
    validate_atom(action)?;
    validate_atom(outcome)?;
    Ok(format!(
        "{AUDIT_MAGIC}\nrequest_id={request_id}\nrequest_digest={request_digest}\nclient_id={client_id}\naction={action}\noutcome={outcome}\noccurred_at={occurred_at}\nresponse_digest={response_digest}\n"
    )
    .into_bytes())
}

fn prepared_path(request_id: &StableId) -> PathBuf {
    PathBuf::from("host/requests").join(format!("{request_id}.prepared"))
}

fn result_path(request_id: &StableId) -> PathBuf {
    PathBuf::from("host/results").join(format!("{request_id}.result"))
}

fn audit_path(request_id: &StableId) -> PathBuf {
    PathBuf::from("host/audit").join(format!("{request_id}.audit"))
}

fn validate_relative(path: &Path) -> Result<(), OwnerJournalError> {
    if path.as_os_str().is_empty()
        || path.is_absolute()
        || path.components().any(|component| !matches!(component, Component::Normal(_)))
    {
        return Err(OwnerJournalError::InvalidPath);
    }
    Ok(())
}

fn validate_atom(value: &str) -> Result<(), OwnerJournalError> {
    if value.is_empty()
        || value.len() > 256
        || value
            .bytes()
            .any(|byte| byte == b'\n' || byte == b'\r' || byte == b'=' || byte == b'|')
    {
        return Err(OwnerJournalError::InvalidRecord);
    }
    Ok(())
}

fn encode_hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        output.push(DIGITS[(byte >> 4) as usize] as char);
        output.push(DIGITS[(byte & 0x0f) as usize] as char);
    }
    output
}

fn decode_hex(value: &str) -> Result<Vec<u8>, OwnerJournalError> {
    if !value.len().is_multiple_of(2) {
        return Err(OwnerJournalError::Corrupt);
    }
    let mut output = Vec::with_capacity(value.len() / 2);
    for pair in value.as_bytes().chunks_exact(2) {
        let high = decode_nibble(pair[0]).ok_or(OwnerJournalError::Corrupt)?;
        let low = decode_nibble(pair[1]).ok_or(OwnerJournalError::Corrupt)?;
        output.push((high << 4) | low);
    }
    Ok(output)
}

const fn decode_nibble(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'a'..=b'f' => Some(value - b'a' + 10),
        _ => None,
    }
}

#[derive(Debug)]
pub enum OwnerJournalError {
    Durability(HostDurabilityError),
    Io(std::io::Error),
    InvalidPath,
    InvalidRecord,
    Corrupt,
    ReplayConflict,
    Capacity,
}

impl fmt::Display for OwnerJournalError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for OwnerJournalError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Durability(error) => Some(error),
            Self::Io(error) => Some(error),
            Self::InvalidPath
            | Self::InvalidRecord
            | Self::Corrupt
            | Self::ReplayConflict
            | Self::Capacity => None,
        }
    }
}

impl From<std::io::Error> for OwnerJournalError {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::AtomicU64;
    use std::sync::atomic::Ordering;

    static NEXT_TEST: AtomicU64 = AtomicU64::new(1);

    #[test]
    fn exact_request_replay_returns_the_original_response_and_drift_conflicts() {
        let id = NEXT_TEST.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-owner-journal-{}-{id}",
            std::process::id()
        ));
        let store: Arc<dyn OwnerDurableStoreV1> =
            Arc::new(FsOwnerDurableStoreV1::open(&root).expect("open store"));
        let journal = OwnerRequestJournalV1::new(store);
        let request_id = StableId::new("request-one".to_owned()).expect("request id");
        let client_id = StableId::new("client-one".to_owned()).expect("client id");
        let digest = Digest32::of_bytes(b"request");
        assert_eq!(
            journal
                .prepare(&request_id, digest, &client_id, "status")
                .expect("prepare"),
            OwnerRequestDispositionV1::Execute
        );
        assert_eq!(
            journal
                .complete(&request_id, digest, b"response")
                .expect("complete"),
            b"response"
        );
        assert_eq!(
            journal
                .prepare(&request_id, digest, &client_id, "status")
                .expect("replay"),
            OwnerRequestDispositionV1::ReturnStored(b"response".to_vec())
        );
        assert!(matches!(
            journal.prepare(
                &request_id,
                Digest32::of_bytes(b"drift"),
                &client_id,
                "status"
            ),
            Err(OwnerJournalError::ReplayConflict)
        ));
        let _ = fs::remove_dir_all(root);
    }
}
