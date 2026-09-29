impl AgentdNeuronGenerationControllerV2 {
    pub fn new(active: AgentdNeuronHandleV2) -> Result<Self, AgentdNeuronControlErrorV2> {
        Self::from_recovered_generations(active, std::iter::empty())
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

        // Controller ownership immediately fences every reachable handle. The
        // active generation opens only after start reconciliation; retained
        // generations remain permanently non-writable.
        active.close_lifecycle_gate()?;
        for handle in retained_by_generation.values() {
            handle.close_lifecycle_gate()?;
        }
        Ok(Self {
            state: Mutex::new(AgentdNeuronGenerationControllerStateV2 {
                lifecycle: AgentdNeuronLifecycleStateV2::Starting,
                active,
                retained: retained_by_generation,
            }),
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

    fn restore_sealed_after_reload_failure(&self, previous_generation: u64) {
        if let Ok(mut state) = self.lock_state()
            && state.lifecycle == AgentdNeuronLifecycleStateV2::Reloading
            && state.active.generation().ok() == Some(previous_generation)
        {
            state.lifecycle = AgentdNeuronLifecycleStateV2::Sealed;
        }
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
        state.lifecycle = AgentdNeuronLifecycleStateV2::Serving;
        if let Err(error) = state.active.open_lifecycle_gate() {
            state.lifecycle = AgentdNeuronLifecycleStateV2::Failed;
            return Err(error);
        }
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
                    return Err(error);
                }
                state.lifecycle = AgentdNeuronLifecycleStateV2::Quiescing;
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
        state.lifecycle = AgentdNeuronLifecycleStateV2::Sealed;
        Ok(())
    }

    pub fn reload(
        &self,
        next: AgentdNeuronHandleV2,
    ) -> Result<(), AgentdNeuronControlErrorV2> {
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
            state.lifecycle = AgentdNeuronLifecycleStateV2::Reloading;
            (state.active.clone(), previous_generation)
        };

        let _next_drain = match next.try_drain_lifecycle_gate() {
            Ok(guard) => guard,
            Err(error) => {
                self.restore_sealed_after_reload_failure(previous_generation);
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
            self.restore_sealed_after_reload_failure(previous_generation);
            return Err(error);
        }

        // The successor remains closed after the drain proof is released, so
        // no invocation can enter between readiness validation and activation.
        drop(_next_drain);
        let mut state = self.lock_state()?;
        if state.lifecycle != AgentdNeuronLifecycleStateV2::Reloading
            || state.active.generation()? != previous_generation
        {
            return Err(AgentdNeuronControlErrorV2::InvalidTransition);
        }
        state.retained.insert(previous_generation, previous);
        state.active = next;
        state.lifecycle = AgentdNeuronLifecycleStateV2::Serving;
        if let Err(error) = state.active.open_lifecycle_gate() {
            state.lifecycle = AgentdNeuronLifecycleStateV2::Failed;
            return Err(error);
        }
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

    pub fn shutdown(&self) -> Result<(), AgentdNeuronControlErrorV2> {
        match self.state()? {
            AgentdNeuronLifecycleStateV2::Serving => self.begin_quiesce()?,
            AgentdNeuronLifecycleStateV2::Quiescing => {}
            AgentdNeuronLifecycleStateV2::Sealed => {
                self.lock_state()?.lifecycle = AgentdNeuronLifecycleStateV2::Stopped;
                return Ok(());
            }
            AgentdNeuronLifecycleStateV2::Stopped => return Ok(()),
            _ => return Err(AgentdNeuronControlErrorV2::InvalidTransition),
        }
        self.seal()?;
        self.lock_state()?.lifecycle = AgentdNeuronLifecycleStateV2::Stopped;
        Ok(())
    }
}
