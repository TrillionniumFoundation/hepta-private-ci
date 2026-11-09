//! Public learning scope pins; only the original Root can register or seal them.

use std::io;
use std::path::PathBuf;

use codex_hepta_memory::CognitiveCheckpointPeerLifetime;

use super::*;
use crate::AgentdIdentity;
use crate::HostAuthorityRegisteredIdentity;

pub const HOST_AUTHORITY_LEARNING_BOOTSTRAP_V1: &str = "runtime.learning.bootstrap.v1";

/// Explicit Root0600 configuration for one exact iteration. The storage owner
/// and directory are fixed by the Root service, never selected by this data.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostAuthorityLearningProfileV1 {
    schema_version: u32,
    identity_digest: String,
    writer_proof_digest: String,
    initial_snapshot: String,
}

impl HostAuthorityLearningProfileV1 {
    pub fn new(
        identity: &AgentdIdentity,
        writer_proof_digest: [u8; 32],
        request: LearningIterationRequestV1,
        owners: LearningIterationOwnersV1,
    ) -> io::Result<Self> {
        let initial =
            LearningIterationCoordinatorV1::new(request, owners).map_err(io::Error::other)?;
        let profile = Self {
            schema_version: 1,
            identity_digest: crate::neuron_generation_process_identity_digest_v1(identity)
                .map_err(io::Error::other)?
                .to_string(),
            writer_proof_digest: Digest32::from_array(writer_proof_digest).to_string(),
            initial_snapshot: STANDARD_NO_PAD
                .encode(codec::encode(initial.snapshot()).map_err(io::Error::other)?),
        };
        profile.require_binding(identity, &profile.writer_proof_digest)?;
        Ok(profile)
    }

    pub(crate) fn require_binding(
        &self,
        identity: &AgentdIdentity,
        writer_proof_digest: &str,
    ) -> io::Result<LearningIterationSnapshotV1> {
        let initial = decode_initial(&self.initial_snapshot)?;
        let proof = self
            .writer_proof_digest
            .parse::<Digest32>()
            .map_err(io::Error::other)?;
        if self.schema_version != 1
            || proof.is_zero()
            || self.writer_proof_digest != writer_proof_digest
            || self.identity_digest
                != crate::neuron_generation_process_identity_digest_v1(identity)
                    .map_err(io::Error::other)?
                    .to_string()
            || initial.request.agent_id.as_str() != identity.agent_id.as_str()
        {
            return Err(io::Error::other(
                "learning profile differs from original Root writer",
            ));
        }
        Ok(initial)
    }

    pub(crate) fn encoded_initial(&self) -> &str {
        &self.initial_snapshot
    }
}

/// Separate sealed handoff. It changes neither the original five-lane schema
/// nor the original writer proof, and carries no private signer or Root store.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostAuthorityLearningBootstrapV1 {
    pub schema_version: u32,
    pub operation: String,
    pub root: CognitiveCheckpointPeerLifetime,
    pub consumer: CognitiveCheckpointPeerLifetime,
    pub registered_identity: HostAuthorityRegisteredIdentity,
    pub writer_proof_digest: String,
    pub initial_snapshot: String,
    pub socket_path: PathBuf,
}

impl HostAuthorityLearningBootstrapV1 {
    pub(crate) fn decode_initial(&self) -> io::Result<LearningIterationSnapshotV1> {
        decode_initial(&self.initial_snapshot)
    }
}

fn decode_initial(encoded: &str) -> io::Result<LearningIterationSnapshotV1> {
    if encoded.len() > codec::MAX_BYTES.div_ceil(3) * 4 {
        return Err(io::Error::other("learning scope exceeds the bounded codec"));
    }
    let bytes = STANDARD_NO_PAD.decode(encoded).map_err(io::Error::other)?;
    let initial = codec::decode(&bytes).map_err(io::Error::other)?;
    let expected =
        LearningIterationCoordinatorV1::new(initial.request.clone(), initial.owners.clone())
            .map_err(io::Error::other)?;
    if STANDARD_NO_PAD.encode(&bytes) != encoded
        || expected.snapshot() != &initial
        || codec::encode(&initial).map_err(io::Error::other)? != bytes
    {
        return Err(io::Error::other(
            "learning handoff requires the exact empty initial scope",
        ));
    }
    Ok(initial)
}

#[cfg(test)]
#[path = "authority_host_learning_profile_tests.rs"]
mod tests;
