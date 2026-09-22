use std::sync::Arc;
use std::sync::Mutex;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_automation::AutomationStore;
use codex_hepta_cognitive_store::DurableCognitiveStore as CognitiveStore;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_learning_ledger::DurableRunStartJournal;
use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::AgentRunCoordinator;
use crate::AgentRunError;
use crate::AgentdError;
use crate::AgentdEventKind;
use crate::AgentdIdentity;
use crate::EventBuffer;
use crate::RunReceipt;
use crate::RuntimeComposition;

#[path = "state_control.rs"]
mod control;

pub(crate) struct AgentdState {
    pub(crate) cognitive_ranker: std::sync::OnceLock<Arc<crate::PinnedCognitiveRanker>>,
    pub(crate) cognitive_retrieval_context:
        std::sync::OnceLock<Arc<dyn crate::CurrentMemoryRetrievalContext>>,
    pub(crate) cognitive_retrieval_learning:
        std::sync::OnceLock<Arc<crate::CognitiveRetrievalLearningSink>>,
    pub(crate) authbus: std::sync::OnceLock<Arc<crate::authbus_ingress::TextIngress>>,
    pub(crate) objective_runtime:
        std::sync::OnceLock<Arc<crate::objective_runtime::ObjectiveRuntimeHost>>,
    identity: AgentdIdentity,
    registry: FleetRegistry,
    runtime: Mutex<RuntimeState>,
    events: Mutex<EventBuffer>,
    automation: Mutex<Option<AutomationStore>>,
    cognitive: Mutex<Option<Arc<CognitiveStore>>>,
    runs: Mutex<AgentRunCoordinator>,
}

struct RuntimeState {
    current_generation: u64,
    lifecycle: AgentLifecycle,
    app_server_ready: bool,
    fenced: bool,
}

impl AgentdState {
    pub(crate) fn new(
        identity: AgentdIdentity,
        registry: FleetRegistry,
        event_capacity: usize,
    ) -> Result<Self, AgentdError> {
        let mut events = EventBuffer::new(event_capacity)?;
        events.push(AgentdEventKind::Bootstrapped);
        events.push(AgentdEventKind::Lifecycle {
            lifecycle: AgentLifecycle::Starting,
            generation: identity.spawn_generation,
        });
        let configuration_material = format!(
            "{}|{}|{}|{}|{}",
            identity.agent_id,
            identity.spawn_generation,
            identity.workspace.display(),
            identity.home_root.display(),
            identity.run_root.display()
        );
        let ports_material = format!(
            "{}|{}|{}",
            identity.control_socket.display(),
            identity.app_server_socket.display(),
            crate::AGENTD_CONTROL_SCHEMA_VERSION
        );
        let run_coordinator = AgentRunCoordinator::compose_runtime(RuntimeComposition {
            agent_id: identity.agent_id.as_str().to_string(),
            supervisor_generation: identity.spawn_generation,
            agentd_generation: identity.spawn_generation,
            configuration_digest: Sha256Digest::for_bytes(configuration_material.as_bytes())
                .as_str()
                .to_string(),
            ports_digest: Sha256Digest::for_bytes(ports_material.as_bytes())
                .as_str()
                .to_string(),
            max_active_runs: usize::from(identity.resources.max_concurrent_turns),
        })
        .map_err(run_error)?;

        Ok(Self {
            authbus: std::sync::OnceLock::new(),
            objective_runtime: std::sync::OnceLock::new(),
            cognitive_ranker: std::sync::OnceLock::new(),
            cognitive_retrieval_context: std::sync::OnceLock::new(),
            cognitive_retrieval_learning: std::sync::OnceLock::new(),
            runtime: Mutex::new(RuntimeState {
                current_generation: identity.spawn_generation,
                lifecycle: AgentLifecycle::Starting,
                app_server_ready: false,
                fenced: false,
            }),
            identity,
            registry,
            events: Mutex::new(events),
            automation: Mutex::new(None),
            cognitive: Mutex::new(None),
            runs: Mutex::new(run_coordinator),
        })
    }

