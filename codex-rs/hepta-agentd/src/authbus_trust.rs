//! One explicitly installed owner key and bounded thread allowlist.

#[cfg(unix)]
use std::fs::File;
#[cfg(unix)]
use std::io::Read;
use std::path::Path;

use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;

use crate::AgentdError;
use crate::AgentdIdentity;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct TextTrust {
    schema_version: u32,
    agent_id: String,
    issuer_id: String,
    key_epoch: u64,
    public_key_hex: String,
    revoked: bool,
    thread_ids: Vec<String>,
}

impl TextTrust {
    /// Reload the owner-controlled file for each admission and dispatch stage.
    /// Updating the public key does not synthesize a signature or a grant.
    pub fn load(path: &Path, identity: &AgentdIdentity) -> Result<Self, AgentdError> {
        let bytes = read_private_owner_file(path, identity, 16_384)?;
        let trust: Self = serde_json::from_slice(&bytes)?;
        if trust.schema_version != 1
            || trust.agent_id != identity.agent_id.as_str()
            || trust.thread_ids.len() > 16
            || trust
                .thread_ids
                .iter()
                .any(|id| id.is_empty() || id.len() > 128)
        {
            return Err(invalid(
                "trust registry owner, schema or thread bound is invalid",
            ));
        }
        trust.issuer()?;
        Ok(trust)
    }

    pub fn issuer(&self) -> Result<IssuerRegistration, AgentdError> {
        Ok(IssuerRegistration {
            issuer_id: StableId::new(&self.issuer_id)
                .map_err(|error| invalid(&error.to_string()))?,
            key_epoch: Generation::new(self.key_epoch)
                .map_err(|error| invalid(&error.to_string()))?,
            verifying_key: VerifyingKey::from_bytes(&hex_bytes(&self.public_key_hex)?)
                .map_err(|_| invalid("invalid registered Ed25519 public key"))?,
            revoked: self.revoked,
        })
    }

    pub fn permits(&self, thread_id: &str) -> bool {
        !self.revoked && self.thread_ids.iter().any(|id| id == thread_id)
    }
}

pub(crate) fn hex_bytes<const N: usize>(value: &str) -> Result<[u8; N], AgentdError> {
    if value.len() != N * 2 || !value.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err(invalid("invalid fixed-width hexadecimal value"));
    }
    let mut bytes = [0; N];
    for (index, byte) in bytes.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&value[index * 2..index * 2 + 2], 16)
            .map_err(|_| invalid("invalid hexadecimal value"))?;
    }
    Ok(bytes)
}

// This profile uses the already-private owner home. Refuse links, foreign
// ownership, writable-by-others files, oversized files and replacement/drift
// during the read. Do not create a file, key or registration on this path.
#[cfg(unix)]
pub(crate) fn read_private_owner_file(
    path: &Path,
    identity: &AgentdIdentity,
    maximum_bytes: u64,
) -> Result<Vec<u8>, AgentdError> {
    use std::os::unix::fs::MetadataExt;

    if !path.is_absolute()
        || path.parent() != Some(identity.home_root.as_path())
        || identity.home_root.canonicalize()? != identity.home_root
    {
        return Err(invalid(
            "trust file must be a direct child of the canonical Agent home",
        ));
    }
    let home = std::fs::metadata(&identity.home_root)?;
    let before = std::fs::symlink_metadata(path)?;
    if !home.is_dir()
        || home.mode() & 0o077 != 0
        || !before.is_file()
        || before.nlink() != 1
        || before.uid() != home.uid()
        || before.mode() & 0o077 != 0
        || before.len() > maximum_bytes
    {
        return Err(invalid(
            "trust file must be a private owner-controlled regular file",
        ));
    }
    let mut file = File::open(path)?;
    let opened = file.metadata()?;
    let identity = |m: &std::fs::Metadata| {
        (
            m.dev(),
            m.ino(),
            m.len(),
            m.mtime(),
            m.mtime_nsec(),
            m.ctime(),
            m.ctime_nsec(),
        )
    };
    if identity(&opened) != identity(&before) {
        return Err(invalid("trust file changed while opening"));
    }
    let mut bytes = Vec::new();
    file.by_ref()
        .take(maximum_bytes.saturating_add(1))
        .read_to_end(&mut bytes)?;
    let after = std::fs::symlink_metadata(path)?;
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > maximum_bytes
        || !after.is_file()
        || identity(&after) != identity(&before)
        || identity(&file.metadata()?) != identity(&before)
    {
        return Err(invalid("trust file changed while reading"));
    }
    Ok(bytes)
}

#[cfg(not(unix))]
pub(crate) fn read_private_owner_file(
    _path: &Path,
    _identity: &AgentdIdentity,
    _maximum_bytes: u64,
) -> Result<Vec<u8>, AgentdError> {
    Err(invalid(
        "private owner configuration currently requires Unix ownership checks",
    ))
}

pub(crate) fn invalid(message: &str) -> AgentdError {
    AgentdError::Invalid(format!("AuthBus text: {message}"))
}
