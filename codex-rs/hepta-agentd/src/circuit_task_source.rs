//! Original ordinary-task source and result persistence. This owner stores data;
//! signed admission, source withdrawal, Cell computation and learning authority
//! remain with their existing owners. The host supplies an exclusively owned
//! authorized file and an independently scoped durable rollback witness.

use std::collections::BTreeMap;
use std::fs::File;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_automation::BoundedCircuitDefinitionV2;
use codex_hepta_automation::CircuitDispatchV2;
use codex_hepta_automation::CircuitNodeKindV2;
use codex_hepta_automation::CircuitStartV2;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_intelligence_eval::LockedFileProductEvaluationExecutionStoreV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionAnchorV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionClaimV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStateV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreV1;
use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellCandidateMaskV1;
use codex_hepta_neuron::CellScopeV1;
use codex_hepta_neuron::CellStepInputV1;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::CircuitTaskErrorV1 as Error;
use super::CircuitTaskInputModeV1;
use super::CircuitTaskInputProviderV1;
use super::CircuitTaskReceiptV1;
use super::CircuitTaskRequestV1;
use crate::AgentdCircuitTaskInvocationProviderV1;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::CircuitCellExecutionV1;
use crate::CircuitCellRegistryV1;
use crate::circuit_cell_operation_id_v1;
use crate::circuit_cell_scope_digest_v1;

#[path = "circuit_task_source_codec.rs"]
mod codec;
#[cfg(target_os = "linux")]
pub(crate) use codec::RootHistoricalTaskPublicationDataV1;
#[path = "circuit_task_source_history.rs"]
mod history;
#[cfg(target_os = "linux")]
#[path = "circuit_task_source_close.rs"]
pub(crate) mod source_close;
pub use history::HistoricalCircuitTaskSourceObservationV1;
pub use history::HistoricalCircuitTaskSourceV1;
#[path = "circuit_task_source_journal.rs"]
mod journal;
#[path = "circuit_task_source_readback.rs"]
mod readback;
pub use readback::CircuitTaskSourceReadbackV1;

/// Explicit source bytes and original Cell-clock values, fixed before task
/// ingress. Only the operation ID is derived later from the original Circuit
/// dispatch. No ambient input lookup or clock is consulted on retry/recovery.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CircuitTaskSourceInputV1 {
    pub scope: CellScopeV1,
    pub source_frontier: Digest32,
    pub objective_digest: Digest32,
    pub ndu_snapshot_digest: Digest32,
    pub monotonic_micros: u64,
    pub deadline_micros: u64,
    pub observation: Vec<u8>,
    pub candidates: Vec<CellCandidateMaskV1>,
    pub lease_duration_ms: u64,
}

impl CircuitTaskSourceInputV1 {
    pub(crate) fn input(&self, operation_id: StableId) -> CellStepInputV1 {
        CellStepInputV1 {
            operation_id,
            scope: self.scope.clone(),
            source_frontier: self.source_frontier,
            objective_digest: self.objective_digest,
            ndu_snapshot_digest: self.ndu_snapshot_digest,
            monotonic_micros: self.monotonic_micros,
            deadline_micros: self.deadline_micros,
            observation: self.observation.clone(),
            candidates: self.candidates.clone(),
        }
    }
}

/// Read-only data observed from this owner's original published sealed receipt.
/// It is neither a Circuit receipt constructor nor a learning attestation. A
/// learner must still authenticate current source custody and its own scope.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CircuitTaskSourcePublicationV1 {
    record: RunStartRecordV1,
    input: CellStepInputV1,
    output: Vec<u8>,
    history_digest: Sha256Digest,
    publication_digest: Digest32,
    bundle_digest: Digest32,
    checkpoint_digest: Digest32,
    result_bytes: Vec<u8>,
}

impl CircuitTaskSourcePublicationV1 {
    pub fn original_record(&self) -> &RunStartRecordV1 {
        &self.record
    }
    pub fn input(&self) -> &CellStepInputV1 {
        &self.input
    }
    pub fn output(&self) -> &[u8] {
        &self.output
    }
    pub fn history_digest(&self) -> &Sha256Digest {
        &self.history_digest
    }
    pub fn publication_digest(&self) -> Digest32 {
        self.publication_digest
    }
    pub fn result_bytes(&self) -> &[u8] {
        &self.result_bytes
    }
    pub fn bundle_digest(&self) -> Digest32 {
        self.bundle_digest
    }
    pub fn checkpoint_digest(&self) -> Digest32 {
        self.checkpoint_digest
    }

    pub(crate) fn require_decision(
        &self,
        decision: &codex_hepta_neuron::CellDecisionReceiptV1,
    ) -> Result<(), Error> {
        codec::require_decision(&self.result_bytes, decision)
    }
}

struct SourceOwner<W> {
    journal: LockedFileProductEvaluationExecutionStoreV1,
    witness: W,
    identity: AgentdIdentity,
    fence: TaskFlowFence,
    definition: BoundedCircuitDefinitionV2,
    sources: BTreeMap<String, CircuitTaskSourceInputV1>,
    binding: Digest32,
    fenced: bool,
}