    pub(crate) fn attach_cognitive_store(
        &self,
        store: Arc<CognitiveStore>,
    ) -> Result<(), AgentdError> {
        if store.owner_agent_id() != &self.identity.agent_id {
            return Err(AgentdError::GenerationFenced(
                "cognitive store owner does not match agentd identity".to_string(),
            ));
        }
        let mut cognitive = self.cognitive.lock().map_err(poisoned_state)?;
        if cognitive.is_some() {
            return Err(AgentdError::Protocol(
                "cognitive store was attached more than once".to_string(),
            ));
        }
        *cognitive = Some(store);
        Ok(())
    }

    pub(crate) fn attach_automation_store(
        &self,
        store: AutomationStore,
    ) -> Result<(), AgentdError> {
        if store.owner_agent_id() != &self.identity.agent_id {
            return Err(AgentdError::GenerationFenced(
                "automation store owner does not match agentd identity".to_string(),
            ));
        }
        let mut automation = self.automation.lock().map_err(poisoned_state)?;
        if automation.is_some() {
            return Err(AgentdError::Protocol(
                "automation store was attached more than once".to_string(),
            ));
        }
        *automation = Some(store);
        Ok(())
    }

    pub(crate) fn mark_automation_unavailable(&self) -> Result<(), AgentdError> {
        self.automation.lock().map_err(poisoned_state)?.take();
        Ok(())
    }

    pub(crate) fn automation_is_available(&self) -> Result<bool, AgentdError> {
        Ok(self.automation.lock().map_err(poisoned_state)?.is_some())
    }

    pub(crate) fn identity(&self) -> &AgentdIdentity {
        &self.identity
    }

    pub(crate) fn current_generation(&self) -> Result<u64, AgentdError> {
        self.refresh_generation()?;
        Ok(self
            .runtime
            .lock()
            .map_err(poisoned_state)?
            .current_generation)
    }

    pub(crate) fn refresh_generation(&self) -> Result<(), AgentdError> {
        // Registration/startup retains fleet-wide validation. Serving an
        // already admitted generation must not scan or depend on peer stores.
        let record = self
            .registry
            .load_agent(&self.identity.agent_id)
            .map_err(|_| {
                self.mark_fenced();
                AgentdError::GenerationFenced(format!(
                    "agent {} control record is unavailable or invalid",
                    self.identity.agent_id
                ))
            })?;
        if record.layout.home_root() != self.identity.home_root
            || record.layout.run_root() != self.identity.run_root
            || record.layout.cognitive_root() != self.identity.layout.cognitive_root()
            || record.layout.automation_root() != self.identity.layout.automation_root()
            || record.manifest.workspace.as_path() != self.identity.workspace
            || record.manifest.resources != self.identity.resources
        {
            return Err(AgentdError::GenerationFenced(
                "registered agent roots or resource budget changed while agentd was running"
                    .to_string(),
            ));
        }
        let distance = record
            .lifecycle
            .generation
            .checked_sub(self.identity.spawn_generation);
        let accepted = matches!(
            (record.lifecycle.lifecycle, distance),
            (AgentLifecycle::Starting, Some(0))
                | (AgentLifecycle::Running, Some(1))
                | (AgentLifecycle::Draining, Some(2))
        );
        if !accepted {
            return Err(AgentdError::GenerationFenced(format!(
                "agent {} spawn generation {} cannot serve {:?} generation {}",
                self.identity.agent_id,
                self.identity.spawn_generation,
                record.lifecycle.lifecycle,
                record.lifecycle.generation
            )));
        }

        let mut runtime = self.runtime.lock().map_err(poisoned_state)?;
        if runtime.current_generation != record.lifecycle.generation
            || runtime.lifecycle != record.lifecycle.lifecycle
        {
            runtime.current_generation = record.lifecycle.generation;
            runtime.lifecycle = record.lifecycle.lifecycle;
            if runtime.lifecycle != AgentLifecycle::Running {
                runtime.app_server_ready = false;
            }
            self.events
                .lock()
                .map_err(poisoned_state)?
                .push(AgentdEventKind::Lifecycle {
                    lifecycle: record.lifecycle.lifecycle,
                    generation: record.lifecycle.generation,
                });
            if runtime.lifecycle == AgentLifecycle::Draining {
                self.runs
                    .lock()
                    .map_err(poisoned_state)?
                    .begin_drain(unix_now_ms()?, "supervisor_draining")
                    .map_err(run_error)?;
            }
        }
        Ok(())
    }

