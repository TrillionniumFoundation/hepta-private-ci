//! Immutable HCSN supervisor identities and receipts. Candidate publication and
//! adoption remain with the learning-artifact owner, outside this protocol.

use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use thiserror::Error;

pub const HCSN_SUPERVISOR_SCHEMA_VERSION: u32 = 1;
pub const HCSN_MAX_TRAINING_PAYLOAD_BYTES: usize = 8 * 1024 * 1024;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HcsnJobIdentityV1 {
    pub key: ProviderEffectKey,
    pub payload_sha256: Sha256Digest,
    pub job_id: Sha256Digest,
    pub output_id: Sha256Digest,
}

impl HcsnJobIdentityV1 {
    /// Uses the existing TaskFlow provider key, independent of retry attempt.
    /// Colons in a step ID would make that legacy key framing ambiguous.
    pub fn for_taskflow(
        provider_scope: &str,
        run_id: &str,
        step_id: &str,
        payload_sha256: Sha256Digest,
    ) -> Result<Self, HcsnSupervisorError> {
        if run_id.is_empty() || step_id.is_empty() || step_id.contains(':') {
            return Err(HcsnSupervisorError::BeforeContact);
        }
        let key = ProviderEffectKey::for_logical_effect(
            provider_scope,
            &format!("taskflow:{run_id}:{step_id}"),
        )
        .map_err(|_| HcsnSupervisorError::BeforeContact)?;
        Self::for_key(key, payload_sha256)
    }

    pub fn for_key(
        key: ProviderEffectKey,
        payload_sha256: Sha256Digest,
    ) -> Result<Self, HcsnSupervisorError> {
        ProviderEffectKey::parse(key.as_str()).map_err(|_| HcsnSupervisorError::BeforeContact)?;
        Sha256Digest::parse(payload_sha256.as_str())
            .map_err(|_| HcsnSupervisorError::BeforeContact)?;
        let identity = format!("{}\0{}", key.as_str(), payload_sha256.as_str());
        Ok(Self {
            job_id: Sha256Digest::for_bytes(
                [b"hepta.hcsn.job.v1\0".as_slice(), identity.as_bytes()]
                    .concat()
                    .as_slice(),
            ),
            output_id: Sha256Digest::for_bytes(
                [b"hepta.hcsn.output.v1\0".as_slice(), identity.as_bytes()]
                    .concat()
                    .as_slice(),
            ),
            key,
            payload_sha256,
        })
    }

