impl<W, P, G> SharedProductNeuronOwnerV2<W, P, G>
where
    W: AnchorWitnessStore,
    P: DurableNeuronInferenceControlPort,
{
    fn recover_typed_or_neuron_control(
        &self,
        invocation: Option<&DecisionCellInvocationV2>,
        input: &NeuronTickInputV1,
        policy: AgentdNeuronRecoveryPolicyV2,
    ) -> Result<NeuronOperationStatusV2, AgentdNeuronControlErrorV2> {
        self.counters
            .recovery_attempts
            .fetch_add(1, Ordering::Relaxed);
        if policy == AgentdNeuronRecoveryPolicyV2::CloseUnexecuted {
            self.counters
                .recovery_close_requests
                .fetch_add(1, Ordering::Relaxed);
        } else {
            self.counters
                .recovery_preserve_requests
                .fetch_add(1, Ordering::Relaxed);
        }
        let result = (|| {
            let mut locked = self.lock_control()?;
            let AgentdNeuronOwnerV2 {
                runtime,
                inference_control,
            } = &mut locked.owner;
            let mut model = DurableInferenceControlModelPort::new(inference_control);
            let recovered = match (invocation, policy) {
                (Some(cell), AgentdNeuronRecoveryPolicyV2::CloseUnexecuted) => runtime
                    .close_unexecuted_decision_cell_operation(&mut model, cell, input)
                    .map_err(decision_cell::runtime_error),
                (Some(cell), AgentdNeuronRecoveryPolicyV2::PreserveUnexecuted) => runtime
                    .recover_decision_cell_operation(&mut model, cell, input)
                    .map_err(decision_cell::runtime_error),
                (None, AgentdNeuronRecoveryPolicyV2::CloseUnexecuted) => {
                    runtime.close_unexecuted_operation(&mut model, input)
                }
                (None, AgentdNeuronRecoveryPolicyV2::PreserveUnexecuted) => {
                    runtime.recover_operation(&mut model, input)
                }
            };
            recovered.map_err(AgentdNeuronControlErrorV2::Runtime)
        })();
        match &result {
            Ok(status) if status.requires_reconciliation() => {
                self.counters
                    .recovery_pending
                    .fetch_add(1, Ordering::Relaxed);
            }
            Ok(_) => {
                self.counters
                    .recovery_converged
                    .fetch_add(1, Ordering::Relaxed);
            }
            Err(_) => {
                self.counters
                    .recovery_errors
                    .fetch_add(1, Ordering::Relaxed);
            }
        }
        result
    }

    fn lock_control(
        &self,
    ) -> Result<AgentdNeuronOwnerLockGuardV2<'_, W, P, G>, AgentdNeuronControlErrorV2> {
        self.counters
            .owner_lock_attempts
            .fetch_add(1, Ordering::Relaxed);
        let started = Instant::now();
        match self.guarded.try_lock() {
            Ok(guard) => {
                self.counters.record_lock_wait(elapsed_micros(started));
                Ok(AgentdNeuronOwnerLockGuardV2 {
                    guard,
                    counters: &self.counters,
                    acquired_at: Instant::now(),
                })
            }
            Err(TryLockError::WouldBlock) => {
                self.counters
                    .owner_busy_rejections
                    .fetch_add(1, Ordering::Relaxed);
                Err(AgentdNeuronControlErrorV2::OwnerBusy)
            }
            Err(TryLockError::Poisoned(_)) => {
                self.counters
                    .owner_poisoned_failures
                    .fetch_add(1, Ordering::Relaxed);
                Err(AgentdNeuronControlErrorV2::OwnerPoisoned)
            }
        }
    }

    fn observe_locked(
        &self,
        locked: &mut GuardedOwnerV2<W, P, G>,
    ) -> Result<AgentdNeuronOperationalSnapshotV2, AgentdNeuronControlErrorV2> {
        let pending = locked
            .owner
            .runtime
            .pending_operation_status()
            .map_err(AgentdNeuronControlErrorV2::Runtime)?;
        let pending_witness_count = locked
            .owner
            .runtime
            .pending_witness_count()
            .map_err(AgentdNeuronControlErrorV2::Runtime)?;
        let capacity = locked
            .owner
            .runtime
            .capacity_snapshot()
            .map_err(AgentdNeuronControlErrorV2::Runtime)?;
        let last_measurement = locked.owner.runtime.last_measurement().cloned();
        let now = Instant::now();
        let mut telemetry = self.telemetry.lock().map_err(|_| {
            self.counters
                .owner_poisoned_failures
                .fetch_add(1, Ordering::Relaxed);
            AgentdNeuronControlErrorV2::OwnerPoisoned
        })?;

        let outcome_unknown = pending
            .as_ref()
            .is_some_and(|(_, status)| matches!(status, NeuronOperationStatusV2::OutcomeUnknown));
        if outcome_unknown {
            telemetry.outcome_unknown_since.get_or_insert(now);
        } else {
            telemetry.outcome_unknown_since = None;
        }
        if pending_witness_count > 0 {
            telemetry.witness_pending_since.get_or_insert(now);
        } else {
            telemetry.witness_pending_since = None;
        }

        let capacity_trend = telemetry.previous_capacity.map(|(previous_at, previous)| {
            AgentdNeuronCapacityTrendV2 {
                elapsed_micros: elapsed_micros(previous_at),
                generation_records_delta: signed_delta_usize(
                    capacity.generation.records,
                    previous.generation.records,
                ),
                generation_effective_bytes_delta: signed_delta_u64(
                    capacity.generation.effective_bytes(),
                    previous.generation.effective_bytes(),
                ),
                index_records_delta: signed_delta_usize(
                    capacity.index.records,
                    previous.index.records,
                ),
                index_effective_bytes_delta: signed_delta_u64(
                    capacity.index.effective_bytes(),
                    previous.index.effective_bytes(),
                ),
                witness_records_remaining_delta: match (
                    capacity.witness_records_remaining,
                    previous.witness_records_remaining,
                ) {
                    (Some(current), Some(previous)) => Some(signed_delta_usize(current, previous)),
                    _ => None,
                },
            }
        });
        telemetry.previous_capacity = Some((now, capacity));

        let (pending_tick_id, pending_input_digest, pending_operation_code) = pending
            .as_ref()
            .map_or((None, None, None), |(key, status)| {
                (
                    Some(key.tick_id.as_str().to_owned()),
                    Some(key.input_semantic_digest.to_string()),
                    Some(status.stable_code().to_owned()),
                )
            });
        Ok(AgentdNeuronOperationalSnapshotV2 {
            generation: Some(self.generation),
            body_bundle_digest: Some(self.body_bundle_digest.to_string()),
            pending_tick_id,
            pending_input_digest,
            pending_operation_code,
            oldest_outcome_unknown_age_micros: telemetry.outcome_unknown_since.map(elapsed_micros),
            pending_witness_count,
            pending_witness_age_micros: telemetry.witness_pending_since.map(elapsed_micros),
            capacity,
            capacity_trend,
            counters: self.counters.snapshot(),
            last_measurement,
        })
    }
}