/// One bounded registry (1..=64 runs) for a single root Cell followed by exits.
/// Clones share one writer/lock. Pass a clone to `circuit_task_channel_v1` and
/// an Arc of the same owner to `with_circuit_task_bootstrap`. No key, model,
/// source authorization, path admission or current generation is invented.
pub struct DurableCircuitTaskSourceV1<W: AnchorWitnessStore>(Arc<Mutex<SourceOwner<W>>>);

impl<W: AnchorWitnessStore> Clone for DurableCircuitTaskSourceV1<W> {
    fn clone(&self) -> Self {
        Self(Arc::clone(&self.0))
    }
}

impl<W: AnchorWitnessStore> DurableCircuitTaskSourceV1<W> {
    pub fn create(
        file: File,
        mut witness: W,
        identity: &AgentdIdentity,
        fence: &TaskFlowFence,
        registry: &CircuitCellRegistryV1,
        sources: Vec<CircuitTaskSourceInputV1>,
    ) -> Result<Self, Error> {
        let (sources, binding) = codec::configuration(identity, fence, registry, sources)?;
        if witness
            .current()
            .map_err(|_| Error::CommitUncertain)?
            .is_some()
        {
            return Err(Error::InvalidBinding);
        }
        let journal = LockedFileProductEvaluationExecutionStoreV1::create(file, binding)
            .map_err(|_| Error::Unavailable)?;
        witness
            .compare_and_swap(None, anchor(journal.anchor()))
            .map_err(|_| Error::CommitUncertain)?;
        Ok(Self(Arc::new(Mutex::new(SourceOwner {
            journal,
            witness,
            identity: identity.clone(),
            fence: fence.clone(),
            definition: registry.definition().clone(),
            sources,
            binding,
            fenced: false,
        }))))
    }

    /// Requires the exact original registry, source bytes and witness. Recovery
    /// may acknowledge one fsynced suffix; it never completes a Pending record,
    /// creates an input, reissues computation or changes published result bytes.
    pub fn recover(
        file: File,
        mut witness: W,
        identity: &AgentdIdentity,
        fence: &TaskFlowFence,
        registry: &CircuitCellRegistryV1,
        sources: Vec<CircuitTaskSourceInputV1>,
    ) -> Result<Self, Error> {
        let (sources, binding) = codec::configuration(identity, fence, registry, sources)?;
        let minimum = witness
            .current()
            .map_err(|_| Error::CommitUncertain)?
            .ok_or(Error::ReconciliationRequired)?;
        let sequence = minimum
            .sequence
            .checked_sub(1)
            .ok_or(Error::InvalidBinding)?;
        let journal = LockedFileProductEvaluationExecutionStoreV1::recover(
            file,
            binding,
            ProductEvaluationExecutionAnchorV1 {
                sequence,
                history_digest: minimum.checkpoint_digest,
            },
        )
        .map_err(|_| Error::ReconciliationRequired)?;
        let current = anchor(journal.anchor());
        if current != minimum {
            if current.sequence != minimum.sequence.saturating_add(1) {
                return Err(Error::ReconciliationRequired);
            }
            witness
                .compare_and_swap(Some(minimum), current)
                .map_err(|_| Error::CommitUncertain)?;
        }
        Ok(Self(Arc::new(Mutex::new(SourceOwner {
            journal,
            witness,
            identity: identity.clone(),
            fence: fence.clone(),
            definition: registry.definition().clone(),
            sources,
            binding,
            fenced: false,
        }))))
    }

