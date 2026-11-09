//! Public learning scope pins; only the original Root can register or seal them.

use std::io;
use std::path::PathBuf;

use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use codex_hepta_learning_artifacts::LearningUpdateScopeV2;

use super::*;
use crate::AgentdIdentity;
use crate::HostAuthorityRegisteredIdentity;

pub const HOST_AUTHORITY_LEARNING_BOOTSTRAP_V1: &str = "runtime.learning.bootstrap.v1";
pub const HOST_AUTHORITY_LEARNING_BOOTSTRAP_V2: &str = "runtime.learning.bootstrap.v2";

/// Public description of an exact frozen medium-cadence scope, never a grant.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostAuthorityLearningScopeV2 {
    update_scope: String,
    update_rule: String,
    binding: String,
}

impl HostAuthorityLearningScopeV2 {
    fn new(
        initial: &LearningIterationSnapshotV1,
        scope: LearningUpdateScopeV2,
        update_rule: Digest32,
    ) -> io::Result<Self> {
        let frozen = FrozenLearningScopeV2::freeze(
            &initial.request, &initial.owners, scope, update_rule,
        ).map_err(io::Error::other)?;
        let update_scope = match scope {
            LearningUpdateScopeV2::Cell => "cell",
            LearningUpdateScopeV2::Organ => "organ",
            LearningUpdateScopeV2::BaseRelease => return Err(io::Error::other("slow release required")),
        };
        Ok(Self {
            update_scope: update_scope.into(),
            update_rule: update_rule.to_string(),
            binding: frozen.binding().to_string(),
        })
    }

    fn freeze(&self, initial: &LearningIterationSnapshotV1) -> io::Result<FrozenLearningScopeV2> {
        let scope = match self.update_scope.as_str() {
            "cell" => LearningUpdateScopeV2::Cell,
            "organ" => LearningUpdateScopeV2::Organ,
            _ => return Err(io::Error::other("unsupported medium-cadence update scope")),
        };
        let rule = self.update_rule.parse::<Digest32>().map_err(io::Error::other)?;
        let frozen = FrozenLearningScopeV2::freeze(
            &initial.request, &initial.owners, scope, rule,
        ).map_err(io::Error::other)?;
        if self.update_rule != rule.to_string() || self.binding != frozen.binding().to_string() {
            return Err(io::Error::other("learning frozen scope binding differs"));
        }
        Ok(frozen)
    }
}

/// Explicit Root0600 configuration for one exact iteration. The storage owner
/// and directory are fixed by the Root service, never selected by this data.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostAuthorityLearningProfileV1 {
    schema_version: u32,
    identity_digest: String,
    writer_proof_digest: String,
    initial_snapshot: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    update_scope: Option<HostAuthorityLearningScopeV2>,
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

    /// Explicit schema-2 registration; the legacy constructor remains schema 1.
    pub fn new_scoped_v2(
        identity: &AgentdIdentity,
        writer_proof_digest: [u8; 32],
        request: LearningIterationRequestV1,
        owners: LearningIterationOwnersV1,
        scope: LearningUpdateScopeV2,
        update_rule: Digest32,
    ) -> io::Result<Self> {
        let mut profile = Self::new(identity, writer_proof_digest, request, owners)?;
        let initial = decode_initial(&profile.initial_snapshot)?;
        profile.update_scope = Some(HostAuthorityLearningScopeV2::new(&initial, scope, update_rule)?);
        profile.schema_version = 2;
        profile.require_binding(identity, &profile.writer_proof_digest)?;
        Ok(profile)
    }

    pub(crate) fn require_binding(
        &self,
        identity: &AgentdIdentity,
        writer_proof_digest: &str,
    ) -> io::Result<LearningIterationSnapshotV1> {
        let initial = decode_initial(&self.initial_snapshot)?;
        let _scope = self.frozen_scope(&initial)?;
        let proof = self
            .writer_proof_digest
            .parse::<Digest32>()
            .map_err(io::Error::other)?;
        if proof.is_zero()
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

    pub(crate) fn frozen_scope(&self, initial: &LearningIterationSnapshotV1) -> io::Result<Option<FrozenLearningScopeV2>> {
        decode_scope(self.schema_version, self.update_scope.as_ref(), initial)
    }

    pub(crate) fn bootstrap_profile(&self) -> (u32, &'static str, Option<HostAuthorityLearningScopeV2>) {
        let operation = if self.schema_version == 2 {
            HOST_AUTHORITY_LEARNING_BOOTSTRAP_V2
        } else {
            HOST_AUTHORITY_LEARNING_BOOTSTRAP_V1
        };
        (self.schema_version, operation, self.update_scope.clone())
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
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub update_scope: Option<HostAuthorityLearningScopeV2>,
}

impl HostAuthorityLearningBootstrapV1 {
    pub(crate) fn decode_initial(&self) -> io::Result<LearningIterationSnapshotV1> {
        decode_initial(&self.initial_snapshot)
    }

    pub(crate) fn decode_frozen_scope(&self, initial: &LearningIterationSnapshotV1) -> io::Result<Option<FrozenLearningScopeV2>> {
        let expected = match self.schema_version {
            1 => HOST_AUTHORITY_LEARNING_BOOTSTRAP_V1,
            2 => HOST_AUTHORITY_LEARNING_BOOTSTRAP_V2,
            _ => return Err(io::Error::other("unsupported learning bootstrap schema")),
        };
        if self.operation != expected {
            return Err(io::Error::other("learning bootstrap operation differs from its schema"));
        }
        decode_scope(self.schema_version, self.update_scope.as_ref(), initial)
    }
}

fn decode_scope(
    schema: u32,
    scope: Option<&HostAuthorityLearningScopeV2>,
    initial: &LearningIterationSnapshotV1,
) -> io::Result<Option<FrozenLearningScopeV2>> {
    match (schema, scope) {
        (1, None) => Ok(None),
        (2, Some(scope)) => scope.freeze(initial).map(Some),
        _ => Err(io::Error::other("learning schema and frozen scope must match exactly")),
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
