//! Bounded control commands executed inside the existing sole journal owner.
//! The wire carries references; state, prefix and admission time stay here.

use codex_hepta_agent_protocol::GenerationControlRequestV1 as Request;
use codex_hepta_agent_protocol::GenerationControlResponseV1 as Response;
use codex_hepta_agent_protocol::GenerationOutputReferenceV1;
use codex_hepta_agent_protocol::GenerationStatusV1;
use codex_hepta_agent_protocol::GenerationStepV1;
use codex_hepta_agent_protocol::MAX_GENERATION_CONTROL_INPUT_BYTES;
use codex_hepta_agent_protocol::MAX_GENERATION_OUTPUT_PAGE_BYTES;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellCostAccountingV2;
use codex_hepta_neuron::CellCostEntryV2;
use codex_hepta_neuron::CellCostMetricsV2;
use codex_hepta_neuron::CellCostOutcomeV2;
use codex_hepta_neuron::CellCostStageV2;
use codex_hepta_neuron::CellGenerationControlPortV2;
use codex_hepta_neuron::CellGenerationErrorV2 as Error;
use codex_hepta_neuron::CellGenerationIntentV2;
use codex_hepta_neuron::CellGenerationRequestV2;
use codex_hepta_neuron::CellOutputChunkV2;
use codex_hepta_neuron::CellTaskCostV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::BoundGenerationOwner;
use super::GenerationOwnerBoundary;
use super::require_admission;
use super::require_pending;
use super::require_recovery;
use crate::AgentdState;

#[path = "neuron_generation_control_codec.rs"]
mod codec;

