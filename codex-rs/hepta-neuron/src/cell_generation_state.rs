//! Pure replay reducer for the versioned state backend of the Cell owner.

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use crate::cell_generation_types::*;
use crate::cell_task_cost::CellCostEntryV2;
use crate::cell_task_cost::CellTaskCostIdentityV2;
use crate::cell_task_cost::CellTaskCostV2;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CellGenerationConfigV2 {
    pub manifest: CellBackendManifestV2,
    pub initial: CellRuntimeSnapshotV2,
    pub source_frontier: [u8; 32],
    pub task_digest: [u8; 32],
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(tag = "event", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum GenerationEvent {
    Admit {
        request: CellGenerationRequestV2,
        observed_at_micros: u64,
    },
    DispatchObserved {
        request_digest: [u8; 32],
        observed_at_micros: u64,
    },
    Commit {
        proposal: CellGenerationProposalV2,
        settled_at_micros: u64,
    },
    Cancel {
        request_digest: [u8; 32],
    },
    Drain,
    Resume,
    Ack {
        chunk: CellOutputChunkV2,
        acknowledgement: [u8; 32],
        cost: CellTaskCostV2,
    },
    Cost {
        entry: CellCostEntryV2,
    },
}

#[derive(Clone)]
pub(crate) struct GenerationState {
    pub(crate) snapshot: CellRuntimeSnapshotV2,
    pub(crate) first_advance_input_digest: Option<[u8; 32]>,
    pub(crate) pending: Option<CellGenerationRequestV2>,
    pub(crate) cancelled: bool,
    pub(crate) draining: bool,
    pub(crate) outbox: Option<CellOutputChunkV2>,
    pub(crate) receipts: Vec<CellGenerationReceiptV2>,
    pub(crate) intents: Vec<CellGenerationIntentV2>,
    pub(crate) acknowledgements: Vec<[u8; 32]>,
    pub(crate) cost: CellTaskCostV2,
    pub(crate) last_observed_micros: u64,
    pub(crate) dispatch_observed: bool,
}

impl GenerationState {
    pub(crate) fn new(config: &CellGenerationConfigV2) -> Result<Self, CellGenerationErrorV2> {
        config.initial.digest()?;
        if config.initial.manifest_digest != config.manifest.digest()?
            || config.initial.state.len() > config.manifest.max_state_bytes as usize
            || config.initial.revision != 0
            || !config.initial.prefix.is_empty()
            || config.initial.stopped
            || config.source_frontier == [0; 32]
            || config.task_digest == [0; 32]
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        let cost = CellTaskCostV2::new(CellTaskCostIdentityV2 {
            task_digest: config.task_digest,
            source_digest: config.manifest.source_digest,
        })
        .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        Ok(Self {
            snapshot: config.initial.clone(),
            first_advance_input_digest: None,
            pending: None,
            cancelled: false,
            draining: false,
            outbox: None,
            receipts: Vec::new(),
            intents: Vec::new(),
            acknowledgements: Vec::new(),
            cost,
            last_observed_micros: 0,
            dispatch_observed: false,
        })
    }

    pub(crate) fn lookup(
        &self,
        request: &CellGenerationRequestV2,
    ) -> Result<Option<CellGenerationReceiptV2>, CellGenerationErrorV2> {
        let request_digest = request.digest()?;
        if let Some(receipt) = self
            .receipts
            .iter()
            .find(|r| r.operation_id == request.operation_id)
        {
            return if receipt.request_digest == request_digest {
                Ok(Some(receipt.clone()))
            } else {
                Err(CellGenerationErrorV2::Conflict)
            };
        }
        Ok(None)
    }

    pub(crate) fn reserved_records(&self) -> u64 {
        // Pending work needs settlement and possibly cancellation, drain and ACK.
        if self.pending.is_some() {
            2 + u64::from(!self.cancelled)
                + u64::from(!self.draining)
                + u64::from(!self.dispatch_observed)
        } else {
            u64::from(self.outbox.is_some()) + u64::from(!self.draining)
        }
    }

    pub(crate) fn apply(
        &mut self,
        config: &CellGenerationConfigV2,
        event: &GenerationEvent,
    ) -> Result<(), CellGenerationErrorV2> {
        match event {
            GenerationEvent::Admit {
                request,
                observed_at_micros,
            } => {
                if *observed_at_micros < self.last_observed_micros
                    || *observed_at_micros < request.admitted_at_micros
                    || *observed_at_micros >= request.deadline_micros
                {
                    return Err(CellGenerationErrorV2::Deadline);
                }
                if self.lookup(request)?.is_some() {
                    return Err(CellGenerationErrorV2::Conflict);
                }
                if self.draining {
                    return Err(CellGenerationErrorV2::Draining);
                }
                if self.snapshot.stopped {
                    return Err(CellGenerationErrorV2::Stopped);
                }
                if self.pending.is_some() || self.outbox.is_some() {
                    return Err(CellGenerationErrorV2::Pending);
                }
                if request.predecessor != self.snapshot
                    || request.source_frontier != config.source_frontier
                    || request.task_digest != config.task_digest
                {
                    return Err(CellGenerationErrorV2::Conflict);
                }
                if request.input.len() > config.manifest.max_input_bytes as usize
                    || self.receipts.len() >= 256
                    || self.snapshot.revision == u64::MAX
                {
                    return Err(CellGenerationErrorV2::Capacity);
                }
                self.pending = Some(request.clone());
                self.cancelled = false;
                self.last_observed_micros = *observed_at_micros;
                self.dispatch_observed = false;
            }
            GenerationEvent::DispatchObserved {
                request_digest,
                observed_at_micros,
            } => {
                let pending = self
                    .pending
                    .as_ref()
                    .ok_or(CellGenerationErrorV2::Conflict)?;
                if pending.digest()? != *request_digest || self.dispatch_observed {
                    return Err(CellGenerationErrorV2::Conflict);
                }
                if *observed_at_micros < self.last_observed_micros
                    || *observed_at_micros >= pending.deadline_micros
                {
                    return Err(CellGenerationErrorV2::Deadline);
                }
                self.last_observed_micros = *observed_at_micros;
                self.dispatch_observed = true;
            }
            GenerationEvent::Commit {
                proposal,
                settled_at_micros,
            } => {
                self.commit(config, proposal, *settled_at_micros)?;
            }
            GenerationEvent::Cancel { request_digest } => {
                if self
                    .pending
                    .as_ref()
                    .ok_or(CellGenerationErrorV2::Conflict)?
                    .digest()?
                    != *request_digest
                {
                    return Err(CellGenerationErrorV2::Conflict);
                }
                self.cancelled = true;
            }
            GenerationEvent::Drain => self.draining = true,
            GenerationEvent::Resume => {
                if self.pending.is_some() || self.outbox.is_some() {
                    return Err(CellGenerationErrorV2::Pending);
                }
                self.draining = false;
            }
            GenerationEvent::Ack {
                chunk,
                acknowledgement,
                cost,
            } => {
                if self.outbox.as_ref() != Some(chunk) || *acknowledgement == [0; 32] {
                    return Err(CellGenerationErrorV2::Conflict);
                }
                if cost.entries().len() > config.manifest.max_ack_cost_entries as usize {
                    return Err(CellGenerationErrorV2::Capacity);
                }
                self.merge_cost(cost)?;
                self.acknowledgements
                    .push(digest(b"hepta.cell.output-ack.v2\0", event)?);
                self.outbox = None;
            }
            GenerationEvent::Cost { entry } => {
                self.cost
                    .record(entry.clone())
                    .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
            }
        }
        let reserved_cost = if self.pending.is_some() {
            config.manifest.max_step_cost_entries + config.manifest.max_ack_cost_entries
        } else if self.outbox.is_some() {
            config.manifest.max_ack_cost_entries
        } else {
            0
        };
        if self.cost.entries().len() + reserved_cost as usize > 4_096 {
            return Err(CellGenerationErrorV2::Capacity);
        }
        Ok(())
    }

    fn merge_cost(&mut self, cost: &CellTaskCostV2) -> Result<(), CellGenerationErrorV2> {
        cost.validate()
            .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        if cost.identity() != self.cost.identity() {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        for entry in cost.entries() {
            self.cost
                .record(entry.clone())
                .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        }
        Ok(())
    }

    fn commit(
        &mut self,
        config: &CellGenerationConfigV2,
        proposal: &CellGenerationProposalV2,
        now_micros: u64,
    ) -> Result<(), CellGenerationErrorV2> {
        let request = self
            .pending
            .as_ref()
            .ok_or(CellGenerationErrorV2::Conflict)?
            .clone();
        let manifest = &config.manifest;
        if request.digest()? != proposal.request_digest
            || proposal.bundle_digest != manifest.bundle_digest
            || proposal.runtime_digest != manifest.runtime_digest
            || proposal.device_digest != manifest.device_digest
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        if now_micros < request.admitted_at_micros || now_micros < self.last_observed_micros {
            return Err(CellGenerationErrorV2::Deadline);
        }
        if proposal.successor_state.len() > manifest.max_state_bytes as usize
            || proposal.cost.entries().len() > manifest.max_step_cost_entries as usize
            || proposal.output_delta.len() > manifest.max_delta_bytes as usize
        {
            return Err(CellGenerationErrorV2::Capacity);
        }
        let advances = matches!(
            proposal.disposition,
            CellGenerationDispositionV2::Advanced | CellGenerationDispositionV2::Stopped
        );
        if !advances
            && (!proposal.output_delta.is_empty()
                || proposal.successor_state != self.snapshot.state)
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        self.merge_cost(&proposal.cost)?;
        let disposition = if self.cancelled {
            CellGenerationDispositionV2::Cancelled
        } else if now_micros >= request.deadline_micros {
            CellGenerationDispositionV2::DeadlineExceeded
        } else {
            proposal.disposition
        };
        if matches!(
            disposition,
            CellGenerationDispositionV2::Advanced | CellGenerationDispositionV2::Stopped
        ) {
            if self.snapshot.prefix.len() + proposal.output_delta.len()
                > manifest.max_prefix_bytes as usize
            {
                return Err(CellGenerationErrorV2::Capacity);
            }
            if !proposal.output_delta.is_empty() {
                self.outbox = Some(CellOutputChunkV2 {
                    operation_id: request.operation_id.clone(),
                    request_digest: proposal.request_digest,
                    prefix_offset: self.snapshot.prefix.len() as u64,
                    bytes: proposal.output_delta.clone(),
                });
            }
            self.first_advance_input_digest
                .get_or_insert_with(|| Digest32::of_bytes(&request.input).into_array());
            self.snapshot.state = proposal.successor_state.clone();
            self.snapshot
                .prefix
                .extend_from_slice(&proposal.output_delta);
            self.snapshot.stopped = disposition == CellGenerationDispositionV2::Stopped;
        }
        self.snapshot.revision += 1;
        self.intents.push(request.intent()?);
        self.receipts.push(CellGenerationReceiptV2 {
            operation_id: request.operation_id,
            request_digest: proposal.request_digest,
            proposal_digest: digest(b"hepta.cell.generation-proposal.v2\0", proposal)?,
            checkpoint_after: self.snapshot.digest()?,
            disposition,
            cost: proposal.cost.clone(),
        });
        self.pending = None;
        self.cancelled = false;
        self.last_observed_micros = now_micros;
        Ok(())
    }
}
