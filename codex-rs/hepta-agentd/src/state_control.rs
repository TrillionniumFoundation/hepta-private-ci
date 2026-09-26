//! Domain control dispatch kept separate from process lifecycle state.

use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_automation::AutomationError;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_automation::TaskFlowStepObservation;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStoreError;
use codex_hepta_memory::FederationCapabilityId;
use codex_hepta_memory::FederationCapabilityState;
use codex_hepta_memory::FederationCapabilityStatus;
use codex_hepta_memory::FederationGrantRequest;
use codex_hepta_memory::FederationGrantScope;
use codex_hepta_memory::MAX_FEDERATION_GRANT_LIFETIME_SECONDS;
use codex_hepta_memory::workspace_binding_digest;

use crate::AgentdError;
use crate::AgentdPayload;
use crate::AgentdResponse;
use crate::HealthSnapshot;
use crate::LifecycleSnapshot;
use crate::SessionIngress;
use crate::SessionTransport;
use crate::cognitive_context::CognitiveContextError;

use super::AgentdState;
use super::poisoned_state;
use super::run_error;

const AUTOMATION_THRESHOLD_CIRCUIT_LEASE_MS: u64 = 60_000;
const AUTOMATION_UNAVAILABLE_CODE: &str = "automation_unavailable";
const AUTOMATION_UNAVAILABLE_MESSAGE: &str =
    "this Agent's private automation storage is unavailable";
const AUTOMATION_EFFECT_UNAVAILABLE_CODE: &str = "automation_effect_unavailable";
const AUTOMATION_EFFECT_UNAVAILABLE_MESSAGE: &str =
    "this Agent generation has no verified automation effect host";
const COGNITIVE_CONTROL_UNAVAILABLE_CODE: &str = "cognitive_control_unavailable";
const COGNITIVE_CONTROL_UNAVAILABLE_MESSAGE: &str =
    "this Agent's private cognitive control storage is unavailable";
const COGNITIVE_READ_UNAVAILABLE_CODE: &str = "cognitive_read_unavailable";

