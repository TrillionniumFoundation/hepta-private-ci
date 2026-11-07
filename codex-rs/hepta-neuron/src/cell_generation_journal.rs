//! Stateful backend for the existing host-owned Cell journal boundary. It is
//! selected instead of the sparse backend for a partition, never alongside it.
//! A single frame commits successor state, immutable prefix, outbox and cost.

use std::fs::File;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::sync::Arc;

use codex_hepta_types::Digest32;

use crate::AnchorWitnessStore;
use crate::JournalAnchor;
use crate::cell_generation_current::CellGenerationCurrentV1;
use crate::cell_generation_current::CellGenerationOpenModeV1;
use crate::cell_generation_current::CellGenerationOwnerBindingV1;
use crate::cell_generation_current::CellGenerationPreparedCheckpointV1;
use crate::cell_generation_current::continuity_checkpoint;
use crate::cell_generation_observation::CellGenerationObservationV1;
use crate::cell_generation_state::CellGenerationConfigV2;
use crate::cell_generation_state::GenerationEvent;
use crate::cell_generation_state::GenerationState;
use crate::cell_generation_types::*;
use crate::cell_task_cost::CellCostEntryV2;
use crate::cell_task_cost::CellCostRecordV2;
use crate::cell_task_cost::CellTaskCostV2;
use crate::journal_lock::LockedFile;

const MAGIC: &[u8; 8] = b"HPTACG02";
const HEADER_BYTES: usize = 40;
const MAX_FRAME: usize = 2 * 1024 * 1024;
const MAX_BYTES: u64 = 128 * 1024 * 1024;

/// The host supplies the exclusive owner file and separately retained witness.
/// This type supplies no authenticated transport, model grant or adoption right.
pub struct CellGenerationJournalV2<W: AnchorWitnessStore> {
    file: LockedFile,
    witness: W,
    config: CellGenerationConfigV2,
    state: GenerationState,
    header: Vec<u8>,
    head: Option<JournalAnchor>,
    length: u64,
    max_records: u64,
    healthy: bool,
    current: Option<(
        Arc<dyn CellGenerationCurrentV1>,
        CellGenerationOwnerBindingV1,
    )>,
}

impl<W: AnchorWitnessStore> CellGenerationJournalV2<W> {
    pub fn open(
        file: File,
        witness: W,
        config: CellGenerationConfigV2,
        max_records: u64,
    ) -> Result<Self, CellGenerationErrorV2> {
        Self::open_inner(file, witness, config, max_records, /*current*/ None)
    }

    /// Opt-in current-generation custody. Ordinary `open` rejects this format;
    /// an old guarded journal cannot bypass its live Control floor on reopen.
    pub fn open_guarded(
        file: File,
        witness: W,
        config: CellGenerationConfigV2,
        max_records: u64,
        current: Arc<dyn CellGenerationCurrentV1>,
    ) -> Result<Self, CellGenerationErrorV2> {
        let binding = CellGenerationOwnerBindingV1::new(&config, max_records)?;
        current.check_open(&binding)?;
        Self::open_inner(file, witness, config, max_records, Some((current, binding)))
    }

    fn open_inner(
        file: File,
        witness: W,
        config: CellGenerationConfigV2,
        max_records: u64,
        current: Option<(
            Arc<dyn CellGenerationCurrentV1>,
            CellGenerationOwnerBindingV1,
        )>,
    ) -> Result<Self, CellGenerationErrorV2> {
        if !(6..=65_536).contains(&max_records) {
            return Err(CellGenerationErrorV2::Capacity);
        }
        let state = GenerationState::new(&config)?;
        let mut header = MAGIC.to_vec();
        header.extend_from_slice(&digest(
            b"hepta.cell.generation-owner.v2\0",
            &(&config, max_records),
        )?);
        if let Some((_, binding)) = &current {
            header = binding.header();
        }
        let mut file = LockedFile::acquire(file).map_err(|_| CellGenerationErrorV2::Unavailable)?;
        if file
            .metadata()
            .map_err(|_| CellGenerationErrorV2::Unavailable)?
            .len()
            == 0
        {
            if witness
                .current()
                .map_err(|_| CellGenerationErrorV2::Unavailable)?
                .is_some()
            {
                return Err(CellGenerationErrorV2::AcknowledgedHistoryMissing);
            }
            file.seek(SeekFrom::Start(0))
                .map_err(|_| CellGenerationErrorV2::Unavailable)?;
            file.write_all(&header)
                .map_err(|_| CellGenerationErrorV2::CommitUncertain)?;
            file.sync_all()
                .map_err(|_| CellGenerationErrorV2::CommitUncertain)?;
        }
        let mut owner = Self {
            file,
            witness,
            config,
            state,
            header,
            head: None,
            length: 0,
            max_records,
            healthy: false,
            current,
        };
        owner.recover()?;
        Ok(owner)
    }

