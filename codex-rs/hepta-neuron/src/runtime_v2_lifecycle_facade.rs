impl<W: AnchorWitnessStore> NeuronRuntimeV2<W> {
    /// Measurements are process-local and include admission, provider work,
    /// encoding, durable commits, witness reconciliation and final-use checks.
    /// They never modify a durable receipt.
    pub fn tick_guarded(
        &mut self,
        model: &mut impl DurableNeuronModelPort,
        input: NeuronTickInputV1,
        guard: &mut dyn NeuronAdmissionGuard,
    ) -> Result<NeuronRuntimeCommitV2, NeuronRuntimeV2Error> {
        let input_digest = input.semantic_digest()?;
        self.tick_with_input_digest_guarded(model, input, input_digest, guard)
    }

    /// Internal typed-input entry. Only a validated owning adapter may derive
    /// an extended identity; ordinary V1 tick keys and persisted bytes stay intact.
    pub(crate) fn tick_with_input_digest_guarded(
        &mut self,
        model: &mut impl DurableNeuronModelPort,
        input: NeuronTickInputV1,
        input_digest: Digest32,
        guard: &mut dyn NeuronAdmissionGuard,
    ) -> Result<NeuronRuntimeCommitV2, NeuronRuntimeV2Error> {
        let started = Instant::now();
        let store_before = self.store.storage_observation();
        let index_before = self.index.storage_observation();
        let witness_before = self.witness.io_metrics();
        let mut phases = PhaseMeasurementV2::default();
        let result = self.tick_guarded_inner(model, input, input_digest, guard, &mut phases);
        let store_after = self.store.storage_observation();
        let index_after = self.index.storage_observation();
        let witness_after = self.witness.io_metrics();
        self.last_measurement = Some(crate::NeuronRuntimeMeasurementV2 {
            total_micros: elapsed_micros(started),
            returned_success: result.is_ok(),
            recovery_only: phases.recovery_only,
            admission_micros: phases.admission_micros,
            local_reconciliation_micros: phases.local_reconciliation_micros,
            provider_micros: phases.provider_micros,
            transition_micros: phases.transition_micros,
            receipt_encode_micros: phases.receipt_encode_micros,
            store_commit_micros: phases.store_commit_micros,
            index_commit_micros: phases.index_commit_micros,
            witness_micros: phases.witness_micros,
            final_use_check_micros: phases.final_use_check_micros,
            checkpoint_payload_bytes: phases.checkpoint_payload_bytes,
            full_receipt_bytes: phases.full_receipt_bytes,
            store_before,
            store_after,
            index_before,
            index_after,
            witness_sync: witness_after
                .zip(witness_before)
                .map(|(after, before)| after.since(before)),
        });
        result
    }

    /// Converge one exact reserved operation without admitting new work or
    /// releasing a result. This method never calls `execute`, never creates a
    /// reservation and never changes the operation identity. A durable owner may
    /// call it while normal admission is revoked or the daemon is quiescing.
    pub fn recover_operation(
        &mut self,
        model: &mut impl DurableNeuronModelPort,
        input: &NeuronTickInputV1,
    ) -> Result<NeuronOperationStatusV2, NeuronRuntimeV2Error> {
        let started = Instant::now();
        let store_before = self.store.storage_observation();
        let index_before = self.index.storage_observation();
        let witness_before = self.witness.io_metrics();
        let mut phases = PhaseMeasurementV2 {
            recovery_only: true,
            ..PhaseMeasurementV2::default()
        };
        let result = self.recover_operation_inner(model, input, &mut phases);
        let store_after = self.store.storage_observation();
        let index_after = self.index.storage_observation();
        let witness_after = self.witness.io_metrics();
        self.last_measurement = Some(crate::NeuronRuntimeMeasurementV2 {
            total_micros: elapsed_micros(started),
            returned_success: result.is_ok(),
            recovery_only: phases.recovery_only,
            admission_micros: phases.admission_micros,
            local_reconciliation_micros: phases.local_reconciliation_micros,
            provider_micros: phases.provider_micros,
            transition_micros: phases.transition_micros,
            receipt_encode_micros: phases.receipt_encode_micros,
            store_commit_micros: phases.store_commit_micros,
            index_commit_micros: phases.index_commit_micros,
            witness_micros: phases.witness_micros,
            final_use_check_micros: phases.final_use_check_micros,
            checkpoint_payload_bytes: phases.checkpoint_payload_bytes,
            full_receipt_bytes: phases.full_receipt_bytes,
            store_before,
            store_after,
            index_before,
            index_after,
            witness_sync: witness_after
                .zip(witness_before)
                .map(|(after, before)| after.since(before)),
        });
        result
    }

    pub fn last_measurement(&self) -> Option<&crate::NeuronRuntimeMeasurementV2> {
        self.last_measurement.as_ref()
    }

    pub fn recovery_micros(&self) -> Option<u64> {
        self.recovery_micros
    }

    pub fn capacity_snapshot(
        &self,
    ) -> Result<crate::NeuronRuntimeCapacityV2, NeuronRuntimeV2Error> {
        Ok(crate::NeuronRuntimeCapacityV2 {
            generation: self.store.capacity_snapshot()?,
            index: self.index.capacity_snapshot()?,
            witness_records_remaining: self.witness.capacity_remaining()?,
        })
    }
}