impl<W, P, C> BoundGenerationOwner<W, P, C>
where
    W: AnchorWitnessStore + Send,
    P: CellGenerationControlPortV2 + Send,
    C: FnMut() -> u64 + Send,
{
    pub(super) fn control(
        &mut self,
        request: Request,
        state: &AgentdState,
    ) -> Result<Response, Error> {
        require_recovery(state)?;
        match request {
            Request::Status {} => {
                let journal = self.owner.journal();
                let snapshot = journal.snapshot()?;
                Ok(Response::Status(Box::new(GenerationStatusV1 {
                    snapshot_digest: snapshot.digest()?,
                    manifest_digest: snapshot.manifest_digest,
                    principal_digest: snapshot.scope.principal_digest,
                    agent_id: snapshot.scope.agent_id.clone(),
                    cell_id: snapshot.scope.cell_id.clone(),
                    run_id: snapshot.scope.run_id.clone(),
                    generation: snapshot.generation,
                    writer_epoch: snapshot.writer_epoch,
                    revision: snapshot.revision,
                    state_bytes: snapshot.state.len() as u32,
                    prefix_bytes: snapshot.prefix.len() as u32,
                    stopped: snapshot.stopped,
                    drained: journal.is_drained()?,
                    observed_at_micros: (self.clock)(),
                    pending: journal.pending_request()?.map(codec::pending).transpose()?,
                    output: journal.pending_output()?.map(codec::output).transpose()?,
                })))
            }
            Request::Step { request } => self.control_step(*request, state),
            Request::Reconcile { request_digest } => {
                if let Some(receipt) = self
                    .owner
                    .journal()
                    .receipt_by_request_digest(request_digest)?
                {
                    return codec::receipt(receipt).map(Response::Receipt);
                }
                require_pending(&self.owner, request_digest)?;
                let result = self
                    .owner
                    .reconcile_checked(&mut self.clock, || require_recovery(state));
                self.control_settlement(result)
            }
            Request::Cancel { request_digest } => {
                require_pending(&self.owner, request_digest)?;
                self.owner
                    .cancel_pending_checked(|| require_recovery(state))?;
                Ok(Response::CancelRequested {})
            }
            Request::Output {
                expected_chunk_digest,
                offset,
                limit,
            } => {
                if limit == 0 || limit > MAX_GENERATION_OUTPUT_PAGE_BYTES {
                    return Err(Error::Capacity);
                }
                let chunk = self
                    .owner
                    .journal()
                    .pending_output()?
                    .ok_or(Error::Conflict)?;
                let delivery = codec::output(chunk)?;
                if delivery.chunk_digest != expected_chunk_digest {
                    return Err(Error::Conflict);
                }
                let start = offset as usize;
                if start >= chunk.bytes.len() {
                    return Err(Error::InvalidBinding);
                }
                let end = (start + usize::from(limit)).min(chunk.bytes.len());
                Ok(Response::Output {
                    delivery,
                    offset,
                    bytes: chunk.bytes[start..end].to_vec(),
                    complete: end == chunk.bytes.len(),
                })
            }
            Request::Acknowledge {
                delivery,
                acknowledgement,
            } => self.control_acknowledge(delivery, acknowledgement, state),
            Request::Cost {} => Ok(Response::Cost(Box::new(codec::cost(
                self.owner.journal().task_cost()?,
            )?))),
            Request::Drain {} => Ok(Response::Drain {
                complete: self.owner.drain()?,
            }),
            Request::Resume {} => {
                require_admission(state)?;
                self.owner.journal_mut().resume()?;
                Ok(Response::Resumed {})
            }
        }
    }

    fn control_step(
        &mut self,
        request: GenerationStepV1,
        state: &AgentdState,
    ) -> Result<Response, Error> {
        StableId::new(&request.client_operation_id).map_err(|_| Error::InvalidBinding)?;
        if request.input.len() > MAX_GENERATION_CONTROL_INPUT_BYTES
            || request.input.len() > self.owner.journal().manifest().max_input_bytes as usize
        {
            return Err(Error::Capacity);
        }
        if request.expected_snapshot_digest == [0; 32]
            || request.task_digest == [0; 32]
            || request.source_frontier == [0; 32]
        {
            return Err(Error::InvalidBinding);
        }
        let operation_id = codec::operation_id(&request)?;
        let intent = CellGenerationIntentV2 {
            operation_id: operation_id.clone(),
            task_digest: request.task_digest,
            source_frontier: request.source_frontier,
            predecessor_digest: request.expected_snapshot_digest,
            input_digest: Digest32::of_bytes(&request.input).into_array(),
            deadline_micros: request.deadline_micros,
        };
        if let Some(receipt) = self.owner.journal().receipt_for_intent(&intent)? {
            return codec::receipt(receipt).map(Response::Receipt);
        }
        if let Some(pending) = self.owner.journal().pending_request()? {
            if pending.intent()? != intent {
                return Err(Error::Conflict);
            }
            let result = self
                .owner
                .reconcile_checked(&mut self.clock, || require_recovery(state));
            return self.control_settlement(result);
        }
        let predecessor = self.owner.journal().snapshot()?;
        if predecessor.digest()? != request.expected_snapshot_digest {
            return Err(Error::Conflict);
        }
        require_admission(state)?;
        let original = CellGenerationRequestV2 {
            operation_id,
            task_digest: request.task_digest,
            source_frontier: request.source_frontier,
            predecessor: predecessor.clone(),
            input: request.input,
            admitted_at_micros: (self.clock)(),
            deadline_micros: request.deadline_micros,
        };
        original.digest()?;
        let result =
            self.owner
                .step_checked(original, &mut self.clock, |boundary| match boundary {
                    GenerationOwnerBoundary::Admission | GenerationOwnerBoundary::Dispatch => {
                        require_admission(state)
                    }
                    GenerationOwnerBoundary::Settlement => require_recovery(state),
                });
        self.control_settlement(result)
    }

    fn control_settlement(
        &self,
        result: Result<codex_hepta_neuron::CellGenerationReceiptV2, Error>,
    ) -> Result<Response, Error> {
        match result {
            Ok(receipt) => codec::receipt(receipt).map(Response::Receipt),
            Err(Error::Pending) => self
                .owner
                .journal()
                .pending_request()?
                .ok_or(Error::CommitUncertain)
                .and_then(codec::pending)
                .map(Response::Pending),
            Err(error) => Err(error),
        }
    }

    fn control_acknowledge(
        &mut self,
        delivery: GenerationOutputReferenceV1,
        acknowledgement: [u8; 32],
        state: &AgentdState,
    ) -> Result<Response, Error> {
        StableId::new(&delivery.operation_id).map_err(|_| Error::InvalidBinding)?;
        let journal = self.owner.journal();
        if delivery.bytes == 0 || delivery.bytes > journal.manifest().max_delta_bytes {
            return Err(Error::Capacity);
        }
        let start = usize::try_from(delivery.prefix_offset).map_err(|_| Error::Capacity)?;
        let end = start
            .checked_add(delivery.bytes as usize)
            .ok_or(Error::Capacity)?;
        let retained = journal
            .snapshot()?
            .prefix
            .get(start..end)
            .ok_or(Error::Conflict)?;
        let chunk = CellOutputChunkV2 {
            operation_id: delivery.operation_id.clone(),
            request_digest: delivery.request_digest,
            prefix_offset: delivery.prefix_offset,
            bytes: retained.to_vec(),
        };
        if codec::output(&chunk)? != delivery {
            return Err(Error::Conflict);
        }
        let mut cost = CellTaskCostV2::new(journal.task_cost()?.identity())
            .map_err(|_| Error::InvalidBinding)?;
        // The caller attests delivery; neither a read nor an ACK proves its
        // transport's elapsed/physical cost. Preserve that missing measurement.
        cost.record(CellCostEntryV2 {
            event_id: codec::digest(
                b"hepta.agentd.generation-ack-cost.v1\0",
                &(&delivery, acknowledgement),
            )?,
            identity: cost.identity(),
            stage: CellCostStageV2::Communication,
            outcome: CellCostOutcomeV2::Succeeded,
            accounting: CellCostAccountingV2::Exclusive,
            metrics: CellCostMetricsV2::default(),
        })
        .map_err(|_| Error::InvalidBinding)?;
        require_recovery(state)?;
        self.owner
            .journal_mut()
            .acknowledge(chunk, acknowledgement, cost)?;
        Ok(Response::Acknowledged {})
    }
}
