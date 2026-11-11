//! HCSN training at the existing signed, durable TaskFlow effect boundary.
//! This adapter does not publish or adopt candidates and does not own a tensor
//! graph. A terminal training receipt is input to the separate artifact owner.

use codex_hepta_contracts::Sha256Digest;

use crate::authorized_effect::AuthorizedEffectDriver;
use crate::authorized_effect::AuthorizedEffectDriverError;
use crate::authorized_effect::AuthorizedEffectOutcome;
use crate::authorized_effect::AuthorizedEffectPending;
use crate::authorized_effect::AuthorizedEffectProviderReceipt;
use crate::authorized_effect::AuthorizedEffectRequest;
use crate::authorized_effect::AuthorizedProviderEffectLookup;
use crate::hcsn_job::HcsnJobIdentityV1;
use crate::hcsn_job::HcsnJobObservationV1;
use crate::hcsn_job::HcsnJobStateV1;
use crate::hcsn_job::HcsnSupervisor;
use crate::hcsn_job::HcsnSupervisorCommandV1;
use crate::hcsn_job::HcsnSupervisorError;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HcsnTaskFlowActionV1 {
    Start,
    Cancel,
}

impl HcsnTaskFlowActionV1 {
    pub fn operation_id(self) -> &'static str {
        match self {
            Self::Start => "hcsn.training.start",
            Self::Cancel => "hcsn.training.cancel",
        }
    }
}

/// Register this driver with `execute_authorized_taskflow_effect`. The existing
/// ledger consumes the signed final-use grant and records provider contact
/// before invoking dispatch. Recovery only queries the same durable job.
pub struct HcsnTaskFlowDriver<S> {
    provider_scope: String,
    action: HcsnTaskFlowActionV1,
    supervisor: S,
}

impl<S: HcsnSupervisor> HcsnTaskFlowDriver<S> {
    pub fn new(
        provider_scope: String,
        action: HcsnTaskFlowActionV1,
        supervisor: S,
    ) -> Result<Self, HcsnSupervisorError> {
        if provider_scope.trim().is_empty() {
            return Err(HcsnSupervisorError::BeforeContact);
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
    ) -> Result<HcsnSupervisorCommandV1, HcsnSupervisorError> {
        if Sha256Digest::for_bytes(wire_payload) != *payload_digest {
            return Err(HcsnSupervisorError::BeforeContact);
        }
        let identity = HcsnJobIdentityV1::for_taskflow(
            &self.provider_scope,
            run_id,
            step_id,
            payload_digest.clone(),
        )?;
        match self.action {
            HcsnTaskFlowActionV1::Start => HcsnSupervisorCommandV1::start(
                identity,
                String::from_utf8(wire_payload.to_vec())
                    .map_err(|_| HcsnSupervisorError::BeforeContact)?,
            ),
            HcsnTaskFlowActionV1::Cancel => HcsnSupervisorCommandV1::cancel(
                identity,
                serde_json::from_slice(wire_payload)
                    .map_err(|_| HcsnSupervisorError::BeforeContact)?,
            ),
        }
    }

    fn receipt(
        &self,
        command: &HcsnSupervisorCommandV1,
        observation: &HcsnJobObservationV1,
    ) -> AuthorizedEffectProviderReceipt {
        if observation.validate_for(command).is_err() {
            return unknown_receipt(command);
        }
        let outcome = match (self.action, observation.state) {
            (HcsnTaskFlowActionV1::Start, HcsnJobStateV1::Succeeded)
            | (HcsnTaskFlowActionV1::Cancel, HcsnJobStateV1::Cancelled) => {
                AuthorizedEffectOutcome::Succeeded
            }
            (HcsnTaskFlowActionV1::Start, HcsnJobStateV1::Failed | HcsnJobStateV1::Cancelled)
            | (HcsnTaskFlowActionV1::Cancel, HcsnJobStateV1::Failed | HcsnJobStateV1::Succeeded) => {
                AuthorizedEffectOutcome::Failed
            }
            (_, HcsnJobStateV1::Reserved | HcsnJobStateV1::Running | HcsnJobStateV1::Unknown) => {
                AuthorizedEffectOutcome::Indeterminate
            }
        };
        // The complete validated observation binds process and all output hashes
        // to both dispatch identities. No file publication occurs at this seam.
        let Ok(bytes) = serde_json::to_vec(observation) else {
            return unknown_receipt(command);
        };
        let material = [b"hepta.hcsn.observation.v1\0".as_slice(), bytes.as_slice()].concat();
        AuthorizedEffectProviderReceipt {
            outcome,
            receipt_digest: Sha256Digest::for_bytes(&material),
        }
    }
}

impl<S: HcsnSupervisor> AuthorizedEffectDriver for HcsnTaskFlowDriver<S> {
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
            Err(HcsnSupervisorError::BeforeContact) => {
                Err(AuthorizedEffectDriverError::BeforeProviderContact)
            }
            Err(HcsnSupervisorError::Unknown) => Ok(unknown_receipt(&command)),
        }
    }
}

fn unknown_receipt(command: &HcsnSupervisorCommandV1) -> AuthorizedEffectProviderReceipt {
    let bytes = format!(
        "hepta.hcsn.unknown.v1\0{}\0{}\0{}\0{}",
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
#[path = "hcsn_taskflow_tests.rs"]
mod tests;
