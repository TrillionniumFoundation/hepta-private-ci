//! Public learning scope pins; only the original Root can register or seal them.

use std::io;
use std::path::PathBuf;

use codex_hepta_learning_artifacts::LearningUpdateScopeV2;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;

use super::*;
use crate::AgentdIdentity;
use crate::HostAuthorityRegisteredIdentity;

pub const HOST_AUTHORITY_LEARNING_BOOTSTRAP_V1: &str = "runtime.learning.bootstrap.v1";
pub const HOST_AUTHORITY_LEARNING_BOOTSTRAP_V2: &str = "runtime.learning.bootstrap.v2";

/// Public scope description sealed by the original Root. The binding is
/// reconstructed from the complete initial request and owners before use.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostAuthorityLearningScopeV2 {
    scope: String,
    update_rule: String,
    binding: String,
}

impl HostAuthorityLearningScopeV2 {
    fn freeze(&self, initial: &LearningIterationSnapshotV1) -> io::Result<FrozenLearningScopeV2> {
        let scope = match self.scope.as_str() {
            "cell" => LearningUpdateScopeV2::Cell,
            "organ" => LearningUpdateScopeV2::Organ,
            "base_release" => LearningUpdateScopeV2::BaseRelease,
            _ => return Err(io::Error::other("unknown learning update scope")),
        };
        let update_rule = self
            .update_rule
            .parse::<Digest32>()
            .map_err(io::Error::other)?;
        let frozen =
            FrozenLearningScopeV2::freeze(&initial.request, &initial.owners, scope, update_rule)
                .map_err(io::Error::other)?;
        if self.update_rule != update_rule.to_string()
            || self.binding != frozen.binding().to_string()
        {
            return Err(io::Error::other("frozen learning scope binding differs"));
        }
        Ok(frozen)
    }
}

/// Explicit Root0600 configuration for one exact iteration. The storage owner
/// and directory are fixed by the Root service, never selected by this data.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostAuthorityLearningProfileV1 {
    pub(crate) schema_version: u32,
    identity_digest: String,
    writer_proof_digest: String,
    initial_snapshot: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub(crate) update_scope: Option<HostAuthorityLearningScopeV2>,
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
            update_scope: None,
        };
        profile.require_binding(identity, &profile.writer_proof_digest)?;
        Ok(profile)
    }

    /// Admit only Cell/Organ updates. A base or representation release requires
    /// its separate owner; no existing V1 registration is upgraded by this data.
    pub fn new_scoped_v2(
        identity: &AgentdIdentity,
        writer_proof_digest: [u8; 32],
        request: LearningIterationRequestV1,
        owners: LearningIterationOwnersV1,
        scope: LearningUpdateScopeV2,
        update_rule: Digest32,
    ) -> io::Result<Self> {
        let frozen = FrozenLearningScopeV2::freeze(&request, &owners, scope, update_rule)
            .map_err(io::Error::other)?;
        let mut profile = Self::new(identity, writer_proof_digest, request, owners)?;
        profile.schema_version = 2;
        profile.update_scope = Some(HostAuthorityLearningScopeV2 {
            scope: match scope {
                LearningUpdateScopeV2::Cell => "cell",
                LearningUpdateScopeV2::Organ => "organ",
                LearningUpdateScopeV2::BaseRelease => {
                    return Err(io::Error::other("slow release required"));
                }
            }
            .into(),
            update_rule: update_rule.to_string(),
            binding: frozen.binding().to_string(),
        });
        profile.require_binding(identity, &profile.writer_proof_digest)?;
        Ok(profile)
    }

    pub(crate) fn frozen_scope(
        &self,
        initial: &LearningIterationSnapshotV1,
    ) -> io::Result<Option<FrozenLearningScopeV2>> {
        decode_scope(self.schema_version, self.update_scope.as_ref(), initial)
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
        if !matches!(self.schema_version, 1 | 2)
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
        self.frozen_scope(&initial)?;
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
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub update_scope: Option<HostAuthorityLearningScopeV2>,
    pub socket_path: PathBuf,
}

impl HostAuthorityLearningBootstrapV1 {
    pub(crate) fn frozen_scope(
        &self,
        initial: &LearningIterationSnapshotV1,
    ) -> io::Result<Option<FrozenLearningScopeV2>> {
        let expected = match self.schema_version {
            1 => HOST_AUTHORITY_LEARNING_BOOTSTRAP_V1,
            2 => HOST_AUTHORITY_LEARNING_BOOTSTRAP_V2,
            _ => return Err(io::Error::other("unknown learning bootstrap schema")),
        };
        if self.operation != expected {
            return Err(io::Error::other(
                "learning bootstrap purpose differs from profile",
            ));
        }
        decode_scope(self.schema_version, self.update_scope.as_ref(), initial)
    }

    pub(crate) fn decode_initial(&self) -> io::Result<LearningIterationSnapshotV1> {
        decode_initial(&self.initial_snapshot)
    }
}

fn decode_scope(
    schema: u32,
    description: Option<&HostAuthorityLearningScopeV2>,
    initial: &LearningIterationSnapshotV1,
) -> io::Result<Option<FrozenLearningScopeV2>> {
    match (schema, description) {
        (1, None) => Ok(None),
        (2, Some(scope)) => scope.freeze(initial).map(Some),
        _ => Err(io::Error::other("learning schema and frozen scope differ")),
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
