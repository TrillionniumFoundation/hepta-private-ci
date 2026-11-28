//! Public pins for a separately sealed original paired-training purpose.
//! These values carry neither enrollment nor permission to read material.

use std::io;
use std::path::PathBuf;

use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentdIdentity;
use crate::HostAuthorityRegisteredIdentity;
use crate::PairedPreparationRegistration;
use crate::PairedTrainingMaterialManifestV1;
use crate::PairedTrainingPlanV1;
use crate::RootPairedTrainingPlanV1;

pub const HOST_AUTHORITY_PAIRED_TRAINING_BOOTSTRAP_V1: &str =
    "runtime.paired-training.bootstrap.v1";

/// Root0600 startup metadata. Material references name raw file bytes, not
/// canonical-JSON record digests. No path, turn or delivery can be supplied.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostAuthorityPairedTrainingProfileV1 {
    pub schema_version: u32,
    pub identity_digest: String,
    pub writer_proof_digest: String,
    pub study: String,
    pub enrollment: String,
    pub frozen_materials: String,
    pub principal_id: String,
    pub policy_generation: u64,
    pub operation: String,
    pub failure_sha256: String,
    pub failure_bytes: u64,
    pub correction_sha256: String,
    pub correction_bytes: u64,
    pub enrollment_revision: u64,
    pub effect_lifetime_ms: u64,
}

impl HostAuthorityPairedTrainingProfileV1 {
    pub(crate) fn decode_plan(&self) -> io::Result<RootPairedTrainingPlanV1> {
        if self.schema_version != 1 {
            return Err(io::Error::other("unsupported paired training profile"));
        }
        let plan = RootPairedTrainingPlanV1 {
            training: PairedTrainingPlanV1 {
                preparation: PairedPreparationRegistration {
                    study: digest(&self.study)?,
                    enrollment: digest(&self.enrollment)?,
                    frozen_materials: digest(&self.frozen_materials)?,
                    principal_id: self.principal_id.clone(),
                    policy_generation: Generation::new(self.policy_generation)
                        .map_err(io::Error::other)?,
                },
                manifest: PairedTrainingMaterialManifestV1 {
                    failure_sha256: digest(&self.failure_sha256)?,
                    failure_bytes: self.failure_bytes,
                    correction_sha256: digest(&self.correction_sha256)?,
                    correction_bytes: self.correction_bytes,
                },
                operation: digest(&self.operation)?,
            },
            enrollment_revision: self.enrollment_revision,
            effect_lifetime_ms: self.effect_lifetime_ms,
        };
        plan.validate()?;
        Ok(plan)
    }

    pub(crate) fn require_binding(
        &self,
        identity: &AgentdIdentity,
        writer_proof_digest: &str,
    ) -> io::Result<RootPairedTrainingPlanV1> {
        let plan = self.decode_plan()?;
        if digest(&self.writer_proof_digest)?.to_string() != writer_proof_digest
            || self.identity_digest
                != crate::neuron_generation_process_identity_digest_v1(identity)
                    .map_err(io::Error::other)?
                    .to_string()
        {
            return Err(io::Error::other(
                "paired training profile differs from its original writer",
            ));
        }
        Ok(plan)
    }
}

/// A distinct sealed purpose beside the unchanged original five-lane packet.
/// Receivers must compare every original Root, consumer and writer binding.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostAuthorityPairedTrainingBootstrapV1 {
    pub schema_version: u32,
    pub operation: String,
    pub root: CognitiveCheckpointPeerLifetime,
    pub consumer: CognitiveCheckpointPeerLifetime,
    pub registered_identity: HostAuthorityRegisteredIdentity,
    pub writer_proof_digest: String,
    pub socket_path: PathBuf,
    pub profile: HostAuthorityPairedTrainingProfileV1,
}

fn digest(value: &str) -> io::Result<Digest32> {
    let parsed = value.parse::<Digest32>().map_err(io::Error::other)?;
    if parsed.is_zero() || parsed.to_string() != value {
        return Err(io::Error::other("noncanonical paired training digest"));
    }
    Ok(parsed)
}

#[cfg(test)]
#[path = "paired_training_bootstrap_tests.rs"]
mod tests;
