/// Host-owned builder for the exact V2 Neuron tick bound to a canonical
/// intelligence request. Request bytes cannot install or replace this provider.
pub trait AgentdNeuronTickProviderV2: Send + Sync {
    fn build_tick(
        &self,
        identity: &crate::AgentdIdentity,
        record: &codex_hepta_agent_components::learning_ledger::RunStartRecordV1,
        invocation: &crate::AgentdIntelligenceInvocationV1,
    ) -> Result<NeuronTickInputV1, crate::AgentdError>;
}

/// One explicitly supplied active generation plus sealed historical
/// generations. Constructing this value does not start service; Agentd owns
/// recovery and activation when its normal daemon lifecycle starts.
pub struct AgentdNeuronRuntimeV2Config {
    active: AgentdNeuronHandleV2,
    retained: Vec<AgentdNeuronHandleV2>,
    control_state_path: PathBuf,
    tick_provider: Arc<dyn AgentdNeuronTickProviderV2>,
}

impl AgentdNeuronRuntimeV2Config {
    pub fn new(
        active: AgentdNeuronHandleV2,
        control_state_path: PathBuf,
        tick_provider: Arc<dyn AgentdNeuronTickProviderV2>,
    ) -> Result<Self, crate::AgentdError> {
        if !control_state_path.is_absolute() || control_state_path.file_name().is_none() {
            return Err(crate::AgentdError::Invalid(
                "Neuron V2 control-state path must be an absolute file path".to_string(),
            ));
        }
        Ok(Self {
            active,
            retained: Vec::new(),
            control_state_path,
            tick_provider,
        })
    }

    #[must_use]
    pub fn with_retained_generation(mut self, retained: AgentdNeuronHandleV2) -> Self {
        self.retained.push(retained);
        self
    }

    pub(crate) fn start(self) -> Result<Arc<AgentdNeuronRuntimeV2Host>, crate::AgentdError> {
        self.start_inner(false)
    }

    pub(crate) fn start_for_iteration_recovery(
        self,
    ) -> Result<Arc<AgentdNeuronRuntimeV2Host>, crate::AgentdError> {
        self.start_inner(true)
    }

    fn start_inner(
        self,
        iteration_recovery: bool,
    ) -> Result<Arc<AgentdNeuronRuntimeV2Host>, crate::AgentdError> {
        let controller =
            AgentdNeuronGenerationControllerV2::from_recovered_generations_with_state_path(
                self.active,
                self.retained,
                self.control_state_path,
            )
            .map_err(|error| neuron_product_error("recover controller", error))?;
        let lifecycle = controller
            .state()
            .map_err(|error| neuron_product_error("read recovered lifecycle", error))?;
        match lifecycle {
            AgentdNeuronLifecycleStateV2::Starting => controller.start(),
            AgentdNeuronLifecycleStateV2::Stopped => controller.restart_stopped(),
            AgentdNeuronLifecycleStateV2::Quiescing | AgentdNeuronLifecycleStateV2::Sealed
                if iteration_recovery =>
            {
                Ok(())
            }
            state => {
                return Err(crate::AgentdError::Protocol(format!(
                    "Neuron V2 recovered in {state:?}; explicit operator recovery is required"
                )));
            }
        }
        .map_err(|error| neuron_product_error("start controller", error))?;
        Ok(Arc::new(AgentdNeuronRuntimeV2Host {
            controller,
            tick_provider: self.tick_provider,
            lifecycle: Mutex::new(()),
            stopped: AtomicBool::new(false),
            iteration_quarantine: AtomicBool::new(iteration_recovery),
        }))
    }
}

/// The sole process owner for V2 execution and lifecycle transitions. Request
/// handlers receive only prepared invocations; they cannot mutate generations.
pub struct AgentdNeuronRuntimeV2Host {
    controller: AgentdNeuronGenerationControllerV2,
    tick_provider: Arc<dyn AgentdNeuronTickProviderV2>,
    lifecycle: Mutex<()>,
    stopped: AtomicBool,
    iteration_quarantine: AtomicBool,
}

