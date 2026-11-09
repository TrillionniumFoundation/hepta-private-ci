//! Retained Joint dispatch and same-identity reconciliation inside the ordinary
//! effect owner. Only the actual FinalUse claim permits Start or Cancel contact.

use std::collections::BTreeMap;
use std::fmt;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_automation::AuthorizedEffectDispatchRequest;
use codex_hepta_automation::AuthorizedEffectDriver;
use codex_hepta_automation::AuthorizedEffectDriverError;
use codex_hepta_automation::AuthorizedEffectIntent;
use codex_hepta_automation::AuthorizedEffectPending;
use codex_hepta_automation::AuthorizedEffectProviderReceipt;
use codex_hepta_automation::AuthorizedEffectRequest;
use codex_hepta_automation::AuthorizedProviderEffectLookup;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::JointTextInputRefV1;
use codex_hepta_automation::JointTextJobIdentityV1;
use codex_hepta_automation::JointTextProcessSupervisor;
use codex_hepta_automation::JointTextProcessSupervisorConfig;
use codex_hepta_automation::JointTextSupervisorError;
use codex_hepta_automation::JointTextTaskFlowActionV1;
use codex_hepta_automation::JointTextTaskFlowDriver;
use codex_hepta_automation::TaskFlowStepReceipt;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentdError;
use crate::automation_joint_text_inputs::JointTextInputCustodyV1;
use crate::automation_joint_text_inputs::JointTextJobBindingV1;
use crate::joint_text_training_owner::JointTextCheckpointBindingV1;

use super::AgentdAutomationEffectHost;
use super::joint_pq::JointTextClaim;
use super::joint_source::JointTextSourceManifestV1;

#[derive(Clone)]
pub(super) struct JointTextProvider {
    pub(super) provider_scope: String,
    pub(super) config: JointTextProcessSupervisorConfig,
    pub(super) custody: Arc<JointTextInputCustodyV1>,
    pub(super) source_manifest: Arc<JointTextSourceManifestV1>,
    pub(super) checkpoints: Arc<Mutex<BTreeMap<String, Arc<JointTextCheckpointBindingV1>>>>,
}

impl fmt::Debug for JointTextProvider {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("JointTextProvider")
            .field("provider_scope", &self.provider_scope)
            .field("config", &self.config)
            .finish_non_exhaustive()
    }
}

#[derive(Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct RetainedRequest {
    intent: AuthorizedEffectIntent,
    wire_payload: String,
}

pub(super) struct RetainedJointTextDriver {
    provider: JointTextProvider,
    driver: JointTextTaskFlowDriver<JointTextProcessSupervisor>,
    payload_digest: Sha256Digest,
    action: JointTextTaskFlowActionV1,
    pub(super) claim: Option<JointTextClaim>,
}

impl JointTextProvider {
    pub(super) fn verify_sources_and_custody(
        &self,
        input: Option<&JointTextInputRefV1>,
    ) -> Result<(), JointTextSupervisorError> {
        self.source_manifest
            .verify(&self.config.repository_root)
            .map_err(|_| JointTextSupervisorError::BeforeContact)?;
        self.custody
            .verify_root()
            .map_err(|_| JointTextSupervisorError::BeforeContact)?;
        if let Some(input) = input {
            if &input.manifest.worker_execution_source_digest
                != self.source_manifest.execution_digest()
            {
                return Err(JointTextSupervisorError::BeforeContact);
            }
            self.custody
                .read(input)
                .map_err(|_| JointTextSupervisorError::BeforeContact)?;
        }
        Ok(())
    }

