//! One explicitly installed owner key and bounded thread allowlist.

#[cfg(unix)]
use std::fs::File;
#[cfg(unix)]
use std::io::Read;
use std::path::Path;

use codex_hepta_authbus::AuthBusReplayCheckpoint;
use codex_hepta_authbus::AuthBusTrustHead;
use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;

use crate::AgentdError;
use crate::AgentdIdentity;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ReplayCheckpointProjection {
    generation: u64,
    replay_digest_hex: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ExternalReplayCheckpointProjection {
    schema_version: u32,
    agent_id: String,
    generation: u64,
    replay_digest_hex: String,
}

pub(crate) fn load_external_replay_checkpoint(
    path: &Path,
    identity: &AgentdIdentity,
) -> Result<AuthBusReplayCheckpoint, AgentdError> {
    let bytes = read_external_checkpoint_file(path, identity)?;
    let projection: ExternalReplayCheckpointProjection = serde_json::from_slice(&bytes)?;
    if projection.schema_version != 1
        || projection.agent_id != identity.agent_id.as_str()
        || projection.generation == 0
    {
        return Err(invalid(
            "external replay checkpoint owner or schema is invalid",
        ));
    }
    let replay_digest = Digest32::from_array(hex_bytes::<32>(&projection.replay_digest_hex)?);
    if replay_digest.is_zero() {
        return Err(invalid("external replay checkpoint digest is empty"));
    }
    Ok(AuthBusReplayCheckpoint {
        generation: projection.generation,
        replay_digest,
    })
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct TextTrust {
    schema_version: u32,
    trust_revision: u64,
    agent_id: String,
    issuer_id: String,
    key_epoch: u64,
    public_key_hex: String,
    revoked: bool,
    thread_ids: Vec<String>,
    #[serde(default)]
    replay_checkpoint: Option<ReplayCheckpointProjection>,
}

impl TextTrust {
    /// Reload the owner-controlled file for each admission and dispatch stage.
    /// Updating the public key does not synthesize a signature or a grant.
    pub fn load(path: &Path, identity: &AgentdIdentity) -> Result<Self, AgentdError> {
        let bytes = read_owner_file(path, identity)?;
        let trust: Self = serde_json::from_slice(&bytes)?;
        if trust.schema_version != 2
            || trust.trust_revision == 0
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

    pub fn trust_head(&self) -> Result<AuthBusTrustHead, AgentdError> {
        let issuer = self.issuer()?;
        let verifying_key_digest = Digest32::of_bytes(issuer.verifying_key.as_bytes());
        let mut threads = self.thread_ids.clone();
        threads.sort();
        threads.dedup();
        if threads.len() != self.thread_ids.len() {
            return Err(invalid("trust registry contains duplicate thread ids"));
        }
        let mut bytes = b"hepta.agentd.authbus-trust.v2\0".to_vec();
        bytes.extend_from_slice(&self.trust_revision.to_be_bytes());
        push_text(&mut bytes, &self.agent_id);
        push_text(&mut bytes, &self.issuer_id);
        bytes.extend_from_slice(&self.key_epoch.to_be_bytes());
        bytes.extend_from_slice(verifying_key_digest.as_array());
        bytes.push(u8::from(self.revoked));
        for thread in threads {
            push_text(&mut bytes, &thread);
        }
        if let Some(checkpoint) = self.replay_checkpoint()? {
            bytes.extend_from_slice(&checkpoint.generation.to_be_bytes());
            bytes.extend_from_slice(checkpoint.replay_digest.as_array());
        } else {
            bytes.extend_from_slice(&0_u64.to_be_bytes());
        }
        Ok(AuthBusTrustHead {
            issuer_id: issuer.issuer_id,
            revision: self.trust_revision,
            key_epoch: issuer.key_epoch.get(),
            verifying_key_digest,
            registration_digest: Digest32::of_bytes(&bytes),
            revoked: issuer.revoked,
        })
    }

    pub fn replay_checkpoint(&self) -> Result<Option<AuthBusReplayCheckpoint>, AgentdError> {
        self.replay_checkpoint
            .as_ref()
            .map(|checkpoint| {
                if checkpoint.generation == 0 {
                    return Err(invalid("replay checkpoint generation must be nonzero"));
                }
                let digest = hex_bytes::<32>(&checkpoint.replay_digest_hex)?;
                let replay_digest = Digest32::from_array(digest);
                if replay_digest.is_zero() {
                    return Err(invalid("replay checkpoint digest must be nonzero"));
                }
                Ok(AuthBusReplayCheckpoint {
                    generation: checkpoint.generation,
                    replay_digest,
                })
            })
            .transpose()
    }

    pub fn permits(&self, thread_id: &str) -> bool {
        !self.revoked && self.thread_ids.iter().any(|id| id == thread_id)
    }
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&u32::try_from(value.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
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
fn read_owner_file(path: &Path, identity: &AgentdIdentity) -> Result<Vec<u8>, AgentdError> {
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
        || before.len() > 16_384
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
    file.by_ref().take(16_385).read_to_end(&mut bytes)?;
    let after = std::fs::symlink_metadata(path)?;
    if bytes.len() > 16_384
        || !after.is_file()
        || identity(&after) != identity(&before)
        || identity(&file.metadata()?) != identity(&before)
    {
        return Err(invalid("trust file changed while reading"));
    }
    Ok(bytes)
}

#[cfg(unix)]
fn read_external_checkpoint_file(
    path: &Path,
    identity: &AgentdIdentity,
) -> Result<Vec<u8>, AgentdError> {
    use std::os::unix::fs::MetadataExt;

    if !path.is_absolute()
        || path.starts_with(&identity.home_root)
        || path.starts_with(&identity.run_root)
        || path.parent().is_none()
    {
        return Err(invalid(
            "external replay checkpoint must be outside the Agent home and run root",
        ));
    }
    let parent = path
        .parent()
        .ok_or_else(|| invalid("checkpoint parent is missing"))?;
    if parent.canonicalize()? != parent || path.canonicalize()? != path {
        return Err(invalid(
            "external replay checkpoint path must be canonical and symlink-free",
        ));
    }
    let owner = std::fs::metadata(&identity.home_root)?;
    let parent_meta = std::fs::metadata(parent)?;
    let before = std::fs::symlink_metadata(path)?;
    if !parent_meta.is_dir()
        || parent_meta.uid() != owner.uid()
        || parent_meta.mode() & 0o077 != 0
        || !before.is_file()
        || before.nlink() != 1
        || before.uid() != owner.uid()
        || before.mode() & 0o077 != 0
        || before.len() > 4_096
    {
        return Err(invalid(
            "external replay checkpoint must be a private owner-controlled regular file",
        ));
    }
    let mut file = File::open(path)?;
    let opened = file.metadata()?;
    let file_identity = |m: &std::fs::Metadata| {
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
    if file_identity(&opened) != file_identity(&before) {
        return Err(invalid("external replay checkpoint changed while opening"));
    }
    let mut bytes = Vec::new();
    file.by_ref().take(4_097).read_to_end(&mut bytes)?;
    let after = std::fs::symlink_metadata(path)?;
    if bytes.len() > 4_096
        || !after.is_file()
        || file_identity(&after) != file_identity(&before)
        || file_identity(&file.metadata()?) != file_identity(&before)
    {
        return Err(invalid("external replay checkpoint changed while reading"));
    }
    Ok(bytes)
}

#[cfg(not(unix))]
fn read_external_checkpoint_file(
    _path: &Path,
    _identity: &AgentdIdentity,
) -> Result<Vec<u8>, AgentdError> {
    Err(invalid(
        "the external replay-checkpoint profile currently requires Unix ownership checks",
    ))
}

#[cfg(not(unix))]
fn read_owner_file(_path: &Path, _identity: &AgentdIdentity) -> Result<Vec<u8>, AgentdError> {
    Err(invalid(
        "the signed text trust-file profile currently requires Unix ownership checks",
    ))
}

pub(crate) fn invalid(message: &str) -> AgentdError {
    AgentdError::Invalid(format!("AuthBus text: {message}"))
}
