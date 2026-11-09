//! Fixed Joint supervisor data. Construction never authorizes worker contact,
//! grants a Training role, or proves that recorded bytes/processes were read.

use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

#[path = "joint_text_input.rs"]
mod input;
#[path = "joint_text_job_observation.rs"]
mod observation;

pub use input::JointTextInputManifestV1;
pub use input::JointTextInputRefV1;
pub use observation::JointTextFileDigestV1;
pub use observation::JointTextJobEvidenceV1;
pub use observation::JointTextJobObservationV1;
pub use observation::JointTextJobOutputsV1;
pub use observation::JointTextJobStateV1;
pub use observation::JointTextProcessIdentityV1;

pub const JOINT_TEXT_SUPERVISOR_SCHEMA_VERSION: u32 = 1;
pub const JOINT_TEXT_MAX_COMMAND_BYTES: usize = 24 * 1024;
pub const JOINT_TEXT_MAX_REQUEST_BYTES: usize = 65_536;
pub const JOINT_TEXT_MAX_PACKET_BYTES: usize = 8 * 1024 * 1024;
pub const JOINT_TEXT_MAX_TERMINAL_BYTES: usize = 1024 * 1024;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum JointTextProfileV1 {
    #[serde(rename = "joint-v4-verified-memory-text-sgd-v1")]
    VerifiedMemoryTextSgdV1,
}

/// Physical root binding from the admitted host deployment, never a task path
/// or a grant of authority. Joint entry/runner/worker retain this same tuple.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct JointTextRootIdentityV1 {
    pub device: u64,
    pub inode: u64,
    pub uid: u32,
}

