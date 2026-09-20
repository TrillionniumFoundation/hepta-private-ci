//! Authenticated final-use capability snapshot provider for intelligence V3.
//!
//! The snapshot is ordinary typed data. Trust comes from an owner-controlled
//! registry reloaded on every final-use check plus one Ed25519 attestation from
//! every owner that has a bound capability in the snapshot. Old keys, revoked
//! keys, stale owner sequences, wrong scopes/subjects and changed global
//! authority/revocation/configuration facts fail closed.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
#[cfg(unix)]
use std::fs::File;
#[cfg(unix)]
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;
use std::str::FromStr;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_intelligence::CapabilitySnapshotV2;
use codex_hepta_intelligence::CurrentCapabilitySnapshotErrorV3;
use codex_hepta_intelligence::CurrentCapabilitySnapshotProviderV3;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::authbus_trust::hex_bytes;

const TRUST_SCHEMA_VERSION: u32 = 1;
const MAX_TRUST_BYTES: u64 = 64 * 1024;
const MAX_OWNER_ATTESTATIONS: usize = 32;

pub struct CapabilityOwnerAttestationV3 {
    pub owner_id: StableId,
    pub message: SignedMessage,
}

pub struct AuthenticatedCapabilitySnapshotProviderV3 {
    identity: AgentdIdentity,
    trust_file: PathBuf,
    snapshot: CapabilitySnapshotV2,
    attestations: BTreeMap<StableId, SignedMessage>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CapabilityTrustFileV3 {
    schema_version: u32,
    agent_id: String,
    authority_epoch: u64,
    body_generation: u64,
    configuration_digest: String,
    revocation_frontier_digest: String,
    owners: Vec<CapabilityOwnerTrustV3>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CapabilityOwnerTrustV3 {
    owner_id: String,
    issuer_id: String,
    key_epoch: u64,
    public_key_hex: String,
    revoked: bool,
    current_sequence: u64,
}

impl AuthenticatedCapabilitySnapshotProviderV3 {
    pub fn new(
        identity: AgentdIdentity,
        trust_file: PathBuf,
        snapshot: CapabilitySnapshotV2,
        attestations: Vec<CapabilityOwnerAttestationV3>,
    ) -> Result<Self, AgentdError> {
        if attestations.is_empty() || attestations.len() > MAX_OWNER_ATTESTATIONS {
            return Err(invalid("invalid owner attestation count"));
        }
        let mut by_owner = BTreeMap::new();
        for attestation in attestations {
            if by_owner
                .insert(attestation.owner_id.clone(), attestation.message)
                .is_some()
            {
                return Err(invalid("duplicate owner attestation"));
            }
        }
        Ok(Self {
            identity,
            trust_file,
            snapshot,
            attestations: by_owner,
        })
    }

    fn verify_at(&self, now_ms: u64) -> Result<CapabilitySnapshotV2, AgentdError> {
        let trust = CapabilityTrustFileV3::load(&self.trust_file, &self.identity)?;
        trust.verify_global(&self.snapshot, &self.identity)?;

        let bound_owners = self
            .snapshot
            .bindings()
            .map(|binding| binding.owner_id.clone())
            .collect::<BTreeSet<_>>();
        if bound_owners.is_empty()
            || self.attestations.len() != bound_owners.len()
            || self
                .attestations
                .keys()
                .any(|owner| !bound_owners.contains(owner))
        {
            return Err(invalid("owner attestation set is not exact"));
        }

        let subject = StableId::new(self.identity.agent_id.as_str())
            .map_err(|error| invalid(&format!("invalid Agent subject: {error}")))?;
        for owner in bound_owners {
            let owner_trust = trust
                .owners
                .iter()
                .find(|entry| entry.owner_id == owner.as_str())
                .ok_or_else(|| invalid("bound capability owner missing from current trust"))?;
            let message = self
                .attestations
                .get(&owner)
                .ok_or_else(|| invalid("bound capability owner attestation missing"))?;
            if message.claims.subject_id != subject
                || message.claims.sequence != owner_trust.current_sequence
            {
                return Err(invalid("owner attestation subject or sequence is stale"));
            }
            message
                .authenticate(
                    &owner_trust.issuer()?,
                    capability_scope(&self.identity, &owner),
                    self.snapshot.digest(),
                    now_ms,
                )
                .map_err(|error| invalid(&format!("owner attestation rejected: {error:?}")))?;
        }
        Ok(self.snapshot.clone())
    }
}

impl CurrentCapabilitySnapshotProviderV3 for AuthenticatedCapabilitySnapshotProviderV3 {
    fn current_snapshot(
        &mut self,
    ) -> Result<CapabilitySnapshotV2, CurrentCapabilitySnapshotErrorV3> {
        self.verify_at(now_ms().map_err(|_| CurrentCapabilitySnapshotErrorV3::Unavailable)?)
            .map_err(|_| CurrentCapabilitySnapshotErrorV3::Rejected)
    }
}

impl CapabilityTrustFileV3 {
    fn load(path: &Path, identity: &AgentdIdentity) -> Result<Self, AgentdError> {
        let bytes = read_private_owner_file(path, identity)?;
        let value: Self = serde_json::from_slice(&bytes)?;
        if value.schema_version != TRUST_SCHEMA_VERSION
            || value.agent_id != identity.agent_id.as_str()
            || value.authority_epoch == 0
            || value.body_generation == 0
            || value.owners.is_empty()
            || value.owners.len() > MAX_OWNER_ATTESTATIONS
        {
            return Err(invalid("invalid capability trust registry"));
        }
        let mut seen = BTreeSet::new();
        for owner in &value.owners {
            StableId::new(&owner.owner_id)
                .map_err(|error| invalid(&format!("invalid owner ID: {error}")))?;
            if !seen.insert(owner.owner_id.as_str())
                || owner.key_epoch == 0
                || owner.current_sequence == 0
            {
                return Err(invalid("duplicate or zero owner trust frontier"));
            }
            owner.issuer()?;
        }
        Ok(value)
    }

    fn verify_global(
        &self,
        snapshot: &CapabilitySnapshotV2,
        identity: &AgentdIdentity,
    ) -> Result<(), AgentdError> {
        let configuration = Digest32::from_str(&self.configuration_digest)
            .map_err(|_| invalid("invalid configuration digest"))?;
        let revocations = Digest32::from_str(&self.revocation_frontier_digest)
            .map_err(|_| invalid("invalid revocation frontier digest"))?;
        let generation = Generation::new(self.body_generation)
            .map_err(|error| invalid(&format!("invalid body generation: {error}")))?;
        if configuration.is_zero()
            || revocations.is_zero()
            || snapshot.current_authority_epoch() != self.authority_epoch
            || snapshot.body_generation() != generation
            || snapshot.configuration_digest() != configuration
            || snapshot.revocation_frontier_digest() != revocations
            || identity.spawn_generation == 0
        {
            return Err(invalid("current capability trust frontier does not match snapshot"));
        }
        Ok(())
    }
}

impl CapabilityOwnerTrustV3 {
    fn issuer(&self) -> Result<IssuerRegistration, AgentdError> {
        Ok(IssuerRegistration {
            issuer_id: StableId::new(&self.issuer_id)
                .map_err(|error| invalid(&format!("invalid issuer ID: {error}")))?,
            key_epoch: Generation::new(self.key_epoch)
                .map_err(|error| invalid(&format!("invalid key epoch: {error}")))?,
            verifying_key: VerifyingKey::from_bytes(&hex_bytes(&self.public_key_hex)?)
                .map_err(|_| invalid("invalid owner Ed25519 public key"))?,
            revoked: self.revoked,
        })
    }
}

fn capability_scope(identity: &AgentdIdentity, owner_id: &StableId) -> Digest32 {
    let mut bytes = b"hepta.agentd.intelligence-capability-owner.v3\0".to_vec();
    bytes.extend_from_slice(identity.agent_id.as_str().as_bytes());
    bytes.push(0);
    bytes.extend_from_slice(owner_id.as_str().as_bytes());
    Digest32::of_bytes(&bytes)
}

fn now_ms() -> Result<u64, AgentdError> {
    u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| invalid("system clock precedes Unix epoch"))?
            .as_millis(),
    )
    .map_err(|_| invalid("system clock exceeds u64 milliseconds"))
}

