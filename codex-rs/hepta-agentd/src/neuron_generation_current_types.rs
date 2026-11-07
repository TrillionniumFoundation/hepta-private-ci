//! Immutable control facts for task-boundary generation replacement.

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::VerifiedUseTokenWitnessV1;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::initial_types::InitialState;
use crate::AgentdError;

/// The explicitly authorized boundary for replacing the prior task owner.
/// OwnerDrained is not a model STOP or terminal learning evidence.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NeuronGenerationPredecessorCompletionV1 {
    #[default]
    ModelStopped,
    OwnerDrained,
    /// Start another task with the identical complete manifest. This carries
    /// no assertion that an evaluation ran or a candidate was adopted.
    OwnerDrainedSameModel,
}

impl NeuronGenerationPredecessorCompletionV1 {
    #[expect(
        clippy::trivially_copy_pass_by_ref,
        reason = "Serde skip_serializing_if requires a borrowed field callback"
    )]
    pub(super) fn is_model_stopped(&self) -> bool {
        matches!(self, Self::ModelStopped)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct UpdateIntent {
    pub(super) operation_id: String,
    pub(super) supersedes: Option<[u8; 32]>,
    pub(super) previous: CellGenerationOwnerBindingV1,
    pub(super) previous_checkpoint: [u8; 32],
    pub(super) previous_observation: [u8; 32],
    pub(super) target: CellGenerationOwnerBindingV1,
    pub(super) genesis_checkpoint: [u8; 32],
    pub(super) selection: [u8; 32],
    #[serde(
        default,
        skip_serializing_if = "NeuronGenerationPredecessorCompletionV1::is_model_stopped"
    )]
    pub(super) completion: NeuronGenerationPredecessorCompletionV1,
}

impl UpdateIntent {
    pub(super) fn digest(&self) -> Result<Digest32, AgentdError> {
        let bytes = serde_json::to_vec(self).map_err(invalid)?;
        Ok(Digest32::of_parts(&[
            b"hepta.agentd.generation-update-intent.v1\0",
            &bytes,
        ]))
    }

    pub(super) fn binding(&self) -> Result<FinalUseBinding, AgentdError> {
        Ok(FinalUseBinding {
            subject_id: self.previous.scope().agent_id.clone(),
            destination_id: match self.completion {
                NeuronGenerationPredecessorCompletionV1::ModelStopped => {
                    "agentd.cell-generation.replace"
                }
                NeuronGenerationPredecessorCompletionV1::OwnerDrained => {
                    "agentd.cell-generation.replace-drained"
                }
                NeuronGenerationPredecessorCompletionV1::OwnerDrainedSameModel => {
                    "agentd.cell-generation.next-task-same-model"
                }
            }
            .into(),
            request_sha256: self.digest()?.into_array(),
            scope_sha256: scope_digest(self.previous.scope())?.into_array(),
            payload_sha256: self.target.digest().map_err(invalid)?,
        })
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Published {
    pub(super) intent: UpdateIntent,
    pub(super) witness: VerifiedUseTokenWitnessV1,
    pub(super) signed: SignedFinalUseGrant,
    pub(super) signed_grant_digest: [u8; 32],
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct CurrentHead {
    pub(super) schema_version: u32,
    pub(super) current: CellGenerationOwnerBindingV1,
    pub(super) prepared: Option<UpdateIntent>,
    pub(super) published: Option<Published>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub(super) initial: Option<InitialState>,
}

/// Readback of the original durable preparation. It holds no nonce token and
/// grants no writer permission. The actual old and new journals remain owned
/// and locked by the coordinator across publication.
#[derive(Debug)]
pub struct PreparedNeuronGenerationUpdateV1 {
    pub(super) head: Option<CurrentHead>,
    pub(super) intent: UpdateIntent,
    pub(super) binding: FinalUseBinding,
    pub(super) digest: Digest32,
}

impl PreparedNeuronGenerationUpdateV1 {
    pub fn completion(&self) -> NeuronGenerationPredecessorCompletionV1 {
        self.intent.completion
    }

    pub fn final_use_binding(&self) -> &FinalUseBinding {
        &self.binding
    }

    pub fn intent_digest(&self) -> Digest32 {
        self.digest
    }

    pub fn target(&self) -> &CellGenerationOwnerBindingV1 {
        &self.intent.target
    }

    pub fn selection_observation_digest(&self) -> Digest32 {
        Digest32::from_array(self.intent.selection)
    }

    pub fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

/// An authenticated store observation, not an activation or adoption grant.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PublishedNeuronGenerationUpdateV1 {
    pub(super) record: Box<Published>,
    pub(super) digest: Digest32,
}

impl PublishedNeuronGenerationUpdateV1 {
    pub(crate) fn operation_id(&self) -> &str {
        &self.record.intent.operation_id
    }

    pub(crate) fn previous(&self) -> &CellGenerationOwnerBindingV1 {
        &self.record.intent.previous
    }

    pub(crate) fn selection_observation_digest(&self) -> Digest32 {
        Digest32::from_array(self.record.intent.selection)
    }

    /// The actual published record, including the consumed grant and witness;
    /// the preparable intent digest alone is not a publication receipt.
    pub(crate) fn publication_digest(&self) -> Result<Digest32, AgentdError> {
        let bytes = serde_json::to_vec(self.record.as_ref()).map_err(invalid)?;
        Ok(Digest32::of_parts(&[
            b"hepta.agentd.generation-publication.v1\0",
            &bytes,
        ]))
    }

    pub fn completion(&self) -> NeuronGenerationPredecessorCompletionV1 {
        self.record.intent.completion
    }

    pub fn target(&self) -> &CellGenerationOwnerBindingV1 {
        &self.record.intent.target
    }

    pub fn intent_digest(&self) -> Digest32 {
        self.digest
    }

    pub fn witness(&self) -> &VerifiedUseTokenWitnessV1 {
        &self.record.witness
    }

    pub fn signed_grant(&self) -> &SignedFinalUseGrant {
        &self.record.signed
    }

    pub fn signed_grant_digest(&self) -> Digest32 {
        Digest32::from_array(self.record.signed_grant_digest)
    }

    pub fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

#[derive(Debug, Eq, PartialEq)]
pub enum NeuronGenerationUpdateReadbackV1 {
    Prepared,
    Published(PublishedNeuronGenerationUpdateV1),
}

pub(super) fn scope_digest(
    scope: &codex_hepta_neuron::CellGenerationScopeV2,
) -> Result<Digest32, AgentdError> {
    let bytes = serde_json::to_vec(&(&scope.agent_id, &scope.cell_id, scope.principal_digest))
        .map_err(invalid)?;
    Ok(Digest32::of_parts(&[
        b"hepta.agentd.generation-current-scope.v1\0",
        &bytes,
    ]))
}

pub(super) fn invalid(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Invalid(error.to_string())
}
