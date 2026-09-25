use std::path::Path;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_app_server::AppServerDrainHandle;
use codex_hepta_agent_protocol::DrainSnapshot;
use codex_hepta_automation::AutomationStore;
use codex_hepta_cognitive_store::DurableCognitiveStore as CognitiveStore;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_learning_ledger::DurableRunStartJournal;
use codex_hepta_learning_ledger::RunStartRecordV1;
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
    pub(crate) intelligence_product:
        std::sync::OnceLock<Arc<crate::AgentdIntelligenceProductRunnerV1>>,
    pub(crate) intelligence_invocation:
        std::sync::OnceLock<Arc<dyn crate::AgentdIntelligenceInvocationProviderV1>>,
    pub(crate) cognitive_ranker: std::sync::OnceLock<Arc<crate::PinnedCognitiveRanker>>,
    pub(crate) cognitive_retrieval_context:
        std::sync::OnceLock<Arc<dyn crate::CurrentMemoryRetrievalContext>>,
    pub(crate) cognitive_retrieval_learning:
        std::sync::OnceLock<Arc<crate::CognitiveRetrievalLearningSink>>,
    pub(crate) intuition_policy: std::sync::OnceLock<Arc<crate::AgentdIntuitionPolicyHostV1>>,
    pub(crate) authbus: std::sync::OnceLock<Arc<crate::authbus_ingress::TextIngress>>,
    pub(crate) production_operations: std::sync::OnceLock<Arc<crate::AgentdProductionWriterHost>>,
    pub(crate) evidence: std::sync::OnceLock<Arc<crate::evidence_host::EvidenceHost>>,
    pub(crate) automation_effect:
        std::sync::OnceLock<Arc<crate::automation_effect_host::AgentdAutomationEffectHost>>,
    pub(crate) objective_runtime:
        std::sync::OnceLock<Arc<crate::objective_runtime::ObjectiveRuntimeHost>>,
    plasticity_runtime: std::sync::OnceLock<
        crate::plasticity_learning_producer::AgentdLearningPlasticityProducerV1,
    >,
    identity: AgentdIdentity,
    registry: FleetRegistry,
    runtime: Mutex<RuntimeState>,
    events: Mutex<EventBuffer>,
    automation: Mutex<Option<AutomationStore>>,
    cognitive: Mutex<Option<Arc<CognitiveStore>>>,
    runs: Mutex<AgentRunCoordinator>,
    app_server_drain: AppServerDrainHandle,
    pub(crate) prompt_pipeline: Arc<crate::AgentdPromptPipelineOwner>,
}

struct RuntimeState {
    current_generation: u64,
    lifecycle: AgentLifecycle,
    app_server_ready: bool,
    critical_stores_ready: bool,
    revocation_ready: bool,
    required_ports_ready: bool,
    admission_open: bool,
    fenced: bool,
}

impl AgentdState {
    pub(crate) fn new(
        identity: AgentdIdentity,
        registry: FleetRegistry,
        event_capacity: usize,
    ) -> Result<Self, AgentdError> {
        Self::new_with_prompt_registry_recovery(identity, registry, event_capacity, None)
    }