impl JointTextRootIdentityV1 {
    pub fn validate(&self) -> Result<(), JointTextSupervisorError> {
        if self.inode == 0 {
            return Err(JointTextSupervisorError::BeforeContact);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct JointTextJobIdentityV1 {
    pub key: ProviderEffectKey,
    pub payload_sha256: Sha256Digest,
    pub job_id: Sha256Digest,
    pub output_id: Sha256Digest,
}

impl JointTextJobIdentityV1 {
    /// Keeps the existing logical effect key, independent of retry attempt.
    pub fn for_taskflow(
        provider_scope: &str,
        run_id: &str,
        step_id: &str,
        payload_sha256: Sha256Digest,
    ) -> Result<Self, JointTextSupervisorError> {
        if run_id.is_empty() || step_id.is_empty() || step_id.contains(':') {
            return Err(JointTextSupervisorError::BeforeContact);
        }
        let key = ProviderEffectKey::for_logical_effect(
            provider_scope,
            &format!("taskflow:{run_id}:{step_id}"),
        )
        .map_err(|_| JointTextSupervisorError::BeforeContact)?;
        Self::for_key(key, payload_sha256)
    }

    pub fn for_key(
        key: ProviderEffectKey,
        payload_sha256: Sha256Digest,
    ) -> Result<Self, JointTextSupervisorError> {
        ProviderEffectKey::parse(key.as_str())
            .map_err(|_| JointTextSupervisorError::BeforeContact)?;
        digest(&payload_sha256)?;
        let identity = format!("{}\0{}", key.as_str(), payload_sha256.as_str());
        Ok(Self {
            job_id: Sha256Digest::for_bytes(
                &[b"hepta.joint.text.job.v1\0".as_slice(), identity.as_bytes()].concat(),
            ),
            output_id: Sha256Digest::for_bytes(
                &[
                    b"hepta.joint.text.output.v1\0".as_slice(),
                    identity.as_bytes(),
                ]
                .concat(),
            ),
            key,
            payload_sha256,
        })
    }

    pub fn validate(&self) -> Result<(), JointTextSupervisorError> {
        if Self::for_key(self.key.clone(), self.payload_sha256.clone())? != *self {
            return Err(JointTextSupervisorError::BeforeContact);
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum JointTextSupervisorActionV1 {
    Start,
    Status,
    Cancel,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct JointTextJobCommandV1 {
    pub schema_version: u32,
    pub profile: JointTextProfileV1,
    pub action: JointTextSupervisorActionV1,
    pub dispatch: JointTextJobIdentityV1,
    pub target: JointTextJobIdentityV1,
    /// Exact small descriptor bytes, never inline training input or a host path.
    pub payload: Option<String>,
}

impl JointTextJobCommandV1 {
    pub fn start(
        identity: JointTextJobIdentityV1,
        payload: String,
    ) -> Result<Self, JointTextSupervisorError> {
        let command = Self {
            schema_version: JOINT_TEXT_SUPERVISOR_SCHEMA_VERSION,
            profile: JointTextProfileV1::VerifiedMemoryTextSgdV1,
            action: JointTextSupervisorActionV1::Start,
            dispatch: identity.clone(),
            target: identity,
            payload: Some(payload),
        };
        command.validate()?;
        Ok(command)
    }

    pub fn cancel(
        dispatch: JointTextJobIdentityV1,
        target: JointTextJobIdentityV1,
    ) -> Result<Self, JointTextSupervisorError> {
        let command = Self {
            schema_version: JOINT_TEXT_SUPERVISOR_SCHEMA_VERSION,
            profile: JointTextProfileV1::VerifiedMemoryTextSgdV1,
            action: JointTextSupervisorActionV1::Cancel,
            dispatch,
            target,
            payload: None,
        };
        command.validate()?;
        Ok(command)
    }

    /// Queries this same dispatch/target; absence never permits another start.
    pub fn status(&self) -> Self {
        Self {
            action: JointTextSupervisorActionV1::Status,
            payload: None,
            ..self.clone()
        }
    }

    pub fn validate(&self) -> Result<(), JointTextSupervisorError> {
        self.dispatch.validate()?;
        self.target.validate()?;
        if self.schema_version != JOINT_TEXT_SUPERVISOR_SCHEMA_VERSION
            || serde_json::to_vec(self)
                .map_err(|_| JointTextSupervisorError::BeforeContact)?
                .len()
                > JOINT_TEXT_MAX_COMMAND_BYTES
        {
            return Err(JointTextSupervisorError::BeforeContact);
        }
        match (self.action, &self.payload) {
            (JointTextSupervisorActionV1::Start, Some(payload))
                if self.dispatch == self.target
                    && Sha256Digest::for_bytes(payload.as_bytes())
                        == self.dispatch.payload_sha256 =>
            {
                JointTextInputRefV1::decode(payload.as_bytes()).map(|_| ())
            }
            (JointTextSupervisorActionV1::Cancel, None) if self.dispatch.key != self.target.key => {
                Ok(())
            }
            (JointTextSupervisorActionV1::Status, None) => Ok(()),
            _ => Err(JointTextSupervisorError::BeforeContact),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, thiserror::Error)]
pub enum JointTextSupervisorError {
    #[error("Joint supervisor request refused before provider contact")]
    BeforeContact,
    #[error("Joint supervisor outcome unknown; query the original identity")]
    Unknown,
}

/// A registered owner supplies permission separately. Implementations reserve
/// the original identity before launch, bound RPC contact, and return Unknown
/// after ambiguous contact. Neither lookup nor a lost ACK may relaunch a job.
pub trait JointTextSupervisor {
    fn exchange(
        &mut self,
        command: &JointTextJobCommandV1,
    ) -> Result<JointTextJobObservationV1, JointTextSupervisorError>;
}

fn digest(value: &Sha256Digest) -> Result<(), JointTextSupervisorError> {
    if value.as_str().len() != 64
        || !value
            .as_str()
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(JointTextSupervisorError::BeforeContact);
    }
    Sha256Digest::parse(value.as_str())
        .map(|_| ())
        .map_err(|_| JointTextSupervisorError::BeforeContact)
}

#[cfg(test)]
#[path = "joint_text_job_tests.rs"]
mod tests;