    /// Return the current fleet lifecycle generation after refreshing the
    /// process fence. This is distinct from `identity.spawn_generation`: the
    /// latter identifies the process launch, while this value is the current
    /// supervisor lifecycle generation used as a host-bound epoch witness.
    #[cfg(feature = "qualification-cognitive-write")]
    pub(crate) fn qualification_turn_authority(&self) -> Result<u64, AgentdError> {
        self.refresh_generation()?;
        let runtime = self.runtime.lock().map_err(poisoned_state)?;
        if runtime.lifecycle != AgentLifecycle::Running
            || !runtime.app_server_ready
            || runtime.fenced
        {
            return Err(AgentdError::GenerationFenced(
                "agentd qualification writer is unavailable until the running App Server is ready"
                    .to_string(),
            ));
        }
        Ok(runtime.current_generation)
    }

    pub(crate) fn mark_app_server_ready(&self) -> Result<(), AgentdError> {
        let mut runtime = self.runtime.lock().map_err(poisoned_state)?;
        if !runtime.app_server_ready {
            runtime.app_server_ready = true;
            self.events
                .lock()
                .map_err(poisoned_state)?
                .push(AgentdEventKind::AppServerReady);
        }
        Ok(())
    }

    pub(crate) fn mark_draining(&self) -> Result<(), AgentdError> {
        let mut runtime = self.runtime.lock().map_err(poisoned_state)?;
        runtime.app_server_ready = false;
        self.events
            .lock()
            .map_err(poisoned_state)?
            .push(AgentdEventKind::Draining);
        drop(runtime);
        self.runs
            .lock()
            .map_err(poisoned_state)?
            .begin_drain(unix_now_ms()?, "agentd_shutdown")
            .map_err(run_error)?;
        Ok(())
    }

    pub(crate) fn mark_fenced(&self) {
        if let Ok(mut runtime) = self.runtime.lock() {
            runtime.app_server_ready = false;
            runtime.fenced = true;
        }
        if let Ok(mut events) = self.events.lock() {
            events.push(AgentdEventKind::GenerationFenced);
        }
        if let Ok(mut runs) = self.runs.lock() {
            runs.close_admissions();
            if let Ok(now_ms) = unix_now_ms() {
                let _ = runs.begin_drain(now_ms, "generation_fenced");
            }
            let _ = runs.mark_unresolved_indeterminate("generation_fenced");
        }
    }

    pub(crate) fn is_fenced(&self) -> Result<bool, AgentdError> {
        Ok(self.runtime.lock().map_err(poisoned_state)?.fenced)
    }

    pub(crate) fn automation_admission_ready(&self) -> Result<bool, AgentdError> {
        self.refresh_generation()?;
        let runtime = self.runtime.lock().map_err(poisoned_state)?;
        Ok(runtime.lifecycle == AgentLifecycle::Running
            && runtime.app_server_ready
            && !runtime.fenced)
    }

    /// Revalidate a durable run-start record against the current owner trust,
    /// current Fleet generation and exact Agentd fence, then project it into
    /// the sole daemon-owned run coordinator.
    pub(crate) fn start_current_run_start(
        &self,
        journal: &DurableRunStartJournal,
        run_id: &StableId,
    ) -> Result<RunReceipt, AgentdError> {
        let record = journal
            .get(run_id)
            .map_err(|error| {
                AgentdError::Protocol(format!("durable run-start journal rejected read: {error}"))
            })?
            .ok_or_else(|| {
                AgentdError::Protocol(format!("durable run-start {run_id} is not published"))
            })?;
        let now_ms = self.require_current_run_start(record)?;
        // Re-read both mutable authority domains immediately before mutation.
        // This is intentionally redundant: a trust/fleet change during the
        // first validation must not survive into runtime admission.
        let final_now_ms = self.require_current_run_start(record)?;
        let now_ms = now_ms.max(final_now_ms);
        self.runs
            .lock()
            .map_err(poisoned_state)?
            .start_revalidated_run_start(now_ms, record)
            .map_err(run_error)
    }