    pub(super) fn driver_with_contact_guard(
        &self,
        operation: &str,
        payload: &[u8],
        guard: impl Fn() -> Result<(), JointTextSupervisorError> + Send + Sync + 'static,
    ) -> Result<RetainedJointTextDriver, AgentdError> {
        let action = action_for_operation(operation)?;
        let input = match action {
            JointTextTaskFlowActionV1::Start => {
                Some(JointTextInputRefV1::decode(payload).map_err(|_| {
                    AgentdError::Invalid("invalid fixed Joint input descriptor".to_string())
                })?)
            }
            JointTextTaskFlowActionV1::Cancel => None,
        };
        let at_contact = self.clone();
        let supervisor =
            JointTextProcessSupervisor::new_with_contact_guard(self.config.clone(), move || {
                at_contact.verify_sources_and_custody(input.as_ref())?;
                // Source and custody IO precede the actual current lease check.
                guard()
            })
            .map_err(|_| {
                AgentdError::Invalid("Joint supervisor deployment pins rejected".to_string())
            })?;
        let driver = JointTextTaskFlowDriver::new(self.provider_scope.clone(), action, supervisor)
            .map_err(|_| AgentdError::Invalid("invalid Joint provider scope".to_string()))?;
        Ok(RetainedJointTextDriver {
            provider: self.clone(),
            driver,
            payload_digest: Sha256Digest::for_bytes(payload),
            action,
            claim: None,
        })
    }

    pub(super) fn lookup(
        &self,
        pending: &AuthorizedEffectPending,
        guard: impl Fn() -> Result<(), JointTextSupervisorError> + Send + Sync + 'static,
    ) -> AuthorizedProviderEffectLookup {
        let Ok(bytes) = self.custody.read_retained_effect(&pending.intent_digest) else {
            return AuthorizedProviderEffectLookup::Unresolved;
        };
        let Ok(saved) = serde_json::from_slice::<RetainedRequest>(&bytes) else {
            return AuthorizedProviderEffectLookup::Unresolved;
        };
        if serde_json::to_vec(&saved).as_ref().ok() != Some(&bytes)
            || saved.intent.digest().as_ref().ok() != Some(&pending.intent_digest)
            || saved.intent.run_id != pending.run_id
            || saved.intent.step_id != pending.step_id
            || saved.intent.attempt != pending.attempt
            || saved.intent.destination_id != pending.destination_id
            || saved.intent.payload_digest != pending.payload_digest
            || Sha256Digest::for_bytes(saved.wire_payload.as_bytes()) != pending.payload_digest
        {
            return AuthorizedProviderEffectLookup::Unresolved;
        }
        let Ok(mut driver) = self.driver_with_contact_guard(
            &saved.intent.operation_id,
            saved.wire_payload.as_bytes(),
            guard,
        ) else {
            return AuthorizedProviderEffectLookup::Unresolved;
        };
        driver.driver.lookup(pending, saved.wire_payload.as_bytes())
    }
}

impl AuthorizedEffectDriver for RetainedJointTextDriver {
    fn prepare_claim(
        &mut self,
        token: &codex_hepta_contracts::VerifiedUseToken,
    ) -> Result<(), AuthorizedEffectDriverError> {
        let claim = self
            .claim
            .as_ref()
            .ok_or(AuthorizedEffectDriverError::BeforeProviderContact)?;
        let admitted = claim
            .lease
            .clone()
            .check_claim(token)
            .map_err(|_| AuthorizedEffectDriverError::BeforeProviderContact)?;
        claim
            .admitted
            .set(admitted)
            .map_err(|_| AuthorizedEffectDriverError::BeforeProviderContact)
    }

