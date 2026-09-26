use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_automation::AuthorizedEffectIntent;
use codex_hepta_automation::AutomationCalendarScheduleV2;
use codex_hepta_automation::AutomationMissedRunPolicy;
use codex_hepta_automation::AutomationOverlapPolicy;
use codex_hepta_automation::AutomationTask;
use codex_hepta_automation::AutomationTaskDraft;
use codex_hepta_automation::AutomationTaskId;
use codex_hepta_automation::ProductEffectPreparationV1;
use codex_hepta_automation::ThresholdCircuitDecisionV1;
use codex_hepta_automation::ThresholdCircuitInvocationV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_uds::UnixStream;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::time::timeout;

use crate::AGENTD_CONTROL_OVERLOAD_FRAME;
use crate::AGENTD_CONTROL_SCHEMA_VERSION;
use crate::AGENTD_OVERLOAD_RETRY_AFTER_MS;
use crate::AgentContextAttachment;
use crate::AgentRunCancellation;
use crate::AgentRunPhase;
use crate::AgentRunReceipt;
use crate::AgentRunSnapshot;
use crate::AgentdCapabilitySet;
use crate::AgentdError;
use crate::AgentdPayload;
use crate::AgentdRequest;
use crate::AgentdResponse;
use crate::AuthBusObjectiveIngress;
use crate::AutomationEffectReconcileSnapshot;
use crate::AutomationEffectSnapshot;
use crate::EventBatch;
use crate::HealthSnapshot;
use crate::LifecycleSnapshot;
use crate::MAX_CONTROL_FRAME_BYTES;
use crate::MemoryFederationCapabilityId;
use crate::MemoryFederationCapabilitySnapshot;
use crate::MemoryFederationScopeKind;
use crate::ObjectiveStartOutcome;
use crate::SessionIngress;

pub struct AgentdClient {
    socket_path: PathBuf,
    expected_agent_id: AgentId,
    spawn_generation: u64,
    next_request_id: AtomicU64,
    timeout: Duration,
}

impl AgentdClient {
    pub fn new(
        socket_path: PathBuf,
        expected_agent_id: AgentId,
        spawn_generation: u64,
    ) -> Result<Self, AgentdError> {
        if !socket_path.is_absolute() || spawn_generation == 0 {
            return Err(AgentdError::Invalid(
                "agentd client requires an absolute socket and non-zero spawn generation"
                    .to_string(),
            ));
        }
        Ok(Self {
            socket_path,
            expected_agent_id,
            spawn_generation,
            next_request_id: AtomicU64::new(1),
            timeout: Duration::from_secs(2),
        })
    }

    pub async fn capabilities(&self) -> Result<AgentdCapabilitySet, AgentdError> {
        match self
            .send(AgentdRequest::capabilities(
                self.request_id(),
                self.spawn_generation,
            ))
            .await?
            .payload
        {
            AgentdPayload::Capabilities(capabilities) => {
                capabilities.validate().map_err(AgentdError::Protocol)?;
                Ok(capabilities)
            }
            payload => unexpected(payload),
        }
    }

    pub async fn health(&self) -> Result<HealthSnapshot, AgentdError> {
        match self
            .send(AgentdRequest::health(
                self.request_id(),
                self.spawn_generation,
            ))
            .await?
            .payload
        {
            AgentdPayload::Health(snapshot) => Ok(snapshot),
            payload => unexpected(payload),
        }
    }

    pub async fn lifecycle(&self) -> Result<LifecycleSnapshot, AgentdError> {
        match self
            .send(AgentdRequest::lifecycle(
                self.request_id(),
                self.spawn_generation,
            ))
            .await?
            .payload
        {
            AgentdPayload::Lifecycle(snapshot) => Ok(snapshot),
            payload => unexpected(payload),
        }
    }

    pub async fn session_ingress(&self) -> Result<SessionIngress, AgentdError> {
        match self
            .send(AgentdRequest::session_ingress(
                self.request_id(),
                self.spawn_generation,
            ))
            .await?
            .payload
        {
            AgentdPayload::SessionIngress(ingress) => Ok(ingress),
            payload => unexpected(payload),
        }
    }

