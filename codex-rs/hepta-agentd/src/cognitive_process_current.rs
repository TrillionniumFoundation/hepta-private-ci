//! Raw process configuration for the existing fenced artifact owner.
//!
//! This uses the original owner CURRENT reader, without a lifetime writer lock.
//! Startup requires original trust and an independently retained signed head
//! floor. Each observation rediscovers CURRENT under the named service's short
//! publication fence and reestablishes real ACK durability after a crash.

use std::path::Path;
use std::path::PathBuf;
use std::str::FromStr;
use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_learning_artifacts as artifacts;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;

use crate::AgentdError;
use crate::CurrentCognitiveRegistry;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct CognitiveCurrentOwnerDescriptorV1 {
    pub root: PathBuf,
    pub trust: ArtifactTrustDescriptorV1,
    pub required_current_head: CurrentHeadDescriptorV1,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ArtifactTrustDescriptorV1 {
    registry_id: String,
    withdrawal_scope_digest: String,
    minimum_registry_generation: u64,
    genesis_predecessor_head_digest: String,
    minimum_authority_epoch: u64,
    writer_signers: Vec<ArtifactSignerDescriptorV1>,
    head_signers: Vec<ArtifactSignerDescriptorV1>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ArtifactSignerDescriptorV1 {
    signer_id: String,
    verifying_key_hex: String,
    minimum_authority_epoch: u64,
    maximum_authority_epoch: u64,
    valid_from: u64,
    expires_at: u64,
    revoked_at: Option<u64>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct CurrentHeadDescriptorV1 {
    withdrawal_scope_digest: String,
    binding: String,
    registry_id: String,
    generation: u64,
    head_digest: String,
    predecessor_head_digest: String,
    authority_epoch: u64,
    signer_id: String,
    signing_key_digest: String,
    issued_at: u64,
    expires_at: u64,
    signature_hex: String,
}

struct ProcessCurrentOwnerV1(artifacts::ArtifactOwnerCurrentReaderV1);

impl CurrentCognitiveRegistry for ProcessCurrentOwnerV1 {
    fn current(&self) -> Result<artifacts::VerifiedCurrentRegistryViewV1, String> {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|error| error.to_string())?
            .as_secs();
        self.0
            .current_registry_view(now)
            .map_err(|error| error.to_string())
    }
}

pub(crate) fn load_current_cognitive_owner_v1(
    descriptor: CognitiveCurrentOwnerDescriptorV1,
    agent_home: &Path,
    now_secs: u64,
) -> Result<Arc<dyn CurrentCognitiveRegistry>, AgentdError> {
    require_external_canonical_path(&descriptor.root, agent_home, /*directory*/ true)?;
    // Original owner open can bootstrap directories. Process installation must
    // reopen an existing store; a missing backup is not permission to bootstrap.
    for name in [
        "writer",
        "transactions",
        "payloads",
        "registries",
        "witnesses",
        "heads",
    ] {
        require_external_canonical_path(
            &descriptor.root.join(name),
            agent_home,
            /*directory*/ true,
        )?;
    }
    require_external_canonical_path(
        &descriptor.root.join("writer/owner.lock"),
        agent_home,
        /*directory*/ false,
    )?;
    let reader = artifacts::ArtifactOwnerCurrentReaderV1::open(
        descriptor.root,
        descriptor.trust.native()?,
        descriptor.required_current_head.native()?,
    )
    .map_err(|error| AgentdError::Invalid(error.to_string()))?;
    // This also checks ACK uncertainty and that a real nonempty CURRENT exists.
    reader
        .current_registry_view(now_secs)
        .map_err(|error| AgentdError::Invalid(error.to_string()))?;
    Ok(Arc::new(ProcessCurrentOwnerV1(reader)))
}

impl ArtifactTrustDescriptorV1 {
    fn native(self) -> Result<artifacts::ArtifactOwnerTrustV1, AgentdError> {
        if self.writer_signers.len() > 32 || self.head_signers.len() > 32 {
            return Err(AgentdError::Invalid(
                "artifact trust exceeds signer bound".to_owned(),
            ));
        }
        Ok(artifacts::ArtifactOwnerTrustV1 {
            registry_id: stable_id(self.registry_id)?,
            withdrawal_scope_digest: parse(&self.withdrawal_scope_digest)?,
            minimum_registry_generation: generation(self.minimum_registry_generation)?,
            genesis_predecessor_head_digest: parse(&self.genesis_predecessor_head_digest)?,
            minimum_authority_epoch: self.minimum_authority_epoch,
            writer_signers: self
                .writer_signers
                .into_iter()
                .map(ArtifactSignerDescriptorV1::native)
                .collect::<Result<_, _>>()?,
            head_signers: self
                .head_signers
                .into_iter()
                .map(ArtifactSignerDescriptorV1::native)
                .collect::<Result<_, _>>()?,
        })
    }
}

impl ArtifactSignerDescriptorV1 {
    fn native(self) -> Result<artifacts::TrustedArtifactSignerV1, AgentdError> {
        Ok(artifacts::TrustedArtifactSignerV1 {
            signer_id: stable_id(self.signer_id)?,
            verifying_key: hex(&self.verifying_key_hex)?,
            minimum_authority_epoch: self.minimum_authority_epoch,
            maximum_authority_epoch: self.maximum_authority_epoch,
            valid_from: self.valid_from,
            expires_at: self.expires_at,
            revoked_at: self.revoked_at,
        })
    }
}

impl CurrentHeadDescriptorV1 {
    fn native(self) -> Result<artifacts::SignedCurrentArtifactHeadV1, AgentdError> {
        Ok(artifacts::SignedCurrentArtifactHeadV1 {
            withdrawal_scope_digest: parse(&self.withdrawal_scope_digest)?,
            binding: parse(&self.binding)?,
            witness: artifacts::RegistryHeadWitnessV1 {
                registry_id: stable_id(self.registry_id)?,
                generation: generation(self.generation)?,
                head_digest: parse(&self.head_digest)?,
                predecessor_head_digest: parse(&self.predecessor_head_digest)?,
                authority_epoch: self.authority_epoch,
                signer_id: stable_id(self.signer_id)?,
                signing_key_digest: parse(&self.signing_key_digest)?,
                issued_at: self.issued_at,
                expires_at: self.expires_at,
            },
            signature: hex(&self.signature_hex)?,
        })
    }
}

fn require_external_canonical_path(
    path: &Path,
    home: &Path,
    directory: bool,
) -> Result<(), AgentdError> {
    if !path.is_absolute() || path.starts_with(home) {
        return Err(AgentdError::Invalid(
            "artifact owner inputs must be absolute and outside the agent home".to_owned(),
        ));
    }
    let metadata = std::fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink()
        || (directory && !metadata.is_dir())
        || (!directory && !metadata.is_file())
        || path.canonicalize()? != path
    {
        return Err(AgentdError::Invalid(
            "artifact owner input must be canonical and non-symlink".to_owned(),
        ));
    }
    Ok(())
}

fn parse<T: FromStr>(value: &str) -> Result<T, AgentdError>
where
    T::Err: std::fmt::Display,
{
    value
        .parse()
        .map_err(|error| AgentdError::Invalid(format!("invalid artifact owner field: {error}")))
}

fn generation(value: u64) -> Result<Generation, AgentdError> {
    Generation::new(value).map_err(|error| AgentdError::Invalid(error.to_string()))
}

fn stable_id(value: String) -> Result<StableId, AgentdError> {
    StableId::new(value).map_err(|error| AgentdError::Invalid(error.to_string()))
}

fn hex<const N: usize>(value: &str) -> Result<[u8; N], AgentdError> {
    if value.len() != N * 2 || !value.is_ascii() {
        return Err(AgentdError::Invalid(
            "invalid artifact signature/key length".to_owned(),
        ));
    }
    let mut result = [0; N];
    for (index, byte) in result.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&value[index * 2..index * 2 + 2], 16)
            .map_err(|error| AgentdError::Invalid(error.to_string()))?;
    }
    Ok(result)
}
