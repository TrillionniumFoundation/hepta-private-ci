use std::fs::File;
use std::io::Read;
use std::path::Path;
use std::sync::Arc;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::VerifyingKey;
use serde_json::Value;

use crate::AuthBusAuthorityError;
use crate::IssuerRegistration;

const MAX_REGISTRY_BYTES: u64 = 65_536;

/// Immutable bytes read from an owner-controlled persistent issuer registry.
/// A message-issuer handle can only be resolved from this verified snapshot or
/// from the SQLite authority registry.
#[derive(Clone)]
pub struct VerifiedIssuerRegistry {
    bytes: Arc<[u8]>,
    digest: Digest32,
}

impl VerifiedIssuerRegistry {
    pub fn open_private(
        registry_path: &Path,
        expected_parent: &Path,
        maximum_bytes: u64,
    ) -> Result<Self, AuthBusAuthorityError> {
        let maximum_bytes = maximum_bytes.min(MAX_REGISTRY_BYTES);
        if maximum_bytes == 0 {
            return Err(AuthBusAuthorityError::UnsafeIssuerRegistry);
        }
        let bytes = read_private_registry(registry_path, expected_parent, maximum_bytes)?;
        let digest = Digest32::of_bytes(&bytes);
        if digest.is_zero() {
            return Err(AuthBusAuthorityError::UnsafeIssuerRegistry);
        }
        Ok(Self {
            bytes: Arc::from(bytes),
            digest,
        })
    }

    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    pub fn digest(&self) -> Digest32 {
        self.digest
    }

    pub fn resolve_message_issuer(
        &self,
        issuer_id: &StableId,
        key_epoch: Generation,
    ) -> Result<IssuerRegistration, AuthBusAuthorityError> {
        let value: Value = serde_json::from_slice(&self.bytes)
            .map_err(|_| AuthBusAuthorityError::UnsafeIssuerRegistry)?;
        let record = find_record(&value, issuer_id.as_str(), key_epoch.get())
            .ok_or(AuthBusAuthorityError::IssuerMissing)?;
        let public_key = record
            .get("public_key_hex")
            .and_then(Value::as_str)
            .ok_or(AuthBusAuthorityError::UnsafeIssuerRegistry)?;
        let revoked = record
            .get("revoked")
            .and_then(Value::as_bool)
            .ok_or(AuthBusAuthorityError::UnsafeIssuerRegistry)?;
        let verifying_key = VerifyingKey::from_bytes(&hex_bytes(public_key)?)
            .map_err(|_| AuthBusAuthorityError::UnsafeIssuerRegistry)?;
        IssuerRegistration::from_registry_parts(
            issuer_id.clone(),
            key_epoch,
            verifying_key,
            revoked,
            self.digest,
        )
    }
}

fn find_record<'a>(value: &'a Value, issuer_id: &str, key_epoch: u64) -> Option<&'a Value> {
    let matches = |record: &&Value| {
        record.get("issuer_id").and_then(Value::as_str) == Some(issuer_id)
            && record.get("key_epoch").and_then(Value::as_u64) == Some(key_epoch)
    };
    if matches(&value) {
        return Some(value);
    }
    value
        .get("issuers")
        .and_then(Value::as_array)
        .and_then(|records| records.iter().find(matches))
}

fn hex_bytes(value: &str) -> Result<[u8; 32], AuthBusAuthorityError> {
    if value.len() != 64 || !value.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(AuthBusAuthorityError::UnsafeIssuerRegistry);
    }
    let mut bytes = [0_u8; 32];
    for (index, byte) in bytes.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&value[index * 2..index * 2 + 2], 16)
            .map_err(|_| AuthBusAuthorityError::UnsafeIssuerRegistry)?;
    }
    Ok(bytes)
}

#[cfg(unix)]
fn read_private_registry(
    path: &Path,
    expected_parent: &Path,
    maximum_bytes: u64,
) -> Result<Vec<u8>, AuthBusAuthorityError> {
    use std::os::unix::fs::MetadataExt;

    if !path.is_absolute() || !expected_parent.is_absolute() || path.parent() != Some(expected_parent)
    {
        return Err(AuthBusAuthorityError::UnsafeIssuerRegistry);
    }
    let parent = expected_parent
        .canonicalize()
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    if parent != expected_parent {
        return Err(AuthBusAuthorityError::UnsafeIssuerRegistry);
    }
    let directory = std::fs::metadata(&parent)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    let before = std::fs::symlink_metadata(path)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    if !directory.is_dir()
        || directory.mode() & 0o077 != 0
        || !before.is_file()
        || before.nlink() != 1
        || before.uid() != directory.uid()
        || before.mode() & 0o077 != 0
        || before.len() > maximum_bytes
        || path
            .canonicalize()
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?
            != path
    {
        return Err(AuthBusAuthorityError::UnsafeIssuerRegistry);
    }
    let mut file = File::open(path)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    let opened = file
        .metadata()
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    let identity = |metadata: &std::fs::Metadata| {
        (
            metadata.dev(),
            metadata.ino(),
            metadata.len(),
            metadata.mtime(),
            metadata.mtime_nsec(),
            metadata.ctime(),
            metadata.ctime_nsec(),
        )
    };
    if identity(&opened) != identity(&before) {
        return Err(AuthBusAuthorityError::UnsafeIssuerRegistry);
    }
    let mut bytes = Vec::new();
    file.by_ref()
        .take(maximum_bytes.saturating_add(1))
        .read_to_end(&mut bytes)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    let after = std::fs::symlink_metadata(path)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > maximum_bytes
        || !after.is_file()
        || identity(&after) != identity(&before)
        || identity(
            &file
                .metadata()
                .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?,
        ) != identity(&before)
    {
        return Err(AuthBusAuthorityError::UnsafeIssuerRegistry);
    }
    Ok(bytes)
}

#[cfg(not(unix))]
fn read_private_registry(
    _path: &Path,
    _expected_parent: &Path,
    _maximum_bytes: u64,
) -> Result<Vec<u8>, AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeIssuerRegistry)
}
