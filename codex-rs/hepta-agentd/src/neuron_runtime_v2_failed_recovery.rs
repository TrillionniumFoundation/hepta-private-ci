impl AgentdNeuronGenerationControllerV2 {
    /// Re-arm a failed controller for startup reconciliation without opening
    /// any execution gate.
    ///
    /// This is an explicit administrative acknowledgement, not a retry of a
    /// model operation and not result-use authorization. Every active and
    /// retained handle is fenced first, the `Starting` state is durably
    /// published, and normal `start()` reconciliation remains mandatory before
    /// the active generation can serve new work.
    pub fn recover_failed(&self) -> Result<(), AgentdNeuronControlErrorV2> {
        let mut state = self.lock_state()?;
        if state.lifecycle != AgentdNeuronLifecycleStateV2::Failed {
            return Err(AgentdNeuronControlErrorV2::InvalidTransition);
        }
        state.active.close_lifecycle_gate()?;
        for handle in state.retained.values() {
            handle.close_lifecycle_gate()?;
        }
        state
            .persist_transition(AgentdNeuronLifecycleStateV2::Starting, None)
            .map_err(poison_control_state)?;
        state.lifecycle = AgentdNeuronLifecycleStateV2::Starting;
        state.reload_target_generation = None;
        Ok(())
    }
}

#[cfg(test)]
mod failed_recovery_tests {
    use super::*;

    use codex_hepta_neuron::NeuronStorageCapacityV2;

    struct FailedRecoveryOwner {
        generation: u64,
        reconciles: AtomicU64,
    }

    impl ProductNeuronOwnerV2 for FailedRecoveryOwner {
        fn execute(
            &self,
            _input: NeuronTickInputV1,
            _guard: &mut dyn NeuronAdmissionGuard,
        ) -> Result<NeuronRuntimeCommitV2, NeuronRuntimeV2Error> {
            Err(NeuronRuntimeV2Error::PendingOperation)
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
            Ok(NeuronOperationStatusV2::NotRecorded)
        }

        fn capacity_snapshot(&self) -> Result<NeuronRuntimeCapacityV2, NeuronRuntimeV2Error> {
            let storage = NeuronStorageCapacityV2 {
                records: 0,
                record_limit: 8,
                file_bytes: 64,
                byte_limit: 8 * 1024,
                reserved_bytes: 0,
            };
            Ok(NeuronRuntimeCapacityV2 {
                generation: storage,
                index: storage,
                witness_records_remaining: Some(8),
            })
        }

        fn generation(&self) -> Option<u64> {
            Some(self.generation)
        }

        fn body_bundle_digest(&self) -> Option<Digest32> {
            Some(Digest32::of_bytes(b"failed-recovery-body"))
        }
    }

    fn failed_handle() -> (AgentdNeuronHandleV2, Arc<FailedRecoveryOwner>) {
        let owner = Arc::new(FailedRecoveryOwner {
            generation: 1,
            reconciles: AtomicU64::new(0),
        });
        (
            AgentdNeuronHandleV2 {
                owner: owner.clone(),
                config_digest: Digest32::of_bytes(b"failed-recovery-config"),
                lifecycle_gate: Arc::new(AgentdNeuronExecutionGateV2::standalone()),
            },
            owner,
        )
    }

    #[test]
    fn failed_controller_requires_explicit_closed_startup_recovery() {
        let directory = super::durable_state_tests::private_state_directory();
        let state_path = directory.path().join("neuron-generation-state.json");
        let failed = AgentdNeuronGenerationStateV2::new(
            AgentdNeuronLifecycleStateV2::Failed,
            1,
            Vec::new(),
            None,
        )
        .expect("failed state");
        write_agentd_neuron_generation_state_v2(&state_path, &failed)
            .expect("persist failed state");

        let (active, owner) = failed_handle();
        let controller =
            AgentdNeuronGenerationControllerV2::from_recovered_generations_with_state_path(
                active,
                std::iter::empty(),
                &state_path,
            )
            .expect("rebuild failed controller");
        assert_eq!(
            controller.state().expect("failed lifecycle"),
            AgentdNeuronLifecycleStateV2::Failed
        );
        let before = controller
            .controller_snapshot()
            .expect("failed controller snapshot");
        assert!(!before.accepting_new_work);

        controller
            .recover_failed()
            .expect("re-arm startup recovery");
        assert_eq!(
            controller.state().expect("starting lifecycle"),
            AgentdNeuronLifecycleStateV2::Starting
        );
        let starting =
            read_agentd_neuron_generation_state_v2(&state_path).expect("persisted starting state");
        assert_eq!(starting.lifecycle, AgentdNeuronLifecycleStateV2::Starting);
        assert!(
            !controller
                .controller_snapshot()
                .expect("starting controller snapshot")
                .accepting_new_work
        );

        controller.start().expect("reconcile and start");
        assert_eq!(owner.reconciles.load(Ordering::SeqCst), 1);
        assert_eq!(
            controller.state().expect("serving lifecycle"),
            AgentdNeuronLifecycleStateV2::Serving
        );
        assert!(
            controller
                .controller_snapshot()
                .expect("serving controller snapshot")
                .accepting_new_work
        );
    }
}