impl AgentdState {
    pub(crate) async fn response(
        &self,
        request_id: u64,
        spawn_generation: u64,
        method: crate::AgentdMethod,
    ) -> Result<AgentdResponse, AgentdError> {
        if spawn_generation != self.identity.spawn_generation {
            return Err(AgentdError::GenerationFenced(format!(
                "request spawn generation {spawn_generation} does not match {}",
                self.identity.spawn_generation
            )));
        }
        self.refresh_generation()?;
        let (
            current_generation,
            lifecycle,
            app_server_ready,
            critical_stores_ready,
            revocation_ready,
            required_ports_ready,
            admission_open,
            fenced,
        ) = {
            let runtime = self.runtime.lock().map_err(poisoned_state)?;
            (
                runtime.current_generation,
                runtime.lifecycle,
                runtime.app_server_ready,
                runtime.critical_stores_ready,
                runtime.revocation_ready,
                runtime.required_ports_ready,
                runtime.admission_open,
                runtime.fenced,
            )
        };
        let automation = self.automation.lock().map_err(poisoned_state)?.clone();
        let cognitive = self.cognitive.lock().map_err(poisoned_state)?.clone();
        // Automation remains an explicitly optional plane and therefore does
        // not gate core Agent readiness. The required cognitive owner is
        // represented by critical_stores_ready, which is frozen only after
        // owner-local startup completes under the generation fence.
        let payload = match method {
            crate::AgentdMethod::Capabilities => {
                let mut capabilities = vec![
                    crate::AgentdCapability::new(
                        crate::AGENTD_CAPABILITY_AUTOMATION_CALENDAR_V2,
                        1,
                        0,
                    )
                    .map_err(AgentdError::Protocol)?,
                ];
                capabilities.push(
                    crate::AgentdCapability::new(
                        crate::AGENTD_CAPABILITY_AUTOMATION_THRESHOLD_CIRCUIT,
                        1,
                        0,
                    )
                    .map_err(AgentdError::Protocol)?,
                );
                if self.automation_effect_host().is_some() {
                    capabilities.push(
                        crate::AgentdCapability::new(
                            crate::AGENTD_CAPABILITY_AUTOMATION_EFFECT_PREPARATION,
                            1,
                            0,
                        )
                        .map_err(AgentdError::Protocol)?,
                    );
                    capabilities.push(
                        crate::AgentdCapability::new(
                            crate::AGENTD_CAPABILITY_AUTOMATION_EXTERNAL_EFFECT,
                            1,
                            0,
                        )
                        .map_err(AgentdError::Protocol)?,
                    );
                }
                if self.evidence.get().is_some() {
                    capabilities.push(
                        crate::AgentdCapability::new("kernel.evidence", 1, 0)
                            .map_err(AgentdError::Protocol)?,
                    );
                }
                capabilities.push(
                    crate::AgentdCapability::new(
                        crate::COGNITIVE_CONTEXT_REVALIDATION_CAPABILITY,
                        1,
                        0,
                    )
                    .map_err(AgentdError::Protocol)?,
                );
                capabilities.push(
                    crate::AgentdCapability::new(
                        crate::AGENTD_RUN_LIFECYCLE_CAPABILITY_ID,
                        crate::AGENTD_RUN_LIFECYCLE_CAPABILITY_MAJOR,
                        crate::AGENTD_RUN_LIFECYCLE_CAPABILITY_MINOR,
                    )
                    .map_err(AgentdError::Protocol)?,
                );
                if self.objective_runtime.get().is_some() {
                    capabilities.push(
                        crate::AgentdCapability::new("objective.start", 1, 0)
                            .map_err(AgentdError::Protocol)?,
                    );
                }
                if self.canonical_intelligence_enabled() {
                    capabilities.push(
                        crate::AgentdCapability::new(
                            crate::AGENTD_CAPABILITY_CANONICAL_INTELLIGENCE_V1,
                            1,
                            0,
                        )
                        .map_err(AgentdError::Protocol)?,
                    );
                }
                AgentdPayload::Capabilities(
                    crate::AgentdCapabilitySet::new(capabilities).map_err(AgentdError::Protocol)?,
                )
            }
            crate::AgentdMethod::Health => AgentdPayload::Health(HealthSnapshot {
                promotion_ready: matches!(
                    lifecycle,
                    AgentLifecycle::Starting | AgentLifecycle::Running
                ) && app_server_ready
                    && critical_stores_ready
                    && revocation_ready
                    && required_ports_ready
                    && !fenced,
                ready: lifecycle == AgentLifecycle::Running
                    && app_server_ready
                    && critical_stores_ready
                    && revocation_ready
                    && required_ports_ready
                    && admission_open
                    && !fenced,
                fenced,
                lifecycle,
                process_id: std::process::id(),
                workspace: self.identity.workspace.clone(),
                home_root: self.identity.home_root.clone(),
                run_root: self.identity.run_root.clone(),
            }),
            crate::AgentdMethod::Lifecycle => AgentdPayload::Lifecycle(LifecycleSnapshot {
                lifecycle,
                app_server_ready,
                fenced,
            }),
            crate::AgentdMethod::Readiness => AgentdPayload::Readiness(crate::ReadinessSnapshot {
                critical_stores_ready,
                revocation_ready,
                required_ports_ready,
                admission_open,
            }),
            crate::AgentdMethod::Drain => {
                AgentdPayload::Drain(self.request_drain(automation.as_ref()).await?)
            }
            crate::AgentdMethod::SessionIngress => {
                if lifecycle != AgentLifecycle::Running
                    || !app_server_ready
                    || !critical_stores_ready
                    || !revocation_ready
                    || !required_ports_ready
                    || !admission_open
                    || fenced
                {
                    AgentdPayload::Error {
                        code: "not_ready".to_string(),
                        message: "session ingress is unavailable until this generation is ready"
                            .to_string(),
                    }
                } else {
                    AgentdPayload::SessionIngress(SessionIngress {
                        socket_path: self.identity.app_server_socket.clone(),
                        transport: SessionTransport::CodexAppServerWebsocketOverUds,
                    })
                }
            }
            crate::AgentdMethod::ObjectiveStart { request } => {
                let Some(host) = self.objective_runtime.get() else {
                    return self.response_with_payload(
                        request_id,
                        current_generation,
                        AgentdPayload::Error {
                            code: "objective_unavailable".to_string(),
                            message: "no owner objective profile is configured".to_string(),
                        },
                    );
                };
                match host.submit(self, request, current_generation).await? {
                    crate::objective_runtime::ObjectiveStartResult::Admitted(receipt) => {
                        AgentdPayload::ObjectiveRun(receipt)
                    }
                    crate::objective_runtime::ObjectiveStartResult::Conflict {
                        run_id,
                        conflict_digest,
                    } => AgentdPayload::ObjectiveConflict {
                        run_id,
                        conflict_digest,
                    },
                }
            }
            crate::AgentdMethod::AuthBusText { request } => AgentdPayload::AuthBusTextStatus(
                crate::authbus_ingress::submit(self, request).await?,
            ),
            crate::AgentdMethod::AuthBusTextStatus { delivery_id } => {
                AgentdPayload::AuthBusTextStatus(
                    crate::authbus_ingress::status(self, delivery_id).await?,
                )
            }
            crate::AgentdMethod::KernelEvidenceAppend { request } => {
                AgentdPayload::KernelEvidenceResult(
                    crate::evidence_host::append(self, request).await?,
                )
            }
            crate::AgentdMethod::KernelEvidenceQuery { request } => {
                AgentdPayload::KernelEvidenceResult(
                    crate::evidence_host::query(self, request).await?,
                )
            }
            crate::AgentdMethod::KernelEvidenceVerify { request } => {
                AgentdPayload::KernelEvidenceResult(
                    crate::evidence_host::verify(self, request).await?,
                )
            }
            crate::AgentdMethod::CognitiveContext { query, limit } => {
                require_cognitive_control_ready(
                    lifecycle,
                    app_server_ready,
                    critical_stores_ready,
                    revocation_ready,
                    required_ports_ready,
                    admission_open,
                    fenced,
                )?;
                let Some(store) = cognitive else {
                    return self.response_with_payload(
                        request_id,
                        current_generation,
                        cognitive_control_unavailable(),
                    );
                };
                // The model and context plan bind to the body that was launched.
                // Current lifecycle authority remains fenced before and after I/O.
                let result = crate::cognitive_context::read_with_retrieval_context_and_learning(
                    &store,
                    &self.identity.agent_id,
                    self.identity.spawn_generation,
                    &query,
                    limit,
                    self.cognitive_ranker.get(),
                    crate::cognitive_context::RetrievalLearningInputs {
                        current_retrieval: self.cognitive_retrieval_context.get(),
                        learning_sink: self.cognitive_retrieval_learning.get(),
                        request_id: Some(request_id),
                    },
                )
                .await;
                self.refresh_generation()?;
                {
                    let runtime = self.runtime.lock().map_err(poisoned_state)?;
                    require_cognitive_control_ready(
                        runtime.lifecycle,
                        runtime.app_server_ready,
                        runtime.critical_stores_ready,
                        runtime.revocation_ready,
                        runtime.required_ports_ready,
                        runtime.admission_open,
                        runtime.fenced,
                    )?;
                }
                match result {
                    Ok(snapshot) => AgentdPayload::CognitiveContext(snapshot),
                    Err(CognitiveContextError::Store(error)) => {
                        return self.cognitive_error_response(
                            request_id,
                            current_generation,
                            error,
                        );
                    }
                    Err(CognitiveContextError::ReadUnavailable(message)) => AgentdPayload::Error {
                        code: COGNITIVE_READ_UNAVAILABLE_CODE.to_string(),
                        message,
                    },
                    Err(CognitiveContextError::RankerUnavailable) => AgentdPayload::Error {
                        code: "cognitive_ranker_unavailable".to_string(),
                        message: "selected ranker is unavailable; explicit reload required"
                            .to_string(),
                    },
                    Err(CognitiveContextError::RetrievalContextUnavailable) => {
                        AgentdPayload::Error {
                            code: "cognitive_retrieval_context_unavailable".to_string(),
                            message: "selected retrieval context is unavailable or no longer current; explicit reload required".to_string(),
                        }
                    }
                    Err(CognitiveContextError::RetrievalLearningUnavailable) => {
                        AgentdPayload::Error {
                            code: "cognitive_retrieval_learning_unavailable".to_string(),
                            message: "retrieval assignment could not be durably recorded by the learning ledger owner".to_string(),
                        }
                    }
                }
            }
            crate::AgentdMethod::CognitiveContextRevalidate {
                snapshot_digest,
                read_digest,
                omitted_records,
                items,
                plan,
            } => {
                require_cognitive_control_ready(
                    lifecycle,
                    app_server_ready,
                    critical_stores_ready,
                    revocation_ready,
                    required_ports_ready,
                    admission_open,
                    fenced,
                )?;
                let Some(store) = cognitive else {
                    return self.response_with_payload(
                        request_id,
                        current_generation,
                        cognitive_control_unavailable(),
                    );
                };
                let result = crate::cognitive_context::revalidate_with_retrieval_context(
                    store.as_ref(),
                    &self.identity.agent_id,
                    crate::cognitive_context::CognitiveContextRevalidationInput {
                        snapshot_digest: &snapshot_digest,
                        read_digest: &read_digest,
                        omitted_records,
                        items: &items,
                        plan: plan.as_ref(),
                    },
                    self.cognitive_ranker.get(),
                    self.identity.spawn_generation,
                    self.cognitive_retrieval_context.get(),
                )
                .await;
                self.refresh_generation()?;
                {
                    let runtime = self.runtime.lock().map_err(poisoned_state)?;
                    require_cognitive_control_ready(
                        runtime.lifecycle,
                        runtime.app_server_ready,
                        runtime.critical_stores_ready,
                        runtime.revocation_ready,
                        runtime.required_ports_ready,
                        runtime.admission_open,
                        runtime.fenced,
                    )?;
                }
                match result {
                    Ok(revalidation) => AgentdPayload::CognitiveContextRevalidated(revalidation),
                    Err(CognitiveContextError::Store(error)) => {
                        return self.cognitive_error_response(
                            request_id,
                            current_generation,
                            error,
                        );
                    }
                    Err(CognitiveContextError::ReadUnavailable(message)) => AgentdPayload::Error {
                        code: COGNITIVE_READ_UNAVAILABLE_CODE.to_string(),
                        message,
                    },
                    Err(CognitiveContextError::RankerUnavailable) => {
                        return self.response_with_payload(
                            request_id,
                            current_generation,
                            AgentdPayload::Error {
                                code: "cognitive_ranker_unavailable".to_string(),
                                message: "current cognitive ranking artifact is unavailable"
                                    .to_string(),
                            },
                        );
                    }
                    Err(CognitiveContextError::RetrievalContextUnavailable) => {
                        AgentdPayload::Error {
                            code: "cognitive_retrieval_context_unavailable".to_string(),
                            message: "selected retrieval context is unavailable or no longer current; explicit reload required".to_string(),
                        }
                    }
                    Err(CognitiveContextError::RetrievalLearningUnavailable) => {
                        AgentdPayload::Error {
                            code: "cognitive_retrieval_learning_unavailable".to_string(),
                            message: "retrieval assignment could not be durably recorded by the learning ledger owner".to_string(),
                        }
                    }
                }
            }
            crate::AgentdMethod::Events {
                after_cursor,
                limit,
            } => {
                if !(1..=crate::MAX_EVENT_BATCH).contains(&limit) {
                    AgentdPayload::Error {
                        code: "invalid_limit".to_string(),
                        message: "event limit must be between 1 and 256".to_string(),
                    }
                } else {
                    let batch = self
                        .events
                        .lock()
                        .map_err(poisoned_state)?
                        .batch(after_cursor, usize::from(limit));
                    AgentdPayload::Events(batch)
                }
            }
            crate::AgentdMethod::RunStart { snapshot } => {
                require_run_admission_ready(lifecycle, app_server_ready, fenced)?;
                require_current_run_identity(
                    &self.identity,
                    current_generation,
                    snapshot.generation,
                    &snapshot.fence_digest,
                )?;
                let receipt = self
                    .runs
                    .lock()
                    .map_err(poisoned_state)?
                    .start_run(now_ms()?, snapshot.into())
                    .map_err(run_error)?;
                AgentdPayload::RunReceipt(wire_run_receipt(receipt))
            }
            crate::AgentdMethod::RunAttachContext {
                expected_revision,
                attachment,
            } => {
                require_run_admission_ready(lifecycle, app_server_ready, fenced)?;
                require_current_run_identity(
                    &self.identity,
                    current_generation,
                    attachment.generation,
                    &attachment.fence_digest,
                )?;
                let receipt = self
                    .runs
                    .lock()
                    .map_err(poisoned_state)?
                    .attach_context(now_ms()?, expected_revision, attachment.into())
                    .map_err(run_error)?;
                AgentdPayload::RunReceipt(wire_run_receipt(receipt))
            }
            crate::AgentdMethod::RunMarkDispatched {
                run_id,
                expected_revision,
            } => {
                require_run_admission_ready(lifecycle, app_server_ready, fenced)?;
                let receipt = self
                    .runs
                    .lock()
                    .map_err(poisoned_state)?
                    .mark_dispatched(now_ms()?, &run_id, expected_revision)
                    .map_err(run_error)?;
                AgentdPayload::RunReceipt(wire_run_receipt(receipt))
            }
            crate::AgentdMethod::RunCancel {
                run_id,
                expected_revision,
                reason,
            } => {
                require_run_reconciliation_ready(lifecycle, fenced)?;
                let (disposition, receipt) = self
                    .runs
                    .lock()
                    .map_err(poisoned_state)?
                    .cancel_run(now_ms()?, &run_id, expected_revision, &reason)
                    .map_err(run_error)?;
                AgentdPayload::RunCancellation(crate::AgentRunCancellation {
                    disposition: wire_cancellation_disposition(disposition),
                    receipt: wire_run_receipt(receipt),
                })
            }
            crate::AgentdMethod::RunObserveTerminal {
                run_id,
                expected_revision,
                phase,
                terminal_observed,
            } => {
                require_run_reconciliation_ready(lifecycle, fenced)?;
                let receipt = self
                    .runs
                    .lock()
                    .map_err(poisoned_state)?
                    .observe_terminal(
                        &run_id,
                        expected_revision,
                        internal_run_phase(phase),
                        terminal_observed,
                    )
                    .map_err(run_error)?;
                AgentdPayload::RunReceipt(wire_run_receipt(receipt))
            }
            crate::AgentdMethod::RunStatus { run_id } => {
                require_run_reconciliation_ready(lifecycle, fenced)?;
                let run = self
                    .runs
                    .lock()
                    .map_err(poisoned_state)?
                    .run(&run_id)
                    .map(wire_run_receipt);
                AgentdPayload::RunStatus { run }
            }
            crate::AgentdMethod::RunReleaseClosed {
                run_id,
                expected_revision,
            } => {
                require_run_reconciliation_ready(lifecycle, fenced)?;
                let receipt = self
                    .runs
                    .lock()
                    .map_err(poisoned_state)?
                    .remove_closed_run(&run_id, expected_revision)
                    .map_err(run_error)?;
                AgentdPayload::RunReceipt(wire_run_receipt(receipt))
            }
            crate::AgentdMethod::AutomationCreate { draft } => {
                require_automation_ready(
                    lifecycle,
                    app_server_ready,
                    critical_stores_ready,
                    revocation_ready,
                    required_ports_ready,
                    admission_open,
                    fenced,
                )?;
                match automation {
                    Some(store) => self.automation_result(
                        store.create_task(&draft).await,
                        AgentdPayload::AutomationTask,
                    )?,
                    None => automation_unavailable(),
                }
            }
            crate::AgentdMethod::AutomationCreateCalendarV2 {
                draft,
                schedule,
                missed_run,
                overlap,
            } => {
                require_automation_ready(
                    lifecycle,
                    app_server_ready,
                    critical_stores_ready,
                    revocation_ready,
                    required_ports_ready,
                    admission_open,
                    fenced,
                )?;
                match automation {
                    Some(store) => self.automation_result(
                        store
                            .create_calendar_task_v2(&draft, &schedule, missed_run, overlap)
                            .await,
                        AgentdPayload::AutomationTask,
                    )?,
                    None => automation_unavailable(),
                }
            }
            crate::AgentdMethod::AutomationRunThresholdCircuit { invocation } => {
                require_automation_ready(
                    lifecycle,
                    app_server_ready,
                    critical_stores_ready,
                    revocation_ready,
                    required_ports_ready,
                    admission_open,
                    fenced,
                )?;
                let Some(store) = automation.as_ref() else {
                    return self.response_with_payload(
                        request_id,
                        current_generation,
                        automation_unavailable(),
                    );
                };
                let fence = threshold_circuit_fence(
                    &self.identity,
                    current_generation,
                    &invocation.candidate.circuit_digest,
                )?;
                let decision = store
                    .run_threshold_circuit_v1(
                        &invocation,
                        &fence,
                        now_ms()?,
                        AUTOMATION_THRESHOLD_CIRCUIT_LEASE_MS,
                    )
                    .await
                    .map_err(|error| {
                        AgentdError::Protocol(format!("threshold circuit execution: {error}"))
                    })?;
                self.fence_after_durable_change()?;
                AgentdPayload::AutomationThresholdCircuit(decision)
            }
            crate::AgentdMethod::AutomationPrepareEffect {
                operation_id,
                wire_payload_hex,
                expected_predecessor_digest,
                compensation_for,
            } => {
                require_automation_ready(
                    lifecycle,
                    app_server_ready,
                    critical_stores_ready,
                    revocation_ready,
                    required_ports_ready,
                    admission_open,
                    fenced,
                )?;
                let Some(store) = automation.as_ref() else {
                    return self.response_with_payload(
                        request_id,
                        current_generation,
                        automation_unavailable(),
                    );
                };
                let Some(host) = self.automation_effect_host() else {
                    return self.response_with_payload(
                        request_id,
                        current_generation,
                        automation_effect_unavailable(),
                    );
                };
                let wire_payload = decode_effect_wire_hex(&wire_payload_hex)?;
                let preparation = host
                    .prepare(
                        store,
                        operation_id,
                        &wire_payload,
                        expected_predecessor_digest,
                        compensation_for,
                        now_ms()?,
                    )
                    .await?;
                self.fence_after_durable_change()?;
                AgentdPayload::AutomationEffectPreparation(Box::new(preparation))
            }
            crate::AgentdMethod::AutomationExecuteEffect {
                intent,
                wire_payload_hex,
                signed_grant,
                command_id,
            } => {
                require_automation_ready(
                    lifecycle,
                    app_server_ready,
                    critical_stores_ready,
                    revocation_ready,
                    required_ports_ready,
                    admission_open,
                    fenced,
                )?;
                let Some(store) = automation.as_ref() else {
                    return self.response_with_payload(
                        request_id,
                        current_generation,
                        automation_unavailable(),
                    );
                };
                let Some(host) = self.automation_effect_host() else {
                    return self.response_with_payload(
                        request_id,
                        current_generation,
                        automation_effect_unavailable(),
                    );
                };
                let wire_payload = decode_effect_wire_hex(&wire_payload_hex)?;
                let receipt = host
                    .execute(
                        store,
                        &intent,
                        &wire_payload,
                        &signed_grant,
                        &command_id,
                        now_ms()?,
                    )
                    .await?;
                self.fence_after_durable_change()?;
                AgentdPayload::AutomationEffect(effect_snapshot(receipt)?)
            }
            crate::AgentdMethod::AutomationReconcileEffect {
                run_id,
                step_id,
                attempt,
            } => {
                require_automation_recovery_ready(
                    lifecycle,
                    critical_stores_ready,
                    revocation_ready,
                    required_ports_ready,
                    fenced,
                )?;
                let Some(store) = automation.as_ref() else {
                    return self.response_with_payload(
                        request_id,
                        current_generation,
                        automation_unavailable(),
                    );
                };
                let Some(host) = self.automation_effect_host() else {
                    return self.response_with_payload(
                        request_id,
                        current_generation,
                        automation_effect_unavailable(),
                    );
                };
                let result = host
                    .reconcile(store, &run_id, &step_id, attempt, now_ms()?)
                    .await?;
                self.fence_after_durable_change()?;
                let snapshot = match result {
                    crate::automation_effect_host::AgentdAutomationEffectReconcileOutcome::Observed(
                        receipt,
                    ) => crate::AutomationEffectReconcileSnapshot {
                        state: crate::AutomationEffectReconcileState::Terminal,
                        effect: Some(effect_snapshot(*receipt)?),
                    },
                    crate::automation_effect_host::AgentdAutomationEffectReconcileOutcome::Indeterminate => {
                        crate::AutomationEffectReconcileSnapshot {
                            state: crate::AutomationEffectReconcileState::Indeterminate,
                            effect: None,
                        }
                    }
                    crate::automation_effect_host::AgentdAutomationEffectReconcileOutcome::ProvenAbsent => {
                        crate::AutomationEffectReconcileSnapshot {
                            state: crate::AutomationEffectReconcileState::ProvenAbsent,
                            effect: None,
                        }
                    }
                };
                AgentdPayload::AutomationEffectReconcile(snapshot)
            }
            crate::AgentdMethod::AutomationList { limit } => {
                require_automation_ready(
                    lifecycle,
                    app_server_ready,
                    critical_stores_ready,
                    revocation_ready,
                    required_ports_ready,
                    admission_open,
                    fenced,
                )?;
                if !(1..=256).contains(&limit) {
                    return Err(AgentdError::Invalid(
                        "automation list limit must be between 1 and 256".to_string(),
                    ));
                }
                match automation {
                    Some(store) => self
                        .automation_result(store.list_tasks(usize::from(limit)).await, |tasks| {
                            AgentdPayload::AutomationTasks { tasks }
                        })?,
                    None => automation_unavailable(),
                }
            }
            crate::AgentdMethod::AutomationCancel { task_id } => {
                require_automation_ready(
                    lifecycle,
                    app_server_ready,
                    critical_stores_ready,
                    revocation_ready,
                    required_ports_ready,
                    admission_open,
                    fenced,
                )?;
                match automation {
                    Some(store) => self.automation_result(
                        store.cancel_task(task_id, now_ms()?).await,
                        AgentdPayload::AutomationTask,
                    )?,
                    None => automation_unavailable(),
                }
            }
            crate::AgentdMethod::AutomationSetEnabled {
                task_id,
                enabled,
                resume_at_ms,
            } => {
                require_automation_ready(
                    lifecycle,
                    app_server_ready,
                    critical_stores_ready,
                    revocation_ready,
                    required_ports_ready,
                    admission_open,
                    fenced,
                )?;
                match automation {
                    Some(store) => self.automation_result(
                        store
                            .set_enabled(task_id, enabled, resume_at_ms, now_ms()?)
                            .await,
                        AgentdPayload::AutomationTask,
                    )?,
                    None => automation_unavailable(),
                }
            }
            crate::AgentdMethod::MemoryFederationGrant {
                consumer_agent_id,
                owner_scope,
                lifetime_seconds,
            } => {
                require_cognitive_control_ready(
                    lifecycle,
                    app_server_ready,
                    critical_stores_ready,
                    revocation_ready,
                    required_ports_ready,
                    admission_open,
                    fenced,
                )?;
                let Some(store) = cognitive else {
                    return self.response_with_payload(
                        request_id,
                        current_generation,
                        cognitive_control_unavailable(),
                    );
                };
                let lifetime = i64::from(lifetime_seconds);
                if !(1..=MAX_FEDERATION_GRANT_LIFETIME_SECONDS).contains(&lifetime) {
                    return Err(AgentdError::Invalid(format!(
                        "memory federation lifetime must be 1..={MAX_FEDERATION_GRANT_LIFETIME_SECONDS} seconds"
                    )));
                }
                if consumer_agent_id == self.identity.agent_id {
                    return Err(AgentdError::Invalid(
                        "memory federation consumer must be another registered AgentId".to_string(),
                    ));
                }
                let snapshot = self.registry.load()?;
                let consumer = snapshot.agent(&consumer_agent_id).ok_or_else(|| {
                    AgentdError::Invalid(format!(
                        "memory federation consumer {consumer_agent_id} is not registered"
                    ))
                })?;
                let consumer_workspace_sha256 =
                    workspace_binding_digest(consumer.manifest.workspace.as_path());
                let (owner_access, owner_scope) = match owner_scope {
                    crate::MemoryFederationScopeKind::AgentPrivate => (
                        CognitiveAccess::agent_private(self.identity.agent_id.clone()),
                        CognitiveScope::AgentPrivate,
                    ),
                    crate::MemoryFederationScopeKind::WorkspacePrivate => {
                        let digest = workspace_binding_digest(&self.identity.workspace);
                        (
                            CognitiveAccess::workspace_private(
                                self.identity.agent_id.clone(),
                                digest.clone(),
                            ),
                            CognitiveScope::WorkspacePrivate {
                                workspace_sha256: digest,
                            },
                        )
                    }
                };
                let effective_at_unix_seconds = now_seconds()?;
                let expires_at_unix_seconds = effective_at_unix_seconds
                    .checked_add(lifetime)
                    .ok_or_else(|| {
                        AgentdError::Invalid(
                            "memory federation expiry exceeds the supported clock".to_string(),
                        )
                    })?;
                let result = store
                    .grant_federated_recall(
                        &owner_access,
                        &FederationGrantRequest {
                            consumer_agent_id,
                            scope: FederationGrantScope::new(
                                owner_scope,
                                consumer_workspace_sha256,
                            ),
                            effective_at_unix_seconds,
                            expires_at_unix_seconds,
                        },
                    )
                    .await;
                let capability = match result {
                    Ok(capability) => capability,
                    Err(error) => {
                        return self.cognitive_error_response(
                            request_id,
                            current_generation,
                            error,
                        );
                    }
                };
                self.fence_after_durable_change()?;
                AgentdPayload::MemoryFederationCapability(federation_snapshot(
                    FederationCapabilityStatus {
                        capability,
                        state: FederationCapabilityState::Granted,
                    },
                )?)
            }
            crate::AgentdMethod::MemoryFederationRevoke { capability_id } => {
                require_cognitive_control_ready(
                    lifecycle,
                    app_server_ready,
                    critical_stores_ready,
                    revocation_ready,
                    required_ports_ready,
                    admission_open,
                    fenced,
                )?;
                let Some(store) = cognitive else {
                    return self.response_with_payload(
                        request_id,
                        current_generation,
                        cognitive_control_unavailable(),
                    );
                };
                let capability_id =
                    FederationCapabilityId::parse(capability_id.as_str().to_string())
                        .map_err(|error| AgentdError::Invalid(error.to_string()))?;
                let status = match store.federation_capability_status(&capability_id).await {
                    Ok(Some(status)) => status,
                    Ok(None) => {
                        return Err(AgentdError::Invalid(
                            "memory federation capability does not exist".to_string(),
                        ));
                    }
                    Err(error) => {
                        return self.cognitive_error_response(
                            request_id,
                            current_generation,
                            error,
                        );
                    }
                };
                let owner_access = owner_access_for_scope(
                    &self.identity.agent_id,
                    &self.identity.workspace,
                    status.capability.scope().owner_scope(),
                )?;
                if let Err(error) = store
                    .revoke_federated_recall_by_id(&owner_access, &capability_id, now_seconds()?)
                    .await
                {
                    return self.cognitive_error_response(request_id, current_generation, error);
                }
                self.fence_after_durable_change()?;
                let status = match store.federation_capability_status(&capability_id).await {
                    Ok(Some(status)) => status,
                    Ok(None) => {
                        return Err(AgentdError::Protocol(
                            "revoked memory federation capability disappeared".to_string(),
                        ));
                    }
                    Err(error) => {
                        return self.cognitive_error_response(
                            request_id,
                            current_generation,
                            error,
                        );
                    }
                };
                AgentdPayload::MemoryFederationCapability(federation_snapshot(status)?)
            }
            crate::AgentdMethod::MemoryFederationList { limit } => {
                require_cognitive_control_ready(
                    lifecycle,
                    app_server_ready,
                    critical_stores_ready,
                    revocation_ready,
                    required_ports_ready,
                    admission_open,
                    fenced,
                )?;
                if !(1..=crate::MAX_FEDERATION_CONTROL_LIST).contains(&limit) {
                    return Err(AgentdError::Invalid(format!(
                        "memory federation list limit must be 1..={}",
                        crate::MAX_FEDERATION_CONTROL_LIST
                    )));
                }
                let Some(store) = cognitive else {
                    return self.response_with_payload(
                        request_id,
                        current_generation,
                        cognitive_control_unavailable(),
                    );
                };
                let statuses = match store.list_federation_capabilities(usize::from(limit)).await {
                    Ok(statuses) => statuses,
                    Err(error) => {
                        return self.cognitive_error_response(
                            request_id,
                            current_generation,
                            error,
                        );
                    }
                };
                AgentdPayload::MemoryFederationCapabilities {
                    capabilities: statuses
                        .into_iter()
                        .map(federation_snapshot)
                        .collect::<Result<Vec<_>, _>>()?,
                }
            }
            crate::AgentdMethod::MemoryFederationStatus { capability_id } => {
                require_cognitive_control_ready(
                    lifecycle,
                    app_server_ready,
                    critical_stores_ready,
                    revocation_ready,
                    required_ports_ready,
                    admission_open,
                    fenced,
                )?;
                let Some(store) = cognitive else {
                    return self.response_with_payload(
                        request_id,
                        current_generation,
                        cognitive_control_unavailable(),
                    );
                };
                let capability_id =
                    FederationCapabilityId::parse(capability_id.as_str().to_string())
                        .map_err(|error| AgentdError::Invalid(error.to_string()))?;
                let status = match store.federation_capability_status(&capability_id).await {
                    Ok(status) => status,
                    Err(error) => {
                        return self.cognitive_error_response(
                            request_id,
                            current_generation,
                            error,
                        );
                    }
                };
                AgentdPayload::MemoryFederationStatus {
                    capability: status.map(federation_snapshot).transpose()?,
                }
            }
        };
        Ok(AgentdResponse {
            schema_version: crate::AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            agent_id: self.identity.agent_id.clone(),
            spawn_generation: self.identity.spawn_generation,
            current_generation,
            payload,
        })
    }

