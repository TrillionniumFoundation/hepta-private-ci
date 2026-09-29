impl<W: AnchorWitnessStore> NeuronRuntimeV2<W> {
    pub fn query_operation(
        &mut self,
        tick_id: &StableId,
        input_digest: Digest32,
    ) -> Result<NeuronOperationStatusV2, NeuronRuntimeV2Error> {
        let key = NeuronOperationKeyV2 {
            tick_id: tick_id.clone(),
            input_semantic_digest: input_digest,
        };
        key.semantic_digest()?;
        // Recover the local commit without making a remote witness outage hide
        // an already durable outcome. The normal execution/recovery paths still
        // reconcile the independent witness.
        self.finish_pending_index_commit()?;
        if let Some(record) = self.store.find_operation(&key)? {
            if self.index.failure(&key)?.is_some() {
                return Err(NeuronRuntimeV2Error::RecoveryMismatch);
            }
            return Ok(NeuronOperationStatusV2::Committed {
                commit: Box::new(self.commit_from_record(&record)?),
                witness_acknowledged: record.witness_acknowledged,
            });
        }
        if let Some(failure) = self.index.failure(&key)? {
            return Ok(NeuronOperationStatusV2::Failed(failure));
        }
        if let Some(pending) = self.index.pending()?
            && pending.key.tick_id == key.tick_id
        {
            if pending.key != key {
                return Err(NeuronRuntimeV2Error::OperationConflict);
            }
            return Ok(if self.index.dispatched()? {
                NeuronOperationStatusV2::OutcomeUnknown
            } else {
                NeuronOperationStatusV2::NotExecuted
            });
        }
        Ok(NeuronOperationStatusV2::NotRecorded)
    }

    /// Convenience entry point that derives the exact semantic operation key
    /// from the same immutable input accepted by `tick_guarded`.
    pub fn query_input_operation(
        &mut self,
        input: &NeuronTickInputV1,
    ) -> Result<NeuronOperationStatusV2, NeuronRuntimeV2Error> {
        self.query_operation(&input.tick_id, input.semantic_digest()?)
    }

    /// Administrative inspection of the single in-flight operation, if any.
    /// The returned status grants neither model execution nor result use.
    pub fn pending_operation_status(
        &mut self,
    ) -> Result<Option<(NeuronOperationKeyV2, NeuronOperationStatusV2)>, NeuronRuntimeV2Error> {
        self.finish_pending_index_commit()?;
        let Some(pending) = self.index.pending()? else {
            return Ok(None);
        };
        let key = pending.key;
        let status = self.query_operation(&key.tick_id, key.input_semantic_digest)?;
        Ok(Some((key, status)))
    }

    /// Administrative result read retained for recovery tooling. Product result
    /// release must use `query_result_guarded` or a guarded execution path.
    pub fn query_result(
        &mut self,
        tick_id: &StableId,
        input_digest: Digest32,
    ) -> Result<Option<NeuronRuntimeCommitV2>, NeuronRuntimeV2Error> {
        self.reconcile()?;
        match self.query_operation(tick_id, input_digest)? {
            NeuronOperationStatusV2::Committed { commit, .. } => Ok(Some(*commit)),
            NeuronOperationStatusV2::Failed(failure) => {
                Err(NeuronRuntimeV2Error::TerminalFailure(failure))
            }
            NeuronOperationStatusV2::NotRecorded => Ok(None),
            NeuronOperationStatusV2::NotExecuted | NeuronOperationStatusV2::OutcomeUnknown => {
                Err(NeuronRuntimeV2Error::PendingOperation)
            }
        }
    }

    /// Current-use gate for an immutable committed result. This performs only
    /// local reconciliation and a live guard check; it never dispatches or
    /// reconciles provider work.
    pub fn query_result_guarded(
        &mut self,
        input: &NeuronTickInputV1,
        guard: &mut dyn NeuronAdmissionGuard,
    ) -> Result<Option<NeuronRuntimeCommitV2>, NeuronRuntimeV2Error> {
        self.query_result_with_input_digest_guarded(input, input.semantic_digest()?, guard)
    }

    /// Reuse current-use authorization for an owning adapter's exact input key.
    pub(crate) fn query_result_with_input_digest_guarded(
        &mut self,
        input: &NeuronTickInputV1,
        input_digest: Digest32,
        guard: &mut dyn NeuronAdmissionGuard,
    ) -> Result<Option<NeuronRuntimeCommitV2>, NeuronRuntimeV2Error> {
        self.reconcile()?;
        match self.query_operation(&input.tick_id, input_digest)? {
            NeuronOperationStatusV2::Committed { commit, .. } => {
                guard
                    .check(&self.config, input)
                    .map_err(NeuronRuntimeV2Error::Admission)?;
                Ok(Some(*commit))
            }
            NeuronOperationStatusV2::Failed(failure) => {
                Err(NeuronRuntimeV2Error::TerminalFailure(failure))
            }
            NeuronOperationStatusV2::NotRecorded => Ok(None),
            NeuronOperationStatusV2::NotExecuted | NeuronOperationStatusV2::OutcomeUnknown => {
                Err(NeuronRuntimeV2Error::PendingOperation)
            }
        }
    }
}
