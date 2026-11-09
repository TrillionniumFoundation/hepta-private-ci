//! Path-free reference to immutable provider-owned inputs. The H worker's
//! request-binding digest is distinct from the exact request-file SHA.

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use super::JOINT_TEXT_MAX_COMMAND_BYTES;
use super::JOINT_TEXT_MAX_PACKET_BYTES;
use super::JOINT_TEXT_MAX_REQUEST_BYTES;
use super::JOINT_TEXT_SUPERVISOR_SCHEMA_VERSION;
use super::JointTextProfileV1;
use super::JointTextSupervisorError;
use super::digest;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct JointTextInputManifestV1 {
    pub schema_version: u32,
    pub profile: JointTextProfileV1,
    pub request_sha256: Sha256Digest,
    pub request_bytes: u64,
    pub request_binding_digest: Sha256Digest,
    pub predecessor_sha256: Sha256Digest,
    pub predecessor_bytes: u64,
    pub worker_execution_source_digest: Sha256Digest,
}

impl JointTextInputManifestV1 {
    pub fn validate(&self) -> Result<(), JointTextSupervisorError> {
        if self.schema_version != JOINT_TEXT_SUPERVISOR_SCHEMA_VERSION
            || self.request_bytes == 0
            || self.request_bytes > JOINT_TEXT_MAX_REQUEST_BYTES as u64
            || self.predecessor_bytes == 0
            || self.predecessor_bytes > JOINT_TEXT_MAX_PACKET_BYTES as u64
        {
            return Err(JointTextSupervisorError::BeforeContact);
        }
        for value in [
            &self.request_sha256,
            &self.request_binding_digest,
            &self.predecessor_sha256,
            &self.worker_execution_source_digest,
        ] {
            digest(value)?;
        }
        Ok(())
    }

    /// Compact declaration-order JSON with no newline is the manifest format.
    pub fn encode(&self) -> Result<Vec<u8>, JointTextSupervisorError> {
        self.validate()?;
        serde_json::to_vec(self).map_err(|_| JointTextSupervisorError::BeforeContact)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct JointTextInputRefV1 {
    pub manifest: JointTextInputManifestV1,
    pub manifest_sha256: Sha256Digest,
    pub input_id: Sha256Digest,
}

impl JointTextInputRefV1 {
    pub fn from_manifest(
        manifest: JointTextInputManifestV1,
    ) -> Result<Self, JointTextSupervisorError> {
        let manifest_sha256 = Sha256Digest::for_bytes(&manifest.encode()?);
        let input_id = Sha256Digest::for_bytes(
            &[
                b"hepta.joint.text.input.v1\0".as_slice(),
                manifest_sha256.as_str().as_bytes(),
            ]
            .concat(),
        );
        Ok(Self {
            manifest,
            manifest_sha256,
            input_id,
        })
    }

    pub fn validate(&self) -> Result<(), JointTextSupervisorError> {
        if Self::from_manifest(self.manifest.clone())? != *self {
            return Err(JointTextSupervisorError::BeforeContact);
        }
        Ok(())
    }

    pub fn encode(&self) -> Result<Vec<u8>, JointTextSupervisorError> {
        self.validate()?;
        let bytes =
            serde_json::to_vec(self).map_err(|_| JointTextSupervisorError::BeforeContact)?;
        if bytes.len() > JOINT_TEXT_MAX_COMMAND_BYTES {
            return Err(JointTextSupervisorError::BeforeContact);
        }
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, JointTextSupervisorError> {
        if bytes.len() > JOINT_TEXT_MAX_COMMAND_BYTES {
            return Err(JointTextSupervisorError::BeforeContact);
        }
        let value: Self =
            serde_json::from_slice(bytes).map_err(|_| JointTextSupervisorError::BeforeContact)?;
        if value.encode()? != bytes {
            return Err(JointTextSupervisorError::BeforeContact);
        }
        Ok(value)
    }
}
