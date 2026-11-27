//! Trusted startup selection only; resolved on the canonical recovered writer.
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::NotesTargetIdentity;
use serde::Deserialize;
use serde::Serialize;
use std::path::PathBuf;

use crate::AgentdError;
use crate::AgentdNotesPreviousRecoveryLaunch;

#[derive(Clone, Debug, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum AgentdNotesRecoverySelector {
    ExactOperation { operation_id: String },
    LatestRecordedOriginalNotes,
}

impl<'de> Deserialize<'de> for AgentdNotesRecoverySelector {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        #[derive(Deserialize)]
        #[serde(rename_all = "snake_case")]
        enum ExactKind {
            ExactOperation,
        }
        #[derive(Deserialize)]
        #[serde(rename_all = "snake_case")]
        enum LatestKind {
            LatestRecordedOriginalNotes,
        }
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Exact {
            kind: ExactKind,
            operation_id: String,
        }
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Latest {
            kind: LatestKind,
        }
        #[derive(Deserialize)]
        #[serde(untagged)]
        enum Fields {
            Exact(Exact),
            Latest(Latest),
        }
        match Fields::deserialize(deserializer)? {
            Fields::Exact(Exact {
                kind: ExactKind::ExactOperation,
                operation_id,
            }) => Self::checked_exact(operation_id).map_err(serde::de::Error::custom),
            Fields::Latest(Latest {
                kind: LatestKind::LatestRecordedOriginalNotes,
            }) => Ok(Self::LatestRecordedOriginalNotes),
        }
    }
}

impl AgentdNotesRecoverySelector {
    pub(crate) fn from_fields(
        operation_id: Option<&str>,
        selector: Option<&Self>,
    ) -> Result<Self, AgentdError> {
        match (operation_id, selector) {
            (Some(operation_id), None) => Self::checked_exact(operation_id.into()),
            (None, Some(Self::ExactOperation { operation_id })) => Self::checked_exact(operation_id.clone()),
            (None, Some(Self::LatestRecordedOriginalNotes)) => Ok(Self::LatestRecordedOriginalNotes),
            _ => Err(AgentdError::Invalid("previous Notes recovery requires exactly one typed selector or legacy operation_id".into())),
        }
    }

    fn checked_exact(operation_id: String) -> Result<Self, AgentdError> {
        codex_hepta_types::StableId::new(&operation_id)
            .map_err(|error| AgentdError::Invalid(error.to_string()))?;
        Ok(Self::ExactOperation { operation_id })
    }
}

/// No effect endpoint or permission; Root's sealed previous-recovery request.
#[derive(Clone, Debug)]
pub struct AgentdNotesPreviousRecoveryRequest {
    pub helper: PathBuf,
    pub helper_sha256: Sha256Digest,
    pub state_directory: PathBuf,
    pub previous_target: NotesTargetIdentity,
    pub selector: AgentdNotesRecoverySelector,
}

impl AgentdNotesPreviousRecoveryRequest {
    pub(crate) fn resolved(self, operation_id: String) -> AgentdNotesPreviousRecoveryLaunch {
        AgentdNotesPreviousRecoveryLaunch {
            helper: self.helper,
            helper_sha256: self.helper_sha256,
            state_directory: self.state_directory,
            previous_target: self.previous_target,
            operation_id,
        }
    }
}

#[cfg(test)]
#[path = "notes_recovery_selection_tests.rs"]
mod tests;