    pub(crate) fn new_with_prompt_registry_recovery(
        identity: AgentdIdentity,
        registry: FleetRegistry,
        event_capacity: usize,
        prompt_registry_recovery_checkpoint: Option<&Path>,
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

        let prompt_registry_root = identity.home_root.join("prompt-registry");
        let prompt_registry_owner_id = format!("agentd:{}:prompt.registry", identity.agent_id);
        let prompt_runtime_root = identity.run_root.join("prompt-runtime");
        let prompt_pipeline = crate::AgentdPromptPipelineOwner::open_state_dirs(
            &prompt_registry_root,
            prompt_registry_recovery_checkpoint,
            &prompt_registry_owner_id,
            &prompt_runtime_root,
            crate::prompt_runtime::AGENTD_PROMPT_REGISTRY_MAX_RECORDS,
        )
        .map_err(|error| {
            AgentdError::Protocol(format!(
                "prompt pipeline durable owners failed to open: {error}"
            ))
        })?;
        let prompt_pipeline = Arc::new(prompt_pipeline);
        Ok(Self {
            authbus: std::sync::OnceLock::new(),
            intelligence_product: std::sync::OnceLock::new(),
            intelligence_invocation: std::sync::OnceLock::new(),
            evidence: std::sync::OnceLock::new(),
            automation_effect: std::sync::OnceLock::new(),
            objective_runtime: std::sync::OnceLock::new(),
            cognitive_ranker: std::sync::OnceLock::new(),
            production_operations: std::sync::OnceLock::new(),
            cognitive_retrieval_context: std::sync::OnceLock::new(),
            cognitive_retrieval_learning: std::sync::OnceLock::new(),
            plasticity_runtime: std::sync::OnceLock::new(),
            intuition_policy: std::sync::OnceLock::new(),
            runtime: Mutex::new(RuntimeState {
                current_generation: identity.spawn_generation,
                lifecycle: AgentLifecycle::Starting,
                app_server_ready: false,
                critical_stores_ready: false,
                revocation_ready: false,
                required_ports_ready: false,
                admission_open: false,
                fenced: false,
            }),
            identity,
            registry,
            events: Mutex::new(events),
            automation: Mutex::new(None),
            cognitive: Mutex::new(None),
            runs: Mutex::new(run_coordinator),
            app_server_drain: AppServerDrainHandle::new(),
            prompt_pipeline,
        })
    }

    pub(crate) fn attach_plasticity_runtime(
        &self,
        handle: crate::PlasticityRuntimeHandleV1,
    ) -> Result<(), AgentdError> {
        self.plasticity_runtime
            .set(
                crate::plasticity_learning_producer::AgentdLearningPlasticityProducerV1::new(
                    handle,
                ),
            )
            .map_err(|_| AgentdError::Protocol("plasticity runtime already attached".to_string()))
    }

    /// Named Agentd-owned producer boundary for governed parameter plasticity.
    /// Callers never receive the mutable writer or a second owner handle.
    pub(crate) async fn submit_parameter_plasticity_v1(
        &self,
        request: codex_hepta_intelligence::ParameterPlasticityProductRequestV1,
        now: u64,
    ) -> Result<
        codex_hepta_intelligence::ParameterPlasticityProductReceiptV1,
        crate::PlasticityRuntimeCallErrorV1,
    > {
        let producer = self
            .plasticity_runtime
            .get()
            .ok_or(crate::PlasticityRuntimeCallErrorV1::Closed)?;
        producer.submit_parameter(request, now).await
    }

