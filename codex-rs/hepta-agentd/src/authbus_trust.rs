//! One explicitly installed owner key and bounded thread allowlist.

#[cfg(unix)]
use std::fs::File;
#[cfg(unix)]
use std::io::Read;
use std::path::Path;

use codex_hepta_authbus::AuthBusAuthorityError;
use codex_hepta_authbus::AuthBusAuthorityHost;
use codex_hepta_authbus::IssuerLifecycleState;
use codex_hepta_authbus::IssuerPurpose;
use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::IssuerSpec;
use codex_hepta_types::Digest32;
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
    /// The file declares expected identity and routing policy; durable issuer
    /// authority always comes from `AuthBusAuthorityHost`.
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
        trust.identity()?;
        trust.verifying_key()?;
        Ok(trust)
    }

    /// Bootstrap a previously empty Message registry or validate the exact
    /// durable epoch. Key changes and epoch rotation are never inferred from a
    /// mutable file; they require the explicit authority rotation operation.
    pub async fn reconcile(
        &self,
        authority: &AuthBusAuthorityHost,
    ) -> Result<IssuerRegistration, AgentdError> {
        let issuer_id = self.identity()?;
        let key_epoch = self.epoch()?;
        let verifying_key = self.verifying_key()?;
        let expected_key_digest = Digest32::of_bytes(verifying_key.as_bytes());
        let mut record = match authority
            .issuer_record(IssuerPurpose::Message, &issuer_id, key_epoch)
            .await
        {
            Ok(record) => record,
            Err(AuthBusAuthorityError::IssuerMissing) => authority
                .enroll_issuer(
                    IssuerPurpose::Message,
                    IssuerSpec {
                        issuer_id: issuer_id.clone(),
                        key_epoch,
                        verifying_key,
                    },
                )
                .await
                .map_err(|error| {
                    invalid(&format!(
                        "durable issuer enrollment failed; explicit rotation may be required: {error}"
                    ))
                })?,
            Err(error) => {
                return Err(invalid(&format!(
                    "durable issuer lookup failed: {error}"
                )));
            }
        };
        if record.purpose() != IssuerPurpose::Message
            || record.issuer_id() != &issuer_id
            || record.key_epoch() != key_epoch
            || record.verifying_key_digest() != expected_key_digest
        {
            return Err(invalid(
                "trust file identity or key differs from the durable issuer registry",
            ));
        }
        if self.revoked && record.state() == IssuerLifecycleState::Active {
            record = authority
                .revoke_issuer(
                    IssuerPurpose::Message,
                    &issuer_id,
                    key_epoch,
                    record.revision(),
                )
                .await
                .map_err(|error| invalid(&format!("durable issuer revocation failed: {error}")))?;
        }
        if !self.revoked && record.state() != IssuerLifecycleState::Active {
            return Err(invalid(
                "trust file attempts to reactivate a revoked or retired durable issuer",
            ));
        }
        authority
            .verify_message_issuer(&issuer_id, key_epoch)
            .await
            .map_err(|error| invalid(&format!("issuer handle resolution failed: {error}")))
    }

    pub fn permits(&self, thread_id: &str) -> bool {
        !self.revoked && self.thread_ids.iter().any(|id| id == thread_id)
    }

    fn identity(&self) -> Result<StableId, AgentdError> {
        StableId::new(&self.issuer_id).map_err(|error| invalid(&error.to_string()))
    }

    fn epoch(&self) -> Result<Generation, AgentdError> {
        Generation::new(self.key_epoch).map_err(|error| invalid(&error.to_string()))
    }

    fn verifying_key(&self) -> Result<VerifyingKey, AgentdError> {
        VerifyingKey::from_bytes(&hex_bytes(&self.public_key_hex)?)
            .map_err(|_| invalid("invalid registered Ed25519 public key"))
    }
}

pub(crate) fn hex_bytes<const N: usize>(value: &str) -> Result<[u8; N], AgentdError> {
    if value.len() != N * 2 || !value.bytes().all(|byte| byte.is_ascii_hexdigit()) {
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