    fn automation_result<T>(
        &self,
        result: Result<T, AutomationError>,
        success: impl FnOnce(T) -> AgentdPayload,
    ) -> Result<AgentdPayload, AgentdError> {
        match result {
            Ok(value) => Ok(success(value)),
            Err(AutomationError::Unavailable | AutomationError::Corrupt) => {
                self.mark_automation_unavailable()?;
                Ok(automation_unavailable())
            }
            Err(AutomationError::AccessDenied) => {
                self.mark_fenced();
                Err(AgentdError::GenerationFenced(
                    "automation store owner or generation boundary was violated".to_string(),
                ))
            }
            Err(error) => Err(error.into()),
        }
    }

    fn response_with_payload(
        &self,
        request_id: u64,
        current_generation: u64,
        payload: AgentdPayload,
    ) -> Result<AgentdResponse, AgentdError> {
        Ok(AgentdResponse {
            schema_version: crate::AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            agent_id: self.identity.agent_id.clone(),
            spawn_generation: self.identity.spawn_generation,
            current_generation,
            payload,
        })
    }

    fn cognitive_error_response(
        &self,
        request_id: u64,
        current_generation: u64,
        error: CognitiveStoreError,
    ) -> Result<AgentdResponse, AgentdError> {
        match error {
            CognitiveStoreError::Unavailable(_) | CognitiveStoreError::Corrupt(_) => {
                self.cognitive.lock().map_err(poisoned_state)?.take();
                self.response_with_payload(
                    request_id,
                    current_generation,
                    cognitive_control_unavailable(),
                )
            }
            CognitiveStoreError::AccessDenied(message) => {
                self.mark_fenced();
                Err(AgentdError::GenerationFenced(message))
            }
            CognitiveStoreError::Invalid(message) => Err(AgentdError::Invalid(message)),
            CognitiveStoreError::Conflict(message) => Err(AgentdError::Protocol(message)),
        }
    }

