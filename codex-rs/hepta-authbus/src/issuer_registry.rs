use std::collections::BTreeMap;
use std::fs::File;
use std::io::Read;
use std::path::Path;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::VerifyingKey;
use serde_json::Value;

use crate::IssuerRegistration;
use crate::IssuerRegistrationView;

const MAX_REGISTRY_ENTRIES: usize = 4096;
const MAX_REGISTRY_FILE_BYTES: u64 = 1_048_576;

/// A bounded, owner-controlled issuer registry document.
///
/// This is the only public construction path for a message issuer registration
/// outside the durable AuthBus authority database. The file is re-opened and
/// checked as a private regular file; message payloads never supply key material.
pub struct PrivateIssuerRegistryDocument {
    bytes: Vec<u8>,
    digest: Digest32,
    entries: BTreeMap<(String, u64), IssuerRegistrationView>,
}

#[derive(Debug, thiserror::Error)]
pub enum IssuerRegistryError {
    #[error("issuer registry path or file metadata is unsafe")]
    UnsafeFile,
    #[error("issuer registry document is invalid: {0}")]
    InvalidDocument(&'static str),
    #[error("issuer registry entry was not found")]
    IssuerMissing,
    #[error("issuer registry I/O failed: {0}")]
    Io(String),
}

impl PrivateIssuerRegistryDocument {
    /// Load a persisted private registry file that is a direct child of
    /// `expected_parent`. The caller supplies a tighter bound when appropriate.
    pub fn load(
        path: &Path,
        expected_parent: &Path,
        maximum_bytes: u64,
    ) -> Result<Self, IssuerRegistryError> {
        let maximum_bytes = maximum_bytes.min(MAX_REGISTRY_FILE_BYTES);
        if maximum_bytes == 0 {
            return Err(IssuerRegistryError::UnsafeFile);
        }
        let bytes = read_private_registry(path, expected_parent, maximum_bytes)?;
        let value: Value = serde_json::from_slice(&bytes)
            .map_err(|_| IssuerRegistryError::InvalidDocument("invalid JSON"))?;
        let mut entries = BTreeMap::new();
        collect_entries(&value, &mut entries)?;
        if entries.is_empty() {
            return Err(IssuerRegistryError::InvalidDocument(
                "no issuer registrations",
            ));
        }
        Ok(Self {
            digest: Digest32::of_bytes(&bytes),
            bytes,
            entries,
        })
    }

    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    pub fn digest(&self) -> Digest32 {
        self.digest
    }

    /// Resolve an opaque registration by exact issuer identity and key epoch.
    pub fn message_issuer(
        &self,
        issuer_id: &StableId,
        key_epoch: Generation,
    ) -> Result<IssuerRegistration, IssuerRegistryError> {
        let view = self
            .entries
            .get(&(issuer_id.to_string(), key_epoch.get()))
            .ok_or(IssuerRegistryError::IssuerMissing)?
            .clone();
        Ok(IssuerRegistration::from_registry_view(view, self.digest))
    }
}

fn collect_entries(
    value: &Value,
    entries: &mut BTreeMap<(String, u64), IssuerRegistrationView>,
) -> Result<(), IssuerRegistryError> {
    match value {
        Value::Object(object) => {
            let candidate = (
                object.get("issuer_id"),
                object.get("key_epoch"),
                object.get("public_key_hex"),
                object.get("revoked"),
            );
            if let (Some(issuer), Some(epoch), Some(key), Some(revoked)) = candidate {
                let issuer = issuer.as_str().ok_or(IssuerRegistryError::InvalidDocument(
                    "issuer_id must be a string",
                ))?;
                let issuer_id = StableId::new(issuer)
                    .map_err(|_| IssuerRegistryError::InvalidDocument("issuer_id is invalid"))?;
                let epoch = epoch.as_u64().ok_or(IssuerRegistryError::InvalidDocument(
                    "key_epoch must be a positive integer",
                ))?;
                let key_epoch = Generation::new(epoch)
                    .map_err(|_| IssuerRegistryError::InvalidDocument("key_epoch is invalid"))?;
                let key = key.as_str().ok_or(IssuerRegistryError::InvalidDocument(
                    "public_key_hex must be a string",
                ))?;
                let verifying_key =
                    VerifyingKey::from_bytes(&hex_bytes::<32>(key)?).map_err(|_| {
                        IssuerRegistryError::InvalidDocument("Ed25519 public key is invalid")
                    })?;
                let revoked = revoked
                    .as_bool()
                    .ok_or(IssuerRegistryError::InvalidDocument(
                        "revoked must be a boolean",
                    ))?;
                if entries.len() >= MAX_REGISTRY_ENTRIES {
                    return Err(IssuerRegistryError::InvalidDocument(
                        "issuer registry capacity exceeded",
                    ));
                }
                let identity = (issuer_id.to_string(), key_epoch.get());
                if entries
                    .insert(
                        identity,
                        IssuerRegistrationView {
                            issuer_id,
                            key_epoch,
                            verifying_key,
                            revoked,
                        },
                    )
                    .is_some()
                {
                    return Err(IssuerRegistryError::InvalidDocument(
                        "duplicate issuer epoch",
                    ));
                }
                return Ok(());
            }
            for child in object.values() {
                collect_entries(child, entries)?;
            }
        }
        Value::Array(values) => {
            for child in values {
                collect_entries(child, entries)?;
            }
        }
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => {}
    }
    Ok(())
}

fn hex_bytes<const N: usize>(value: &str) -> Result<[u8; N], IssuerRegistryError> {
    if value.len() != N * 2 || !value.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(IssuerRegistryError::InvalidDocument(
            "public key must be fixed-width hexadecimal",
        ));
    }
    let mut bytes = [0; N];
    for (index, byte) in bytes.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&value[index * 2..index * 2 + 2], 16).map_err(|_| {
            IssuerRegistryError::InvalidDocument("public key contains invalid hexadecimal")
        })?;
    }
    Ok(bytes)
}