#[cfg(unix)]
fn read_private_owner_file(path: &Path, identity: &AgentdIdentity) -> Result<Vec<u8>, AgentdError> {
    use std::os::unix::fs::MetadataExt;

    if !path.is_absolute()
        || path.parent() != Some(identity.home_root.as_path())
        || identity.home_root.canonicalize()? != identity.home_root
    {
        return Err(invalid(
            "capability trust file must be a direct child of canonical Agent home",
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
        || before.len() > MAX_TRUST_BYTES
    {
        return Err(invalid(
            "capability trust file must be a private owner-controlled regular file",
        ));
    }
    let mut file = File::open(path)?;
    let opened = file.metadata()?;
    let identity_tuple = |metadata: &std::fs::Metadata| {
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
    if identity_tuple(&opened) != identity_tuple(&before) {
        return Err(invalid("capability trust file changed while opening"));
    }
    let mut bytes = Vec::new();
    file.by_ref()
        .take(MAX_TRUST_BYTES + 1)
        .read_to_end(&mut bytes)?;
    let after = std::fs::symlink_metadata(path)?;
    if bytes.len() as u64 > MAX_TRUST_BYTES
        || !after.is_file()
        || identity_tuple(&after) != identity_tuple(&before)
        || identity_tuple(&file.metadata()?) != identity_tuple(&before)
    {
        return Err(invalid("capability trust file changed while reading"));
    }
    Ok(bytes)
}

#[cfg(not(unix))]
fn read_private_owner_file(
    _path: &Path,
    _identity: &AgentdIdentity,
) -> Result<Vec<u8>, AgentdError> {
    Err(invalid(
        "authenticated capability trust-file profile currently requires Unix ownership checks",
    ))
}

fn invalid(message: &str) -> AgentdError {
    AgentdError::Invalid(format!("intelligence capability trust: {message}"))
}

#[cfg(test)]
#[path = "intelligence_snapshot_tests.rs"]
mod tests;