    pub fn validate(&self) -> Result<(), HcsnSupervisorError> {
        if Self::for_key(self.key.clone(), self.payload_sha256.clone())? != *self {
            return Err(HcsnSupervisorError::BeforeContact);
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum HcsnSupervisorActionV1 {
    Start,
    Status,
    Cancel,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HcsnSupervisorCommandV1 {
    pub schema_version: u32,
    pub action: HcsnSupervisorActionV1,
    pub dispatch: HcsnJobIdentityV1,
    pub target: HcsnJobIdentityV1,
    /// Exact authorized worker JSON bytes; present only on initial start.
    pub payload: Option<String>,
}

impl HcsnSupervisorCommandV1 {
    pub fn start(
        identity: HcsnJobIdentityV1,
        payload: String,
    ) -> Result<Self, HcsnSupervisorError> {
        let command = Self {
            schema_version: HCSN_SUPERVISOR_SCHEMA_VERSION,
            action: HcsnSupervisorActionV1::Start,
            dispatch: identity.clone(),
            target: identity,
            payload: Some(payload),
        };
        command.validate()?;
        Ok(command)
    }

    pub fn cancel(
        dispatch: HcsnJobIdentityV1,
        target: HcsnJobIdentityV1,
    ) -> Result<Self, HcsnSupervisorError> {
        let command = Self {
            schema_version: HCSN_SUPERVISOR_SCHEMA_VERSION,
            action: HcsnSupervisorActionV1::Cancel,
            dispatch,
            target,
            payload: None,
        };
        command.validate()?;
        Ok(command)
    }

    /// A read-only command for this exact dispatch; absence never permits start.
    pub fn status(&self) -> Self {
        Self {
            action: HcsnSupervisorActionV1::Status,
            payload: None,
            ..self.clone()
        }
    }

    pub fn validate(&self) -> Result<(), HcsnSupervisorError> {
        self.dispatch.validate()?;
        self.target.validate()?;
        if self.schema_version != HCSN_SUPERVISOR_SCHEMA_VERSION {
            return Err(HcsnSupervisorError::BeforeContact);
        }
        match (self.action, &self.payload) {
            (HcsnSupervisorActionV1::Start, Some(payload))
                if self.dispatch == self.target
                    && payload.len() <= HCSN_MAX_TRAINING_PAYLOAD_BYTES
                    && Sha256Digest::for_bytes(payload.as_bytes())
                        == self.dispatch.payload_sha256
                    && serde_json::from_str::<serde_json::Value>(payload)
                        .is_ok_and(|value| value.is_object()) =>
            {
                Ok(())
            }
            (HcsnSupervisorActionV1::Cancel, None) if self.dispatch.key != self.target.key => {
                Ok(())
            }
            (HcsnSupervisorActionV1::Status, None) => Ok(()),
            _ => Err(HcsnSupervisorError::BeforeContact),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HcsnProcessIdentityV1 {
    pub host_id: Sha256Digest,
    pub process_id: u64,
    /// Host-specific process incarnation (on Linux, boot ID plus start ticks).
    pub incarnation: Sha256Digest,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HcsnJobEvidenceV1 {
    pub receipt_sha256: Sha256Digest,
    pub candidate_sha256: Option<Sha256Digest>,
    pub handoff_sha256: Option<Sha256Digest>,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum HcsnJobStateV1 {
    Reserved,
    Running,
    Succeeded,
    Failed,
    Cancelled,
    Unknown,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HcsnJobObservationV1 {
    pub schema_version: u32,
    pub dispatch: HcsnJobIdentityV1,
    pub target: HcsnJobIdentityV1,
    pub state: HcsnJobStateV1,
    pub process: Option<HcsnProcessIdentityV1>,
    pub evidence: Option<HcsnJobEvidenceV1>,
}

impl HcsnJobObservationV1 {
    /// Validates receipt binding, never an assertion about unobserved file bytes.
    /// The registered supervisor must hash its durable output files; the learning
    /// owner separately verifies handoff/content before candidate publication.
    pub fn validate_for(
        &self,
        command: &HcsnSupervisorCommandV1,
    ) -> Result<(), HcsnSupervisorError> {
        command.validate()?;
        if self.schema_version != HCSN_SUPERVISOR_SCHEMA_VERSION
            || self.dispatch != command.dispatch
            || self.target != command.target
        {
            return Err(HcsnSupervisorError::Unknown);
        }
        if let Some(process) = &self.process
            && (process.process_id == 0
                || Sha256Digest::parse(process.host_id.as_str()).is_err()
                || Sha256Digest::parse(process.incarnation.as_str()).is_err())
        {
            return Err(HcsnSupervisorError::Unknown);
        }
        if let Some(evidence) = &self.evidence {
            for digest in std::iter::once(&evidence.receipt_sha256)
                .chain(evidence.candidate_sha256.iter())
                .chain(evidence.handoff_sha256.iter())
            {
                if Sha256Digest::parse(digest.as_str()).is_err() {
                    return Err(HcsnSupervisorError::Unknown);
                }
            }
        }
        let valid_state = match self.state {
            HcsnJobStateV1::Reserved | HcsnJobStateV1::Unknown => self.evidence.is_none(),
            HcsnJobStateV1::Running => self.process.is_some() && self.evidence.is_none(),
            HcsnJobStateV1::Succeeded => {
                self.process.is_some()
                    && self.evidence.as_ref().is_some_and(|evidence| {
                        evidence.candidate_sha256.is_some() && evidence.handoff_sha256.is_some()
                    })
            }
            HcsnJobStateV1::Failed | HcsnJobStateV1::Cancelled => self.evidence.is_some(),
        };
        if !valid_state {
            return Err(HcsnSupervisorError::Unknown);
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum HcsnSupervisorError {
    #[error("HCSN supervisor request failed before process/provider contact")]
    BeforeContact,
    #[error("HCSN supervisor outcome is unknown; query the original identity")]
    Unknown,
}

/// Registered host supervision seam. Implementations reserve immutable dispatch
/// and output identities durably before process launch, never relaunch an
/// ambiguous reservation, and bind cancellation to the recorded incarnation.
/// Calls must have a bounded deadline. Errors after contact must be Unknown.
pub trait HcsnSupervisor {
    fn exchange(
        &mut self,
        command: &HcsnSupervisorCommandV1,
    ) -> Result<HcsnJobObservationV1, HcsnSupervisorError>;
}

#[cfg(test)]
#[path = "hcsn_job_tests.rs"]
mod tests;
