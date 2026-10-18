//! A byte commitment for one ordinary, independently selected installation.
//! This is descriptive input to the original owners, never another authority.

use std::path::PathBuf;

use anyhow::Result;
use anyhow::ensure;
use codex_hepta_automation::AuthorizedEffectIntent;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_memory::H7SignedArtifactEnvelope;
use codex_hepta_supervisor::H7H89ProductionGrant;
use serde::Deserialize;
use serde::Serialize;

use crate::CognitiveModelReadback;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CognitiveUpgradeSourceV1 {
    pub agent_id: AgentId,
    pub source_release: ReleaseId,
    pub target_release: ReleaseId,
    pub spawn_generation: u64,
    pub descriptor_path: PathBuf,
    pub descriptor_sha256: Sha256Digest,
}

/// SHA-256 commits the domain below followed by serde's ordered, compact JSON
/// representation of this exact schema. There are no maps or floating numbers.
/// The task provider and owner must commit this digest through Chain tags 4/5.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CognitiveUpgradeCommitmentV1 {
    pub schema_version: u32,
    /// Local inspection wall clock, committed with the candidate. It is not an
    /// independent evaluator or future-task observation timestamp.
    pub candidate_observed_at_unix_micros: u64,
    pub source: CognitiveUpgradeSourceV1,
    pub installed: CognitiveModelReadback,
}

impl CognitiveUpgradeCommitmentV1 {
    pub fn output_sha256(&self) -> Result<Sha256Digest> {
        ensure!(self.schema_version == 1 && self.candidate_observed_at_unix_micros != 0, "unsupported cognitive upgrade commitment");
        ensure!(
            self.source.source_release != self.source.target_release
                && self.source.spawn_generation != 0
                && self.source.spawn_generation == self.installed.spawn_generation
                && self.source.descriptor_path.is_absolute(),
            "invalid upgrade release/launch/descriptor binding"
        );
        ensure!(
            self.installed.source_manifest_sha256.is_some()
                && self.installed.selection_sha256.is_some()
                && self.installed.evaluated_predecessor.is_some(),
            "ordinary upgrade requires published product selection and its predecessor"
        );
        let mut bytes = b"hepta.agentd.cognitive-upgrade-task-output.v1\0".to_vec();
        bytes.extend_from_slice(&serde_json::to_vec(self)?);
        Ok(Sha256Digest::for_bytes(&bytes))
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CognitiveUpgradeTaskV1 {
    pub task_id: Sha256Digest,
    pub owner: Sha256Digest,
    pub provider: Sha256Digest,
}

/// Original TaskFlow effect material. Its existing durable owner and signed
/// FinalUse fence control dispatch and exact retries; this file owns no outbox.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CognitiveUpgradeEffectV1 {
    pub intent: AuthorizedEffectIntent,
    pub provider_effect_key: ProviderEffectKey,
    pub packet_path: PathBuf,
    pub final_use_grant: SignedFinalUseGrant,
    pub command_id: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PublishedCognitiveUpgradePlanV1 {
    pub commitment: CognitiveUpgradeCommitmentV1,
    pub task: CognitiveUpgradeTaskV1,
    pub effect: CognitiveUpgradeEffectV1,
    pub production_grant: H7H89ProductionGrant,
    pub h7_envelope: H7SignedArtifactEnvelope,
}