    fn dispatch(
        &mut self,
        request: &AuthorizedEffectRequest<'_>,
    ) -> Result<AuthorizedEffectProviderReceipt, AuthorizedEffectDriverError> {
        if request.intent.payload_digest != self.payload_digest
            || request.intent.operation_id != self.action.operation_id()
            || request.intent.destination_id != self.provider.provider_scope
            || request.intent.digest().as_ref().ok() != Some(request.intent_digest)
            || request.intent.operation_intent_v1().as_ref().ok() != Some(request.operation_intent)
            || request.intent.final_use_binding().as_ref().ok() != Some(request.binding)
            || Sha256Digest::for_bytes(request.wire_payload) != self.payload_digest
            || self
                .claim
                .as_ref()
                .and_then(|claim| claim.admitted.get())
                .is_none()
        {
            return Err(AuthorizedEffectDriverError::BeforeProviderContact);
        }
        let retained = RetainedRequest {
            intent: request.intent.clone(),
            wire_payload: String::from_utf8(request.wire_payload.to_vec())
                .map_err(|_| AuthorizedEffectDriverError::BeforeProviderContact)?,
        };
        let bytes = serde_json::to_vec(&retained)
            .map_err(|_| AuthorizedEffectDriverError::BeforeProviderContact)?;
        self.provider
            .custody
            .retain_effect(&request.intent_digest, &bytes)
            .map_err(|_| AuthorizedEffectDriverError::BeforeProviderContact)?;
        if self.action == JointTextTaskFlowActionV1::Start {
            let input = JointTextInputRefV1::decode(request.wire_payload)
                .map_err(|_| AuthorizedEffectDriverError::BeforeProviderContact)?;
            let identity = JointTextJobIdentityV1::for_taskflow(
                &self.provider.provider_scope,
                &request.intent.run_id,
                &request.intent.step_id,
                request.intent.payload_digest.clone(),
            )
            .map_err(|_| AuthorizedEffectDriverError::BeforeProviderContact)?;
            self.provider
                .custody
                .bind_job(&JointTextJobBindingV1 {
                    schema_version: 1,
                    provider_scope: self.provider.provider_scope.clone(),
                    run_id: request.intent.run_id.clone(),
                    step_id: request.intent.step_id.clone(),
                    identity,
                    input,
                })
                .map_err(|_| AuthorizedEffectDriverError::BeforeProviderContact)?;
        }
        self.driver.dispatch(request)
    }
}

fn action_for_operation(operation: &str) -> Result<JointTextTaskFlowActionV1, AgentdError> {
    match operation {
        "joint.text.training.start" => Ok(JointTextTaskFlowActionV1::Start),
        "joint.text.training.cancel" => Ok(JointTextTaskFlowActionV1::Cancel),
        _ => Err(AgentdError::Invalid(
            "operation is not registered on the Joint host".to_string(),
        )),
    }
}

impl AgentdAutomationEffectHost {
    pub(super) async fn execute_joint_text(
        &self,
        store: &AutomationStore,
        provider: &JointTextProvider,
        request: AuthorizedEffectDispatchRequest<'_>,
    ) -> Result<TaskFlowStepReceipt, AgentdError> {
        let gate = self.pq_gate.as_ref().ok_or_else(|| {
            AgentdError::GenerationFenced(
                "Joint requires its original PQ FinalUse owner".to_string(),
            )
        })?;
        let lease = gate
            .authenticate(
                &self.authority,
                &self.revocations_file,
                request.signed_grant,
            )
            .map_err(|error| AgentdError::GenerationFenced(error.to_string()))?;
        let mut driver = provider.driver_with_lease(
            &request,
            lease,
            Arc::clone(gate),
            self.authority.clone(),
            self.revocations_file.clone(),
        )?;
        store
            .execute_authorized_taskflow_effect(&self.authority, &mut driver, request)
            .await
            .map_err(|error| {
                AgentdError::Protocol(format!(
                    "automation Joint authorized effect dispatch: {error}"
                ))
            })
    }

    pub(super) fn lookup_joint_text(
        &self,
        provider: &JointTextProvider,
        pending: &AuthorizedEffectPending,
    ) -> Result<Option<AuthorizedEffectProviderReceipt>, AgentdError> {
        let gate = self.pq_gate.clone().ok_or_else(|| {
            AgentdError::GenerationFenced(
                "Joint recovery requires its original PQ owner".to_string(),
            )
        })?;
        let authority = self.authority.clone();
        let revocations = self.revocations_file.clone();
        match provider.lookup(pending, move || {
            gate.refresh(&authority, &revocations)
                .map_err(|_| JointTextSupervisorError::BeforeContact)
        }) {
            AuthorizedProviderEffectLookup::Observed(receipt) => Ok(Some(receipt)),
            AuthorizedProviderEffectLookup::Unresolved => Ok(None),
            AuthorizedProviderEffectLookup::ProvenAbsent { .. } => Err(AgentdError::Protocol(
                "Joint status lookup cannot prove absence".to_string(),
            )),
        }
    }
}
