//! Exact public recovery bindings from the original Root's sealed deployment.
//! These paths and identities are not grants or retirement evidence.
use std::path::PathBuf;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CalculatorTargetIdentity;
use codex_hepta_memory::NotesTargetIdentity;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentdCalculatorPreviousRecoveryRequest;
use crate::AgentdCalculatorRecoverySelector;
use crate::AgentdError;
use crate::AgentdNotesPreviousRecoveryRequest;
use crate::AgentdNotesRecoverySelector;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PreviousNotesRecovery {
    pub(crate) helper: PathBuf,
    pub(crate) helper_sha256: String,
    pub(crate) state_directory: PathBuf,
    pub(crate) previous_target: NotesTargetIdentity,
    pub(crate) selector: AgentdNotesRecoverySelector,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PreviousCalculatorRecovery {
    pub(crate) helper: PathBuf,
    pub(crate) helper_sha256: String,
    pub(crate) state_directory: PathBuf,
    pub(crate) previous_target: CalculatorTargetIdentity,
    pub(crate) selector: AgentdCalculatorRecoverySelector,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct DesktopPreviousRecovery {
    pub(crate) notes: PreviousNotesRecovery,
    pub(crate) calculator: PreviousCalculatorRecovery,
}

/// Missing selects the fresh schema; a present null must never mean missing.
pub(crate) fn deserialize_present<'de, D>(
    deserializer: D,
) -> Result<Option<DesktopPreviousRecovery>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    DesktopPreviousRecovery::deserialize(deserializer).map(Some)
}

impl DesktopPreviousRecovery {
    pub(crate) fn validate(&self) -> Result<(), AgentdError> {
        self.notes
            .previous_target
            .validate()
            .map_err(AgentdError::Invalid)?;
        self.calculator
            .previous_target
            .validate()
            .map_err(AgentdError::Invalid)?;
        if self.notes.previous_target.session_instance
            != self.calculator.previous_target.session_instance
            || self.notes.previous_target.task_id == self.calculator.previous_target.task_id
        {
            return Err(AgentdError::Invalid(
                "previous Desktop targets must be the exact distinct apps of one original Session"
                    .into(),
            ));
        }
        for (helper, directory, digest) in [
            (
                &self.notes.helper,
                &self.notes.state_directory,
                &self.notes.helper_sha256,
            ),
            (
                &self.calculator.helper,
                &self.calculator.state_directory,
                &self.calculator.helper_sha256,
            ),
        ] {
            if !helper.is_absolute() || !directory.is_absolute() {
                return Err(AgentdError::Invalid(
                    "previous Desktop helper and state paths must be absolute".into(),
                ));
            }
            Sha256Digest::parse(digest.clone()).map_err(AgentdError::Invalid)?;
        }
        Ok(())
    }

    pub(crate) fn into_requests(
        self,
    ) -> Result<
        (
            AgentdNotesPreviousRecoveryRequest,
            AgentdCalculatorPreviousRecoveryRequest,
        ),
        AgentdError,
    > {
        self.validate()?;
        Ok((
            AgentdNotesPreviousRecoveryRequest {
                helper: self.notes.helper,
                helper_sha256: Sha256Digest::parse(self.notes.helper_sha256)
                    .map_err(AgentdError::Invalid)?,
                state_directory: self.notes.state_directory,
                previous_target: self.notes.previous_target,
                selector: self.notes.selector,
            },
            AgentdCalculatorPreviousRecoveryRequest {
                helper: self.calculator.helper,
                helper_sha256: Sha256Digest::parse(self.calculator.helper_sha256)
                    .map_err(AgentdError::Invalid)?,
                state_directory: self.calculator.state_directory,
                previous_target: self.calculator.previous_target,
                selector: self.calculator.selector,
            },
        ))
    }
}
