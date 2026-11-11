//! The original source writer: claim, witness, immutable bytes, witness.
//! An admitted Pending operation remains unresolved after process reopen.

use super::*;

impl<W: AnchorWitnessStore> SourceOwner<W> {
    pub(super) fn request(
        &mut self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<CircuitTaskRequestV1, Error> {
        self.require_current()?;
        if identity != &self.identity {
            return Err(Error::InvalidBinding);
        }
        self.require_active(record.snapshot.run_id.as_str())?;
        let source = self
            .sources
            .get(record.snapshot.run_id.as_str())
            .ok_or(Error::InvalidBinding)?;
        let created_at_ms = record.admission.observed_at_unix_micros / 1_000;
        let deadline_ms = (record.admission.deadline_unix_micros / 1_000)
            .min(record.authentication.expires_at_ms);
        let request = CircuitTaskRequestV1 {
            start: CircuitStartV2 {
                run_id: record.snapshot.run_id.to_string(),
                scope_digest: circuit_cell_scope_digest_v1(&source.scope)?,
                input_digest: Sha256Digest::for_bytes(&source.observation),
                created_at_ms,
                lease_duration_ms: source.lease_duration_ms,
            },
            objective_digest: source.objective_digest,
            deadline_ms,
        };
        request.validate_record(record, self.fence.generation)?;
        if source.deadline_micros - source.monotonic_micros
            > deadline_ms
                .saturating_sub(created_at_ms)
                .saturating_mul(1_000)
        {
            return Err(Error::InvalidBinding);
        }
        Ok(request)
    }

    fn key(&self, stage: &str, run: &str) -> Result<ProductEvaluationExecutionKeyV1, Error> {
        if !self.sources.contains_key(run) {
            return Err(Error::InvalidBinding);
        }
        Ok(ProductEvaluationExecutionKeyV1 {
            plan_id: StableId::new(format!(
                "circuit-source:{stage}:{}",
                Digest32::of_bytes(run.as_bytes())
            ))
            .map_err(|_| Error::InvalidBinding)?,
            binding_digest: Digest32::of_parts(&[
                self.binding.as_array(),
                stage.as_bytes(),
                run.as_bytes(),
            ]),
        })
    }

    pub(super) fn require_active(&mut self, run: &str) -> Result<(), Error> {
        self.require_current()?;
        let key = self.key("withdraw", run)?;
        match self.journal.readback(&key) {
            Err(ProductEvaluationExecutionStoreErrorV1::Missing) => self.require_current(),
            Ok(_) => Err(Error::Unavailable),
            Err(error) => Err(store_error(error)),
        }
    }

    pub(super) fn read(&mut self, stage: &str, run: &str) -> Result<Vec<u8>, Error> {
        self.require_current()?;
        let key = self.key(stage, run)?;
        let result = self.journal.readback(&key).map_err(store_error)?;
        self.require_current()?;
        match result {
            ProductEvaluationExecutionStateV1::Completed(bytes) => Ok(bytes),
            ProductEvaluationExecutionStateV1::Pending => Err(Error::ReconciliationRequired),
        }
    }

    pub(super) fn require_bytes(
        &mut self,
        stage: &str,
        run: &str,
        expected: &[u8],
    ) -> Result<(), Error> {
        if self.read(stage, run)? != expected {
            return Err(Error::InvalidBinding);
        }
        Ok(())
    }

    pub(super) fn retain(
        &mut self,
        stage: &str,
        run: &str,
        payload: &[u8],
        mode: CircuitTaskInputModeV1,
    ) -> Result<(), Error> {
        codec::bounded(payload)?;
        self.require_current()?;
        let key = self.key(stage, run)?;
        match self.journal.readback(&key) {
            Ok(ProductEvaluationExecutionStateV1::Completed(bytes)) => {
                if bytes != payload {
                    return Err(Error::InvalidBinding);
                }
                return self.require_current();
            }
            Ok(ProductEvaluationExecutionStateV1::Pending) => {
                return Err(Error::ReconciliationRequired);
            }
            Err(ProductEvaluationExecutionStoreErrorV1::Missing)
                if mode == CircuitTaskInputModeV1::Prepare => {}
            Err(error) => return Err(store_error(error)),
        }
        let before = anchor(self.journal.anchor());
        if self.journal.claim(&key).map_err(store_error)?
            != ProductEvaluationExecutionClaimV1::Claimed
        {
            return Err(Error::ReconciliationRequired);
        }
        self.anchor_append(before)?;
        let before = anchor(self.journal.anchor());
        self.journal.complete(&key, payload).map_err(store_error)?;
        self.anchor_append(before)?;
        self.require_bytes(stage, run, payload)
    }

    pub(super) fn require_current(&self) -> Result<(), Error> {
        if self.fenced
            || self.witness.current().map_err(|_| Error::CommitUncertain)?
                != Some(anchor(self.journal.anchor()))
        {
            return Err(Error::CommitUncertain);
        }
        Ok(())
    }

    fn anchor_append(&mut self, before: JournalAnchor) -> Result<(), Error> {
        if self
            .witness
            .compare_and_swap(Some(before), anchor(self.journal.anchor()))
            .is_err()
        {
            self.fenced = true;
            return Err(Error::CommitUncertain);
        }
        Ok(())
    }
}

fn store_error(error: ProductEvaluationExecutionStoreErrorV1) -> Error {
    match error {
        ProductEvaluationExecutionStoreErrorV1::Missing => Error::ReconciliationRequired,
        ProductEvaluationExecutionStoreErrorV1::Conflict
        | ProductEvaluationExecutionStoreErrorV1::Rejected
        | ProductEvaluationExecutionStoreErrorV1::Corrupt => Error::InvalidBinding,
        ProductEvaluationExecutionStoreErrorV1::Unavailable
        | ProductEvaluationExecutionStoreErrorV1::Indeterminate => Error::CommitUncertain,
    }
}
