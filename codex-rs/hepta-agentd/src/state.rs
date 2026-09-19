use std::any::Any;
use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::sync::Arc;
use std::sync::Mutex;

use crate::AgentdError;
use crate::AgentdEventKind;
use crate::AgentdIdentity;
use crate::AgentdOperationsHost;
use crate::EventBuffer;
use codex_hepta_automation::AutomationStore;
use codex_hepta_control_plane::RuntimeModuleAbiV1;
use codex_hepta_control_plane::RuntimeModuleRegistryV1;
use codex_hepta_control_plane::RuntimeModuleStateClassV1;
use codex_hepta_control_plane::RuntimeTopologySnapshotV1;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::RuntimeModuleCatalogV1;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

#[path = "state_control.rs"]
mod control;

const MODULE_AUTHBUS: &str = "auth.authbus";
const MODULE_OBJECTIVE: &str = "objective.compiler";
const MODULE_AUTOMATION: &str = "automation.taskflow";
const MODULE_OPERATIONS: &str = "kernel.operations";
const MODULE_COGNITIVE: &str = "cognitive.store";

#[derive(Default)]
struct RuntimeModuleAttachments {
    entries: BTreeMap<StableId, Arc<dyn Any + Send + Sync>>,
}

impl RuntimeModuleAttachments {
    fn contains(&self, module_id: &StableId) -> bool {
        self.entries.contains_key(module_id)
    }

    fn insert<T>(
        &mut self,
        module_id: StableId,
        attachment: Arc<T>,
    ) -> Result<(), AgentdError>
    where
        T: Any + Send + Sync + 'static,
    {
        if self.entries.contains_key(&module_id) {
            return Err(AgentdError::Protocol(format!(
                "runtime module {} was attached more than once",
                module_id.as_str()
            )));
        }
        let erased: Arc<dyn Any + Send + Sync> = attachment;
        self.entries.insert(module_id, erased);
        Ok(())
    }

    fn get<T>(&self, module_id: &StableId) -> Result<Option<Arc<T>>, AgentdError>
    where
        T: Any + Send + Sync + 'static,
    {
        let Some(attachment) = self.entries.get(module_id) else {
            return Ok(None);
        };
        Arc::clone(attachment)
            .downcast::<T>()
            .map(Some)
            .map_err(|_| {
                AgentdError::Protocol(format!(
                    "runtime module {} attachment type does not match its registered host",
                    module_id.as_str()
                ))
            })
    }

    fn remove(&mut self, module_id: &StableId) -> bool {
        self.entries.remove(module_id).is_some()
    }
}