    /// Reads only an existing original publication; even a valid missing or
    /// Pending run cannot become a new request, input or result here.
    pub fn read_publication(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<CircuitTaskSourcePublicationV1, Error> {
        let mut owner = self.0.lock().map_err(|_| Error::Unavailable)?;
        let request = owner.request(identity, record)?;
        let request_bytes = codec::request(&request, record)?;
        owner.require_bytes("request", &request.start.run_id, &request_bytes)?;
        let saved_input = owner.read("input", &request.start.run_id)?;
        let input = codec::decode_input(&saved_input)?;
        let source = owner
            .sources
            .get(&request.start.run_id)
            .ok_or(Error::InvalidBinding)?;
        if input != source.input(input.operation_id.clone()) {
            return Err(Error::InvalidBinding);
        }
        let result_bytes = owner.read("result", &request.start.run_id)?;
        let (history_digest, output) = codec::publication(&result_bytes, &saved_input)?;
        let (bundle_digest, checkpoint_digest) = codec::decision_metadata(&result_bytes)?;
        owner.require_current()?;
        Ok(CircuitTaskSourcePublicationV1 {
            record: record.clone(),
            input,
            output,
            history_digest,
            bundle_digest,
            checkpoint_digest,
            publication_digest: Digest32::of_parts(&[
                b"hepta.circuit.original-source-publication.v1\0",
                owner.binding.as_array(),
                &request_bytes,
                &saved_input,
                &result_bytes,
            ]),
            result_bytes,
        })
    }

    /// Original source-owner withdrawal. Even an unresolved withdrawal claim
    /// blocks later Prepare and publication reads; this cannot grant authority.
    pub fn withdraw_source(&self, run_id: &StableId) -> Result<(), Error> {
        let mut owner = self.0.lock().map_err(|_| Error::Unavailable)?;
        owner.retain(
            "withdraw",
            run_id.as_str(),
            b"HCSTWDR1",
            CircuitTaskInputModeV1::Prepare,
        )
    }

    /// Read the complete original RunStart from this owner's durable request,
    /// then revalidate its exact publication. This cannot build/admit a task or
    /// fill a missing/Pending stage. Current withdrawal and witness checks run
    /// again after acquiring the publication read lock.
    pub fn read_run_publication(
        &self,
        identity: &AgentdIdentity,
        run_id: &StableId,
    ) -> Result<CircuitTaskSourcePublicationV1, Error> {
        let record = {
            let mut owner = self.0.lock().map_err(|_| Error::Unavailable)?;
            if identity != &owner.identity {
                return Err(Error::InvalidBinding);
            }
            owner.require_active(run_id.as_str())?;
            codec::original_record(&owner.read("request", run_id.as_str())?)?
        };
        if &record.snapshot.run_id != run_id {
            return Err(Error::InvalidBinding);
        }
        self.read_publication(identity, &record)
    }
}

impl<W: AnchorWitnessStore + Send> AgentdCircuitTaskInvocationProviderV1
    for DurableCircuitTaskSourceV1<W>
{
    fn build(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<CircuitTaskRequestV1, AgentdError> {
        let mut owner = self.0.lock().map_err(|_| agent_error(Error::Unavailable))?;
        let request = owner.request(identity, record).map_err(agent_error)?;
        let payload = codec::request(&request, record).map_err(agent_error)?;
        owner
            .retain(
                "request",
                &request.start.run_id,
                &payload,
                CircuitTaskInputModeV1::Prepare,
            )
            .map_err(agent_error)?;
        Ok(request)
    }

    fn observe_learning(
        &self,
        _identity: &AgentdIdentity,
        _record: &RunStartRecordV1,
        _trace: &codex_hepta_automation::CircuitCommittedTraceV2,
    ) -> crate::CircuitTaskLearningReadinessV1 {
        crate::CircuitTaskLearningReadinessV1::NonLearning
    }

    fn publish_result(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
        receipt: &CircuitTaskReceiptV1,
    ) -> Result<(), AgentdError> {
        let mut owner = self.0.lock().map_err(|_| agent_error(Error::Unavailable))?;
        let request = owner.request(identity, record).map_err(agent_error)?;
        owner
            .require_bytes(
                "request",
                &request.start.run_id,
                &codec::request(&request, record).map_err(agent_error)?,
            )
            .map_err(agent_error)?;
        let saved_input = owner
            .read("input", &request.start.run_id)
            .map_err(agent_error)?;
        let input = codec::decode_input(&saved_input).map_err(agent_error)?;
        let payload = codec::result(&owner.definition, &request, &saved_input, &input, receipt)
            .map_err(agent_error)?;
        owner
            .retain(
                "result",
                &request.start.run_id,
                &payload,
                CircuitTaskInputModeV1::Prepare,
            )
            .map_err(agent_error)
    }
}

impl<W: AnchorWitnessStore + Send> CircuitTaskInputProviderV1 for DurableCircuitTaskSourceV1<W> {
    fn resolve(
        &mut self,
        request: &CircuitTaskRequestV1,
        dispatch: &CircuitDispatchV2,
        completed: &BTreeMap<u64, CircuitCellExecutionV1>,
        mode: CircuitTaskInputModeV1,
    ) -> Result<CellStepInputV1, Error> {
        let mut owner = self.0.lock().map_err(|_| Error::Unavailable)?;
        owner.require_active(&request.start.run_id)?;
        let retained = owner.read("request", &request.start.run_id)?;
        codec::require_request(&retained, request)?;
        let source = owner
            .sources
            .get(&request.start.run_id)
            .ok_or(Error::InvalidBinding)?;
        let program = &owner.definition.programs[0];
        if !completed.is_empty()
            || dispatch.run_id != request.start.run_id
            || dispatch.program_id != program.program_id
            || dispatch.node_id != program.entry_node
            || dispatch.round != 0
            || dispatch.scope_digest != request.start.scope_digest
            || dispatch.input_digest != request.start.input_digest
        {
            return Err(Error::InvalidBinding);
        }
        let input = source.input(circuit_cell_operation_id_v1(dispatch)?);
        let payload = codec::dispatch_input(dispatch, &input)?;
        owner.retain("input", &request.start.run_id, &payload, mode)?;
        Ok(input)
    }
}

fn anchor(value: ProductEvaluationExecutionAnchorV1) -> JournalAnchor {
    JournalAnchor {
        sequence: value.sequence + 1,
        checkpoint_digest: value.history_digest,
    }
}

fn agent_error(error: Error) -> AgentdError {
    AgentdError::Protocol(format!("original Circuit source: {error}"))
}

#[cfg(test)]
#[path = "circuit_task_source_tests.rs"]
mod tests;
