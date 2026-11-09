//! Fixed Joint text jobs at the existing signed, durable TaskFlow effect boundary.
//! This adapter does not publish or adopt candidates and does not own a tensor
//! graph. A provider effect receipt grants no Training role or artifact publication.

use codex_hepta_contracts::Sha256Digest;

use crate::authorized_effect::AuthorizedEffectDriver;
use crate::authorized_effect::AuthorizedEffectDriverError;
use crate::authorized_effect::AuthorizedEffectOutcome;
use crate::authorized_effect::AuthorizedEffectPending;
use crate::authorized_effect::AuthorizedEffectProviderReceipt;
use crate::authorized_effect::AuthorizedEffectRequest;
use crate::authorized_effect::AuthorizedProviderEffectLookup;
use crate::joint_text_job::JOINT_TEXT_MAX_COMMAND_BYTES;
use crate::joint_text_job::JointTextJobCommandV1;
use crate::joint_text_job::JointTextJobIdentityV1;
use crate::joint_text_job::JointTextJobObservationV1;
use crate::joint_text_job::JointTextJobStateV1;
use crate::joint_text_job::JointTextSupervisor;
use crate::joint_text_job::JointTextSupervisorError;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum JointTextTaskFlowActionV1 {
    Start,
    Cancel,
}

impl JointTextTaskFlowActionV1 {
    pub fn operation_id(self) -> &'static str {
        match self {
            Self::Start => "joint.text.training.start",
            Self::Cancel => "joint.text.training.cancel",
        }
    }
}

/// Register this driver with `execute_authorized_taskflow_effect`. The existing
/// ledger consumes the signed final-use grant and records provider contact
/// before invoking dispatch. Recovery only queries the same durable job.
pub struct JointTextTaskFlowDriver<S> {
    provider_scope: String,
    action: JointTextTaskFlowActionV1,
    supervisor: S,
}

impl<S: JointTextSupervisor> JointTextTaskFlowDriver<S> {
    pub fn new(
        provider_scope: String,
        action: JointTextTaskFlowActionV1,
        supervisor: S,
    ) -> Result<Self, JointTextSupervisorError> {
        if provider_scope.trim().is_empty() {
            return Err(JointTextSupervisorError::BeforeContact);
        }
        Ok(Self {
            provider_scope,
            action,
            supervisor,
        })
    }

    /// A missing reservation cannot prove absence after a lost launch receipt.
    /// This adapter therefore never returns `ProvenAbsent` or redispatches.
    pub fn lookup(
        &mut self,
        pending: &AuthorizedEffectPending,
        immutable_wire_payload: &[u8],
    ) -> AuthorizedProviderEffectLookup {
        if pending.destination_id != self.provider_scope {
            return AuthorizedProviderEffectLookup::Unresolved;
        }
        let Ok(command) = self.command(
            &pending.run_id,
            &pending.step_id,
            &pending.payload_digest,
            immutable_wire_payload,
        ) else {
            return AuthorizedProviderEffectLookup::Unresolved;
        };
        let status = command.status();
        let Ok(observation) = self.supervisor.exchange(&status) else {
            return AuthorizedProviderEffectLookup::Unresolved;
        };
        let receipt = self.receipt(&status, &observation);
        match receipt.outcome {
            AuthorizedEffectOutcome::Succeeded | AuthorizedEffectOutcome::Failed => {
                AuthorizedProviderEffectLookup::Observed(receipt)
            }
            AuthorizedEffectOutcome::Indeterminate => AuthorizedProviderEffectLookup::Unresolved,
        }
    }

    fn command(
        &self,
        run_id: &str,
        step_id: &str,
        payload_digest: &Sha256Digest,
        wire_payload: &[u8],
    ) -> Result<JointTextJobCommandV1, JointTextSupervisorError> {
        if wire_payload.len() > JOINT_TEXT_MAX_COMMAND_BYTES
            || Sha256Digest::for_bytes(wire_payload) != *payload_digest
        {
            return Err(JointTextSupervisorError::BeforeContact);
        }
        let identity = JointTextJobIdentityV1::for_taskflow(
            &self.provider_scope,
            run_id,
            step_id,
            payload_digest.clone(),
        )?;
        match self.action {
            JointTextTaskFlowActionV1::Start => JointTextJobCommandV1::start(
                identity,
                String::from_utf8(wire_payload.to_vec())
                    .map_err(|_| JointTextSupervisorError::BeforeContact)?,
            ),
            JointTextTaskFlowActionV1::Cancel => JointTextJobCommandV1::cancel(
                identity,
                serde_json::from_slice(wire_payload)
                    .map_err(|_| JointTextSupervisorError::BeforeContact)?,
            ),
        }
    }

