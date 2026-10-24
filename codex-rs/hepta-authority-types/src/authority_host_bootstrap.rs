//! Public handoff values from the trusted root launcher, never an authority
//! created by JSON. The launcher separately transfers already held actual root
//! and consumer pidfds and a fixed bootstrap descriptor. A renderer-supplied
//! object or a self-selected key/path/PID must never reach the trusted compiler.

use crate::CognitiveCheckpointHead;
use crate::CognitiveCheckpointPeerLifetime;
use crate::HostAuthorityRegisteredIdentity;
use crate::HostAuthorityWriterRegistration;
use crate::HostSignedWriterAuthorizationV1;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseIssuerTrustKey;
use codex_hepta_contracts::FinalUseRevocations;
use serde::Deserialize;
use serde::Serialize;
use std::path::PathBuf;

pub const HOST_AUTHORITY_BOOTSTRAP_V1: &str = "runtime.authority.bootstrap.v1";
pub const HOST_AUTHORITY_BOOTSTRAP_BOUND: usize = 64 * 1024;

/// Read-only bundle. The original root session still verifies the complete
/// proof/lease and live feed; original consumers and checkpoint clients retain
/// their independent currentness/CAS contracts. No key, clock or cut defaults
/// are supplied. `checkpoint.last_current` is the original retained local cut,
/// and only its actual protected Current head can enter exact-cut recovery.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostAuthorityPublicBootstrapV1 {
    pub schema_version: u32,
    pub operation: String,
    pub root: CognitiveCheckpointPeerLifetime,
    pub consumer: CognitiveCheckpointPeerLifetime,
    pub registered_identity: HostAuthorityRegisteredIdentity,
    pub issuer_key: HostAuthorityPublicIssuerKeyV1,
    pub revocations: FinalUseRevocations,
    pub writer: HostAuthorityWriterRegistration,
    pub writer_proof: HostSignedWriterAuthorizationV1,
    pub checkpoint: CognitiveCheckpointHead,
    pub consumers: HostAuthorityPublicConsumersV1,
    pub sockets: HostAuthorityFiveLanePathsV1,
}

/// Serialization of the original *public* issuer trust input. Conversion does
/// not attest its provenance; only the root-authenticated handoff may pin it.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostAuthorityPublicIssuerKeyV1 {
    pub key_id: String,
    pub verifying_key: [u8; 32],
    pub not_before_authority_epoch: u64,
    pub not_after_authority_epoch: u64,
}

impl From<FinalUseIssuerTrustKey> for HostAuthorityPublicIssuerKeyV1 {
    fn from(key: FinalUseIssuerTrustKey) -> Self {
        Self {
            key_id: key.key_id,
            verifying_key: key.verifying_key,
            not_before_authority_epoch: key.not_before_authority_epoch,
            not_after_authority_epoch: key.not_after_authority_epoch,
        }
    }
}

impl From<HostAuthorityPublicIssuerKeyV1> for FinalUseIssuerTrustKey {
    fn from(key: HostAuthorityPublicIssuerKeyV1) -> Self {
        Self {
            key_id: key.key_id,
            verifying_key: key.verifying_key,
            not_before_authority_epoch: key.not_before_authority_epoch,
            not_after_authority_epoch: key.not_after_authority_epoch,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostAuthorityPublicConsumersV1 {
    pub device: HostAuthorityPublicConsumerV1,
    pub notes: HostAuthorityPublicConsumerV1,
}

/// Both original owner IDs equal the canonical signer ID; the two protected
/// root directories and original local journals remain independent. This path
/// is the consumer's original local journal, never the private root frontier.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostAuthorityPublicConsumerV1 {
    pub local_state_dir: PathBuf,
    pub owner_id: String,
    pub frontier: FinalUseFrontier,
}

/// Fixed purpose bindings. All five are mandatory in this public profile; no
/// ordinary request chooses a lane, owner, lease, issuer or registration.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostAuthorityFiveLanePathsV1 {
    pub observation: PathBuf,
    pub issuer: PathBuf,
    pub checkpoint: PathBuf,
    pub device_frontier: PathBuf,
    pub notes_frontier: PathBuf,
}