    pub async fn objective_start(
        &self,
        request: AuthBusObjectiveIngress,
    ) -> Result<ObjectiveStartOutcome, AgentdError> {
        match self
            .send(AgentdRequest::objective_start(
                self.request_id(),
                self.spawn_generation,
                request,
            ))
            .await?
            .payload
        {
            AgentdPayload::ObjectiveRun(receipt) => Ok(ObjectiveStartOutcome::Admitted { receipt }),
            AgentdPayload::ObjectiveConflict {
                run_id,
                conflict_digest,
            } => Ok(ObjectiveStartOutcome::Conflict {
                run_id,
                conflict_digest,
            }),
            payload => unexpected(payload),
        }
    }

    /// Read verified context through this exact generation's canonical owner.
    pub async fn cognitive_context(
        &self,
        query: String,
        limit: u16,
    ) -> Result<crate::CognitiveContextSnapshot, AgentdError> {
        match self
            .send(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: self.request_id(),
                spawn_generation: self.spawn_generation,
                method: crate::AgentdMethod::CognitiveContext { query, limit },
            })
            .await?
            .payload
        {
            AgentdPayload::CognitiveContext(snapshot) => Ok(snapshot),
            payload => unexpected(payload),
        }
    }

    /// Reacquire the owner cut immediately before physical model attachment.
    /// Success is only a freshness observation for this instant, not a lease.
    pub async fn revalidate_cognitive_context(
        &self,
        snapshot: &crate::CognitiveContextSnapshot,
    ) -> Result<crate::CognitiveContextRevalidation, AgentdError> {
        match self
            .send(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: self.request_id(),
                spawn_generation: self.spawn_generation,
                method: crate::AgentdMethod::CognitiveContextRevalidate {
                    snapshot_digest: snapshot.snapshot_digest.clone(),
                    read_digest: snapshot.read_digest.clone(),
                    omitted_records: snapshot.omitted_records,
                    items: snapshot.items.clone(),
                    plan: snapshot.plan.clone(),
                },
            })
            .await?
            .payload
        {
            AgentdPayload::CognitiveContextRevalidated(revalidation) => Ok(revalidation),
            payload => unexpected(payload),
        }
    }

    /// Submit text signed by a separately trusted owner-configured issuer.
    pub async fn submit_authbus_text(
        &self,
        request: crate::AuthBusTextIngress,
    ) -> Result<crate::AuthBusTextStatus, AgentdError> {
        match self
            .send(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: self.request_id(),
                spawn_generation: self.spawn_generation,
                method: crate::AgentdMethod::AuthBusText { request },
            })
            .await?
            .payload
        {
            AgentdPayload::AuthBusTextStatus(status) => Ok(status),
            payload => unexpected(payload),
        }
    }

    /// Observe queue-admission state; this never reports model/effect completion.
    pub async fn authbus_text_status(
        &self,
        delivery_id: String,
    ) -> Result<crate::AuthBusTextStatus, AgentdError> {
        match self
            .send(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: self.request_id(),
                spawn_generation: self.spawn_generation,
                method: crate::AgentdMethod::AuthBusTextStatus { delivery_id },
            })
            .await?
            .payload
        {
            AgentdPayload::AuthBusTextStatus(status) => Ok(status),
            payload => unexpected(payload),
        }
    }

    pub async fn append_kernel_evidence(
        &self,
        request: crate::KernelEvidenceAppendIngress,
    ) -> Result<codex_hepta_evidence::EvidenceId, AgentdError> {
        let result = match self
            .send(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: self.request_id(),
                spawn_generation: self.spawn_generation,
                method: crate::AgentdMethod::KernelEvidenceAppend { request },
            })
            .await?
            .payload
        {
            AgentdPayload::KernelEvidenceResult(result) => result,
            payload => return unexpected(payload),
        };
        Ok(serde_json::from_str(&result.json)?)
    }

    pub async fn query_kernel_evidence(
        &self,
        request: crate::KernelEvidenceQueryV1,
    ) -> Result<Vec<codex_hepta_evidence::EvidenceReferenceV1>, AgentdError> {
        let result = match self
            .send(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: self.request_id(),
                spawn_generation: self.spawn_generation,
                method: crate::AgentdMethod::KernelEvidenceQuery { request },
            })
            .await?
            .payload
        {
            AgentdPayload::KernelEvidenceResult(result) => result,
            payload => return unexpected(payload),
        };
        Ok(serde_json::from_str(&result.json)?)
    }

    pub async fn verify_kernel_evidence(
        &self,
        request: crate::KernelEvidenceVerifyV1,
    ) -> Result<codex_hepta_evidence::EvidenceDispositionV1, AgentdError> {
        let result = match self
            .send(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: self.request_id(),
                spawn_generation: self.spawn_generation,
                method: crate::AgentdMethod::KernelEvidenceVerify { request },
            })
            .await?
            .payload
        {
            AgentdPayload::KernelEvidenceResult(result) => result,
            payload => return unexpected(payload),
        };
        Ok(serde_json::from_str(&result.json)?)
    }

    pub async fn events(&self, after_cursor: u64, limit: u16) -> Result<EventBatch, AgentdError> {
        match self
            .send(AgentdRequest::events(
                self.request_id(),
                self.spawn_generation,
                after_cursor,
                limit,
            ))
            .await?
            .payload
        {
            AgentdPayload::Events(events) => Ok(events),
            payload => unexpected(payload),
        }
    }

    pub async fn run_start(
        &self,
        snapshot: AgentRunSnapshot,
    ) -> Result<AgentRunReceipt, AgentdError> {
        match self
            .send(AgentdRequest::run_start(
                self.request_id(),
                self.spawn_generation,
                snapshot,
            ))
            .await?
            .payload
        {
            AgentdPayload::RunReceipt(receipt) => Ok(receipt),
            payload => unexpected(payload),
        }
    }

    pub async fn run_attach_context(
        &self,
        expected_revision: u64,
        attachment: AgentContextAttachment,
    ) -> Result<AgentRunReceipt, AgentdError> {
        match self
            .send(AgentdRequest::run_attach_context(
                self.request_id(),
                self.spawn_generation,
                expected_revision,
                attachment,
            ))
            .await?
            .payload
        {
            AgentdPayload::RunReceipt(receipt) => Ok(receipt),
            payload => unexpected(payload),
        }
    }

    pub async fn run_mark_dispatched(
        &self,
        run_id: String,
        expected_revision: u64,
    ) -> Result<AgentRunReceipt, AgentdError> {
        match self
            .send(AgentdRequest::run_mark_dispatched(
                self.request_id(),
                self.spawn_generation,
                run_id,
                expected_revision,
            ))
            .await?
            .payload
        {
            AgentdPayload::RunReceipt(receipt) => Ok(receipt),
            payload => unexpected(payload),
        }
    }

    pub async fn run_cancel(
        &self,
        run_id: String,
        expected_revision: u64,
        reason: String,
    ) -> Result<AgentRunCancellation, AgentdError> {
        match self
            .send(AgentdRequest::run_cancel(
                self.request_id(),
                self.spawn_generation,
                run_id,
                expected_revision,
                reason,
            ))
            .await?
            .payload
        {
            AgentdPayload::RunCancellation(cancellation) => Ok(cancellation),
            payload => unexpected(payload),
        }
    }

    pub async fn run_observe_terminal(
        &self,
        run_id: String,
        expected_revision: u64,
        phase: AgentRunPhase,
        terminal_observed: bool,
    ) -> Result<AgentRunReceipt, AgentdError> {
        match self
            .send(AgentdRequest::run_observe_terminal(
                self.request_id(),
                self.spawn_generation,
                run_id,
                expected_revision,
                phase,
                terminal_observed,
            ))
            .await?
            .payload
        {
            AgentdPayload::RunReceipt(receipt) => Ok(receipt),
            payload => unexpected(payload),
        }
    }

    pub async fn run_status(&self, run_id: String) -> Result<Option<AgentRunReceipt>, AgentdError> {
        match self
            .send(AgentdRequest::run_status(
                self.request_id(),
                self.spawn_generation,
                run_id,
            ))
            .await?
            .payload
        {
            AgentdPayload::RunStatus { run } => Ok(run),
            payload => unexpected(payload),
        }
    }

    pub async fn run_release_closed(
        &self,
        run_id: String,
        expected_revision: u64,
    ) -> Result<AgentRunReceipt, AgentdError> {
        match self
            .send(AgentdRequest::run_release_closed(
                self.request_id(),
                self.spawn_generation,
                run_id,
                expected_revision,
            ))
            .await?
            .payload
        {
            AgentdPayload::RunReceipt(receipt) => Ok(receipt),
            payload => unexpected(payload),
        }
    }

    pub async fn automation_create(
        &self,
        draft: AutomationTaskDraft,
    ) -> Result<AutomationTask, AgentdError> {
        match self
            .send(AgentdRequest::automation_create(
                self.request_id(),
                self.spawn_generation,
                draft,
            ))
            .await?
            .payload
        {
            AgentdPayload::AutomationTask(task) => Ok(task),
            payload => unexpected(payload),
        }
    }

    pub async fn automation_create_calendar_v2(
        &self,
        draft: AutomationTaskDraft,
        schedule: AutomationCalendarScheduleV2,
        missed_run: AutomationMissedRunPolicy,
        overlap: AutomationOverlapPolicy,
    ) -> Result<AutomationTask, AgentdError> {
        let capabilities = self.capabilities().await?;
        let supported = capabilities.capabilities.iter().any(|capability| {
            capability.id == crate::AGENTD_CAPABILITY_AUTOMATION_CALENDAR_V2
                && capability.major == 1
        });
        if !supported {
            return Err(AgentdError::Protocol(
                "agentd does not advertise Calendar V2 automation control".to_string(),
            ));
        }
        match self
            .send(AgentdRequest::automation_create_calendar_v2(
                self.request_id(),
                self.spawn_generation,
                draft,
                schedule,
                missed_run,
                overlap,
            ))
            .await?
            .payload
        {
            AgentdPayload::AutomationTask(task) => Ok(task),
            payload => unexpected(payload),
        }
    }

    pub async fn automation_run_threshold_circuit(
        &self,
        invocation: ThresholdCircuitInvocationV1,
    ) -> Result<ThresholdCircuitDecisionV1, AgentdError> {
        let capabilities = self.capabilities().await?;
        let supported = capabilities.capabilities.iter().any(|capability| {
            capability.id == crate::AGENTD_CAPABILITY_AUTOMATION_THRESHOLD_CIRCUIT
                && capability.major == 1
        });
        if !supported {
            return Err(AgentdError::Protocol(
                "agentd does not advertise threshold-circuit control".to_string(),
            ));
        }
        match self
            .send(AgentdRequest::automation_run_threshold_circuit(
                self.request_id(),
                self.spawn_generation,
                invocation,
            ))
            .await?
            .payload
        {
            AgentdPayload::AutomationThresholdCircuit(decision) => Ok(decision),
            payload => unexpected(payload),
        }
    }

    pub async fn automation_prepare_effect(
        &self,
        operation_id: String,
        wire_payload: &[u8],
        expected_predecessor_digest: Option<codex_hepta_contracts::Sha256Digest>,
        compensation_for: Option<String>,
    ) -> Result<ProductEffectPreparationV1, AgentdError> {
        if wire_payload.is_empty() || wire_payload.len() > crate::MAX_AUTOMATION_EFFECT_WIRE_BYTES {
            return Err(AgentdError::Invalid(
                "automation effect wire payload is empty or too large".to_string(),
            ));
        }
        let capabilities = self.capabilities().await?;
        let supported = capabilities.capabilities.iter().any(|capability| {
            capability.id == crate::AGENTD_CAPABILITY_AUTOMATION_EFFECT_PREPARATION
                && capability.major == 1
        });
        if !supported {
            return Err(AgentdError::Protocol(
                "agentd does not advertise automation external-effect control".to_string(),
            ));
        }
        match self
            .send(AgentdRequest::automation_prepare_effect(
                self.request_id(),
                self.spawn_generation,
                operation_id,
                encode_hex(wire_payload),
                expected_predecessor_digest,
                compensation_for,
            ))
            .await?
            .payload
        {
            AgentdPayload::AutomationEffectPreparation(preparation) => Ok(*preparation),
            payload => unexpected(payload),
        }
    }

    pub async fn automation_execute_effect(
        &self,
        intent: AuthorizedEffectIntent,
        wire_payload: &[u8],
        signed_grant: SignedFinalUseGrant,
        command_id: String,
    ) -> Result<AutomationEffectSnapshot, AgentdError> {
        if wire_payload.is_empty() || wire_payload.len() > crate::MAX_AUTOMATION_EFFECT_WIRE_BYTES {
            return Err(AgentdError::Invalid(
                "automation effect wire payload is empty or too large".to_string(),
            ));
        }
        let capabilities = self.capabilities().await?;
        let supported = capabilities.capabilities.iter().any(|capability| {
            capability.id == crate::AGENTD_CAPABILITY_AUTOMATION_EXTERNAL_EFFECT
                && capability.major == 1
        });
        if !supported {
            return Err(AgentdError::Protocol(
                "agentd does not advertise automation external-effect control".to_string(),
            ));
        }
        match self
            .send(AgentdRequest::automation_execute_effect(
                self.request_id(),
                self.spawn_generation,
                intent,
                encode_hex(wire_payload),
                signed_grant,
                command_id,
            ))
            .await?
            .payload
        {
            AgentdPayload::AutomationEffect(receipt) => Ok(receipt),
            payload => unexpected(payload),
        }
    }

    pub async fn automation_reconcile_effect(
        &self,
        run_id: String,
        step_id: String,
        attempt: u32,
    ) -> Result<AutomationEffectReconcileSnapshot, AgentdError> {
        let capabilities = self.capabilities().await?;
        let supported = capabilities.capabilities.iter().any(|capability| {
            capability.id == crate::AGENTD_CAPABILITY_AUTOMATION_EXTERNAL_EFFECT
                && capability.major == 1
        });
        if !supported {
            return Err(AgentdError::Protocol(
                "agentd does not advertise automation external-effect control".to_string(),
            ));
        }
        match self
            .send(AgentdRequest::automation_reconcile_effect(
                self.request_id(),
                self.spawn_generation,
                run_id,
                step_id,
                attempt,
            ))
            .await?
            .payload
        {
            AgentdPayload::AutomationEffectReconcile(receipt) => Ok(receipt),
            payload => unexpected(payload),
        }
    }

    pub async fn automation_list(&self, limit: u16) -> Result<Vec<AutomationTask>, AgentdError> {
        match self
            .send(AgentdRequest::automation_list(
                self.request_id(),
                self.spawn_generation,
                limit,
            ))
            .await?
            .payload
        {
            AgentdPayload::AutomationTasks { tasks } => Ok(tasks),
            payload => unexpected(payload),
        }
    }

    pub async fn automation_cancel(
        &self,
        task_id: AutomationTaskId,
    ) -> Result<AutomationTask, AgentdError> {
        match self
            .send(AgentdRequest::automation_cancel(
                self.request_id(),
                self.spawn_generation,
                task_id,
            ))
            .await?
            .payload
        {
            AgentdPayload::AutomationTask(task) => Ok(task),
            payload => unexpected(payload),
        }
    }

    pub async fn automation_set_enabled(
        &self,
        task_id: AutomationTaskId,
        enabled: bool,
        resume_at_ms: Option<u64>,
    ) -> Result<AutomationTask, AgentdError> {
        match self
            .send(AgentdRequest::automation_set_enabled(
                self.request_id(),
                self.spawn_generation,
                task_id,
                enabled,
                resume_at_ms,
            ))
            .await?
            .payload
        {
            AgentdPayload::AutomationTask(task) => Ok(task),
            payload => unexpected(payload),
        }
    }

    pub async fn memory_federation_grant(
        &self,
        consumer_agent_id: AgentId,
        owner_scope: MemoryFederationScopeKind,
        lifetime_seconds: u32,
    ) -> Result<MemoryFederationCapabilitySnapshot, AgentdError> {
        match self
            .send(AgentdRequest::memory_federation_grant(
                self.request_id(),
                self.spawn_generation,
                consumer_agent_id,
                owner_scope,
                lifetime_seconds,
            ))
            .await?
            .payload
        {
            AgentdPayload::MemoryFederationCapability(capability) => Ok(capability),
            payload => unexpected(payload),
        }
    }

    pub async fn memory_federation_revoke(
        &self,
        capability_id: MemoryFederationCapabilityId,
    ) -> Result<MemoryFederationCapabilitySnapshot, AgentdError> {
        match self
            .send(AgentdRequest::memory_federation_revoke(
                self.request_id(),
                self.spawn_generation,
                capability_id,
            ))
            .await?
            .payload
        {
            AgentdPayload::MemoryFederationCapability(capability) => Ok(capability),
            payload => unexpected(payload),
        }
    }

    pub async fn memory_federation_list(
        &self,
        limit: u16,
    ) -> Result<Vec<MemoryFederationCapabilitySnapshot>, AgentdError> {
        match self
            .send(AgentdRequest::memory_federation_list(
                self.request_id(),
                self.spawn_generation,
                limit,
            ))
            .await?
            .payload
        {
            AgentdPayload::MemoryFederationCapabilities { capabilities } => Ok(capabilities),
            payload => unexpected(payload),
        }
    }

    pub async fn memory_federation_status(
        &self,
        capability_id: MemoryFederationCapabilityId,
    ) -> Result<Option<MemoryFederationCapabilitySnapshot>, AgentdError> {
        match self
            .send(AgentdRequest::memory_federation_status(
                self.request_id(),
                self.spawn_generation,
                capability_id,
            ))
            .await?
            .payload
        {
            AgentdPayload::MemoryFederationStatus { capability } => Ok(capability),
            payload => unexpected(payload),
        }
    }

    async fn send(&self, request: AgentdRequest) -> Result<AgentdResponse, AgentdError> {
        let expected_request_id = request.request_id;
        let response_timeout = crate::control_budget::response_timeout(&request.method);
        let stream = timeout(self.timeout, UnixStream::connect(&self.socket_path))
            .await
            .map_err(|_| AgentdError::Protocol("agentd control connect timed out".to_string()))??;
        let (reader, mut writer) = tokio::io::split(stream);
        let mut bytes = serde_json::to_vec(&request)?;
        bytes.push(b'\n');
        if bytes.len() as u64 > MAX_CONTROL_FRAME_BYTES {
            return Err(AgentdError::Protocol(
                "agentd request exceeded frame bound".to_string(),
            ));
        }
        timeout(self.timeout, writer.write_all(&bytes))
            .await
            .map_err(|_| AgentdError::Protocol("agentd control write timed out".to_string()))??;
        let mut reader = BufReader::new(reader).take(MAX_CONTROL_FRAME_BYTES + 1);
        let mut response_bytes = Vec::new();
        let count = timeout(
            response_timeout,
            reader.read_until(b'\n', &mut response_bytes),
        )
        .await
        .map_err(|_| AgentdError::Protocol("agentd control read timed out".to_string()))??;
        if count == 0 || count as u64 > MAX_CONTROL_FRAME_BYTES || !response_bytes.ends_with(b"\n")
        {
            return Err(AgentdError::Protocol(
                "agentd returned an invalid bounded response frame".to_string(),
            ));
        }
        if response_bytes.as_slice() == AGENTD_CONTROL_OVERLOAD_FRAME {
            return Err(AgentdError::Overloaded {
                retry_after_ms: AGENTD_OVERLOAD_RETRY_AFTER_MS,
            });
        }
        let response: AgentdResponse = serde_json::from_slice(&response_bytes)?;
        if response.schema_version != AGENTD_CONTROL_SCHEMA_VERSION
            || response.request_id != expected_request_id
            || response.agent_id != self.expected_agent_id
            || response.spawn_generation != self.spawn_generation
        {
            return Err(AgentdError::Protocol(
                "agentd response identity does not match request".to_string(),
            ));
        }
        Ok(response)
    }

    fn request_id(&self) -> u64 {
        self.next_request_id.fetch_add(1, Ordering::Relaxed)
    }
}

fn encode_hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len().saturating_mul(2));
    for byte in bytes {
        output.push(char::from(HEX[usize::from(byte >> 4)]));
        output.push(char::from(HEX[usize::from(byte & 0x0f)]));
    }
    output
}

fn unexpected<T>(payload: AgentdPayload) -> Result<T, AgentdError> {
    match payload {
        AgentdPayload::Error { code, message } => Err(AgentdError::Protocol(format!(
            "agentd rejected request ({code}): {message}"
        ))),
        other => Err(AgentdError::Protocol(format!(
            "agentd returned unexpected payload {other:?}"
        ))),
    }
}
