//! Concrete owner registration and completion at the already opened host.
//! The in-process bridge supplies original objects; no control payload can
//! register a checkpoint implementation or reinterpret a Ledger run as a job.

use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::JointTextInputRefV1;
use codex_hepta_automation::JointTextJobIdentityV1;

use crate::AgentdError;
use crate::PreparedJointTextTrainingRequestV1;
use crate::automation_joint_text_inputs::JointTextCompletedOutputV1;
use crate::joint_text_training_owner::JointTextCheckpointBindingV1;

use super::AgentdAutomationEffectHost;
use super::EffectProvider;
use super::joint::JointTextProvider;

// Same finite bound as the original bridge queue; entries are never evicted to
// admit another owner. Restart re-registration still restores the actual head.
const MAX_REGISTERED_INPUTS: usize = 64;

impl JointTextProvider {
    pub(super) fn checkpoint_for(
        &self,
        input: &JointTextInputRefV1,
    ) -> Result<Arc<JointTextCheckpointBindingV1>, AgentdError> {
        self.checkpoints
            .lock()
            .map_err(|_| {
                AgentdError::Protocol("Joint original owner registry poisoned".to_string())
            })?
            .get(input.input_id.as_str())
            .cloned()
            .ok_or_else(|| {
                AgentdError::GenerationFenced(
                    "Joint input lacks its concrete registered owner".to_string(),
                )
            })
    }
}

impl AgentdAutomationEffectHost {
    pub(crate) fn stage_joint_text_input(
        &self,
        prepared: &PreparedJointTextTrainingRequestV1,
        predecessor: &[u8],
        checkpoint: Arc<JointTextCheckpointBindingV1>,
    ) -> Result<JointTextInputRefV1, AgentdError> {
        let EffectProvider::JointText(provider) = &self.adapter else {
            return Err(AgentdError::Invalid(
                "Joint custody requires its admitted provider".to_string(),
            ));
        };
        if self.pq_gate.is_none()
            || prepared.iteration_snapshot() != checkpoint.iteration_snapshot()
            || prepared.iteration_snapshot().request.agent_id.as_str() != self.agent_id.as_str()
        {
            return Err(AgentdError::GenerationFenced(
                "Joint prepared request differs from its original owner".to_string(),
            ));
        }
        self.refresh_revocations()?;
        checkpoint.require_current()?;
        let expected = prepared.input_reference(predecessor).map_err(|error| {
            AgentdError::Invalid(format!("Joint original prepared input: {error}"))
        })?;
        if &expected.manifest.worker_execution_source_digest
            != provider.source_manifest.execution_digest()
        {
            return Err(AgentdError::GenerationFenced(
                "Joint request selects another execution source".to_string(),
            ));
        }
        provider.verify_sources_and_custody(None).map_err(|_| {
            AgentdError::GenerationFenced("Joint deployment or custody changed".to_string())
        })?;
        let mut registered = provider.checkpoints.lock().map_err(|_| {
            AgentdError::Protocol("Joint original owner registry poisoned".to_string())
        })?;
        if let Some(existing) = registered.get(expected.input_id.as_str()) {
            if !Arc::ptr_eq(existing, &checkpoint) {
                return Err(AgentdError::GenerationFenced(
                    "Joint input already has another concrete owner".to_string(),
                ));
            }
        } else if registered.len() >= MAX_REGISTERED_INPUTS {
            return Err(AgentdError::Invalid(
                "Joint original owner registry is full".to_string(),
            ));
        }
        let input = provider.custody.stage(prepared, predecessor)?;
        if input != expected {
            return Err(AgentdError::Protocol(
                "Joint custody changed the prepared descriptor".to_string(),
            ));
        }
        provider
            .verify_sources_and_custody(Some(&input))
            .map_err(|_| {
                AgentdError::GenerationFenced("Joint staged source or custody changed".to_string())
            })?;
        checkpoint.require_current()?;
        self.refresh_revocations()?;
        registered.insert(input.input_id.as_str().to_string(), checkpoint);
        Ok(input)
    }

    pub(crate) async fn read_joint_text_training_output(
        &self,
        store: &AutomationStore,
        job: &JointTextJobIdentityV1,
        input: &JointTextInputRefV1,
        now_ms: u64,
    ) -> Result<JointTextCompletedOutputV1, AgentdError> {
        let EffectProvider::JointText(provider) = &self.adapter else {
            return Err(AgentdError::Invalid(
                "Joint output requires its admitted provider".to_string(),
            ));
        };
        if self.pq_gate.is_none() {
            return Err(AgentdError::GenerationFenced(
                "Joint completion requires its original PQ owner".to_string(),
            ));
        }
        self.refresh_revocations()?;
        let checkpoint = provider.checkpoint_for(input)?;
        checkpoint.require_current()?;
        let binding = provider.custody.read_bound_job(input)?;
        if binding.identity != *job || binding.provider_scope != provider.provider_scope {
            return Err(AgentdError::GenerationFenced(
                "Joint output is not the originally authorized logical job".to_string(),
            ));
        }
        let run = store
            .taskflow_run(&binding.run_id)
            .await
            .map_err(|error| {
                AgentdError::Protocol(format!("Joint original TaskFlow run: {error}"))
            })?
            .ok_or_else(|| {
                AgentdError::GenerationFenced("Joint original TaskFlow run is missing".to_string())
            })?;
        let fence = self.current_fence(&run, now_ms)?;
        provider
            .verify_sources_and_custody(Some(input))
            .map_err(|_| {
                AgentdError::GenerationFenced(
                    "Joint completion source or custody changed".to_string(),
                )
            })?;
        let output = provider.custody.read_completed(
            job,
            input,
            &provider.config.root_identity,
            checkpoint
                .iteration_snapshot()
                .request
                .budget
                .maximum_training_milliseconds,
            checkpoint
                .iteration_snapshot()
                .request
                .budget
                .maximum_artifact_bytes,
        )?;
        provider
            .source_manifest
            .verify_reservation(
                &provider.config.repository_root,
                &provider.config.python_executable,
                &provider.config.python_sha256,
                &output.reservation,
            )
            .map_err(|error| {
                AgentdError::GenerationFenced(format!("Joint original execution capture: {error}"))
            })?;
        if provider.custody.read_bound_job(input)? != binding {
            return Err(AgentdError::GenerationFenced(
                "Joint original job binding changed".to_string(),
            ));
        }
        let fresh = store
            .taskflow_run(&binding.run_id)
            .await
            .map_err(|error| AgentdError::Protocol(format!("Joint current TaskFlow run: {error}")))?
            .ok_or_else(|| {
                AgentdError::GenerationFenced("Joint TaskFlow run disappeared".to_string())
            })?;
        let current_ms = u64::try_from(
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_err(|_| {
                    AgentdError::Protocol("Joint completion clock precedes Unix epoch".to_string())
                })?
                .as_millis(),
        )
        .map_err(|_| AgentdError::Protocol("Joint completion clock overflow".to_string()))?;
        if current_ms < now_ms || self.current_fence(&fresh, current_ms)? != fence {
            return Err(AgentdError::GenerationFenced(
                "Joint TaskFlow owner fence changed during completion".to_string(),
            ));
        }
        checkpoint.require_current()?;
        self.refresh_revocations()?;
        provider
            .verify_sources_and_custody(Some(input))
            .map_err(|_| {
                AgentdError::GenerationFenced(
                    "Joint completed source or custody changed".to_string(),
                )
            })?;
        Ok(output)
    }
}