    fn fence_after_durable_change(&self) -> Result<(), AgentdError> {
        if let Err(error) = self.refresh_generation() {
            self.mark_fenced();
            return Err(error);
        }
        Ok(())
    }
}

fn automation_effect_unavailable() -> AgentdPayload {
    AgentdPayload::Error {
        code: AUTOMATION_EFFECT_UNAVAILABLE_CODE.to_string(),
        message: AUTOMATION_EFFECT_UNAVAILABLE_MESSAGE.to_string(),
    }
}

fn effect_snapshot(
    receipt: codex_hepta_automation::TaskFlowStepReceipt,
) -> Result<crate::AutomationEffectSnapshot, AgentdError> {
    let observation = match receipt.observation {
        Some(TaskFlowStepObservation::Succeeded) => crate::AutomationEffectObservation::Succeeded,
        Some(TaskFlowStepObservation::Failed) => crate::AutomationEffectObservation::Failed,
        Some(TaskFlowStepObservation::Indeterminate) => {
            crate::AutomationEffectObservation::Indeterminate
        }
        None => {
            return Err(AgentdError::Protocol(
                "automation effect receipt has no provider observation".to_string(),
            ));
        }
    };
    Ok(crate::AutomationEffectSnapshot {
        run_id: receipt.run_id,
        step_id: receipt.step_id,
        attempt: receipt.attempt,
        event_seq: receipt.event_seq,
        receipt_digest: receipt.receipt_digest,
        observation,
    })
}