impl AgentdNeuronRuntimeV2Host {
    pub(crate) fn prepare(
        &self,
        identity: &crate::AgentdIdentity,
        record: &codex_hepta_agent_components::learning_ledger::RunStartRecordV1,
        invocation: &crate::AgentdIntelligenceInvocationV1,
    ) -> Result<AgentdNeuronInvocationV2, crate::AgentdError> {
        if self.stopped.load(Ordering::Acquire) || self.iteration_quarantine.load(Ordering::Acquire)
        {
            return Err(crate::AgentdError::Protocol(
                "Neuron V2 runtime is stopped".to_string(),
            ));
        }
        let input = self
            .tick_provider
            .build_tick(identity, record, invocation)?;
        invocation.validate(identity, record)?;
        let runtime_body_digest = record.runtime_body_digest;
        self.controller
            .prepare(
                invocation.request.run_id.clone(),
                runtime_body_digest,
                input,
            )
            .map_err(|error| neuron_product_error("prepare invocation", error))
    }

    pub(crate) fn begin_quiesce(&self) -> Result<(), crate::AgentdError> {
        let _lifecycle = self.lifecycle.lock().map_err(|_| {
            crate::AgentdError::Protocol("Neuron V2 lifecycle lock poisoned".to_string())
        })?;
        match self
            .controller
            .state()
            .map_err(|error| neuron_product_error("read controller state", error))?
        {
            AgentdNeuronLifecycleStateV2::Serving => self
                .controller
                .begin_quiesce()
                .map_err(|error| neuron_product_error("begin quiesce", error)),
            AgentdNeuronLifecycleStateV2::Quiescing
            | AgentdNeuronLifecycleStateV2::Sealed
            | AgentdNeuronLifecycleStateV2::Stopped => Ok(()),
            state => Err(crate::AgentdError::Protocol(format!(
                "Neuron V2 cannot quiesce from {state:?}"
            ))),
        }
    }

    pub(crate) fn shutdown(&self) -> Result<(), crate::AgentdError> {
        if self.stopped.load(Ordering::Acquire) {
            return Ok(());
        }
        let _lifecycle = self.lifecycle.lock().map_err(|_| {
            crate::AgentdError::Protocol("Neuron V2 lifecycle lock poisoned".to_string())
        })?;
        if self.stopped.load(Ordering::Acquire) {
            return Ok(());
        }
        self.controller
            .shutdown()
            .map_err(|error| neuron_product_error("shutdown controller", error))?;
        self.stopped.store(true, Ordering::Release);
        Ok(())
    }
}

impl Drop for AgentdNeuronRuntimeV2Host {
    fn drop(&mut self) {
        if !self.stopped.load(Ordering::Acquire) {
            let _ = self.controller.shutdown();
        }
    }
}

fn neuron_product_error(operation: &str, error: AgentdNeuronControlErrorV2) -> crate::AgentdError {
    crate::AgentdError::Protocol(format!(
        "Neuron V2 {operation} failed [{}]: {error}",
        error.stable_code()
    ))
}