#[cfg(unix)]
fn read_private_registry(
    path: &Path,
    expected_parent: &Path,
    maximum_bytes: u64,
) -> Result<Vec<u8>, IssuerRegistryError> {
    use std::os::unix::fs::MetadataExt;

    if !path.is_absolute()
        || !expected_parent.is_absolute()
        || path.parent() != Some(expected_parent)
        || expected_parent.canonicalize().map_err(io_error)? != expected_parent
        || path.canonicalize().map_err(io_error)? != path
    {
        return Err(IssuerRegistryError::UnsafeFile);
    }
    let parent = std::fs::metadata(expected_parent).map_err(io_error)?;
    let before = std::fs::symlink_metadata(path).map_err(io_error)?;
    if !parent.is_dir()
        || parent.mode() & 0o077 != 0
        || !before.is_file()
        || before.nlink() != 1
        || before.uid() != parent.uid()
        || before.mode() & 0o077 != 0
        || before.len() > maximum_bytes
    {
        return Err(IssuerRegistryError::UnsafeFile);
    }
    let mut file = File::open(path).map_err(io_error)?;
    let opened = file.metadata().map_err(io_error)?;
    if metadata_identity(&opened) != metadata_identity(&before) {
        return Err(IssuerRegistryError::UnsafeFile);
    }
    let mut bytes = Vec::new();
    file.by_ref()
        .take(maximum_bytes.saturating_add(1))
        .read_to_end(&mut bytes)
        .map_err(io_error)?;
    let after = std::fs::symlink_metadata(path).map_err(io_error)?;
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > maximum_bytes
        || metadata_identity(&after) != metadata_identity(&before)
        || metadata_identity(&file.metadata().map_err(io_error)?) != metadata_identity(&before)
    {
        return Err(IssuerRegistryError::UnsafeFile);
    }
    Ok(bytes)
}

#[cfg(unix)]
fn metadata_identity(metadata: &std::fs::Metadata) -> (u64, u64, u64, i64, i64, i64, i64) {
    use std::os::unix::fs::MetadataExt;
    (
        metadata.dev(),
        metadata.ino(),
        metadata.len(),
        metadata.mtime(),
        metadata.mtime_nsec(),
        metadata.ctime(),
        metadata.ctime_nsec(),
    )
}

#[cfg(not(unix))]
fn read_private_registry(
    _path: &Path,
    _expected_parent: &Path,
    _maximum_bytes: u64,
) -> Result<Vec<u8>, IssuerRegistryError> {
    Err(IssuerRegistryError::UnsafeFile)
}

fn io_error(error: std::io::Error) -> IssuerRegistryError {
    IssuerRegistryError::Io(error.to_string())
}
