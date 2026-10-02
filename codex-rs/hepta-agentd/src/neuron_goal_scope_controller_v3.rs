struct GoalScopeTopologyV3 {
    active_ordinal: u64,
    reload_target: Option<AgentdNeuronGoalScopeV3>,
}

impl AgentdNeuronGenerationControllerStateV2 {
    fn goal_scope_state(
        &self,
        lifecycle: AgentdNeuronLifecycleStateV2,
    ) -> Result<AgentdNeuronGoalScopeStateV3, AgentdNeuronControlStateErrorV2> {
        let topology = self
            .goal_scope
            .as_ref()
            .ok_or(AgentdNeuronControlStateErrorV2::Invalid)?;
        let capture = |ordinal, handle: &AgentdNeuronHandleV2| {
            AgentdNeuronGoalScopeV3::capture(ordinal, handle)
                .map_err(|_| AgentdNeuronControlStateErrorV2::Invalid)
        };
        AgentdNeuronGoalScopeStateV3::new(
            lifecycle,
            capture(topology.active_ordinal, &self.active)?,
            self.retained
                .iter()
                .map(|(ordinal, handle)| capture(*ordinal, handle))
                .collect::<Result<Vec<_>, _>>()?,
            if lifecycle == AgentdNeuronLifecycleStateV2::Reloading {
                topology.reload_target.clone()
            } else {
                None
            },
        )
    }
}

impl AgentdNeuronGenerationControllerV2 {
    /// Reopen exact V3 scope owners under the same sole controller. A new file
    /// starts only at slot one. Ordinals never replace actual model generation.
    pub fn from_recovered_goal_scopes_v3(
        active_scope: AgentdNeuronGoalScopeV3,
        active: AgentdNeuronHandleV2,
        retained: impl IntoIterator<Item = (AgentdNeuronGoalScopeV3, AgentdNeuronHandleV2)>,
        state_path: impl AsRef<Path>,
    ) -> Result<Self, AgentdNeuronControlErrorV2> {
        let path = state_path.as_ref();
        if AgentdNeuronGoalScopeV3::capture(active_scope.ordinal, &active)? != active_scope {
            return Err(AgentdNeuronControlErrorV2::GenerationConflict);
        }
        let archives = archive_store::GenerationArchiveStore::open(
            path,
            archive_store::DEFAULT_MAX_TOTAL_BYTES,
        )?;
        let mut owners = BTreeMap::new();
        for (scope, handle) in retained {
            if scope.ordinal >= active_scope.ordinal
                || AgentdNeuronGoalScopeV3::capture(scope.ordinal, &handle)? != scope
                || owners.insert(scope.ordinal, handle).is_some()
            {
                return Err(AgentdNeuronControlErrorV2::GenerationConflict);
            }
        }
        if owners.len() > MAX_RETAINED_NEURON_GENERATION_OWNERS_V2 {
            return Err(AgentdNeuronControlErrorV2::PendingRecovery);
        }
        let mut state = AgentdNeuronGenerationControllerStateV2 {
            lifecycle: AgentdNeuronLifecycleStateV2::Starting,
            active,
            retained: owners,
            reload_target_generation: None,
            state_path: Some(path.to_owned()),
            archives: Some(archives),
            goal_scope: Some(GoalScopeTopologyV3 {
                active_ordinal: active_scope.ordinal,
                reload_target: None,
            }),
        };
        let live = state
            .goal_scope_state(AgentdNeuronLifecycleStateV2::Starting)
            .map_err(poison_control_state)?;
        state.lifecycle = if generation_state_exists(path).map_err(poison_control_state)? {
            let persisted =
                read_agentd_neuron_goal_scope_state_v3(path).map_err(poison_control_state)?;
            resolve_recovered_goal_scope_v3(&persisted, &live)?
        } else if active_scope.ordinal == 1 && live.retained_scopes.is_empty() {
            AgentdNeuronLifecycleStateV2::Starting
        } else {
            return Err(AgentdNeuronControlErrorV2::GenerationConflict);
        };
        // Validate complete topology before fencing caller clones. Startup may
        // reopen only the active gate, after fresh admission and reconciliation.
        state.active.close_lifecycle_gate()?;
        for handle in state.retained.values() {
            handle.close_lifecycle_gate()?;
        }
        state
            .persist_transition(state.lifecycle, None)
            .map_err(poison_control_state)?;
        Ok(Self {
            state: Mutex::new(state),
        })
    }