impl AgentdNeuronRuntimeV2Host {
    pub(crate) fn quarantine_iteration(&self) -> Result<(), crate::AgentdError> {
        self.iteration_quarantine.store(true, Ordering::Release);
        self.begin_quiesce()
    }
    pub(crate) fn release_iteration_quarantine(&self) -> Result<(), crate::AgentdError> {
        if self
            .controller
            .state()
            .map_err(|error| neuron_product_error("iteration state", error))?
            != AgentdNeuronLifecycleStateV2::Serving
        {
            return Err(crate::AgentdError::Protocol(
                "iteration runtime is not serving".into(),
            ));
        }
        self.iteration_quarantine.store(false, Ordering::Release);
        Ok(())
    }
    pub(crate) fn install_iteration_generation(
        &self,
        next: AgentdNeuronHandleV2,
        expected_previous: u64,
    ) -> Result<(), crate::AgentdError> {
        let _lifecycle = self
            .lifecycle
            .try_lock()
            .map_err(|_| crate::AgentdError::Protocol("iteration lifecycle busy".into()))?;
        if self.stopped.load(Ordering::Acquire)
            || !self.iteration_quarantine.load(Ordering::Acquire)
        {
            return Err(crate::AgentdError::Protocol(
                "iteration host is stopped or not quarantined".into(),
            ));
        }
        let active = self
            .controller
            .active_generation()
            .map_err(|error| neuron_product_error("active generation", error))?;
        let target = next
            .generation()
            .map_err(|error| neuron_product_error("target generation", error))?;
        if active == target {
            let current = self
                .controller
                .operational_snapshot()
                .map_err(|error| neuron_product_error("iteration snapshot", error))?;
            if current.body_bundle_digest
                != next.body_bundle_digest().map(|digest| digest.to_string())
            {
                return Err(crate::AgentdError::Protocol(
                    "recovered generation content changed".into(),
                ));
            }
            let lifecycle = self
                .controller
                .state()
                .map_err(|error| neuron_product_error("iteration state", error))?;
            if lifecycle == AgentdNeuronLifecycleStateV2::Quiescing {
                // Recovery froze an installed generation while awaiting its
                // independent canary evidence. Seal it; explicit start below
                // restores its execution gate only for owner-controlled probes.
                self.controller
                    .seal()
                    .map_err(|error| neuron_product_error("recovery seal", error))?;
            }
            if matches!(
                lifecycle,
                AgentdNeuronLifecycleStateV2::Quiescing | AgentdNeuronLifecycleStateV2::Sealed
            ) {
                self.controller
                    .resume_sealed_for_iteration()
                    .map_err(|error| neuron_product_error("recovery start", error))?;
            } else if lifecycle != AgentdNeuronLifecycleStateV2::Serving {
                return Err(crate::AgentdError::Protocol(
                    "recovered iteration lifecycle cannot execute".into(),
                ));
            }
            return Ok(());
        }
        if active != expected_previous {
            return Err(crate::AgentdError::Protocol(
                "iteration predecessor changed".into(),
            ));
        }
        if self
            .controller
            .state()
            .map_err(|error| neuron_product_error("iteration state", error))?
            == AgentdNeuronLifecycleStateV2::Serving
        {
            self.controller
                .begin_quiesce()
                .map_err(|error| neuron_product_error("iteration quiesce", error))?;
        }
        if self
            .controller
            .state()
            .map_err(|error| neuron_product_error("iteration state", error))?
            != AgentdNeuronLifecycleStateV2::Sealed
        {
            self.controller
                .seal()
                .map_err(|error| neuron_product_error("iteration seal", error))?;
        }
        self.controller
            .reload(next)
            .map_err(|error| neuron_product_error("iteration reload", error))
    }
    pub(crate) fn prepare_iteration_probe(
        &self,
        run_id: StableId,
        body: Digest32,
        input: NeuronTickInputV1,
    ) -> Result<AgentdNeuronInvocationV2, crate::AgentdError> {
        if !self.iteration_quarantine.load(Ordering::Acquire) {
            return Err(crate::AgentdError::Protocol(
                "canary quarantine missing".into(),
            ));
        }
        self.controller
            .prepare(run_id, body, input)
            .map_err(|error| neuron_product_error("iteration probe", error))
    }
}

impl AgentdNeuronRuntimeV2Host {
    pub fn generation_snapshot(
        &self,
    ) -> Result<AgentdNeuronGenerationControllerSnapshotV2, crate::AgentdError> {
        self.controller
            .controller_snapshot()
            .map_err(|error| neuron_product_error("generation snapshot", error))
    }
}