    /// Reconstruct only retained events. Complete lost-ACK frames are synced
    /// and witnessed before exposure. Missing witnessed suffixes are rejected
    /// before truncation; recovery never calls a model or transport.
    pub fn recover(&mut self) -> Result<(), CellGenerationErrorV2> {
        self.healthy = false;
        let mode = self.open_mode()?;
        let expected = self
            .witness
            .current()
            .map_err(|_| CellGenerationErrorV2::Unavailable)?;
        let length = self
            .file
            .metadata()
            .map_err(|_| CellGenerationErrorV2::Unavailable)?
            .len();
        if !(HEADER_BYTES as u64..=MAX_BYTES).contains(&length) {
            return Err(CellGenerationErrorV2::Corrupt);
        }
        self.file
            .seek(SeekFrom::Start(0))
            .map_err(|_| CellGenerationErrorV2::Unavailable)?;
        let mut bytes = vec![0; length as usize];
        self.file
            .read_exact(&mut bytes)
            .map_err(|_| CellGenerationErrorV2::Unavailable)?;
        if bytes[..HEADER_BYTES] != self.header {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        let mut state = GenerationState::new(&self.config)?;
        let mut offset = HEADER_BYTES;
        let mut head = None;
        let mut witnessed = expected.is_none();
        while bytes.len() - offset >= 4 {
            let size = u32::from_be_bytes(
                bytes[offset..offset + 4]
                    .try_into()
                    .map_err(|_| CellGenerationErrorV2::Corrupt)?,
            ) as usize;
            if size == 0 || size > MAX_FRAME {
                return Err(CellGenerationErrorV2::Corrupt);
            }
            let end = offset + size + 36;
            if end > bytes.len() {
                break;
            }
            let payload = &bytes[offset + 4..end - 32];
            let next = next_anchor(&self.header, head, payload)?;
            if next.sequence > self.max_records
                || next.checkpoint_digest.as_array() != &bytes[end - 32..end]
            {
                return Err(CellGenerationErrorV2::Corrupt);
            }
            let event: GenerationEvent =
                serde_json::from_slice(payload).map_err(|_| CellGenerationErrorV2::Corrupt)?;
            if serde_json::to_vec(&event).map_err(|_| CellGenerationErrorV2::Corrupt)? != payload {
                return Err(CellGenerationErrorV2::Corrupt);
            }
            state.apply(&self.config, &event)?;
            witnessed |= expected == Some(next);
            head = Some(next);
            offset = end;
        }
        if !witnessed {
            return Err(CellGenerationErrorV2::AcknowledgedHistoryMissing);
        }
        if mode == CellGenerationOpenModeV1::Preparing
            && (head.is_some() || length != HEADER_BYTES as u64)
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        self.open_mode()?;
        if offset < bytes.len() {
            self.file
                .set_len(offset as u64)
                .map_err(|_| CellGenerationErrorV2::CommitUncertain)?;
        }
        self.file
            .sync_all()
            .map_err(|_| CellGenerationErrorV2::CommitUncertain)?;
        if let Some(next) = head
            && expected != Some(next)
        {
            self.witness
                .compare_and_swap(expected, next)
                .map_err(|_| CellGenerationErrorV2::CommitUncertain)?;
        }
        self.state = state;
        self.head = head;
        self.length = offset as u64;
        self.healthy = true;
        Ok(())
    }

    pub fn manifest(&self) -> &CellBackendManifestV2 {
        &self.config.manifest
    }

    pub fn snapshot(&self) -> Result<&CellRuntimeSnapshotV2, CellGenerationErrorV2> {
        self.require_healthy()?;
        Ok(&self.state.snapshot)
    }

    /// Capture state, cost, unresolved work and delivery at one healthy owner
    /// cut. This read adds no events and cannot dispatch or settle work.
    pub fn observe_generation(&self) -> Result<CellGenerationObservationV1, CellGenerationErrorV2> {
        CellGenerationObservationV1::capture(
            &self.config,
            &self.state,
            self.continuity_checkpoint()?,
        )
    }

    /// Identify the exact healthy journal cut without adding persistent bytes.
    /// The header binds the frozen config and limits; the head binds every
    /// retained event, including cost, cancellation, drain and delivery ACKs.
    /// This is a continuity observation, not an adoption or writer grant.
    pub fn continuity_checkpoint(&self) -> Result<Digest32, CellGenerationErrorV2> {
        self.require_healthy()?;
        Ok(continuity_checkpoint(&self.header, self.head, self.length))
    }

    pub fn owner_binding(&self) -> Option<&CellGenerationOwnerBindingV1> {
        self.current.as_ref().map(|(_, binding)| binding)
    }

    /// Read an actually synced empty guarded journal. The returned cut cannot
    /// activate it; only the original Control publication changes current.
    pub fn prepared_checkpoint(
        &self,
    ) -> Result<CellGenerationPreparedCheckpointV1, CellGenerationErrorV2> {
        if !self.healthy || self.head.is_some() || self.length != HEADER_BYTES as u64 {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        self.open_mode()?;
        let binding = self
            .owner_binding()
            .ok_or(CellGenerationErrorV2::InvalidBinding)?;
        Ok(CellGenerationPreparedCheckpointV1 {
            binding: binding.clone(),
            checkpoint: continuity_checkpoint(&self.header, self.head, self.length),
        })
    }

    /// Add the host's live selected-artifact and revocation checks before
    /// handing this guarded journal to the normal runtime. Its immutable
    /// binding and original protected header cannot change through this API.
    pub fn rebind_current(
        mut self,
        current: Arc<dyn CellGenerationCurrentV1>,
    ) -> Result<Self, CellGenerationErrorV2> {
        self.require_healthy()?;
        let binding = self
            .owner_binding()
            .ok_or(CellGenerationErrorV2::InvalidBinding)?
            .clone();
        current.check_current(&binding)?;
        self.current = Some((current, binding));
        Ok(self)
    }

    /// Recheck the same live owner immediately before external computation.
    pub fn require_current(&self) -> Result<(), CellGenerationErrorV2> {
        if let Some((current, binding)) = &self.current {
            current.check_current(binding)?;
        }
        Ok(())
    }

    fn open_mode(&self) -> Result<CellGenerationOpenModeV1, CellGenerationErrorV2> {
        self.current.as_ref().map_or(
            Ok(CellGenerationOpenModeV1::Active),
            |(current, binding)| current.check_open(binding),
        )
    }

    pub fn pending_request(
        &self,
    ) -> Result<Option<&CellGenerationRequestV2>, CellGenerationErrorV2> {
        self.require_healthy()?;
        Ok(self.state.pending.as_ref())
    }

    pub fn pending_output(&self) -> Result<Option<&CellOutputChunkV2>, CellGenerationErrorV2> {
        self.require_healthy()?;
        Ok(self.state.outbox.as_ref())
    }

    /// Recorded cost only; use `observe_generation` for episode completeness.
    pub fn task_cost(&self) -> Result<&CellTaskCostV2, CellGenerationErrorV2> {
        self.require_healthy()?;
        Ok(&self.state.cost)
    }

    pub fn lookup(
        &self,
        request: &CellGenerationRequestV2,
    ) -> Result<Option<CellGenerationReceiptV2>, CellGenerationErrorV2> {
        self.require_healthy()?;
        self.state.lookup(request)
    }

    /// Read an already committed receipt after checking its complete intent.
    /// Absence is not proof that a computation was never admitted or dispatched.
    /// The bounded intent is derived from original events during replay; this
    /// lookup does not introduce another writer or grant fresh dispatch.
    pub fn receipt_for_intent(
        &self,
        intent: &CellGenerationIntentV2,
    ) -> Result<Option<CellGenerationReceiptV2>, CellGenerationErrorV2> {
        self.require_healthy()?;
        let original = self
            .state
            .intents
            .iter()
            .find(|original| original.operation_id == intent.operation_id);
        let receipt = self
            .state
            .receipts
            .iter()
            .find(|receipt| receipt.operation_id == intent.operation_id);
        match (original, receipt) {
            (None, None) => Ok(None),
            (Some(original), Some(receipt)) if original == intent => Ok(Some(receipt.clone())),
            (Some(_), Some(_)) => Err(CellGenerationErrorV2::Conflict),
            (None, Some(_)) | (Some(_), None) => Err(CellGenerationErrorV2::Corrupt),
        }
    }

    /// Read the terminal result for the exact original request after a lost
    /// reconcile response. This never admits or executes missing work.
    pub fn receipt_by_request_digest(
        &self,
        request_digest: [u8; 32],
    ) -> Result<Option<CellGenerationReceiptV2>, CellGenerationErrorV2> {
        self.require_healthy()?;
        Ok(self
            .state
            .receipts
            .iter()
            .find(|receipt| receipt.request_digest == request_digest)
            .cloned())
    }

    /// Some(receipt) is an exact committed replay and MUST NOT dispatch. None
    /// means this call durably admitted fresh computation. Pending is read-only.
    pub fn admit(
        &mut self,
        request: CellGenerationRequestV2,
        now_micros: u64,
    ) -> Result<Option<CellGenerationReceiptV2>, CellGenerationErrorV2> {
        self.require_healthy()?;
        if let Some(receipt) = self.state.lookup(&request)? {
            return Ok(Some(receipt));
        }
        if now_micros < request.admitted_at_micros || now_micros >= request.deadline_micros {
            return Err(CellGenerationErrorV2::Deadline);
        }
        self.persist(GenerationEvent::Admit {
            request,
            observed_at_micros: now_micros,
        })?;
        Ok(None)
    }

    pub fn commit(
        &mut self,
        proposal: CellGenerationProposalV2,
        now_micros: u64,
    ) -> Result<CellGenerationReceiptV2, CellGenerationErrorV2> {
        self.require_healthy()?;
        if let Some(receipt) = self
            .state
            .receipts
            .iter()
            .find(|r| r.request_digest == proposal.request_digest)
        {
            proposal
                .cost
                .validate()
                .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
            if proposal.successor_state.len() > self.config.manifest.max_state_bytes as usize
                || proposal.output_delta.len() > self.config.manifest.max_delta_bytes as usize
            {
                return Err(CellGenerationErrorV2::Capacity);
            }
            return if receipt.proposal_digest
                == digest(b"hepta.cell.generation-proposal.v2\0", &proposal)?
            {
                Ok(receipt.clone())
            } else {
                Err(CellGenerationErrorV2::Conflict)
            };
        }
        self.persist(GenerationEvent::Commit {
            proposal,
            settled_at_micros: now_micros,
        })?;
        self.state
            .receipts
            .last()
            .cloned()
            .ok_or(CellGenerationErrorV2::Corrupt)
    }

    /// Retain the host's pre-contact clock floor even if the worker response is
    /// lost or the host reopens. This is an observation, never a dispatch grant.
    pub fn observe_dispatch_time(
        &mut self,
        request_digest: [u8; 32],
        observed_at_micros: u64,
    ) -> Result<(), CellGenerationErrorV2> {
        self.persist(GenerationEvent::DispatchObserved {
            request_digest,
            observed_at_micros,
        })
    }

    /// Record cancellation before contacting the worker. It never clears a
    /// pending admission. Late successful readback settles with no new output.
    pub fn cancel(&mut self, request_digest: [u8; 32]) -> Result<(), CellGenerationErrorV2> {
        self.require_healthy()?;
        if self.state.cancelled
            && self
                .state
                .pending
                .as_ref()
                .is_some_and(|r| r.digest() == Ok(request_digest))
        {
            return Ok(());
        }
        self.persist(GenerationEvent::Cancel { request_digest })
    }

    pub fn drain(&mut self) -> Result<(), CellGenerationErrorV2> {
        self.require_healthy()?;
        if self.state.draining {
            return Ok(());
        }
        self.persist(GenerationEvent::Drain)
    }

    pub fn is_drained(&self) -> Result<bool, CellGenerationErrorV2> {
        self.require_healthy()?;
        Ok(self.state.draining && self.state.pending.is_none() && self.state.outbox.is_none())
    }

    pub fn resume(&mut self) -> Result<(), CellGenerationErrorV2> {
        self.require_healthy()?;
        if !self.state.draining {
            return Ok(());
        }
        self.persist(GenerationEvent::Resume)
    }

    pub fn acknowledge(
        &mut self,
        chunk: CellOutputChunkV2,
        acknowledgement: [u8; 32],
        cost: CellTaskCostV2,
    ) -> Result<(), CellGenerationErrorV2> {
        self.require_healthy()?;
        cost.validate()
            .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        if chunk.bytes.len() > self.config.manifest.max_delta_bytes as usize {
            return Err(CellGenerationErrorV2::Capacity);
        }
        let event = GenerationEvent::Ack {
            chunk,
            acknowledgement,
            cost,
        };
        if self
            .state
            .acknowledgements
            .contains(&digest(b"hepta.cell.output-ack.v2\0", &event)?)
        {
            return Ok(());
        }
        self.persist(event)
    }

    pub fn record_cost(&mut self, entry: CellCostEntryV2) -> Result<(), CellGenerationErrorV2> {
        self.require_healthy()?;
        let mut cost = self.state.cost.clone();
        if cost
            .record(entry.clone())
            .map_err(|_| CellGenerationErrorV2::InvalidBinding)?
            == CellCostRecordV2::Replayed
        {
            return Ok(());
        }
        self.persist(GenerationEvent::Cost { entry })
    }

    fn require_healthy(&self) -> Result<(), CellGenerationErrorV2> {
        if self.healthy {
            self.require_current()
        } else {
            Err(CellGenerationErrorV2::CommitUncertain)
        }
    }

    fn persist(&mut self, event: GenerationEvent) -> Result<(), CellGenerationErrorV2> {
        self.require_healthy()?;
        let mut next_state = self.state.clone();
        next_state.apply(&self.config, &event)?;
        let payload =
            serde_json::to_vec(&event).map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        let next = next_anchor(&self.header, self.head, &payload)?;
        let reserved = next_state.reserved_records();
        if payload.len() > MAX_FRAME
            || next.sequence + reserved > self.max_records
            || self.length + payload.len() as u64 + 36 + reserved * (MAX_FRAME as u64 + 36)
                > MAX_BYTES
        {
            return Err(CellGenerationErrorV2::Capacity);
        }
        let mut frame = Vec::with_capacity(payload.len() + 36);
        frame.extend_from_slice(&(payload.len() as u32).to_be_bytes());
        frame.extend_from_slice(&payload);
        frame.extend_from_slice(next.checkpoint_digest.as_array());
        self.healthy = false;
        if self
            .file
            .metadata()
            .map_err(|_| CellGenerationErrorV2::CommitUncertain)?
            .len()
            != self.length
        {
            return Err(CellGenerationErrorV2::CommitUncertain);
        }
        self.file
            .seek(SeekFrom::Start(self.length))
            .map_err(|_| CellGenerationErrorV2::CommitUncertain)?;
        self.file
            .write_all(&frame)
            .map_err(|_| CellGenerationErrorV2::CommitUncertain)?;
        self.file
            .sync_all()
            .map_err(|_| CellGenerationErrorV2::CommitUncertain)?;
        self.witness
            .compare_and_swap(self.head, next)
            .map_err(|_| CellGenerationErrorV2::CommitUncertain)?;
        self.state = next_state;
        self.head = Some(next);
        self.length += frame.len() as u64;
        self.healthy = true;
        Ok(())
    }
}

fn next_anchor(
    header: &[u8],
    previous: Option<JournalAnchor>,
    payload: &[u8],
) -> Result<JournalAnchor, CellGenerationErrorV2> {
    let sequence = previous
        .map_or(0, |a| a.sequence)
        .checked_add(1)
        .ok_or(CellGenerationErrorV2::Capacity)?;
    let predecessor = previous.map_or_else(|| Digest32::of_bytes(header), |a| a.checkpoint_digest);
    Ok(JournalAnchor {
        sequence,
        checkpoint_digest: Digest32::of_parts(&[
            b"hepta.cell.generation-frame.v2\0",
            predecessor.as_array(),
            &sequence.to_be_bytes(),
            &(payload.len() as u64).to_be_bytes(),
            payload,
        ]),
    })
}

#[cfg(test)]
#[path = "cell_generation_tests.rs"]
mod tests;