    pub fn goal_scope_state_v3(
        &self,
    ) -> Result<AgentdNeuronGoalScopeStateV3, AgentdNeuronControlErrorV2> {
        let state = self.lock_state()?;
        state
            .goal_scope_state(state.lifecycle)
            .map_err(poison_control_state)
    }

    /// Explicit scope lookup avoids confusing several goals on model one with
    /// generation-one lookup. A topology DTO grants no execution authority.
    pub fn query_goal_scope_operation_v3(
        &self,
        expected_scope: &AgentdNeuronGoalScopeV3,
        tick_id: &StableId,
        input_digest: Digest32,
    ) -> Result<NeuronOperationStatusV2, AgentdNeuronControlErrorV2> {
        let handle = {
            let state = self.lock_state()?;
            let topology = state
                .goal_scope
                .as_ref()
                .ok_or(AgentdNeuronControlErrorV2::GenerationConflict)?;
            let handle = if expected_scope.ordinal == topology.active_ordinal {
                &state.active
            } else {
                state
                    .retained
                    .get(&expected_scope.ordinal)
                    .ok_or(AgentdNeuronControlErrorV2::UnknownGeneration)?
            };
            if AgentdNeuronGoalScopeV3::capture(expected_scope.ordinal, handle)? != *expected_scope
            {
                return Err(AgentdNeuronControlErrorV2::GenerationConflict);
            }
            handle.clone()
        };
        handle.query_operation_control(tick_id, input_digest)
    }

    /// Exact current-scope CAS through the existing quiesce/seal/drain gates.
    /// The successor may use the same model; it still needs independent fresh
    /// scope admission and its own strictly bound journal/header.
    pub fn reload_goal_scope_v3(
        &self,
        expected: &AgentdNeuronGoalScopeV3,
        next: AgentdNeuronHandleV2,
    ) -> Result<(), AgentdNeuronControlErrorV2> {
        let next_scope = AgentdNeuronGoalScopeV3::capture(
            expected
                .ordinal
                .checked_add(1)
                .ok_or(AgentdNeuronControlErrorV2::GenerationConflict)?,
            &next,
        )?;
        {
            let state = self.lock_state()?;
            let current = state
                .goal_scope_state(state.lifecycle)
                .map_err(poison_control_state)?;
            if state.lifecycle != AgentdNeuronLifecycleStateV2::Sealed
                || current.active_scope != *expected
            {
                return Err(AgentdNeuronControlErrorV2::GenerationConflict);
            }
            AgentdNeuronGoalScopeStateV3::new(
                AgentdNeuronLifecycleStateV2::Reloading,
                expected.clone(),
                current.retained_scopes,
                Some(next_scope.clone()),
            )
            .map_err(poison_control_state)?;
            if state.retained.len() >= MAX_RETAINED_NEURON_GENERATION_OWNERS_V2 {
                return Err(AgentdNeuronControlErrorV2::PendingRecovery);
            }
        }
        next.validate_goal_scope_admission()?;
        {
            let mut state = self.lock_state()?;
            if state.lifecycle != AgentdNeuronLifecycleStateV2::Sealed
                || state
                    .goal_scope_state(state.lifecycle)
                    .map_err(poison_control_state)?
                    .active_scope
                    != *expected
            {
                return Err(AgentdNeuronControlErrorV2::InvalidTransition);
            }
            next.close_lifecycle_gate()?;
            state
                .goal_scope
                .as_mut()
                .ok_or(AgentdNeuronControlErrorV2::GenerationConflict)?
                .reload_target = Some(next_scope.clone());
            if let Err(error) =
                state.persist_transition(AgentdNeuronLifecycleStateV2::Reloading, None)
            {
                state
                    .goal_scope
                    .as_mut()
                    .ok_or(AgentdNeuronControlErrorV2::GenerationConflict)?
                    .reload_target = None;
                return Err(poison_control_state(error));
            }
            state.lifecycle = AgentdNeuronLifecycleStateV2::Reloading;
        }
        let ready = (|| {
            let _drain = next.try_drain_lifecycle_gate()?;
            next.reconcile_control()?;
            let snapshot = next.operational_snapshot()?;
            if snapshot.pending_operation_code.is_some() || snapshot.pending_witness_count != 0 {
                return Err(AgentdNeuronControlErrorV2::PendingRecovery);
            }
            next.validate_goal_scope_admission()
        })();
        if let Err(error) = ready {
            self.restore_goal_scope_sealed_v3(expected, &next_scope)?;
            return Err(error);
        }
        let mut state = self.lock_state()?;
        let current = state
            .goal_scope_state(state.lifecycle)
            .map_err(poison_control_state)?;
        if state.lifecycle != AgentdNeuronLifecycleStateV2::Reloading
            || current.active_scope != *expected
            || current.reload_target_scope.as_ref() != Some(&next_scope)
            || AgentdNeuronGoalScopeV3::capture(next_scope.ordinal, &next)? != next_scope
        {
            return Err(AgentdNeuronControlErrorV2::InvalidTransition);
        }
        if let Err(error) = next.validate_goal_scope_admission() {
            drop(state);
            self.restore_goal_scope_sealed_v3(expected, &next_scope)?;
            return Err(error);
        }
        let mut retained_scopes = current.retained_scopes;
        retained_scopes.push(expected.clone());
        let published = AgentdNeuronGoalScopeStateV3::new(
            AgentdNeuronLifecycleStateV2::Serving,
            next_scope.clone(),
            retained_scopes,
            None,
        )
        .map_err(poison_control_state)?;
        let path = state
            .state_path
            .as_deref()
            .ok_or(AgentdNeuronControlErrorV2::ControllerPoisoned)?;
        write_agentd_neuron_goal_scope_state_v3(path, &published).map_err(poison_control_state)?;
        let previous = std::mem::replace(&mut state.active, next);
        state.retained.insert(expected.ordinal, previous);
        state.goal_scope = Some(GoalScopeTopologyV3 {
            active_ordinal: next_scope.ordinal,
            reload_target: None,
        });
        if let Err(error) = state.active.open_lifecycle_gate() {
            state.lifecycle = AgentdNeuronLifecycleStateV2::Failed;
            let _ = state.persist_transition(AgentdNeuronLifecycleStateV2::Failed, None);
            return Err(error);
        }
        state.lifecycle = AgentdNeuronLifecycleStateV2::Serving;
        Ok(())
    }

