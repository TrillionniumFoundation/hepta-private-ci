/// Installed composition alone supplies this factory. It must derive a fresh
/// scope from the durable RunStart and actual canonical stage, retain the same
/// physical model owner, and attach current model-use admission. Request bytes
/// cannot construct or replace this capability. The sole host performs CAS.
pub trait AgentdNeuronGoalScopeFactoryV3: Send + Sync {
    fn open_goal_scope(
        &self,
        identity: &crate::AgentdIdentity,
        record: &codex_hepta_agent_components::learning_ledger::RunStartRecordV1,
        invocation: &crate::AgentdIntelligenceInvocationV1,
        stage: &codex_hepta_agent_components::intelligence::CanonicalPortInputV1,
        expected: &AgentdNeuronGoalScopeV3,
    ) -> Result<AgentdNeuronHandleV2, crate::AgentdError>;
}

struct RecoveredGoalScopesV3 {
    active: AgentdNeuronGoalScopeV3,
    retained: Vec<(AgentdNeuronGoalScopeV3, AgentdNeuronHandleV2)>,
    factory: Arc<dyn AgentdNeuronGoalScopeFactoryV3>,
}

impl AgentdNeuronRuntimeV2Config {
    /// Explicit installed Goal mode preserves the legacy model-generation
    /// constructor and all V1 headers. Ordinals never become model generations.
    pub fn with_goal_scope_factory_v3(
        mut self,
        active: AgentdNeuronGoalScopeV3,
        factory: Arc<dyn AgentdNeuronGoalScopeFactoryV3>,
    ) -> Result<Self, crate::AgentdError> {
        if self.goal_scopes.is_some()
            || !self.retained.is_empty()
            || AgentdNeuronGoalScopeV3::capture(active.ordinal, &self.active)
                .map_err(|error| neuron_product_error("capture active Goal scope", error))?
                != active
        {
            return Err(crate::AgentdError::Invalid(
                "Goal factory does not match the sole active owner".into(),
            ));
        }
        self.goal_scopes = Some(RecoveredGoalScopesV3 {
            active,
            retained: Vec::new(),
            factory,
        });
        Ok(self)
    }

    pub fn with_retained_goal_scope_v3(
        mut self,
        scope: AgentdNeuronGoalScopeV3,
        handle: AgentdNeuronHandleV2,
    ) -> Result<Self, crate::AgentdError> {
        let scopes = self.goal_scopes.as_mut().ok_or_else(|| {
            crate::AgentdError::Invalid("retained Goal scope requires explicit Goal mode".into())
        })?;
        scopes.retained.push((scope, handle));
        Ok(self)
    }
}

impl AgentdNeuronRuntimeV2Host {
    fn ensure_goal_scope_v3(
        &self,
        identity: &crate::AgentdIdentity,
        record: &codex_hepta_agent_components::learning_ledger::RunStartRecordV1,
        invocation: &crate::AgentdIntelligenceInvocationV1,
        stage: &codex_hepta_agent_components::intelligence::CanonicalPortInputV1,
    ) -> Result<(), NeuronRuntimeV2Error> {
        let Some(factory) = self.goal_scope_factory.as_ref() else {
            return Ok(());
        };
        let unavailable = || NeuronRuntimeV2Error::Admission(NeuronAdmissionError::Unavailable);
        let denied = || NeuronRuntimeV2Error::Admission(NeuronAdmissionError::BindingMismatch);
        let _lifecycle = self.lifecycle.try_lock().map_err(|_| unavailable())?;
        if self.stopped.load(Ordering::Acquire) || self.iteration_quarantine.load(Ordering::Acquire)
        {
            return Err(NeuronRuntimeV2Error::Admission(
                NeuronAdmissionError::Revoked,
            ));
        }
        invocation
            .validate(identity, record)
            .map_err(|_| denied())?;
        let state = self
            .controller
            .goal_scope_state_v3()
            .map_err(compatibility_error)?;
        let expected = state.active_scope;
        let scope = NeuronTickInputV1::journal_scope_for_subject(
            &StableId::new(identity.agent_id.as_str()).map_err(|_| denied())?,
            stage.objective_digest,
        )
        .map_err(|_| denied())?;
        if expected.identity.subject_scope_digest != scope.scope_digest
            || expected.identity.body_bundle_digest != record.runtime_body_digest
            || expected.identity.model_generation
                != invocation.request.snapshot.body_generation().get()
        {
            return Err(denied());
        }
        if expected.identity.objective_digest == stage.objective_digest {
            return if state.lifecycle == AgentdNeuronLifecycleStateV2::Serving {
                Ok(())
            } else {
                Err(unavailable())
            };
        }
        if !matches!(
            state.lifecycle,
            AgentdNeuronLifecycleStateV2::Serving
                | AgentdNeuronLifecycleStateV2::Quiescing
                | AgentdNeuronLifecycleStateV2::Sealed
        ) {
            return Err(unavailable());
        }
        if state.lifecycle == AgentdNeuronLifecycleStateV2::Serving {
            self.controller
                .current_tick_anchor()
                .map_err(compatibility_error)?;
        }
        let next = factory
            .open_goal_scope(identity, record, invocation, stage, &expected)
            .map_err(|_| unavailable())?;
        let next_scope = AgentdNeuronGoalScopeV3::capture(
            expected
                .ordinal
                .checked_add(1)
                .ok_or(NeuronRuntimeV2Error::Arithmetic)?,
            &next,
        )
        .map_err(compatibility_error)?;
        let mut desired = expected.identity.clone();
        desired.objective_digest = stage.objective_digest;
        if next_scope.identity != desired {
            return Err(denied());
        }
        // Admission is current before closing any old gate, and reload checks
        // it again after drain/reconciliation and immediately before publication.
        next.validate_goal_scope_admission()
            .map_err(compatibility_error)?;
        if state.lifecycle == AgentdNeuronLifecycleStateV2::Serving {
            self.controller
                .begin_quiesce()
                .map_err(compatibility_error)?;
        }
        if state.lifecycle != AgentdNeuronLifecycleStateV2::Sealed {
            self.controller.seal().map_err(compatibility_error)?;
        }
        self.controller
            .reload_goal_scope_v3(&expected, next)
            .map_err(compatibility_error)
    }
}
