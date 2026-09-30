impl AgentdNeuronGenerationControllerV2 {
    pub fn new(active: AgentdNeuronHandleV2) -> Result<Self, AgentdNeuronControlErrorV2> {
        Self::from_recovered_generations(active, std::iter::empty())
    }

    /// Construct a controller whose lifecycle and generation-handoff intent are
    /// published through a crash-visible, checksummed control-state file.
    pub fn new_with_state_path(
        active: AgentdNeuronHandleV2,
        state_path: impl AsRef<Path>,
    ) -> Result<Self, AgentdNeuronControlErrorV2> {
        Self::from_recovered_generations_with_state_path(active, std::iter::empty(), state_path)
    }

    /// Rebuild the daemon controller from one active generation and sealed
    /// historical generations opened from durable storage.
    ///
    /// Historical generations must be unique and strictly older than the
    /// active generation. They remain queryable but can never receive new work
    /// through this controller or through a handle clone retained by a caller.
    pub fn from_recovered_generations(
        active: AgentdNeuronHandleV2,
        retained: impl IntoIterator<Item = AgentdNeuronHandleV2>,
    ) -> Result<Self, AgentdNeuronControlErrorV2> {
        Self::from_recovered_generations_inner(active, retained, None)
    }

    /// Rebuild the controller and reconcile it with the durable Agentd
    /// lifecycle/topology record. A prior serving process always restarts in
    /// `Starting`; an interrupted reload resolves only when the supplied
    /// topology proves either the old sealed side or the completed successor.
    pub fn from_recovered_generations_with_state_path(
        active: AgentdNeuronHandleV2,
        retained: impl IntoIterator<Item = AgentdNeuronHandleV2>,
        state_path: impl AsRef<Path>,
    ) -> Result<Self, AgentdNeuronControlErrorV2> {
        Self::from_recovered_generations_inner(
            active,
            retained,
            Some(state_path.as_ref().to_path_buf()),
        )
    }

    fn from_recovered_generations_inner(
        active: AgentdNeuronHandleV2,
        retained: impl IntoIterator<Item = AgentdNeuronHandleV2>,
        state_path: Option<PathBuf>,
    ) -> Result<Self, AgentdNeuronControlErrorV2> {
        let active_generation = active.generation()?;
        let mut retained_by_generation = BTreeMap::new();
        for handle in retained {
            let generation = handle.generation()?;
            if generation >= active_generation
                || retained_by_generation.insert(generation, handle).is_some()
            {
                return Err(AgentdNeuronControlErrorV2::GenerationConflict);
            }
        }
        let retained_generations = retained_by_generation.keys().copied().collect::<Vec<_>>();
        let lifecycle = if let Some(path) = state_path.as_deref() {
            if generation_state_exists(path).map_err(poison_control_state)? {
                let persisted =
                    read_agentd_neuron_generation_state_v2(path).map_err(poison_control_state)?;
                resolve_recovered_lifecycle(&persisted, active_generation, &retained_generations)?
            } else {
                AgentdNeuronLifecycleStateV2::Starting
            }
        } else {
            AgentdNeuronLifecycleStateV2::Starting
        };

        // All validation and durable-state reads happen before fencing caller
        // handles. Once accepted, controller ownership immediately closes every
        // reachable generation; only `start` may open the active generation.
        active.close_lifecycle_gate()?;
        for handle in retained_by_generation.values() {
            handle.close_lifecycle_gate()?;
        }
        let state = AgentdNeuronGenerationControllerStateV2 {
            lifecycle,
            active,
            retained: retained_by_generation,
            reload_target_generation: None,
            state_path,
        };
        state
            .persist_transition(lifecycle, None)
            .map_err(poison_control_state)?;
        Ok(Self {
            state: Mutex::new(state),
        })
    }

    fn lock_state(
        &self,
    ) -> Result<MutexGuard<'_, AgentdNeuronGenerationControllerStateV2>, AgentdNeuronControlErrorV2>
    {
        self.state.try_lock().map_err(|error| match error {
            TryLockError::WouldBlock => AgentdNeuronControlErrorV2::ControllerBusy,
            TryLockError::Poisoned(_) => AgentdNeuronControlErrorV2::ControllerPoisoned,
        })
    }

    fn restore_sealed_after_reload_failure(
        &self,
        previous_generation: u64,
        target_generation: u64,
    ) -> Result<(), AgentdNeuronControlErrorV2> {
        let mut state = self.lock_state()?;
        if state.lifecycle != AgentdNeuronLifecycleStateV2::Reloading
            || state.active.generation()? != previous_generation
            || state.reload_target_generation != Some(target_generation)
        {
            return Err(AgentdNeuronControlErrorV2::InvalidTransition);
        }
        state
            .persist_transition(AgentdNeuronLifecycleStateV2::Sealed, None)
            .map_err(poison_control_state)?;
        state.lifecycle = AgentdNeuronLifecycleStateV2::Sealed;
        state.reload_target_generation = None;
        Ok(())
    }

    pub fn state(&self) -> Result<AgentdNeuronLifecycleStateV2, AgentdNeuronControlErrorV2> {
        Ok(self.lock_state()?.lifecycle)
    }

    pub fn active_generation(&self) -> Result<u64, AgentdNeuronControlErrorV2> {
        self.lock_state()?.active.generation()
    }

    pub fn retained_generations(&self) -> Result<Vec<u64>, AgentdNeuronControlErrorV2> {
        Ok(self.lock_state()?.retained.keys().copied().collect())
    }

    /// Administrative projection of the exact durable topology record. It is
    /// not execution authority and contains no model result.
    pub fn generation_state(
        &self,
    ) -> Result<AgentdNeuronGenerationStateV2, AgentdNeuronControlErrorV2> {
        let state = self.lock_state()?;
        state
            .generation_state(state.lifecycle, state.reload_target_generation)
            .map_err(poison_control_state)
    }

    pub fn start(&self) -> Result<(), AgentdNeuronControlErrorV2> {
        let (active, retained, active_generation) = {
            let state = self.lock_state()?;
            if state.lifecycle != AgentdNeuronLifecycleStateV2::Starting {
                return Err(AgentdNeuronControlErrorV2::InvalidTransition);
            }
            (
                state.active.clone(),
                state.retained.values().cloned().collect::<Vec<_>>(),
                state.active.generation()?,
            )
        };

        // A recovered historical generation was sealed before handoff. Refuse
        // service if replay discovers unfinished work instead of silently
        // dropping that history or making it writable again.
        for handle in retained {
            handle.reconcile_control()?;
            let snapshot = handle.operational_snapshot()?;
            if snapshot.pending_operation_code.is_some() || snapshot.pending_witness_count != 0 {
                return Err(AgentdNeuronControlErrorV2::PendingRecovery);
            }
        }
        active.reconcile_control()?;

        let mut state = self.lock_state()?;
        if state.lifecycle != AgentdNeuronLifecycleStateV2::Starting
            || state.active.generation()? != active_generation
        {
            return Err(AgentdNeuronControlErrorV2::InvalidTransition);
        }
        state
            .persist_transition(AgentdNeuronLifecycleStateV2::Serving, None)
            .map_err(poison_control_state)?;
        if let Err(error) = state.active.open_lifecycle_gate() {
            state.lifecycle = AgentdNeuronLifecycleStateV2::Failed;
            state.reload_target_generation = None;
            let _ = state.persist_transition(AgentdNeuronLifecycleStateV2::Failed, None);
            return Err(error);
        }
        state.lifecycle = AgentdNeuronLifecycleStateV2::Serving;
        state.reload_target_generation = None;
        Ok(())
    }

    pub fn prepare(
        &self,
        run_id: StableId,
        runtime_body_digest: Digest32,
        input: NeuronTickInputV1,
    ) -> Result<AgentdNeuronInvocationV2, AgentdNeuronControlErrorV2> {
        let active = {
            let state = self.lock_state()?;
            if state.lifecycle != AgentdNeuronLifecycleStateV2::Serving {
                state.active.owner.record_entry_rejection();
                return Err(AgentdNeuronControlErrorV2::NotServing);
            }
            state.active.clone()
        };
        active
            .prepare(run_id, runtime_body_digest, input)
            .map_err(AgentdNeuronControlErrorV2::Runtime)
    }

    pub fn begin_quiesce(&self) -> Result<(), AgentdNeuronControlErrorV2> {
        let mut state = self.lock_state()?;
        match state.lifecycle {
            AgentdNeuronLifecycleStateV2::Serving => {
                if let Err(error) = state.active.close_lifecycle_gate() {
                    state.lifecycle = AgentdNeuronLifecycleStateV2::Failed;
                    state.reload_target_generation = None;
                    let _ = state.persist_transition(AgentdNeuronLifecycleStateV2::Failed, None);
                    return Err(error);
                }
                if let Err(error) =
                    state.persist_transition(AgentdNeuronLifecycleStateV2::Quiescing, None)
                {
                    state.lifecycle = AgentdNeuronLifecycleStateV2::Failed;
                    state.reload_target_generation = None;
                    let _ = state.persist_transition(AgentdNeuronLifecycleStateV2::Failed, None);
                    return Err(poison_control_state(error));
                }
                state.lifecycle = AgentdNeuronLifecycleStateV2::Quiescing;
                state.reload_target_generation = None;
                Ok(())
            }
            AgentdNeuronLifecycleStateV2::Quiescing => Ok(()),
            _ => Err(AgentdNeuronControlErrorV2::InvalidTransition),
        }
    }

    pub fn recover_operation(
        &self,
        input: &NeuronTickInputV1,
    ) -> Result<AgentdNeuronRecoveryReportV2, AgentdNeuronControlErrorV2> {
        let (active, policy) = {
            let state = self.lock_state()?;
            match state.lifecycle {
                AgentdNeuronLifecycleStateV2::Serving => (
                    state.active.clone(),
                    AgentdNeuronRecoveryPolicyV2::PreserveUnexecuted,
                ),
                AgentdNeuronLifecycleStateV2::Quiescing => (
                    state.active.clone(),
                    AgentdNeuronRecoveryPolicyV2::CloseUnexecuted,
                ),
                _ => return Err(AgentdNeuronControlErrorV2::InvalidTransition),
            }
        };
        active.recover_operation_with_policy(input, policy)
    }

    pub fn seal(&self) -> Result<(), AgentdNeuronControlErrorV2> {
        let (active, generation) = {
            let state = self.lock_state()?;
            if state.lifecycle != AgentdNeuronLifecycleStateV2::Quiescing {
                return Err(AgentdNeuronControlErrorV2::InvalidTransition);
            }
            (state.active.clone(), state.active.generation()?)
        };
        // Quiesce invalidates every captured epoch. The write guard proves that
        // all invocations admitted by an earlier epoch have left the runtime.
        let _drain = active.try_drain_lifecycle_gate()?;
        active.reconcile_control()?;
        let snapshot = active.operational_snapshot()?;
        if snapshot.pending_operation_code.is_some() || snapshot.pending_witness_count != 0 {
            return Err(AgentdNeuronControlErrorV2::PendingRecovery);
        }
        let mut state = self.lock_state()?;
        if state.lifecycle != AgentdNeuronLifecycleStateV2::Quiescing
            || state.active.generation()? != generation
        {
            return Err(AgentdNeuronControlErrorV2::InvalidTransition);
        }
        state
            .persist_transition(AgentdNeuronLifecycleStateV2::Sealed, None)
            .map_err(poison_control_state)?;
        state.lifecycle = AgentdNeuronLifecycleStateV2::Sealed;
        state.reload_target_generation = None;
        Ok(())
    }

    pub fn reload(&self, next: AgentdNeuronHandleV2) -> Result<(), AgentdNeuronControlErrorV2> {
        let next_generation = next.generation()?;
        let (previous, previous_generation) = {
            let mut state = self.lock_state()?;
            if state.lifecycle != AgentdNeuronLifecycleStateV2::Sealed {
                return Err(AgentdNeuronControlErrorV2::InvalidTransition);
            }
            let previous_generation = state.active.generation()?;
            if next_generation <= previous_generation
                || state.retained.contains_key(&next_generation)
            {
                return Err(AgentdNeuronControlErrorV2::GenerationConflict);
            }
            // Invalidate invocations prepared from successor-handle clones before
            // it is accepted as the active generation.
            next.close_lifecycle_gate()?;
            state
                .persist_transition(
                    AgentdNeuronLifecycleStateV2::Reloading,
                    Some(next_generation),
                )
                .map_err(poison_control_state)?;
            state.lifecycle = AgentdNeuronLifecycleStateV2::Reloading;
            state.reload_target_generation = Some(next_generation);
            (state.active.clone(), previous_generation)
        };

        let next_drain = match next.try_drain_lifecycle_gate() {
            Ok(guard) => guard,
            Err(error) => {
                self.restore_sealed_after_reload_failure(previous_generation, next_generation)?;
                return Err(error);
            }
        };
        let ready = next.reconcile_control().and_then(|_| {
            let snapshot = next.operational_snapshot()?;
            if snapshot.pending_operation_code.is_some() || snapshot.pending_witness_count != 0 {
                Err(AgentdNeuronControlErrorV2::PendingRecovery)
            } else {
                Ok(())
            }
        });
        if let Err(error) = ready {
            drop(next_drain);
            self.restore_sealed_after_reload_failure(previous_generation, next_generation)?;
            return Err(error);
        }

        // The successor remains closed after the drain proof is released, so
        // no invocation can enter between readiness validation and activation.
        drop(next_drain);
        let mut state = self.lock_state()?;
        if state.lifecycle != AgentdNeuronLifecycleStateV2::Reloading
            || state.active.generation()? != previous_generation
            || state.reload_target_generation != Some(next_generation)
        {
            return Err(AgentdNeuronControlErrorV2::InvalidTransition);
        }
        let mut retained_generations = state.retained.keys().copied().collect::<Vec<_>>();
        retained_generations.push(previous_generation);
        retained_generations.sort_unstable();
        persist_generation_state(
            state.state_path.as_deref(),
            AgentdNeuronLifecycleStateV2::Serving,
            next_generation,
            retained_generations,
            None,
        )
        .map_err(poison_control_state)?;
        state.retained.insert(previous_generation, previous);
        state.active = next;
        state.reload_target_generation = None;
        if let Err(error) = state.active.open_lifecycle_gate() {
            state.lifecycle = AgentdNeuronLifecycleStateV2::Failed;
            let _ = state.persist_transition(AgentdNeuronLifecycleStateV2::Failed, None);
            return Err(error);
        }
        state.lifecycle = AgentdNeuronLifecycleStateV2::Serving;
        Ok(())
    }

    pub fn operational_snapshot(
        &self,
    ) -> Result<AgentdNeuronOperationalSnapshotV2, AgentdNeuronControlErrorV2> {
        let active = self.lock_state()?.active.clone();
        active.operational_snapshot()
    }

    pub fn controller_snapshot(
        &self,
    ) -> Result<AgentdNeuronGenerationControllerSnapshotV2, AgentdNeuronControlErrorV2> {
        let (lifecycle, active, active_generation, retained_generations) = {
            let state = self.lock_state()?;
            (
                state.lifecycle,
                state.active.clone(),
                state.active.generation()?,
                state.retained.keys().copied().collect(),
            )
        };
        let (accepting_new_work, execution_epoch) = active.lifecycle_gate_snapshot();
        Ok(AgentdNeuronGenerationControllerSnapshotV2 {
            lifecycle,
            active_generation,
            retained_generations,
            accepting_new_work,
            execution_epoch,
            active: active.operational_snapshot()?,
        })
    }

    pub fn query_operation(
        &self,
        generation: u64,
        tick_id: &StableId,
        input_digest: Digest32,
    ) -> Result<NeuronOperationStatusV2, AgentdNeuronControlErrorV2> {
        let handle = {
            let state = self.lock_state()?;
            if state.active.generation()? == generation {
                state.active.clone()
            } else {
                state
                    .retained
                    .get(&generation)
                    .cloned()
                    .ok_or(AgentdNeuronControlErrorV2::UnknownGeneration)?
            }
        };
        handle.query_operation_control(tick_id, input_digest)
    }

    /// Reopen a generation after a graceful daemon shutdown. The
    /// transition is durably published as `Starting` before ordinary
    /// reconciliation; execution remains closed until the full startup
    /// postcondition succeeds.
    pub fn restart_stopped(&self) -> Result<(), AgentdNeuronControlErrorV2> {
        {
            let mut state = self.lock_state()?;
            if state.lifecycle != AgentdNeuronLifecycleStateV2::Stopped {
                return Err(AgentdNeuronControlErrorV2::InvalidTransition);
            }
            state
                .persist_transition(AgentdNeuronLifecycleStateV2::Starting, None)
                .map_err(poison_control_state)?;
            state.lifecycle = AgentdNeuronLifecycleStateV2::Starting;
            state.reload_target_generation = None;
        }
        self.start()
    }

    pub fn shutdown(&self) -> Result<(), AgentdNeuronControlErrorV2> {
        match self.state()? {
            AgentdNeuronLifecycleStateV2::Serving => self.begin_quiesce()?,
            AgentdNeuronLifecycleStateV2::Quiescing => {}
            AgentdNeuronLifecycleStateV2::Sealed => {
                let mut state = self.lock_state()?;
                state
                    .persist_transition(AgentdNeuronLifecycleStateV2::Stopped, None)
                    .map_err(poison_control_state)?;
                state.lifecycle = AgentdNeuronLifecycleStateV2::Stopped;
                state.reload_target_generation = None;
                return Ok(());
            }
            AgentdNeuronLifecycleStateV2::Stopped => return Ok(()),
            _ => return Err(AgentdNeuronControlErrorV2::InvalidTransition),
        }
        self.seal()?;
        let mut state = self.lock_state()?;
        state
            .persist_transition(AgentdNeuronLifecycleStateV2::Stopped, None)
            .map_err(poison_control_state)?;
        state.lifecycle = AgentdNeuronLifecycleStateV2::Stopped;
        state.reload_target_generation = None;
        Ok(())
    }
}