pub(crate) struct AgentdState {
    pub(crate) cognitive_ranker: std::sync::OnceLock<Arc<crate::PinnedCognitiveRanker>>,
    identity: AgentdIdentity,
    registry: FleetRegistry,
    runtime: Mutex<RuntimeState>,
    events: Mutex<EventBuffer>,
    attachments: Mutex<RuntimeModuleAttachments>,
    runtime_modules: Mutex<RuntimeModuleRegistryV1>,
    runtime_catalog: RuntimeModuleCatalogV1,
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
        let runtime_catalog = RuntimeModuleCatalogV1::canonical().map_err(|error| {
            AgentdError::Protocol(format!(
                "canonical runtime module catalog is invalid: {error}"
            ))
        })?;
        Ok(Self {
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
            attachments: Mutex::new(RuntimeModuleAttachments::default()),
            runtime_modules: Mutex::new(RuntimeModuleRegistryV1::new()),
            runtime_catalog,
        })
    }

    fn module_id(module_id: &str) -> Result<StableId, AgentdError> {
        StableId::new(module_id).map_err(|error| AgentdError::Protocol(error.to_string()))
    }

    fn attach_runtime_module<T>(
        &self,
        module_id: &str,
        effect_scope: &[&str],
        attachment: Arc<T>,
    ) -> Result<(), AgentdError>
    where
        T: Any + Send + Sync + 'static,
    {
        let stable_id = Self::module_id(module_id)?;
        let mut attachments = self.attachments.lock().map_err(poisoned_state)?;
        if attachments.contains(&stable_id) {
            return Err(AgentdError::Protocol(format!(
                "runtime module {module_id} was attached more than once"
            )));
        }
        self.activate_builtin_runtime_module(module_id, effect_scope)?;
        attachments.insert(stable_id, attachment)
    }

    fn runtime_attachment<T>(&self, module_id: &str) -> Result<Option<Arc<T>>, AgentdError>
    where
        T: Any + Send + Sync + 'static,
    {
        let stable_id = Self::module_id(module_id)?;
        self.attachments
            .lock()
            .map_err(poisoned_state)?
            .get(&stable_id)
    }

    fn quarantine_runtime_attachment(&self, module_id: &str) -> Result<(), AgentdError> {
        let stable_id = Self::module_id(module_id)?;
        let mut attachments = self.attachments.lock().map_err(poisoned_state)?;
        if !attachments.contains(&stable_id) {
            return Ok(());
        }
        let generation = Generation::new(self.identity.spawn_generation)
            .map_err(|error| AgentdError::Protocol(error.to_string()))?;
        self.runtime_modules
            .lock()
            .map_err(poisoned_state)?
            .quarantine(&stable_id, generation)
            .map_err(|error| {
                AgentdError::Protocol(format!(
                    "runtime module {module_id} quarantine failed: {error}"
                ))
            })?;
        attachments.remove(&stable_id);
        Ok(())
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
        self.attach_runtime_module(MODULE_COGNITIVE, &[], store)
    }

    pub(crate) fn cognitive_store(&self) -> Result<Option<Arc<CognitiveStore>>, AgentdError> {
        self.runtime_attachment(MODULE_COGNITIVE)
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
        self.attach_runtime_module(MODULE_AUTOMATION, &[], Arc::new(store))
    }

    pub(crate) fn automation_store(&self) -> Result<Option<Arc<AutomationStore>>, AgentdError> {
        self.runtime_attachment(MODULE_AUTOMATION)
    }

    pub(crate) fn attach_automation_operations(
        &self,
        host: Arc<AgentdOperationsHost>,
    ) -> Result<(), AgentdError> {
        if host.generation().get() != self.identity.spawn_generation {
            return Err(AgentdError::GenerationFenced(
                "automation operations host generation does not match agentd process generation"
                    .to_string(),
            ));
        }
        self.attach_runtime_module(
            MODULE_OPERATIONS,
            &["external_effect_dispatch"],
            host,
        )
    }

    pub(crate) fn automation_operations(
        &self,
    ) -> Result<Option<Arc<AgentdOperationsHost>>, AgentdError> {
        self.runtime_attachment(MODULE_OPERATIONS)
    }

    pub(crate) fn attach_authbus(
        &self,
        host: Arc<crate::authbus_ingress::TextIngress>,
    ) -> Result<(), AgentdError> {
        self.attach_runtime_module(MODULE_AUTHBUS, &[], host)
    }

    pub(crate) fn authbus(
        &self,
    ) -> Result<Option<Arc<crate::authbus_ingress::TextIngress>>, AgentdError> {
        self.runtime_attachment(MODULE_AUTHBUS)
    }

    pub(crate) fn attach_objective_ingress(
        &self,
        host: Arc<crate::objective_ingress::ObjectiveIngressHost>,
    ) -> Result<(), AgentdError> {
        self.attach_runtime_module(MODULE_OBJECTIVE, &[], host)
    }

    pub(crate) fn objective_ingress(
        &self,
    ) -> Result<Option<Arc<crate::objective_ingress::ObjectiveIngressHost>>, AgentdError> {
        self.runtime_attachment(MODULE_OBJECTIVE)
    }

    pub(crate) fn runtime_topology_snapshot(
        &self,
    ) -> Result<RuntimeTopologySnapshotV1, AgentdError> {
        Ok(self
            .runtime_modules
            .lock()
            .map_err(poisoned_state)?
            .snapshot())
    }

    fn activate_builtin_runtime_module(
        &self,
        module_id: &str,
        effect_scope: &[&str],
    ) -> Result<(), AgentdError> {
        let row = self.runtime_catalog.module(module_id).ok_or_else(|| {
            AgentdError::Protocol(format!(
                "runtime module {module_id} is absent from canonical catalog"
            ))
        })?;
        let module_id =
            StableId::new(&row.id).map_err(|error| AgentdError::Protocol(error.to_string()))?;
        let owner_id =
            StableId::new(&row.owner).map_err(|error| AgentdError::Protocol(error.to_string()))?;
        let generation = Generation::new(self.identity.spawn_generation)
            .map_err(|error| AgentdError::Protocol(error.to_string()))?;
        let dependencies = row
            .dependencies
            .iter()
            .map(|value| {
                StableId::new(value).map_err(|error| AgentdError::Protocol(error.to_string()))
            })
            .collect::<Result<Vec<_>, _>>()?;
        let authoritative_domains = row
            .authoritative_domains
            .iter()
            .map(|value| {
                StableId::new(value).map_err(|error| AgentdError::Protocol(error.to_string()))
            })
            .collect::<Result<BTreeSet<_>, _>>()?;
        let effect_scope = effect_scope
            .iter()
            .map(|value| {
                StableId::new(*value).map_err(|error| AgentdError::Protocol(error.to_string()))
            })
            .collect::<Result<BTreeSet<_>, _>>()?;
        let state_class = match row.state.as_str() {
            "stateful_external" => RuntimeModuleStateClassV1::ExternalStateful,
            value if value.contains("stateful") => RuntimeModuleStateClassV1::Stateful,
            _ => RuntimeModuleStateClassV1::Stateless,
        };
        // This bootstrap binding intentionally names the reviewed runtime
        // manifest, not executable provenance. Candidate replacement uses the
        // independently evaluated implementation/artifact digests carried by
        // RuntimeModuleAbiV1 and supervisor selection evidence.
        let manifest_binding = format!(
            "hepta.runtime-module-manifest.v1:{}:{}",
            self.runtime_catalog.digest(),
            row.manifest_digest
        );
        let implementation_digest = Digest32::of_bytes(manifest_binding.as_bytes());
        let abi = RuntimeModuleAbiV1 {
            module_id: module_id.clone(),
            owner_id,
            generation,
            implementation_digest,
            candidate_artifact_digest: implementation_digest,
            predecessor_generation: None,
            rollback_predecessor_digest: Digest32::ZERO,
            state_class,
            dependencies,
            input_ports: Vec::new(),
            output_ports: Vec::new(),
            authoritative_domains,
            effect_scope,
        };
        let mut modules = self.runtime_modules.lock().map_err(poisoned_state)?;
        modules.register_candidate(abi).map_err(|error| {
            AgentdError::Protocol(format!("runtime module registration failed: {error}"))
        })?;
        modules
            .activate_bootstrap(&module_id, generation)
            .map_err(|error| {
                AgentdError::Protocol(format!("runtime module activation failed: {error}"))
            })?;
        Ok(())
    }

    pub(crate) fn mark_automation_unavailable(&self) -> Result<(), AgentdError> {
        self.quarantine_runtime_attachment(MODULE_AUTOMATION)
    }

    pub(crate) fn automation_is_available(&self) -> Result<bool, AgentdError> {
        Ok(self.automation_store()?.is_some())
    }

    pub(crate) fn mark_cognitive_unavailable(&self) -> Result<(), AgentdError> {
        self.quarantine_runtime_attachment(MODULE_COGNITIVE)
    }

    pub(crate) fn identity(&self) -> &AgentdIdentity {
        &self.identity
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
