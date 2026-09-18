//! Domain control dispatch kept separate from process lifecycle state.

use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_automation::AutomationError;
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

const AUTOMATION_UNAVAILABLE_CODE: &str = "automation_unavailable";
const AUTOMATION_UNAVAILABLE_MESSAGE: &str =
    "this Agent's private automation storage is unavailable";
const COGNITIVE_CONTROL_UNAVAILABLE_CODE: &str = "cognitive_control_unavailable";
const COGNITIVE_CONTROL_UNAVAILABLE_MESSAGE: &str =
    "this Agent's private cognitive control storage is unavailable";

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
        let (current_generation, lifecycle, app_server_ready, fenced) = {
            let runtime = self.runtime.lock().map_err(poisoned_state)?;
            (
                runtime.current_generation,
                runtime.lifecycle,
                runtime.app_server_ready,
                runtime.fenced,
            )
        };
        let automation = self.automation.lock().map_err(poisoned_state)?.clone();
        let cognitive = self.cognitive.lock().map_err(poisoned_state)?.clone();
        let payload = match method {
            crate::AgentdMethod::Capabilities => {
                AgentdPayload::Capabilities(crate::AgentdCapabilitySet::empty())
            }
            crate::AgentdMethod::Health => AgentdPayload::Health(HealthSnapshot {
                promotion_ready: matches!(
                    lifecycle,
                    AgentLifecycle::Starting | AgentLifecycle::Running
                ) && app_server_ready
                    && !fenced,
                ready: lifecycle == AgentLifecycle::Running && app_server_ready && !fenced,
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
            crate::AgentdMethod::SessionIngress => {
                if lifecycle != AgentLifecycle::Running || !app_server_ready || fenced {
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
            crate::AgentdMethod::AuthBusText { request } => AgentdPayload::AuthBusTextStatus(
                crate::authbus_ingress::submit(self, request).await?,
            ),
            crate::AgentdMethod::AuthBusTextStatus { delivery_id } => {
                AgentdPayload::AuthBusTextStatus(
                    crate::authbus_ingress::status(self, delivery_id).await?,
                )
            }
            crate::AgentdMethod::CognitiveContext { query, limit } => {
                require_cognitive_control_ready(lifecycle, app_server_ready, fenced)?;
                let Some(store) = cognitive else {
                    return self.response_with_payload(
                        request_id,
                        current_generation,
                        cognitive_control_unavailable(),
                    );
                };
                // The model/context plan bind to the launched body; the cognitive
                // authoritative read additionally binds the current fleet lifecycle
                // generation as its host authority epoch.
                let result = crate::cognitive_context::read(
                    &store,
                    &self.identity.agent_id,
                    self.identity.spawn_generation,
                    current_generation,
                    &query,
                    limit,
                    self.cognitive_ranker.get(),
                )
                .await;
                self.refresh_generation()?;
                {
                    let runtime = self.runtime.lock().map_err(poisoned_state)?;
                    if runtime.current_generation != current_generation {
                        return Err(AgentdError::GenerationFenced(format!(
                            "cognitive authority epoch changed during read: expected {current_generation}, observed {}",
                            runtime.current_generation
                        )));
                    }
                    require_cognitive_control_ready(
                        runtime.lifecycle,
                        runtime.app_server_ready,
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
                    Err(CognitiveContextError::RankerUnavailable) => AgentdPayload::Error {
                        code: "cognitive_ranker_unavailable".to_string(),
                        message: "selected ranker is unavailable; explicit reload required"
                            .to_string(),
                    },
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
            crate::AgentdMethod::AutomationCreate { draft } => {
                require_automation_ready(lifecycle, app_server_ready, fenced)?;
                match automation {
                    Some(store) => self.automation_result(
                        store.create_task(&draft).await,
                        AgentdPayload::AutomationTask,
                    )?,
                    None => automation_unavailable(),
                }
            }
            crate::AgentdMethod::AutomationList { limit } => {
                require_automation_ready(lifecycle, app_server_ready, fenced)?;
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
                require_automation_ready(lifecycle, app_server_ready, fenced)?;
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
                require_automation_ready(lifecycle, app_server_ready, fenced)?;
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
                require_cognitive_control_ready(lifecycle, app_server_ready, fenced)?;
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
                require_cognitive_control_ready(lifecycle, app_server_ready, fenced)?;
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
                require_cognitive_control_ready(lifecycle, app_server_ready, fenced)?;
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
                require_cognitive_control_ready(lifecycle, app_server_ready, fenced)?;
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
    fenced: bool,
) -> Result<(), AgentdError> {
    if lifecycle == AgentLifecycle::Running && app_server_ready && !fenced {
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

fn require_automation_ready(
    lifecycle: AgentLifecycle,
    app_server_ready: bool,
    fenced: bool,
) -> Result<(), AgentdError> {
    if lifecycle == AgentLifecycle::Running && app_server_ready && !fenced {
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
