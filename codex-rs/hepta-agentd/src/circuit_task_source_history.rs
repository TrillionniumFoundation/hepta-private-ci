//! Historical data from a fully witnessed original source, without reopening
//! its writer. This does not prove publisher retirement, authenticate a new
//! incarnation, or grant Cell, Dataset, learning or Root authority.

use codex_hepta_intelligence_eval::ReadOnlyProductEvaluationExecutionStoreV1;

use super::*;

/// A read-only original source cut. The host must supply the original authorized
/// descriptor, independent witness and exact original configuration. Signed
/// RunStart bytes are recovered from that cut, never accepted as caller claims;
/// their authentication and cross-incarnation admission remain owner duties.
pub struct HistoricalCircuitTaskSourceV1<W> {
    journal: ReadOnlyProductEvaluationExecutionStoreV1,
    witness: W,
    identity: AgentdIdentity,
    fence: TaskFlowFence,
    sources: BTreeMap<String, CircuitTaskSourceInputV1>,
    binding: Digest32,
    fenced: bool,
}

/// One observed original data cut for an independent owner to bind to its own
/// custody record. It does not prove process lifetime or authorize its reuse.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HistoricalCircuitTaskSourceObservationV1 {
    identity: AgentdIdentity,
    fence: TaskFlowFence,
    source: CircuitTaskSourceInputV1,
    binding: Digest32,
    anchor: JournalAnchor,
    publication: CircuitTaskSourcePublicationV1,
}

impl HistoricalCircuitTaskSourceObservationV1 {
    pub fn original_identity(&self) -> &AgentdIdentity {
        &self.identity
    }
    pub fn original_fence(&self) -> &TaskFlowFence {
        &self.fence
    }
    pub fn original_source(&self) -> &CircuitTaskSourceInputV1 {
        &self.source
    }
    pub fn binding_digest(&self) -> Digest32 {
        self.binding
    }
    pub fn journal_anchor(&self) -> JournalAnchor {
        self.anchor
    }
    pub fn publication(&self) -> &CircuitTaskSourcePublicationV1 {
        &self.publication
    }
}

impl<W: AnchorWitnessStore> HistoricalCircuitTaskSourceV1<W> {
    pub fn open(
        file: File,
        witness: W,
        original_identity: &AgentdIdentity,
        original_fence: &TaskFlowFence,
        registry: &CircuitCellRegistryV1,
        sources: Vec<CircuitTaskSourceInputV1>,
    ) -> Result<Self, Error> {
        let (sources, binding) =
            codec::configuration(original_identity, original_fence, registry, sources)?;
        let current = witness
            .current()
            .map_err(|_| Error::CommitUncertain)?
            .ok_or(Error::ReconciliationRequired)?;
        let sequence = current
            .sequence
            .checked_sub(1)
            .ok_or(Error::InvalidBinding)?;
        let journal = ReadOnlyProductEvaluationExecutionStoreV1::open(
            file,
            binding,
            ProductEvaluationExecutionAnchorV1 {
                sequence,
                history_digest: current.checkpoint_digest,
            },
        )
        .map_err(|_| Error::ReconciliationRequired)?;
        let mut history = Self {
            journal,
            witness,
            identity: original_identity.clone(),
            fence: original_fence.clone(),
            sources,
            binding,
            fenced: false,
        };
        history.require_current()?;
        Ok(history)
    }

    /// Observe publication and its exact original context in one exclusive
    /// borrow, after physical journal, withdrawal and witness revalidation.
    pub fn observe_run_publication(
        &mut self,
        run_id: &StableId,
    ) -> Result<HistoricalCircuitTaskSourceObservationV1, Error> {
        let publication = self.read_run_publication(run_id)?;
        Ok(HistoricalCircuitTaskSourceObservationV1 {
            identity: self.identity.clone(),
            fence: self.fence.clone(),
            source: self.sources[run_id.as_str()].clone(),
            binding: self.binding,
            anchor: anchor(self.journal.anchor()),
            publication,
        })
    }