    fn restore_goal_scope_sealed_v3(
        &self,
        expected: &AgentdNeuronGoalScopeV3,
        target: &AgentdNeuronGoalScopeV3,
    ) -> Result<(), AgentdNeuronControlErrorV2> {
        let mut state = self.lock_state()?;
        let current = state
            .goal_scope_state(state.lifecycle)
            .map_err(poison_control_state)?;
        if state.lifecycle != AgentdNeuronLifecycleStateV2::Reloading
            || current.active_scope != *expected
            || current.reload_target_scope.as_ref() != Some(target)
        {
            return Err(AgentdNeuronControlErrorV2::InvalidTransition);
        }
        state
            .persist_transition(AgentdNeuronLifecycleStateV2::Sealed, None)
            .map_err(poison_control_state)?;
        state
            .goal_scope
            .as_mut()
            .ok_or(AgentdNeuronControlErrorV2::GenerationConflict)?
            .reload_target = None;
        state.lifecycle = AgentdNeuronLifecycleStateV2::Sealed;
        Ok(())
    }
}

fn resolve_recovered_goal_scope_v3(
    persisted: &AgentdNeuronGoalScopeStateV3,
    live: &AgentdNeuronGoalScopeStateV3,
) -> Result<AgentdNeuronLifecycleStateV2, AgentdNeuronControlErrorV2> {
    persisted.validate().map_err(poison_control_state)?;
    if persisted.active_scope == live.active_scope
        && persisted.retained_scopes == live.retained_scopes
    {
        return Ok(match persisted.lifecycle {
            AgentdNeuronLifecycleStateV2::Reloading | AgentdNeuronLifecycleStateV2::Sealed => {
                AgentdNeuronLifecycleStateV2::Sealed
            }
            AgentdNeuronLifecycleStateV2::Failed => AgentdNeuronLifecycleStateV2::Failed,
            AgentdNeuronLifecycleStateV2::Quiescing => AgentdNeuronLifecycleStateV2::Quiescing,
            AgentdNeuronLifecycleStateV2::Stopped => AgentdNeuronLifecycleStateV2::Stopped,
            AgentdNeuronLifecycleStateV2::Starting | AgentdNeuronLifecycleStateV2::Serving => {
                AgentdNeuronLifecycleStateV2::Starting
            }
        });
    }
    if persisted.lifecycle == AgentdNeuronLifecycleStateV2::Reloading
        && persisted.reload_target_scope.as_ref() == Some(&live.active_scope)
    {
        let mut expected = persisted.retained_scopes.clone();
        expected.push(persisted.active_scope.clone());
        if expected == live.retained_scopes {
            return Ok(AgentdNeuronLifecycleStateV2::Starting);
        }
    }
    Err(AgentdNeuronControlErrorV2::GenerationConflict)
}