    fn receipt(
        &self,
        command: &JointTextJobCommandV1,
        observation: &JointTextJobObservationV1,
    ) -> AuthorizedEffectProviderReceipt {
        if observation.validate_for(command).is_err() {
            return unknown_receipt(command);
        }
        let outcome = match (self.action, observation.state) {
            (JointTextTaskFlowActionV1::Start, JointTextJobStateV1::Succeeded)
            | (JointTextTaskFlowActionV1::Cancel, JointTextJobStateV1::Cancelled) => {
                AuthorizedEffectOutcome::Succeeded
            }
            (
                JointTextTaskFlowActionV1::Start,
                JointTextJobStateV1::Failed | JointTextJobStateV1::Cancelled,
            )
            | (
                JointTextTaskFlowActionV1::Cancel,
                JointTextJobStateV1::Failed | JointTextJobStateV1::Succeeded,
            ) => AuthorizedEffectOutcome::Failed,
            (
                _,
                JointTextJobStateV1::Reserved
                | JointTextJobStateV1::Running
                | JointTextJobStateV1::Unknown,
            ) => AuthorizedEffectOutcome::Indeterminate,
        };
        // The complete validated observation binds process and all output hashes
        // to both dispatch identities. No file publication occurs at this seam.
        let Ok(bytes) = serde_json::to_vec(observation) else {
            return unknown_receipt(command);
        };
        let material = [
            b"hepta.joint.text.observation.v1\0".as_slice(),
            bytes.as_slice(),
        ]
        .concat();
        AuthorizedEffectProviderReceipt {
            outcome,
            receipt_digest: Sha256Digest::for_bytes(&material),
        }
    }
}

impl<S: JointTextSupervisor> AuthorizedEffectDriver for JointTextTaskFlowDriver<S> {
    fn dispatch(
        &mut self,
        request: &AuthorizedEffectRequest<'_>,
    ) -> Result<AuthorizedEffectProviderReceipt, AuthorizedEffectDriverError> {
        if request.intent.destination_id != self.provider_scope
            || request.intent.operation_id != self.action.operation_id()
            || request.intent.digest().as_ref().ok() != Some(request.intent_digest)
            || request.intent.operation_intent_v1().as_ref().ok() != Some(request.operation_intent)
            || request.intent.final_use_binding().as_ref().ok() != Some(request.binding)
        {
            return Err(AuthorizedEffectDriverError::BeforeProviderContact);
        }
        let command = self
            .command(
                &request.intent.run_id,
                &request.intent.step_id,
                &request.intent.payload_digest,
                request.wire_payload,
            )
            .map_err(|_| AuthorizedEffectDriverError::BeforeProviderContact)?;
        match self.supervisor.exchange(&command) {
            Ok(observation) => Ok(self.receipt(&command, &observation)),
            Err(JointTextSupervisorError::BeforeContact) => {
                Err(AuthorizedEffectDriverError::BeforeProviderContact)
            }
            Err(JointTextSupervisorError::Unknown) => Ok(unknown_receipt(&command)),
        }
    }
}

fn unknown_receipt(command: &JointTextJobCommandV1) -> AuthorizedEffectProviderReceipt {
    let bytes = format!(
        "hepta.joint.text.unknown.v1\0{}\0{}\0{}\0{}",
        command.dispatch.key.as_str(),
        command.dispatch.payload_sha256.as_str(),
        command.target.key.as_str(),
        command.target.payload_sha256.as_str(),
    );
    AuthorizedEffectProviderReceipt {
        outcome: AuthorizedEffectOutcome::Indeterminate,
        receipt_digest: Sha256Digest::for_bytes(bytes.as_bytes()),
    }
}

#[cfg(test)]
#[path = "joint_text_taskflow_tests.rs"]
mod tests;
