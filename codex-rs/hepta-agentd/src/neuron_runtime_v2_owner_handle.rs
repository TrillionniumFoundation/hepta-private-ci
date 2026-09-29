impl<W, P> AgentdNeuronOwnerV2<W, P>
where
    W: AnchorWitnessStore + Send + 'static,
    P: DurableNeuronInferenceControlPort + Send + 'static,
{
    pub fn into_shared<G>(
        self,
        admission: G,
    ) -> Result<AgentdNeuronHandleV2, NeuronRuntimeV2Error>
    where
        G: NeuronAdmissionGuard + Send + 'static,
    {
        let config_digest = self.runtime.configuration_digest()?;
        let generation = self.runtime.configuration().generation.get();
        let body_bundle_digest = self.runtime.body_bundle_digest();
        Ok(AgentdNeuronHandleV2 {
            owner: Arc::new(SharedProductNeuronOwnerV2 {
                guarded: Mutex::new(GuardedOwnerV2 {
                    owner: self,
                    admission,
                }),
                counters: AgentdNeuronCounterStoreV2::default(),
                telemetry: Mutex::new(AgentdNeuronTelemetryV2::default()),
                generation,
                body_bundle_digest,
            }),
            config_digest,
            lifecycle_gate: Arc::new(AgentdNeuronExecutionGateV2::standalone()),
        })
    }
}

impl AgentdNeuronHandleV2 {
    pub fn configuration_digest(&self) -> Digest32 {
        self.config_digest
    }

    pub fn generation(&self) -> Result<u64, AgentdNeuronControlErrorV2> {
        self.owner
            .generation()
            .ok_or(AgentdNeuronControlErrorV2::GenerationConflict)
    }

    pub fn body_bundle_digest(&self) -> Option<Digest32> {
        self.owner.body_bundle_digest()
    }

    /// Administrative local reconciliation. This never dispatches model work.
    pub fn reconcile(&self) -> Result<(), NeuronRuntimeV2Error> {
        self.owner.reconcile()
    }

    /// Reconcile local durable obligations and prove that no operation or
    /// witness acknowledgement remains pending before a lifecycle transition.
    ///
    /// This postcondition is intentionally stronger than the compatibility
    /// `reconcile()` method: daemon start, seal and generation handoff must not
    /// open an execution gate while exact recovery is still required.
    pub fn reconcile_control(&self) -> Result<(), AgentdNeuronControlErrorV2> {
        self.owner.reconcile_control()?;
        let snapshot = self.owner.operational_snapshot_control()?;
        if snapshot.pending_operation_code.is_some() || snapshot.pending_witness_count != 0 {
            Err(AgentdNeuronControlErrorV2::PendingRecovery)
        } else {
            Ok(())
        }
    }

    /// Query exact operation truth through the same serialized product owner.
    pub fn query_operation(
        &self,
        tick_id: &StableId,
        input_digest: Digest32,
    ) -> Result<NeuronOperationStatusV2, NeuronRuntimeV2Error> {
        self.owner.query_operation(tick_id, input_digest)
    }

    pub fn query_operation_control(
        &self,
        tick_id: &StableId,
        input_digest: Digest32,
    ) -> Result<NeuronOperationStatusV2, AgentdNeuronControlErrorV2> {
        self.owner.query_operation_control(tick_id, input_digest)
    }

    /// Derive the canonical input digest and query the exact operation through
    /// the same serialized owner. This is the preferred host integration path.
    pub fn query_input_operation(
        &self,
        input: &NeuronTickInputV1,
    ) -> Result<NeuronOperationStatusV2, NeuronRuntimeV2Error> {
        self.query_operation(&input.tick_id, input.semantic_digest()?)
    }

    /// Converge provider truth without closing a proven-unexecuted reservation.
    /// This is the serving/startup-safe recovery boundary; the report omits the
    /// model result and grants no result-use authority.
    pub fn recover_operation(
        &self,
        input: &NeuronTickInputV1,
    ) -> Result<AgentdNeuronRecoveryReportV2, AgentdNeuronControlErrorV2> {
        self.recover_operation_with_policy(
            input,
            AgentdNeuronRecoveryPolicyV2::PreserveUnexecuted,
        )
    }

    pub(crate) fn recover_operation_with_policy(
        &self,
        input: &NeuronTickInputV1,
        policy: AgentdNeuronRecoveryPolicyV2,
    ) -> Result<AgentdNeuronRecoveryReportV2, AgentdNeuronControlErrorV2> {
        self.owner
            .recover_operation_control_with_policy(input, policy)
            .map(AgentdNeuronRecoveryReportV2::from_status)
    }

    /// Current-use check for a durable result. This performs no provider work.
    pub fn query_result_guarded(
        &self,
        input: &NeuronTickInputV1,
        guard: &mut dyn NeuronAdmissionGuard,
    ) -> Result<Option<NeuronRuntimeCommitV2>, NeuronRuntimeV2Error> {
        self.owner.query_result_guarded(input, guard)
    }

    /// Advisory capacity through the same serialized product owner. Admission
    /// remains authoritative and may reject payload-specific work sooner.
    pub fn capacity_snapshot(&self) -> Result<NeuronRuntimeCapacityV2, NeuronRuntimeV2Error> {
        self.owner.capacity_snapshot()
    }

    pub fn operational_snapshot(
        &self,
    ) -> Result<AgentdNeuronOperationalSnapshotV2, AgentdNeuronControlErrorV2> {
        self.owner.operational_snapshot_control()
    }

    pub fn operational_counters(&self) -> AgentdNeuronOperationalCountersV2 {
        self.owner.operational_counters()
    }

    pub fn prepare(
        &self,
        run_id: StableId,
        runtime_body_digest: Digest32,
        input: NeuronTickInputV1,
    ) -> Result<AgentdNeuronInvocationV2, NeuronRuntimeV2Error> {
        let semantic = input.semantic_digest();
        if semantic.is_err() {
            self.owner.record_entry_rejection();
        }
        semantic?;
        let body_matches = self
            .body_bundle_digest()
            .is_none_or(|expected| expected == runtime_body_digest);
        if input.tick_id != run_id
            || runtime_body_digest.is_zero()
            || !body_matches
            || input.body_generation.is_none_or(|generation| generation == 0)
        {
            self.owner.record_entry_rejection();
            return Err(NeuronRuntimeV2Error::Admission(
                NeuronAdmissionError::BindingMismatch,
            ));
        }
        let lifecycle_epoch = match self.lifecycle_gate.capture() {
            Ok(epoch) => epoch,
            Err(error) => {
                self.owner.record_stale_invocation_rejection();
                return Err(error);
            }
        };
        Ok(AgentdNeuronInvocationV2 {
            handle: self.clone(),
            run_id,
            runtime_body_digest,
            input,
            lifecycle_epoch,
        })
    }

    pub(crate) fn close_lifecycle_gate(&self) -> Result<(), AgentdNeuronControlErrorV2> {
        self.lifecycle_gate.close()
    }

    pub(crate) fn open_lifecycle_gate(&self) -> Result<(), AgentdNeuronControlErrorV2> {
        self.lifecycle_gate.open()
    }

    pub(crate) fn try_drain_lifecycle_gate(
        &self,
    ) -> Result<RwLockWriteGuard<'_, ()>, AgentdNeuronControlErrorV2> {
        self.lifecycle_gate.try_drain()
    }

    pub(crate) fn lifecycle_gate_snapshot(&self) -> (bool, u64) {
        self.lifecycle_gate.snapshot()
    }
}