impl<W, P, G> ProductNeuronOwnerV2 for SharedProductNeuronOwnerV2<W, P, G>
where
    W: AnchorWitnessStore + Send,
    P: DurableNeuronInferenceControlPort + Send,
    G: NeuronAdmissionGuard + Send,
{
    fn execute_decision_cell(
        &self,
        invocation: &DecisionCellInvocationV2,
        input: NeuronTickInputV1,
        stage: &mut dyn NeuronAdmissionGuard,
    ) -> Result<NeuronRuntimeCommitV2, NeuronRuntimeV2Error> {
        let mut locked = self.lock_control().map_err(compatibility_error)?;
        let GuardedOwnerV2 { owner, admission } = &mut *locked;
        let AgentdNeuronOwnerV2 {
            runtime,
            inference_control,
        } = owner;
        let mut model = DurableInferenceControlModelPort::new(inference_control);
        let mut guard = CombinedAdmission {
            selected: admission,
            stage,
        };
        let result = runtime
            .tick_decision_cell_guarded(&mut model, invocation, input, &mut guard)
            .map_err(decision_cell::runtime_error);
        if matches!(&result, Err(NeuronRuntimeV2Error::Admission(_))) {
            self.counters
                .runtime_admission_denials
                .fetch_add(1, Ordering::Relaxed);
        }
        result
    }

    fn query_decision_cell_operation(
        &self,
        invocation: &DecisionCellInvocationV2,
        input: &NeuronTickInputV1,
    ) -> Result<NeuronOperationStatusV2, NeuronRuntimeV2Error> {
        self.lock_control()
            .map_err(compatibility_error)?
            .owner
            .runtime
            .query_decision_cell_operation(invocation, input)
            .map_err(decision_cell::runtime_error)
    }

    fn query_decision_cell_result_guarded(
        &self,
        invocation: &DecisionCellInvocationV2,
        input: &NeuronTickInputV1,
        stage: &mut dyn NeuronAdmissionGuard,
    ) -> Result<Option<NeuronRuntimeCommitV2>, NeuronRuntimeV2Error> {
        let mut locked = self.lock_control().map_err(compatibility_error)?;
        let GuardedOwnerV2 { owner, admission } = &mut *locked;
        let mut guard = CombinedAdmission {
            selected: admission,
            stage,
        };
        let result = owner
            .runtime
            .query_decision_cell_result_guarded(invocation, input, &mut guard)
            .map_err(decision_cell::runtime_error);
        if matches!(&result, Err(NeuronRuntimeV2Error::Admission(_))) {
            self.counters
                .runtime_admission_denials
                .fetch_add(1, Ordering::Relaxed);
        }
        result
    }

    fn recover_decision_cell_control(
        &self,
        invocation: &DecisionCellInvocationV2,
        input: &NeuronTickInputV1,
        policy: AgentdNeuronRecoveryPolicyV2,
    ) -> Result<NeuronOperationStatusV2, AgentdNeuronControlErrorV2> {
        self.recover_typed_or_neuron_control(Some(invocation), input, policy)
    }

    fn execute(
        &self,
        input: NeuronTickInputV1,
        stage: &mut dyn NeuronAdmissionGuard,
    ) -> Result<NeuronRuntimeCommitV2, NeuronRuntimeV2Error> {
        let mut locked = self.lock_control().map_err(compatibility_error)?;
        let GuardedOwnerV2 { owner, admission } = &mut *locked;
        let AgentdNeuronOwnerV2 {
            runtime,
            inference_control,
        } = owner;
        let mut model = DurableInferenceControlModelPort::new(inference_control);
        let mut guard = CombinedAdmission {
            selected: admission,
            stage,
        };
        let result = runtime.tick_guarded(&mut model, input, &mut guard);
        if matches!(&result, Err(NeuronRuntimeV2Error::Admission(_))) {
            self.counters
                .runtime_admission_denials
                .fetch_add(1, Ordering::Relaxed);
        }
        result
    }

    fn query_result_guarded(
        &self,
        input: &NeuronTickInputV1,
        stage: &mut dyn NeuronAdmissionGuard,
    ) -> Result<Option<NeuronRuntimeCommitV2>, NeuronRuntimeV2Error> {
        let mut locked = self.lock_control().map_err(compatibility_error)?;
        let GuardedOwnerV2 { owner, admission } = &mut *locked;
        let mut guard = CombinedAdmission {
            selected: admission,
            stage,
        };
        let result = owner.runtime.query_result_guarded(input, &mut guard);
        if matches!(&result, Err(NeuronRuntimeV2Error::Admission(_))) {
            self.counters
                .runtime_admission_denials
                .fetch_add(1, Ordering::Relaxed);
        }
        result
    }

    fn recover_operation_control_with_policy(
        &self,
        input: &NeuronTickInputV1,
        policy: AgentdNeuronRecoveryPolicyV2,
    ) -> Result<NeuronOperationStatusV2, AgentdNeuronControlErrorV2> {
        self.recover_typed_or_neuron_control(None, input, policy)
    }

    fn reconcile(&self) -> Result<(), NeuronRuntimeV2Error> {
        self.reconcile_control().map_err(compatibility_error)
    }

    fn reconcile_control(&self) -> Result<(), AgentdNeuronControlErrorV2> {
        let mut locked = self.lock_control()?;
        locked
            .owner
            .reconcile()
            .map_err(AgentdNeuronControlErrorV2::Runtime)
    }

    fn query_operation(
        &self,
        tick_id: &StableId,
        input_digest: Digest32,
    ) -> Result<NeuronOperationStatusV2, NeuronRuntimeV2Error> {
        self.query_operation_control(tick_id, input_digest)
            .map_err(compatibility_error)
    }

    fn query_operation_control(
        &self,
        tick_id: &StableId,
        input_digest: Digest32,
    ) -> Result<NeuronOperationStatusV2, AgentdNeuronControlErrorV2> {
        let mut locked = self.lock_control()?;
        locked
            .owner
            .runtime
            .query_operation(tick_id, input_digest)
            .map_err(AgentdNeuronControlErrorV2::Runtime)
    }

    fn capacity_snapshot(&self) -> Result<NeuronRuntimeCapacityV2, NeuronRuntimeV2Error> {
        let locked = self.lock_control().map_err(compatibility_error)?;
        locked.owner.runtime.capacity_snapshot()
    }

    fn operational_snapshot_control(
        &self,
    ) -> Result<AgentdNeuronOperationalSnapshotV2, AgentdNeuronControlErrorV2> {
        let mut locked = self.lock_control()?;
        self.observe_locked(&mut locked)
    }

    fn generation(&self) -> Option<u64> {
        Some(self.generation)
    }

    fn body_bundle_digest(&self) -> Option<Digest32> {
        Some(self.body_bundle_digest)
    }

    fn operational_counters(&self) -> AgentdNeuronOperationalCountersV2 {
        self.counters.snapshot()
    }

    fn record_entry_rejection(&self) {
        self.counters
            .entry_rejections_before_runtime
            .fetch_add(1, Ordering::Relaxed);
    }

    fn record_stale_invocation_rejection(&self) {
        self.counters
            .entry_rejections_before_runtime
            .fetch_add(1, Ordering::Relaxed);
        self.counters
            .stale_invocation_rejections
            .fetch_add(1, Ordering::Relaxed);
    }
}