    /// Named Agentd-owned producer boundary for governed topology plasticity.
    /// The long-lived owner performs final artifact/ledger/trust/anchor checks.
    pub(crate) async fn submit_topology_plasticity_v1(
        &self,
        request: codex_hepta_intelligence::TopologyPlasticityProductRequestV1,
        now: u64,
    ) -> Result<
        codex_hepta_intelligence::TopologyPlasticityProductReceiptV1,
        crate::PlasticityRuntimeCallErrorV1,
    > {
        let producer = self
            .plasticity_runtime
            .get()
            .ok_or(crate::PlasticityRuntimeCallErrorV1::Closed)?;
        producer.submit_topology(request, now).await
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

    pub(crate) fn attach_production_operations(
        &self,
        host: Arc<crate::AgentdProductionWriterHost>,
    ) -> Result<(), AgentdError> {
        if host.writer().authority().agent_id != self.identity.agent_id {
            return Err(AgentdError::GenerationFenced(
                "production operation host authority does not match agentd identity".to_string(),
            ));
        }
        self.production_operations.set(host).map_err(|_| {
            AgentdError::Protocol(
                "production operation host was attached more than once".to_string(),
            )
        })
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

    pub(crate) fn attach_automation_effect_host(
        &self,
        host: Arc<crate::automation_effect_host::AgentdAutomationEffectHost>,
    ) -> Result<(), AgentdError> {
        self.automation_effect.set(host).map_err(|_| {
            AgentdError::Protocol("automation effect host was attached more than once".to_string())
        })
    }

    pub(crate) fn automation_effect_host(
        &self,
    ) -> Option<Arc<crate::automation_effect_host::AgentdAutomationEffectHost>> {
        self.automation_effect.get().cloned()
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

    pub(crate) fn prompt_pipeline_owner(&self) -> Arc<crate::AgentdPromptPipelineOwner> {
        Arc::clone(&self.prompt_pipeline)
    }

    pub(crate) fn authbus(
        &self,
    ) -> Result<Option<Arc<crate::authbus_ingress::TextIngress>>, AgentdError> {
        Ok(self.authbus.get().cloned())
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
                runtime.admission_open = false;
            }
            if matches!(
                runtime.lifecycle,
                AgentLifecycle::Draining | AgentLifecycle::Stopped | AgentLifecycle::Failed
            ) {
                runtime.app_server_ready = false;
                runtime.required_ports_ready = false;
            }
            if runtime.lifecycle == AgentLifecycle::Running
                && runtime.app_server_ready
                && runtime.critical_stores_ready
                && runtime.revocation_ready
                && runtime.required_ports_ready
                && !runtime.fenced
            {
                runtime.admission_open = true;
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
            || !runtime.critical_stores_ready
            || !runtime.revocation_ready
            || !runtime.required_ports_ready
            || !runtime.admission_open
            || runtime.fenced
        {
            return Err(AgentdError::GenerationFenced(
                "agentd qualification writer is unavailable until the running App Server is ready"
                    .to_string(),
            ));
        }
        Ok(runtime.current_generation)
    }

    /// Freeze owner-local startup prerequisites under this generation. The
    /// default Agentd composition has zero production effect authority, so a
    /// current zero-authority revocation baseline is sufficient here; any
    /// effect-authorized composition must replace it before opening admission.
    pub(crate) fn mark_runtime_prerequisites_ready(&self) -> Result<(), AgentdError> {
        let critical_stores_ready = self.cognitive.lock().map_err(poisoned_state)?.is_some();
        let mut runtime = self.runtime.lock().map_err(poisoned_state)?;
        runtime.critical_stores_ready = critical_stores_ready;
        runtime.revocation_ready = true;
        Ok(())
    }

    pub(crate) fn mark_app_server_ready(&self) -> Result<(), AgentdError> {
        let mut runtime = self.runtime.lock().map_err(poisoned_state)?;
        if !runtime.app_server_ready {
            runtime.app_server_ready = true;
            runtime.required_ports_ready = true;
            if runtime.lifecycle == AgentLifecycle::Running
                && runtime.critical_stores_ready
                && runtime.revocation_ready
                && !runtime.fenced
            {
                runtime.admission_open = true;
            }
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
        runtime.required_ports_ready = false;
        runtime.admission_open = false;
        self.app_server_drain.request_drain();
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

    pub(crate) fn app_server_drain_handle(&self) -> AppServerDrainHandle {
        self.app_server_drain.clone()
    }

    pub(crate) async fn request_drain(
        &self,
        automation: Option<&AutomationStore>,
    ) -> Result<DrainSnapshot, AgentdError> {
        self.refresh_generation()?;
        {
            let runtime = self.runtime.lock().map_err(poisoned_state)?;
            if runtime.lifecycle != AgentLifecycle::Draining || runtime.fenced {
                return Err(AgentdError::GenerationFenced(
                    "Agentd drain requires the current supervisor generation to be Draining"
                        .to_string(),
                ));
            }
        }
        self.mark_draining()?;
        let automation_blockers = match automation {
            Some(store) => store.drain_blockers().await?,
            None => 1,
        };
        self.drain_snapshot(automation_blockers)
    }

    pub(crate) fn drain_snapshot(
        &self,
        automation_blockers: u32,
    ) -> Result<DrainSnapshot, AgentdError> {
        self.refresh_generation()?;
        let runtime = self.runtime.lock().map_err(poisoned_state)?;
        let running_turns = u32::try_from(self.app_server_drain.running_turns()).map_err(|_| {
            AgentdError::Protocol("running assistant turn count exceeds u32".to_string())
        })?;
        Ok(DrainSnapshot {
            admission_closed: runtime.lifecycle == AgentLifecycle::Draining
                && !runtime.app_server_ready
                && !runtime.fenced,
            running_turns,
            drained: runtime.lifecycle == AgentLifecycle::Draining
                && !runtime.fenced
                && self.app_server_drain.drained()
                && running_turns == 0
                && automation_blockers == 0,
            lifecycle: runtime.lifecycle,
            fenced: runtime.fenced,
        })
    }

    pub(crate) fn mark_fenced(&self) {
        if let Ok(mut runtime) = self.runtime.lock() {
            runtime.app_server_ready = false;
            runtime.required_ports_ready = false;
            runtime.admission_open = false;
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

    /// Observation of already-admitted work is distinct from new admission.
    /// The existing Agent generation and stores must still be current.
    pub(crate) fn automation_recovery_ready(&self) -> Result<bool, AgentdError> {
        self.refresh_generation()?;
        let runtime = self.runtime.lock().map_err(poisoned_state)?;
        Ok(matches!(
            runtime.lifecycle,
            AgentLifecycle::Running | AgentLifecycle::Draining
        ) && runtime.app_server_ready
            && runtime.critical_stores_ready
            && runtime.revocation_ready
            && runtime.required_ports_ready
            && !runtime.fenced)
    }

    pub(crate) fn automation_admission_ready(&self) -> Result<bool, AgentdError> {
        self.refresh_generation()?;
        let runtime = self.runtime.lock().map_err(poisoned_state)?;
        Ok(runtime.lifecycle == AgentLifecycle::Running
            && runtime.app_server_ready
            && runtime.critical_stores_ready
            && runtime.revocation_ready
            && runtime.required_ports_ready
            && runtime.admission_open
            && !runtime.fenced)
    }

    /// Plasticity proposal admission is available only on the live Running
    /// generation after App Server readiness. This fences the long-lived
    /// proposal owner with the same lifecycle boundary as other Agentd work.
    pub(crate) fn plasticity_admission_ready(&self) -> Result<bool, AgentdError> {
        self.refresh_generation()?;
        let runtime = self.runtime.lock().map_err(poisoned_state)?;
        Ok(runtime.lifecycle == AgentLifecycle::Running
            && runtime.app_server_ready
            && !runtime.fenced)
    }
    pub(crate) fn canonical_intelligence_enabled(&self) -> bool {
        self.intelligence_product.get().is_some() && self.intelligence_invocation.get().is_some()
    }

    /// Prepare the exact durable Objective through the configured canonical
    /// seven-owner composition, then atomically freeze its run/context identity
    /// into the sole Agentd run coordinator. None is explicit compatibility
    /// mode: both the runner and host-owned invocation provider must be present
    /// before canonical execution is attempted or advertised.
    pub(crate) async fn start_canonical_intelligence(
        &self,
        record: &RunStartRecordV1,
    ) -> Result<Option<crate::AgentdIntelligenceAdmittedOutcomeV1>, AgentdError> {
        let (runner, provider) =
            match (
                self.intelligence_product.get(),
                self.intelligence_invocation.get(),
            ) {
                (None, None) => return Ok(None),
                (Some(runner), Some(provider)) => (runner, provider),
                _ => return Err(AgentdError::Invalid(
                    "incomplete canonical intelligence attachment; refusing compatibility fallback"
                        .to_string(),
                )),
            };

        self.require_current_run_start(record)?;
        let invocation = runner
            .build_invocation(Arc::clone(provider), self.identity.clone(), record.clone())
            .await?;
        let now_ms = self.require_current_run_start(record)?;
        let durable_snapshot =
            crate::RunSnapshot::from_revalidated_run_start(record).map_err(run_error)?;
        let remaining_ms = durable_snapshot
            .deadline_ms
            .min(record.authentication.expires_at_ms)
            .checked_sub(now_ms)
            .filter(|value| *value > 0)
            .ok_or_else(|| {
                AgentdError::Invalid("RunStart expired during owner input production".to_string())
            })?;

        // Freeze only the small immutable composition while holding the run
        // lock. Owner execution is allowed to block without monopolizing run
        // lifecycle operations.
        let composition = self
            .runs
            .lock()
            .map_err(poisoned_state)?
            .composition()
            .clone();
        let outcome = tokio::time::timeout(
            std::time::Duration::from_millis(remaining_ms),
            runner.prepare_for_composition(&composition, invocation.request, invocation.inputs),
        )
        .await
        .map_err(|_| {
            AgentdError::Protocol("RunStart expired during canonical preparation".to_string())
        })?
        .map_err(|error| {
            AgentdError::Protocol(format!(
                "canonical intelligence preparation failed: {error}"
            ))
        })?;

        match outcome {
            crate::AgentdIntelligenceProductOutcomeV1::Ready(mut prepared) => {
                // Owner preparation is asynchronous. Revalidate the durable
                // signed Objective and Fleet fence again after it completes,
                // twice as the compatibility path does at its final boundary.
                let first_now = self.require_current_run_start(record)?;
                let second_now = self.require_current_run_start(record)?;
                let now_ms = first_now.max(second_now);
                prepared
                    .bind_revalidated_run_start(record, now_ms)
                    .map_err(|error| {
                        AgentdError::Protocol(format!("canonical RunStart binding failed: {error}"))
                    })?;
                let snapshot = prepared.run_snapshot();
                let attachment = prepared.context_attachment();
                let mut runs = self.runs.lock().map_err(poisoned_state)?;
                let admitted = runs.start_run(now_ms, snapshot.into()).map_err(run_error)?;
                let run_receipt = runs
                    .attach_context(now_ms, admitted.revision, attachment.into())
                    .map_err(run_error)?;
                Ok(Some(crate::AgentdIntelligenceAdmittedOutcomeV1::Ready {
                    prepared,
                    run_receipt,
                }))
            }
            crate::AgentdIntelligenceProductOutcomeV1::Abstained => {
                Ok(Some(crate::AgentdIntelligenceAdmittedOutcomeV1::Abstained))
            }
            crate::AgentdIntelligenceProductOutcomeV1::SlowPath => {
                Ok(Some(crate::AgentdIntelligenceAdmittedOutcomeV1::SlowPath))
            }
        }
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
        self.start_current_run_start_record(record)
    }

    pub(crate) fn start_current_run_start_record(
        &self,
        record: &RunStartRecordV1,
    ) -> Result<RunReceipt, AgentdError> {
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
        let current_generation = self
            .runtime
            .lock()
            .map_err(poisoned_state)?
            .current_generation;
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
        if !crate::objective_runtime::authentication_is_current(
            record,
            &trust,
            &self.identity,
            now_ms,
        )? {
            return Err(AgentdError::Invalid(
                "durable run-start authentication is not current".to_string(),
            ));
        }
        if let Some(owner) = self.objective_runtime.get() {
            owner.revalidate_projection(record, &self.identity)?;
        }
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

pub(crate) fn objective_run_fence(identity: &AgentdIdentity, current_generation: u64) -> String {
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