fn decode_effect_wire_hex(value: &str) -> Result<Vec<u8>, AgentdError> {
    if value.is_empty()
        || value.len() > crate::MAX_AUTOMATION_EFFECT_WIRE_BYTES.saturating_mul(2)
        || !value.len().is_multiple_of(2)
    {
        return Err(AgentdError::Invalid(
            "automation effect wire payload hex is empty, odd, or too large".to_string(),
        ));
    }
    let bytes = value.as_bytes();
    let mut output = Vec::with_capacity(value.len() / 2);
    for offset in (0..bytes.len()).step_by(2) {
        let high = control_hex_nibble(bytes[offset]).ok_or_else(|| {
            AgentdError::Invalid("automation effect wire payload contains non-hex data".to_string())
        })?;
        let low = control_hex_nibble(bytes[offset + 1]).ok_or_else(|| {
            AgentdError::Invalid("automation effect wire payload contains non-hex data".to_string())
        })?;
        output.push((high << 4) | low);
    }
    Ok(output)
}

fn control_hex_nibble(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'a'..=b'f' => Some(value - b'a' + 10),
        b'A'..=b'F' => Some(value - b'A' + 10),
        _ => None,
    }
}

fn automation_unavailable() -> AgentdPayload {
    AgentdPayload::Error {
        code: AUTOMATION_UNAVAILABLE_CODE.to_string(),
        message: AUTOMATION_UNAVAILABLE_MESSAGE.to_string(),
    }
}