fn resolve_recovered_lifecycle(
    persisted: &AgentdNeuronGenerationStateV2,
    active_generation: u64,
    retained_generations: &[u64],
) -> Result<AgentdNeuronLifecycleStateV2, AgentdNeuronControlErrorV2> {
    persisted.validate().map_err(poison_control_state)?;
    if persisted.lifecycle == AgentdNeuronLifecycleStateV2::Reloading {
        let target = persisted
            .reload_target_generation
            .ok_or(AgentdNeuronControlErrorV2::ControllerPoisoned)?;
        if active_generation == persisted.active_generation
            && retained_generations == persisted.retained_generations.as_slice()
        {
            return Ok(AgentdNeuronLifecycleStateV2::Sealed);
        }
        let mut completed_retained = persisted.retained_generations.clone();
        completed_retained.push(persisted.active_generation);
        completed_retained.sort_unstable();
        if active_generation == target && retained_generations == completed_retained.as_slice() {
            return Ok(AgentdNeuronLifecycleStateV2::Starting);
        }
        return Err(AgentdNeuronControlErrorV2::GenerationConflict);
    }
    if active_generation != persisted.active_generation
        || retained_generations != persisted.retained_generations.as_slice()
    {
        return Err(AgentdNeuronControlErrorV2::GenerationConflict);
    }
    Ok(match persisted.lifecycle {
        AgentdNeuronLifecycleStateV2::Starting | AgentdNeuronLifecycleStateV2::Serving => {
            AgentdNeuronLifecycleStateV2::Starting
        }
        AgentdNeuronLifecycleStateV2::Quiescing => AgentdNeuronLifecycleStateV2::Quiescing,
        AgentdNeuronLifecycleStateV2::Sealed => AgentdNeuronLifecycleStateV2::Sealed,
        AgentdNeuronLifecycleStateV2::Stopped => AgentdNeuronLifecycleStateV2::Stopped,
        AgentdNeuronLifecycleStateV2::Failed => AgentdNeuronLifecycleStateV2::Failed,
        AgentdNeuronLifecycleStateV2::Reloading => unreachable!("handled above"),
    })
}
