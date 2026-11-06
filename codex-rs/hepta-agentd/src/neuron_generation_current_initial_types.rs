//! First guarded generation publication, separate from replacement history.
//! These records bind the actual genesis and an existing selection. They do
//! not fabricate a predecessor, a signing authority or a runtime capability.

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::VerifiedUseTokenWitnessV1;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use super::signed_grant_digest;
use super::types::CurrentHead;
use super::types::invalid;
use super::types::scope_digest;
use crate::AgentdError;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct InitialIntent {
    pub(super) operation_id: String,
    pub(super) supersedes: Option<[u8; 32]>,
    pub(super) target: CellGenerationOwnerBindingV1,
    pub(super) genesis_checkpoint: [u8; 32],
    pub(super) selection: [u8; 32],
}

impl InitialIntent {
    pub(super) fn validate(&self) -> Result<(), AgentdError> {
        StableId::new(&self.operation_id).map_err(invalid)?;
        self.target.digest().map_err(invalid)?;
        if self.genesis_checkpoint != self.target.genesis_checkpoint().into_array()
            || self.selection == [0; 32]
            || self.supersedes == Some([0; 32])
        {
            return Err(invalid("initial generation intent binding differs"));
        }
        Ok(())
    }

    pub(super) fn digest(&self) -> Result<Digest32, AgentdError> {
        self.validate()?;
        let bytes = serde_json::to_vec(self).map_err(invalid)?;
        Ok(Digest32::of_parts(&[
            b"hepta.agentd.generation-initial-intent.v1\0",
            &bytes,
        ]))
    }

    pub(super) fn binding(&self) -> Result<FinalUseBinding, AgentdError> {
        Ok(FinalUseBinding {
            subject_id: self.target.scope().agent_id.clone(),
            destination_id: "agentd.cell-generation.initialize".into(),
            request_sha256: self.digest()?.into_array(),
            scope_sha256: scope_digest(self.target.scope())?.into_array(),
            payload_sha256: self.target.digest().map_err(invalid)?,
        })
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct InitialPublished {
    pub(super) intent: InitialIntent,
    pub(super) witness: VerifiedUseTokenWitnessV1,
    pub(super) signed: SignedFinalUseGrant,
    pub(super) signed_grant_digest: [u8; 32],
}

impl InitialPublished {
    pub(super) fn validate(&self) -> Result<(), AgentdError> {
        self.intent.validate()?;
        self.witness.validate().map_err(invalid)?;
        if signed_grant_digest(&self.signed)?.as_array() != &self.signed_grant_digest
            || self.signed.grant.binding != self.intent.binding()?
        {
            return Err(invalid("retained initial generation grant differs"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "state", content = "record", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum InitialState {
    Prepared(Box<InitialIntent>),
    Published(Box<InitialPublished>),
}

impl CurrentHead {
    pub(super) fn validate_initial(&self) -> Result<(), AgentdError> {
        match &self.initial {
            None => Ok(()),
            Some(InitialState::Prepared(intent)) => {
                intent.validate()?;
                if self.current != intent.target
                    || self.prepared.is_some()
                    || self.published.is_some()
                {
                    return Err(invalid("initial preparation is not the sole Control record"));
                }
                Ok(())
            }
            Some(InitialState::Published(record)) => {
                record.validate()?;
                if self.current != record.intent.target || self.published.is_some() {
                    return Err(invalid("initial publication differs from current generation"));
                }
                Ok(())
            }
        }
    }
}

/// Original protected preparation; it contains no grant or dispatch token.
#[derive(Debug)]
pub struct PreparedNeuronGenerationInitialV1 {
    pub(super) head: Option<CurrentHead>,
    pub(super) intent: InitialIntent,
    pub(super) binding: FinalUseBinding,
    pub(super) digest: Digest32,
}

impl PreparedNeuronGenerationInitialV1 {
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

/// The original signed publication read from protected Control storage.
/// Runtime use still requires the live existing-authority checks.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PublishedNeuronGenerationInitialV1 {
    pub(super) record: Box<InitialPublished>,
    pub(super) digest: Digest32,
}

impl PublishedNeuronGenerationInitialV1 {
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
pub enum NeuronGenerationInitialReadbackV1 {
    Prepared,
    Published(PublishedNeuronGenerationInitialV1),
}
