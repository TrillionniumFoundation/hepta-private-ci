impl AgentdNeuronGenerationControllerV2 {
    /// Canonical exact-operation recovery boundary for daemon lifecycle control.
    ///
    /// `Starting` and `Serving` preserve authoritative unexecuted work. A
    /// quiescing generation may close only a proven-unexecuted reservation.
    /// No branch opens the execution gate, calls provider `execute`, returns a
    /// model result, or grants current-use authority.
    pub fn recover_existing_operation(
        &self,
        input: &NeuronTickInputV1,
    ) -> Result<AgentdNeuronRecoveryReportV2, AgentdNeuronControlErrorV2> {
        let (active, policy) = {
            let state = self.lock_state()?;
            match state.lifecycle {
                AgentdNeuronLifecycleStateV2::Starting
                | AgentdNeuronLifecycleStateV2::Serving => (
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

    /// Explicitly close a proven-unexecuted operation while the active
    /// generation is fenced.
    ///
    /// This is available during startup recovery and quiesce. Unknown provider
    /// outcomes remain pending and therefore continue to block `start`, `seal`
    /// and generation handoff.
    pub fn close_unexecuted_operation(
        &self,
        input: &NeuronTickInputV1,
    ) -> Result<AgentdNeuronRecoveryReportV2, AgentdNeuronControlErrorV2> {
        let active = {
            let state = self.lock_state()?;
            match state.lifecycle {
                AgentdNeuronLifecycleStateV2::Starting
                | AgentdNeuronLifecycleStateV2::Quiescing => state.active.clone(),
                _ => return Err(AgentdNeuronControlErrorV2::InvalidTransition),
            }
        };
        active.recover_operation_with_policy(
            input,
            AgentdNeuronRecoveryPolicyV2::CloseUnexecuted,
        )
    }
}

#[cfg(test)]
mod startup_recovery_tests {
    use super::*;

    struct StartupRecoveryOwner {
        generation: u64,
        pending: AtomicBool,
        reconciles: AtomicU64,
        preserve_recoveries: AtomicU64,
        close_recoveries: AtomicU64,
    }

    impl StartupRecoveryOwner {
        fn status(&self) -> NeuronOperationStatusV2 {
            if self.pending.load(Ordering::SeqCst) {
                NeuronOperationStatusV2::NotExecuted
            } else {
                NeuronOperationStatusV2::NotRecorded
            }
        }

        fn capacity() -> NeuronRuntimeCapacityV2 {
            let storage = codex_hepta_neuron::NeuronStorageCapacityV2 {
                records: 1,
                record_limit: 16,
                file_bytes: 256,
                byte_limit: 16 * 1024,
                reserved_bytes: 0,
            };
            NeuronRuntimeCapacityV2 {
                generation: storage,
                index: storage,
                witness_records_remaining: Some(15),
            }
        }
    }

    impl ProductNeuronOwnerV2 for StartupRecoveryOwner {
        fn execute(
            &self,
            _input: NeuronTickInputV1,
            _guard: &mut dyn NeuronAdmissionGuard,
        ) -> Result<NeuronRuntimeCommitV2, NeuronRuntimeV2Error> {
            Err(NeuronRuntimeV2Error::PendingOperation)
        }

        fn recover_operation_control_with_policy(
            &self,
            _input: &NeuronTickInputV1,
            policy: AgentdNeuronRecoveryPolicyV2,
        ) -> Result<NeuronOperationStatusV2, AgentdNeuronControlErrorV2> {
            match policy {
                AgentdNeuronRecoveryPolicyV2::PreserveUnexecuted => {
                    self.preserve_recoveries.fetch_add(1, Ordering::SeqCst);
                    Ok(self.status())
                }
                AgentdNeuronRecoveryPolicyV2::CloseUnexecuted => {
                    self.close_recoveries.fetch_add(1, Ordering::SeqCst);
                    if self.pending.swap(false, Ordering::SeqCst) {
                        Ok(NeuronOperationStatusV2::Failed(
                            codex_hepta_neuron::NeuronOperationFailureV2::AdmissionDenied,
                        ))
                    } else {
                        Ok(NeuronOperationStatusV2::NotRecorded)
                    }
                }
            }
        }

        fn reconcile(&self) -> Result<(), NeuronRuntimeV2Error> {
            self.reconciles.fetch_add(1, Ordering::SeqCst);
            Ok(())
        }

        fn query_operation(
            &self,
            _tick_id: &StableId,
            _input_digest: Digest32,
        ) -> Result<NeuronOperationStatusV2, NeuronRuntimeV2Error> {
            Ok(self.status())
        }

        fn capacity_snapshot(&self) -> Result<NeuronRuntimeCapacityV2, NeuronRuntimeV2Error> {
            Ok(Self::capacity())
        }

        fn operational_snapshot_control(
            &self,
        ) -> Result<AgentdNeuronOperationalSnapshotV2, AgentdNeuronControlErrorV2> {
            let pending = self.pending.load(Ordering::SeqCst);
            Ok(AgentdNeuronOperationalSnapshotV2 {
                generation: Some(self.generation),
                body_bundle_digest: Some(
                    Digest32::of_bytes(
                        format!("startup-recovery-body-{}", self.generation).as_bytes(),
                    )
                    .to_string(),
                ),
                pending_tick_id: pending.then_some("startup.recovery.tick".to_owned()),
                pending_input_digest: pending
                    .then_some(Digest32::of_bytes(b"startup.recovery.input").to_string()),
                pending_operation_code: pending.then_some(
                    NeuronOperationStatusV2::NotExecuted.stable_code().to_owned(),
                ),
                oldest_outcome_unknown_age_micros: None,
                pending_witness_count: 0,
                pending_witness_age_micros: None,
                capacity: Self::capacity(),
                capacity_trend: None,
                counters: AgentdNeuronOperationalCountersV2::default(),
                last_measurement: None,
            })
        }

        fn generation(&self) -> Option<u64> {
            Some(self.generation)
        }

        fn body_bundle_digest(&self) -> Option<Digest32> {
            Some(Digest32::of_bytes(
                format!("startup-recovery-body-{}", self.generation).as_bytes(),
            ))
        }
    }

    fn handle(
        generation: u64,
        pending: bool,
    ) -> (AgentdNeuronHandleV2, Arc<StartupRecoveryOwner>) {
        let owner = Arc::new(StartupRecoveryOwner {
            generation,
            pending: AtomicBool::new(pending),
            reconciles: AtomicU64::new(0),
            preserve_recoveries: AtomicU64::new(0),
            close_recoveries: AtomicU64::new(0),
        });
        (
            AgentdNeuronHandleV2 {
                owner: owner.clone(),
                config_digest: Digest32::of_bytes(
                    format!("startup-recovery-config-{generation}").as_bytes(),
                ),
                lifecycle_gate: Arc::new(AgentdNeuronExecutionGateV2::standalone()),
            },
            owner,
        )
    }

    fn input(generation: u64) -> NeuronTickInputV1 {
        let features = vec![1, 2, 3];
        NeuronTickInputV1 {
            tick_id: StableId::new("startup.recovery.tick").expect("stable tick"),
            subject_id: StableId::new("startup.recovery.subject").expect("stable subject"),
            logical_sequence: 1,
            monotonic_time_micros: 1,
            checkpoint_digest: Digest32::ZERO,
            input_feature_digest: codex_hepta_neuron::canonical_feature_vector_digest_v1(
                &features,
            ),
            feature_vector_q24: features,
            objective_digest: Digest32::of_bytes(b"startup.recovery.objective"),
            ndu_snapshot_digest: Digest32::of_bytes(b"startup.recovery.ndu"),
            body_generation: Some(generation),
            modulator_digest: None,
        }
    }

    #[test]
    fn startup_refuses_service_until_exact_pending_work_is_closed() {
        let (active, owner) = handle(1, true);
        let active_clone = active.clone();
        let controller =
            AgentdNeuronGenerationControllerV2::new(active).expect("controller");
        let request = input(1);

        let start_error = controller.start().expect_err("pending startup must fail");
        assert_eq!(start_error.stable_code(), "pending_recovery");
        assert_eq!(
            controller.state().expect("starting state"),
            AgentdNeuronLifecycleStateV2::Starting
        );
        assert!(!controller
            .controller_snapshot()
            .expect("starting snapshot")
            .accepting_new_work);
        assert!(matches!(
            active_clone.prepare(
                request.tick_id.clone(),
                active_clone.body_bundle_digest().expect("body digest"),
                request.clone(),
            ),
            Err(NeuronRuntimeV2Error::Admission(NeuronAdmissionError::Revoked))
        ));

        let preserved = controller
            .recover_existing_operation(&request)
            .expect("query-only startup recovery");
        assert_eq!(preserved.status_code, "reserved_not_executed");
        assert!(!preserved.terminal);
        assert_eq!(owner.preserve_recoveries.load(Ordering::SeqCst), 1);
        let preserved_error = controller
            .start()
            .expect_err("preserved work still blocks start");
        assert_eq!(preserved_error.stable_code(), "pending_recovery");

        let closed = controller
            .close_unexecuted_operation(&request)
            .expect("explicit startup closure");
        assert!(closed.terminal);
        assert_eq!(closed.failure_code.as_deref(), Some("admission_denied"));
        assert_eq!(owner.close_recoveries.load(Ordering::SeqCst), 1);

        controller.start().expect("clean startup");
        assert_eq!(
            controller.state().expect("serving state"),
            AgentdNeuronLifecycleStateV2::Serving
        );
        assert!(controller
            .controller_snapshot()
            .expect("serving snapshot")
            .accepting_new_work);
    }

    #[test]
    fn canonical_recovery_policy_tracks_lifecycle_without_opening_the_gate() {
        let (active, owner) = handle(2, true);
        let controller =
            AgentdNeuronGenerationControllerV2::new(active).expect("controller");
        let request = input(2);

        let starting = controller
            .recover_existing_operation(&request)
            .expect("starting recovery");
        assert_eq!(starting.status_code, "reserved_not_executed");
        assert!(!controller
            .controller_snapshot()
            .expect("closed startup snapshot")
            .accepting_new_work);

        controller
            .close_unexecuted_operation(&request)
            .expect("close startup work");
        controller.start().expect("start after closure");
        owner.pending.store(true, Ordering::SeqCst);

        let serving = controller
            .recover_existing_operation(&request)
            .expect("serving recovery");
        assert_eq!(serving.status_code, "reserved_not_executed");
        assert_eq!(owner.preserve_recoveries.load(Ordering::SeqCst), 2);

        controller.begin_quiesce().expect("quiesce");
        let quiescing = controller
            .recover_existing_operation(&request)
            .expect("quiescing recovery");
        assert!(quiescing.terminal);
        assert_eq!(owner.close_recoveries.load(Ordering::SeqCst), 2);
    }

    #[test]
    fn explicit_closure_is_rejected_while_serving() {
        let (active, _) = handle(3, false);
        let controller =
            AgentdNeuronGenerationControllerV2::new(active).expect("controller");
        controller.start().expect("start");
        let error = controller
            .close_unexecuted_operation(&input(3))
            .expect_err("serving closure must be rejected");
        assert_eq!(error.stable_code(), "invalid_lifecycle_transition");
    }
}
