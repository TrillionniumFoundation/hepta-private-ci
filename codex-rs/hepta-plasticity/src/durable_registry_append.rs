//! Read-only proposal preparation followed by one synchronous final admission.
//! Rejection leaves original file bytes and writer state unchanged. An identical
//! observation also requires current admission; it never receives a new frame.
use super::AppendDisposition;
use super::AuthorityPosture;
use super::Digest32;
use super::DurableProposalAppendReceiptV1;
use super::DurableProposalRegistry;
use super::DurableProposalRegistryError;
use super::HEADER_SIZE;
use super::MAX_FILE_BYTES;
use super::ParameterProposalV2;
use super::ProposalRegistry;
use super::encode_frame;
use super::verify_parameter_proposal_v2;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

enum PreparedAppend {
    Unchanged(DurableProposalAppendReceiptV1),
    Insert(PreparedInsert),
}

struct PreparedInsert {
    frame: Vec<u8>,
    receipt: DurableProposalAppendReceiptV1,
    candidate_registry: ProposalRegistry,
}

impl DurableProposalRegistry {
    /// Prepare all proposal, conflict, capacity and encoding checks, then run
    /// the host's final admission immediately before the first write. The
    /// callback is synchronous and cannot carry a future across admission.
    /// This checks current observations as well as newly inserted records.
    pub fn append_v2_after_admission<E, F>(
        &mut self,
        expected_predecessor_frame_digest: Digest32,
        proposal: ParameterProposalV2,
        final_admission: F,
    ) -> Result<DurableProposalAppendReceiptV1, E>
    where
        E: From<DurableProposalRegistryError>,
        F: FnOnce() -> Result<(), E>,
    {
        let prepared = self
            .prepare_append(expected_predecessor_frame_digest, proposal)
            .map_err(E::from)?;
        final_admission()?;
        self.commit_prepared(prepared).map_err(E::from)
    }

    fn prepare_append(
        &self,
        expected_predecessor_frame_digest: Digest32,
        proposal: ParameterProposalV2,
    ) -> Result<PreparedAppend, DurableProposalRegistryError> {
        if self.poisoned {
            return Err(DurableProposalRegistryError::Poisoned);
        }
        verify_parameter_proposal_v2(&proposal)?;
        if let Some(existing) = self.receipts.get(&proposal.proposal_id) {
            let stored = self
                .registry
                .get_v2_by_proposal_id(&proposal.proposal_id)
                .ok_or(DurableProposalRegistryError::Corrupt)?;
            if stored == &proposal {
                let mut observed = existing.clone();
                observed.disposition = AppendDisposition::Unchanged;
                return Ok(PreparedAppend::Unchanged(observed));
            }
        }
        let current = self.frame_digests.last().copied().unwrap_or(Digest32::ZERO);
        if current != expected_predecessor_frame_digest {
            return Err(DurableProposalRegistryError::Conflict);
        }
        if self.frame_digests.len() >= self.maximum_records {
            return Err(DurableProposalRegistryError::Capacity);
        }

        let mut candidate_registry = self.registry.clone();
        let disposition = candidate_registry.append_v2(proposal.clone())?;
        if disposition != AppendDisposition::Inserted {
            return Err(DurableProposalRegistryError::Corrupt);
        }
        let sequence = self.frame_digests.len() as u64 + 1;
        let (frame, frame_digest) =
            encode_frame(sequence, expected_predecessor_frame_digest, &proposal)?;
        let frame_total = 4_u64
            .checked_add(frame.len() as u64)
            .ok_or(DurableProposalRegistryError::Capacity)?;
        let expected_offset = self.file.metadata()?.len();
        if expected_offset < HEADER_SIZE as u64
            || expected_offset
                .checked_add(frame_total)
                .is_none_or(|length| length > MAX_FILE_BYTES)
        {
            return Err(DurableProposalRegistryError::Capacity);
        }

        let receipt = DurableProposalAppendReceiptV1 {
            registry_scope_digest: self.registry_scope_digest,
            writer_fence: self.writer_fence,
            sequence,
            proposal_id: proposal.proposal_id.clone(),
            proposal_digest: proposal.proposal_digest,
            selected_artifact_digest: proposal.selected_artifact_digest,
            window_id: proposal.window.window_id,
            predecessor_frame_digest: expected_predecessor_frame_digest,
            frame_digest,
            disposition: AppendDisposition::Inserted,
            authority: AuthorityPosture::DENY_ALL,
        };
        Ok(PreparedAppend::Insert(PreparedInsert {
            frame,
            receipt,
            candidate_registry,
        }))
    }

    fn commit_prepared(
        &mut self,
        prepared: PreparedAppend,
    ) -> Result<DurableProposalAppendReceiptV1, DurableProposalRegistryError> {
        let PreparedInsert {
            frame,
            receipt,
            candidate_registry,
        } = match prepared {
            PreparedAppend::Unchanged(receipt) => return Ok(receipt),
            PreparedAppend::Insert(insert) => insert,
        };
        self.poisoned = true;
        self.file.seek(SeekFrom::End(0))?;
        self.file
            .write_all(&(frame.len() as u32).to_be_bytes())
            .map_err(|_| DurableProposalRegistryError::Indeterminate)?;
        self.file
            .write_all(&frame)
            .map_err(|_| DurableProposalRegistryError::Indeterminate)?;
        self.file
            .sync_data()
            .map_err(|_| DurableProposalRegistryError::Indeterminate)?;

        self.registry = candidate_registry;
        self.frame_digests.push(receipt.frame_digest);
        self.receipts
            .insert(receipt.proposal_id.clone(), receipt.clone());
        self.poisoned = false;
        Ok(receipt)
    }
}