fn cognitive_control_unavailable() -> AgentdPayload {
    AgentdPayload::Error {
        code: COGNITIVE_CONTROL_UNAVAILABLE_CODE.to_string(),
        message: COGNITIVE_CONTROL_UNAVAILABLE_MESSAGE.to_string(),
    }
}

fn require_cognitive_control_ready(
    lifecycle: AgentLifecycle,
    app_server_ready: bool,
    critical_stores_ready: bool,
    revocation_ready: bool,
    required_ports_ready: bool,
    admission_open: bool,
    fenced: bool,
) -> Result<(), AgentdError> {
    if lifecycle == AgentLifecycle::Running
        && app_server_ready
        && critical_stores_ready
        && revocation_ready
        && required_ports_ready
        && admission_open
        && !fenced
    {
        Ok(())
    } else {
        Err(AgentdError::Protocol(
            "memory federation control is unavailable until this Agent generation is ready"
                .to_string(),
        ))
    }
}

fn owner_access_for_scope(
    owner_agent_id: &codex_hepta_contracts::AgentId,
    owner_workspace: &std::path::Path,
    scope: &CognitiveScope,
) -> Result<CognitiveAccess, AgentdError> {
    match scope {
        CognitiveScope::AgentPrivate => Ok(CognitiveAccess::agent_private(owner_agent_id.clone())),
        CognitiveScope::WorkspacePrivate { workspace_sha256 } => {
            let actual = workspace_binding_digest(owner_workspace);
            if &actual != workspace_sha256 {
                return Err(AgentdError::GenerationFenced(
                    "memory federation owner workspace binding changed".to_string(),
                ));
            }
            Ok(CognitiveAccess::workspace_private(
                owner_agent_id.clone(),
                actual,
            ))
        }
    }
}