    fn require_current_run_start(&self, record: &RunStartRecordV1) -> Result<u64, AgentdError> {
        crate::authbus_ingress::require_ready(self)?;
        let now_ms = crate::authbus_ingress::now_ms()?;
        let current_generation = self.runtime.lock().map_err(poisoned_state)?.current_generation;
        if record.snapshot.generation != current_generation
            || record.snapshot.fence_digest.to_string()
                != objective_run_fence(&self.identity, current_generation)
        {
            return Err(AgentdError::GenerationFenced(
                "durable run-start generation or fence is not current".to_string(),
            ));
        }

        let host = crate::authbus_ingress::attached(self)?;
        let trust = host.trust(self)?;
        let authentication = &record.authentication;
        let message = SignedMessage {
            claims: SignedMessageClaims {
                issuer_id: authentication.issuer_id.clone(),
                key_epoch: Generation::new(authentication.key_epoch).map_err(|error| {
                    AgentdError::Invalid(format!("durable run-start key epoch: {error}"))
                })?,
                message_id: authentication.message_id.clone(),
                subject_id: StableId::new(self.identity.agent_id.as_str()).map_err(|error| {
                    AgentdError::Invalid(format!("durable run-start subject: {error}"))
                })?,
                scope_digest: authentication.scope_digest,
                payload_digest: authentication.signed_body_digest,
                sequence: authentication.sequence,
                expires_at_ms: authentication.expires_at_ms,
            },
            signature: authentication.signature,
        };
        message
            .authenticate(
                &trust.issuer()?,
                objective_run_scope(&self.identity),
                authentication.signed_body_digest,
                now_ms,
            )
            .map_err(|error| {
                AgentdError::Invalid(format!(
                    "durable run-start authentication is not current: {error}"
                ))
            })?;
        Ok(now_ms)
    }

    pub(crate) fn expire_run_deadlines(&self) -> Result<usize, AgentdError> {
        self.runs
            .lock()
            .map_err(poisoned_state)?
            .expire_deadlines(unix_now_ms()?)
            .map_err(run_error)
    }

    pub(crate) fn active_run_count(&self) -> Result<usize, AgentdError> {
        Ok(self.runs.lock().map_err(poisoned_state)?.active_run_count())
    }

    pub(crate) fn unresolved_run_count(&self) -> Result<usize, AgentdError> {
        Ok(self
            .runs
            .lock()
            .map_err(poisoned_state)?
            .unresolved_run_count())
    }

    pub(crate) fn mark_unresolved_runs_indeterminate(
        &self,
        reason: &str,
    ) -> Result<usize, AgentdError> {
        self.runs
            .lock()
            .map_err(poisoned_state)?
            .mark_unresolved_indeterminate(reason)
            .map_err(run_error)
    }
}

pub(super) fn run_error(error: AgentRunError) -> AgentdError {
    AgentdError::Protocol(format!("agent run lifecycle rejected: {error:?}"))
}

fn objective_run_scope(identity: &AgentdIdentity) -> Digest32 {
    let mut bytes = b"hepta:agentd:signed-objective:v1\0".to_vec();
    bytes.extend_from_slice(identity.agent_id.as_str().as_bytes());
    Digest32::of_bytes(&bytes)
}

fn objective_run_fence(identity: &AgentdIdentity, current_generation: u64) -> String {
    let mut bytes = b"hepta:agentd:objective-fence:v1\0".to_vec();
    bytes.extend_from_slice(identity.agent_id.as_str().as_bytes());
    bytes.extend_from_slice(&identity.spawn_generation.to_be_bytes());
    bytes.extend_from_slice(&current_generation.to_be_bytes());
    Sha256Digest::for_bytes(&bytes).as_str().to_string()
}

fn unix_now_ms() -> Result<u64, AgentdError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| AgentdError::Protocol("system clock precedes Unix epoch".to_string()))?
        .as_millis();
    u64::try_from(millis)
        .map_err(|_| AgentdError::Protocol("system clock exceeds u64 milliseconds".to_string()))
}

fn poisoned_state<T>(_error: std::sync::PoisonError<T>) -> AgentdError {
    AgentdError::Protocol("agentd control state mutex is poisoned".to_string())
}

#[cfg(test)]
#[path = "state_isolation_tests.rs"]
mod isolation_tests;