    /// Reads the complete original request, input and result. Missing/Pending
    /// stages, a withdrawal claim, changed bytes or changed witness all refuse
    /// publication. No task or computation is replayed by this operation.
    pub fn read_run_publication(
        &mut self,
        run_id: &StableId,
    ) -> Result<CircuitTaskSourcePublicationV1, Error> {
        let run = run_id.as_str();
        self.require_active(run)?;
        let request_bytes = self.read("request", run)?;
        let record = codec::original_record(&request_bytes)?;
        if &record.snapshot.run_id != run_id {
            return Err(Error::InvalidBinding);
        }
        let source = self.sources.get(run).ok_or(Error::InvalidBinding)?;
        let created_at_ms = record.admission.observed_at_unix_micros / 1_000;
        let deadline_ms = (record.admission.deadline_unix_micros / 1_000)
            .min(record.authentication.expires_at_ms);
        let request = CircuitTaskRequestV1 {
            start: CircuitStartV2 {
                run_id: run.to_owned(),
                scope_digest: circuit_cell_scope_digest_v1(&source.scope)?,
                input_digest: Sha256Digest::for_bytes(&source.observation),
                created_at_ms,
                lease_duration_ms: source.lease_duration_ms,
            },
            objective_digest: source.objective_digest,
            deadline_ms,
        };
        request.validate_record(&record, self.fence.generation)?;
        if source.deadline_micros - source.monotonic_micros
            > deadline_ms
                .saturating_sub(created_at_ms)
                .saturating_mul(1_000)
            || codec::request(&request, &record)? != request_bytes
        {
            return Err(Error::InvalidBinding);
        }
        let saved_input = self.read("input", run)?;
        let input = codec::decode_input(&saved_input)?;
        if input != self.sources[run].input(input.operation_id.clone()) {
            return Err(Error::InvalidBinding);
        }
        let result_bytes = self.read("result", run)?;
        let (history_digest, output) = codec::publication(&result_bytes, &saved_input)?;
        let (bundle_digest, checkpoint_digest) = codec::decision_metadata(&result_bytes)?;
        self.require_active(run)?;
        Ok(CircuitTaskSourcePublicationV1 {
            record,
            input,
            output,
            history_digest,
            bundle_digest,
            checkpoint_digest,
            publication_digest: Digest32::of_parts(&[
                b"hepta.circuit.original-source-publication.v1\0",
                self.binding.as_array(),
                &request_bytes,
                &saved_input,
                &result_bytes,
            ]),
            result_bytes,
        })
    }

    fn state(
        &mut self,
        stage: &str,
        run: &str,
    ) -> Result<ProductEvaluationExecutionStateV1, Error> {
        self.require_current()?;
        if !self.sources.contains_key(run) {
            return Err(Error::InvalidBinding);
        }
        let key = ProductEvaluationExecutionKeyV1 {
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
        };
        let state = self.journal.readback(&key);
        self.require_current()?;
        state.map_err(|error| match error {
            ProductEvaluationExecutionStoreErrorV1::Missing => Error::ReconciliationRequired,
            ProductEvaluationExecutionStoreErrorV1::Conflict
            | ProductEvaluationExecutionStoreErrorV1::Rejected
            | ProductEvaluationExecutionStoreErrorV1::Corrupt => Error::InvalidBinding,
            ProductEvaluationExecutionStoreErrorV1::Unavailable
            | ProductEvaluationExecutionStoreErrorV1::Indeterminate => Error::CommitUncertain,
        })
    }

    fn require_active(&mut self, run: &str) -> Result<(), Error> {
        match self.state("withdraw", run) {
            Err(Error::ReconciliationRequired) => Ok(()),
            Ok(_) => Err(Error::Unavailable),
            Err(error) => Err(error),
        }
    }

    fn read(&mut self, stage: &str, run: &str) -> Result<Vec<u8>, Error> {
        match self.state(stage, run)? {
            ProductEvaluationExecutionStateV1::Completed(bytes) => Ok(bytes),
            ProductEvaluationExecutionStateV1::Pending => Err(Error::ReconciliationRequired),
        }
    }

    fn require_current(&mut self) -> Result<(), Error> {
        if self.fenced {
            return Err(Error::CommitUncertain);
        }
        if !matches!(
            self.witness.current(),
            Ok(Some(current)) if current == anchor(self.journal.anchor())
        ) {
            self.fenced = true;
            return Err(Error::CommitUncertain);
        }
        Ok(())
    }
}
