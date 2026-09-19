use std::sync::Arc;
use std::sync::Mutex;
use std::time::Instant;

use codex_hepta_automation::AutomationStore;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_memory::CognitiveStore;

use crate::AgentdError;
use crate::AgentdEventKind;
use crate::AgentdIdentity;
use crate::EventBuffer;

#[path = "state_control.rs"]
mod control;

pub(crate) struct AgentdState {
    pub(crate) cognitive_ranker: std::sync::OnceLock<Arc<crate::PinnedCognitiveRanker>>,
    pub(crate) authbus: std::sync::OnceLock<Arc<crate::authbus_ingress::TextIngress>>,
    identity: AgentdIdentity,
    registry: FleetRegistry,
    runtime: Mutex<RuntimeState>,
    events: Mutex<EventBuffer>,
    automation: Mutex<Option<AutomationStore>>,
    cognitive: Mutex<Option<Arc<CognitiveStore>>>,
    monotonic_origin: Instant,
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
        Ok(Self {
            authbus: std::sync::OnceLock::new(),
            cognitive_ranker: std::sync::OnceLock::new(),
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
            monotonic_origin: Instant::now(),
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

    pub(crate) fn monotonic_origin(&self) -> Instant {
        self.monotonic_origin
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
}

fn poisoned_state<T>(_error: std::sync::PoisonError<T>) -> AgentdError {
    AgentdError::Protocol("agentd control state mutex is poisoned".to_string())
}

#[cfg(test)]
#[path = "state_isolation_tests.rs"]
mod isolation_tests;