fn federation_snapshot(
    status: FederationCapabilityStatus,
) -> Result<crate::MemoryFederationCapabilitySnapshot, AgentdError> {
    let capability = status.capability;
    let capability_id =
        crate::MemoryFederationCapabilityId::parse(capability.id().as_str().to_string())
            .map_err(AgentdError::Protocol)?;
    let owner_scope = match capability.scope().owner_scope() {
        CognitiveScope::AgentPrivate => crate::MemoryFederationScopeKind::AgentPrivate,
        CognitiveScope::WorkspacePrivate { .. } => {
            crate::MemoryFederationScopeKind::WorkspacePrivate
        }
    };
    Ok(crate::MemoryFederationCapabilitySnapshot {
        capability_id,
        owner_agent_id: capability.owner_agent_id().clone(),
        consumer_agent_id: capability.consumer_agent_id().clone(),
        owner_scope,
        generation: capability.generation(),
        revision: capability.revision(),
        effective_at_unix_seconds: capability.effective_at_unix_seconds(),
        expires_at_unix_seconds: capability.expires_at_unix_seconds(),
        state: match status.state {
            FederationCapabilityState::Granted => crate::MemoryFederationCapabilityState::Granted,
            FederationCapabilityState::Revoked => crate::MemoryFederationCapabilityState::Revoked,
        },
    })
}

fn require_run_admission_ready(
    lifecycle: AgentLifecycle,
    app_server_ready: bool,
    fenced: bool,
) -> Result<(), AgentdError> {
    if lifecycle == AgentLifecycle::Running && app_server_ready && !fenced {
        Ok(())
    } else {
        Err(AgentdError::Protocol(
            "run admission is unavailable until this Agent generation is ready".to_string(),
        ))
    }
}

fn require_run_reconciliation_ready(
    lifecycle: AgentLifecycle,
    fenced: bool,
) -> Result<(), AgentdError> {
    if matches!(
        lifecycle,
        AgentLifecycle::Running | AgentLifecycle::Draining
    ) && !fenced
    {
        Ok(())
    } else {
        Err(AgentdError::Protocol(
            "run reconciliation is unavailable outside a live Running/Draining generation"
                .to_string(),
        ))
    }
}

