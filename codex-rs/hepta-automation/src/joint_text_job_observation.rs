//! Recorded outcome shapes; only the registered provider can observe actual
//! process/file facts, and H-B separately revalidates current learning inputs.

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use super::JOINT_TEXT_MAX_PACKET_BYTES;
use super::JOINT_TEXT_MAX_REQUEST_BYTES;
use super::JOINT_TEXT_MAX_TERMINAL_BYTES;
use super::JOINT_TEXT_SUPERVISOR_SCHEMA_VERSION;
use super::JointTextInputRefV1;
use super::JointTextJobCommandV1;
use super::JointTextJobIdentityV1;
use super::JointTextProfileV1;
use super::JointTextSupervisorError;
use super::digest;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct JointTextFileDigestV1 {
    pub sha256: Sha256Digest,
    pub bytes: u64,
}

impl JointTextFileDigestV1 {
    fn validate(&self, maximum_bytes: usize) -> Result<(), JointTextSupervisorError> {
        digest(&self.sha256).map_err(|_| JointTextSupervisorError::Unknown)?;
        if self.bytes == 0 || self.bytes > maximum_bytes as u64 {
            return Err(JointTextSupervisorError::Unknown);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct JointTextJobOutputsV1 {
    pub input: JointTextInputRefV1,
    pub started: JointTextFileDigestV1,
    pub candidate: JointTextFileDigestV1,
    pub observation: JointTextFileDigestV1,
    pub completed: JointTextFileDigestV1,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum JointTextJobEvidenceV1 {
    Stopped {
        terminal: JointTextFileDigestV1,
    },
    Completed {
        terminal: JointTextFileDigestV1,
        outputs: Box<JointTextJobOutputsV1>,
    },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct JointTextProcessIdentityV1 {
    pub host_id: Sha256Digest,
    pub process_id: u64,
    pub incarnation: Sha256Digest,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum JointTextJobStateV1 {
    Reserved,
    Running,
    Succeeded,
    Failed,
    Cancelled,
    Unknown,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct JointTextJobObservationV1 {
    pub schema_version: u32,
    pub profile: JointTextProfileV1,
    pub dispatch: JointTextJobIdentityV1,
    pub target: JointTextJobIdentityV1,
    pub state: JointTextJobStateV1,
    pub process: Option<JointTextProcessIdentityV1>,
    pub evidence: Option<JointTextJobEvidenceV1>,
}

impl JointTextJobObservationV1 {
    /// Validates data binding, never unobserved file bytes or worker execution.
    pub fn validate_for(
        &self,
        command: &JointTextJobCommandV1,
    ) -> Result<(), JointTextSupervisorError> {
        command.validate()?;
        if self.schema_version != JOINT_TEXT_SUPERVISOR_SCHEMA_VERSION
            || self.profile != command.profile
            || self.dispatch != command.dispatch
            || self.target != command.target
        {
            return Err(JointTextSupervisorError::Unknown);
        }
        if let Some(process) = &self.process {
            digest(&process.host_id).map_err(|_| JointTextSupervisorError::Unknown)?;
            digest(&process.incarnation).map_err(|_| JointTextSupervisorError::Unknown)?;
            if process.process_id == 0 {
                return Err(JointTextSupervisorError::Unknown);
            }
        }
        if let Some(evidence) = &self.evidence {
            match evidence {
                JointTextJobEvidenceV1::Stopped { terminal } => {
                    terminal.validate(JOINT_TEXT_MAX_TERMINAL_BYTES)?;
                }
                JointTextJobEvidenceV1::Completed { terminal, outputs } => {
                    terminal.validate(JOINT_TEXT_MAX_TERMINAL_BYTES)?;
                    let payload = outputs
                        .input
                        .encode()
                        .map_err(|_| JointTextSupervisorError::Unknown)?;
                    if Sha256Digest::for_bytes(&payload) != self.target.payload_sha256 {
                        return Err(JointTextSupervisorError::Unknown);
                    }
                    outputs.started.validate(JOINT_TEXT_MAX_REQUEST_BYTES)?;
                    outputs.candidate.validate(JOINT_TEXT_MAX_PACKET_BYTES)?;
                    outputs.observation.validate(JOINT_TEXT_MAX_REQUEST_BYTES)?;
                    outputs.completed.validate(JOINT_TEXT_MAX_REQUEST_BYTES)?;
                }
            }
        }
        let valid = match (&self.state, &self.evidence) {
            (JointTextJobStateV1::Reserved | JointTextJobStateV1::Unknown, None) => true,
            (JointTextJobStateV1::Running, None) => self.process.is_some(),
            (JointTextJobStateV1::Succeeded, Some(JointTextJobEvidenceV1::Completed { .. })) => {
                self.process.is_some()
            }
            (
                JointTextJobStateV1::Failed | JointTextJobStateV1::Cancelled,
                Some(JointTextJobEvidenceV1::Stopped { .. }),
            ) => true,
            _ => false,
        };
        if !valid {
            return Err(JointTextSupervisorError::Unknown);
        }
        Ok(())
    }
}
