// Read current eligibility through the original Serving controller. A prior
// operation's prepared bytes and retired archives cannot supply this fact.
impl AgentdNeuronGenerationControllerV2 {
    pub fn current_sparse_checkpoint_v2(
        &self,
        generation: AgentdNeuronGenerationIdV2,
        configuration: Digest32,
        body: Digest32,
        scope: codex_hepta_agent_components::neuron::JournalScope,
        required_anchor: codex_hepta_agent_components::neuron::JournalAnchor,
    ) -> Result<
        Option<codex_hepta_agent_components::neuron::SparseCheckpoint>,
        AgentdNeuronControlErrorV2,
    > {
        let state = self.lock_state()?;
        if state.lifecycle != AgentdNeuronLifecycleStateV2::Serving {
            return Err(AgentdNeuronControlErrorV2::NotServing);
        }
        if state.active.generation()? != generation.get()
            || state.active.configuration_digest() != configuration
            || state.active.body_bundle_digest() != Some(body)
        {
            return Err(AgentdNeuronControlErrorV2::GenerationConflict);
        }
        let (actual_generation, actual_scope, checkpoint) = state
            .active
            .owner
            .current_sparse_checkpoint_control(required_anchor)?;
        if actual_generation.get() != generation.get() || actual_scope != scope {
            return Err(AgentdNeuronControlErrorV2::GenerationConflict);
        }
        Ok(checkpoint)
    }
}
impl AgentdNeuronRuntimeV2Host {
    pub(crate) fn parameter_serving_scope_observation(
        &self,
    ) -> Result<
        (
            u64,
            Digest32,
            Digest32,
            codex_hepta_agent_components::neuron::JournalScope,
            Option<u64>,
        ),
        crate::AgentdError,
    > {
        let _lifecycle = self
            .lifecycle
            .try_lock()
            .map_err(|_| crate::AgentdError::Overloaded {
                retry_after_ms: 1_000,
            })?;
        if self.stopped.load(Ordering::Acquire) || self.iteration_quarantine.load(Ordering::Acquire)
        {
            return Err(crate::AgentdError::Invalid(
                "scope original owner unavailable".into(),
            ));
        }
        let observe = || -> Result<_, crate::AgentdError> {
            let (lifecycle, owner, goal) = self
                .controller
                .current_installed_owner_v3()
                .map_err(|e| neuron_product_error("scope original controller", e))?;
            if lifecycle != AgentdNeuronLifecycleStateV2::Serving {
                return Err(crate::AgentdError::Invalid(
                    "scope original owner not Serving".into(),
                ));
            }
            owner
                .validate_goal_scope_admission()
                .map_err(|e| neuron_product_error("scope original admission", e))?;
            let identity = owner
                .scope_identity()
                .map_err(|e| neuron_product_error("scope original held identity", e))?;
            let scope = codex_hepta_agent_components::neuron::JournalScope {
                scope_digest: identity.subject_scope_digest,
                objective_digest: identity.objective_digest,
            };
            let tuple = (
                identity.model_generation,
                identity.runtime_configuration_digest,
                identity.body_bundle_digest,
                scope,
                goal.as_ref().map(|g| g.ordinal),
            );
            if let Some(goal) = goal
                && (goal.identity != identity || goal.ordinal == 0)
            {
                return Err(crate::AgentdError::Invalid(
                    "scope original Goal identity differs".into(),
                ));
            }
            Ok((tuple, owner))
        };
        let (before, owner) = observe()?;
        let (after, after_owner) = observe()?;
        if before != after || !Arc::ptr_eq(&owner.owner, &after_owner.owner) {
            return Err(crate::AgentdError::Invalid(
                "scope original active tuple changed".into(),
            ));
        }
        Ok(before)
    }
    /// Read one current whole checkpoint under the original lifecycle owner.
    /// Neither the physical stores nor a Goal driver are opened or dispatched.
    pub(crate) fn prepare_parameter_checkpoint_observation(
        &self,
        material: &codex_hepta_agent_components::neuron::NeuronGenerationMaterialV2,
    ) -> Result<
        (
            codex_hepta_agent_components::neuron::JournalAnchor,
            Vec<u8>,
            Option<u64>,
        ),
        crate::AgentdError,
    > {
        let _lifecycle = self
            .lifecycle
            .try_lock()
            .map_err(|_| crate::AgentdError::Overloaded {
                retry_after_ms: 1_000,
            })?;
        if self.stopped.load(Ordering::Acquire) || self.iteration_quarantine.load(Ordering::Acquire)
        {
            return Err(crate::AgentdError::Invalid(
                "checkpoint owner is not available".into(),
            ));
        }
        codex_hepta_agent_components::neuron::validate_neuron_generation_material_v2(material)
            .map_err(|e| crate::AgentdError::Invalid(e.to_string()))?;
        let (lifecycle, original_owner, goal) = self
            .controller
            .current_installed_owner_v3()
            .map_err(|e| neuron_product_error("checkpoint installed owner", e))?;
        if lifecycle != AgentdNeuronLifecycleStateV2::Serving {
            return Err(crate::AgentdError::Invalid(
                "checkpoint owner not Serving".into(),
            ));
        }
        let original_identity = original_owner
            .scope_identity()
            .map_err(|e| neuron_product_error("checkpoint original identity", e))?;
        original_owner
            .validate_goal_scope_admission()
            .map_err(|e| neuron_product_error("checkpoint installed admission", e))?;
        let (generation, before) = self
            .controller
            .current_tick_anchor()
            .map_err(|e| neuron_product_error("actual checkpoint ACK", e))?;
        let anchor = before
            .ok_or_else(|| crate::AgentdError::Invalid("checkpoint has no actual ACK".into()))?;
        if generation != material.runtime.generation {
            return Err(crate::AgentdError::Invalid(
                "checkpoint active generation differs".into(),
            ));
        }
        let body = material
            .body
            .semantic_digest()
            .map_err(|e| crate::AgentdError::Invalid(e.to_string()))?;
        let checkpoint = self
            .controller
            .current_sparse_checkpoint_v2(
                AgentdNeuronGenerationIdV2::from_generation(generation),
                material
                    .runtime
                    .semantic_digest()
                    .map_err(|e| crate::AgentdError::Invalid(e.to_string()))?,
                body,
                material.scope,
                anchor,
            )
            .map_err(|e| neuron_product_error("same original full checkpoint", e))?
            .ok_or_else(|| crate::AgentdError::Invalid("checkpoint ACK state missing".into()))?;
        let bytes = checkpoint
            .encode_observation_v1()
            .map_err(|e| crate::AgentdError::Protocol(e.to_string()))?;
        codex_hepta_agent_components::neuron::SparseCheckpoint::decode_observation_v1(
            &bytes,
            Digest32::of_bytes(&bytes),
            &material.native,
            material.scope,
            body,
            anchor,
        )
        .map_err(|e| crate::AgentdError::Protocol(e.to_string()))?;
        let after = self
            .controller
            .current_tick_anchor()
            .map_err(|e| neuron_product_error("final actual checkpoint ACK", e))?;
        if after != (generation, Some(anchor)) {
            return Err(crate::AgentdError::Invalid(
                "checkpoint actual ACK changed".into(),
            ));
        }
        let (after_lifecycle, after_owner, after_goal) = self
            .controller
            .current_installed_owner_v3()
            .map_err(|e| neuron_product_error("checkpoint final original owner", e))?;
        after_owner
            .validate_goal_scope_admission()
            .map_err(|e| neuron_product_error("checkpoint final original admission", e))?;
        if after_lifecycle != lifecycle
            || after_goal != goal
            || after_owner
                .scope_identity()
                .map_err(|e| neuron_product_error("checkpoint final original identity", e))?
                != original_identity
            || !Arc::ptr_eq(&original_owner.owner, &after_owner.owner)
        {
            return Err(crate::AgentdError::Invalid(
                "checkpoint active whole identity changed".into(),
            ));
        }
        Ok((anchor, bytes, goal.map(|g| g.ordinal)))
    }

    /// Read current owner state without holding the Goal driver or dispatching.
    pub fn current_sparse_checkpoint_v2(
        &self,
        generation: AgentdNeuronGenerationIdV2,
        configuration: Digest32,
        body: Digest32,
        scope: codex_hepta_agent_components::neuron::JournalScope,
        required_anchor: codex_hepta_agent_components::neuron::JournalAnchor,
    ) -> Result<Option<codex_hepta_agent_components::neuron::SparseCheckpoint>, crate::AgentdError>
    {
        self.controller
            .current_sparse_checkpoint_v2(generation, configuration, body, scope, required_anchor)
            .map_err(|error| neuron_product_error("current sparse checkpoint inspection", error))
    }
}