fn require_current_run_identity(
    identity: &crate::AgentdIdentity,
    current_generation: u64,
    run_generation: u64,
    fence_digest: &str,
) -> Result<(), AgentdError> {
    if run_generation != current_generation {
        return Err(AgentdError::GenerationFenced(format!(
            "run generation {run_generation} does not match current Agent generation {current_generation}"
        )));
    }
    let mut material = b"hepta:agentd:objective-fence:v1\0".to_vec();
    material.extend_from_slice(identity.agent_id.as_str().as_bytes());
    material.extend_from_slice(&identity.spawn_generation.to_be_bytes());
    material.extend_from_slice(&current_generation.to_be_bytes());
    let expected = codex_hepta_contracts::Sha256Digest::for_bytes(&material);
    if fence_digest != expected.as_str() {
        return Err(AgentdError::GenerationFenced(
            "run fence digest does not match the current Agent generation".to_string(),
        ));
    }
    Ok(())
}

fn internal_run_phase(value: crate::AgentRunPhase) -> crate::RunPhase {
    match value {
        crate::AgentRunPhase::Admitted => crate::RunPhase::Admitted,
        crate::AgentRunPhase::ContextAttached => crate::RunPhase::ContextAttached,
        crate::AgentRunPhase::Dispatched => crate::RunPhase::Dispatched,
        crate::AgentRunPhase::Cancelling => crate::RunPhase::Cancelling,
        crate::AgentRunPhase::Cancelled => crate::RunPhase::Cancelled,
        crate::AgentRunPhase::Succeeded => crate::RunPhase::Succeeded,
        crate::AgentRunPhase::Failed => crate::RunPhase::Failed,
        crate::AgentRunPhase::Indeterminate => crate::RunPhase::Indeterminate,
    }
}

fn wire_run_phase(value: crate::RunPhase) -> crate::AgentRunPhase {
    match value {
        crate::RunPhase::Admitted => crate::AgentRunPhase::Admitted,
        crate::RunPhase::ContextAttached => crate::AgentRunPhase::ContextAttached,
        crate::RunPhase::Dispatched => crate::AgentRunPhase::Dispatched,
        crate::RunPhase::Cancelling => crate::AgentRunPhase::Cancelling,
        crate::RunPhase::Cancelled => crate::AgentRunPhase::Cancelled,
        crate::RunPhase::Succeeded => crate::AgentRunPhase::Succeeded,
        crate::RunPhase::Failed => crate::AgentRunPhase::Failed,
        crate::RunPhase::Indeterminate => crate::AgentRunPhase::Indeterminate,
    }
}

fn wire_run_receipt(value: crate::RunReceipt) -> crate::AgentRunReceipt {
    crate::AgentRunReceipt {
        run_id: value.run_id,
        revision: value.revision,
        phase: wire_run_phase(value.phase),
        context_digest: value.context_digest,
        compilation_receipt_digest: value.compilation_receipt_digest,
        authority_epoch: value.authority_epoch,
        generation: value.generation,
        fence_digest: value.fence_digest,
        deadline_ms: value.deadline_ms,
        cancel_reason: value.cancel_reason,
        cancel_ack_deadline_ms: value.cancel_ack_deadline_ms,
        terminal_observed: value.terminal_observed,
        idempotent: value.idempotent,
    }
}

fn wire_cancellation_disposition(
    value: crate::CancellationDisposition,
) -> crate::AgentCancellationDisposition {
    match value {
        crate::CancellationDisposition::CancelledBeforeDispatch => {
            crate::AgentCancellationDisposition::CancelledBeforeDispatch
        }
        crate::CancellationDisposition::CancellingAfterDispatch => {
            crate::AgentCancellationDisposition::CancellingAfterDispatch
        }
        crate::CancellationDisposition::AlreadyTerminal => {
            crate::AgentCancellationDisposition::AlreadyTerminal
        }
    }
}

fn threshold_circuit_fence(
    identity: &crate::AgentdIdentity,
    generation: u64,
    circuit_digest: &Sha256Digest,
) -> Result<TaskFlowFence, AgentdError> {
    let mut bytes = b"hepta.agentd.threshold-circuit-fence.v1\0".to_vec();
    bytes.extend_from_slice(identity.agent_id.as_str().as_bytes());
    bytes.extend_from_slice(&generation.to_be_bytes());
    bytes.extend_from_slice(circuit_digest.as_str().as_bytes());
    TaskFlowFence::new(
        identity.agent_id.clone(),
        "agentd.automation-threshold-circuit",
        generation,
        generation,
        Sha256Digest::for_bytes(&bytes).as_str().to_string(),
    )
    .map_err(|error| AgentdError::Protocol(format!("threshold circuit fence: {error}")))
}

fn require_automation_recovery_ready(
    lifecycle: AgentLifecycle,
    critical_stores_ready: bool,
    revocation_ready: bool,
    required_ports_ready: bool,
    fenced: bool,
) -> Result<(), AgentdError> {
    if matches!(
        lifecycle,
        AgentLifecycle::Running | AgentLifecycle::Draining
    ) && critical_stores_ready
        && revocation_ready
        && required_ports_ready
        && !fenced
    {
        Ok(())
    } else {
        Err(AgentdError::Protocol(
            "automation recovery is unavailable outside a live Running/Draining generation"
                .to_string(),
        ))
    }
}

fn require_automation_ready(
    lifecycle: AgentLifecycle,
    app_server_ready: bool,
    critical_stores_ready: bool,
    revocation_ready: bool,
    required_ports_ready: bool,
    admission_open: bool,
    fenced: bool,
) -> Result<(), AgentdError> {
    if lifecycle == AgentLifecycle::Running
        && app_server_ready
        && critical_stores_ready
        && revocation_ready
        && required_ports_ready
        && admission_open
        && !fenced
    {
        Ok(())
    } else {
        Err(AgentdError::Protocol(
            "automation control is unavailable until this Agent generation is ready".to_string(),
        ))
    }
}

fn now_ms() -> Result<u64, AgentdError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| AgentdError::Protocol("system clock precedes Unix epoch".to_string()))?
        .as_millis();
    u64::try_from(millis)
        .map_err(|_| AgentdError::Protocol("system clock exceeds u64 milliseconds".to_string()))
}

fn now_seconds() -> Result<i64, AgentdError> {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| AgentdError::Protocol("system clock precedes Unix epoch".to_string()))?
        .as_secs();
    i64::try_from(seconds)
        .map_err(|_| AgentdError::Protocol("system clock exceeds i64 seconds".to_string()))
}
