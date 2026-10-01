//! Parameter append preparation and its final admission boundary.

use super::*;

struct PreparedParameterAppend {
    receipt: DurableProposalAppendReceiptV1,
    write: Option<PreparedParameterWrite>,
}

struct PreparedParameterWrite {
    proposal: ParameterProposalV2,
    frame: Vec<u8>,
    next_file_bytes: u64,
}

impl DurableProposalRegistry {
    /// Append a verified proposal after the exact durable predecessor.
    /// An identical retry returns its original frame without another write.
    /// Persistence grants no independent acceptance or execution authority.
    pub fn append_v2(
        &mut self,
        expected_predecessor_frame_digest: Digest32,
        proposal: ParameterProposalV2,
    ) -> Result<DurableProposalAppendReceiptV1, DurableProposalRegistryError> {
        self.append_v2_with_final_admission(expected_predecessor_frame_digest, proposal, || Ok(()))
    }

    /// Invoke final admission exactly once after all read-only preparation,
    /// including live-history verification, proposal checks and frame encoding.
    /// Rejection performs no write and does not poison an otherwise healthy
    /// registry. Identical retries cross this same gate before returning their
    /// unchanged receipt. The host retains exclusive file-description ownership.
    pub fn append_v2_with_final_admission<E>(
        &mut self,
        expected_predecessor_frame_digest: Digest32,
        proposal: ParameterProposalV2,
        final_admission: impl FnOnce() -> Result<(), E>,
    ) -> Result<DurableProposalAppendReceiptV1, E>
    where
        E: From<DurableProposalRegistryError>,
    {
        let prepared = self
            .prepare_append_v2(expected_predecessor_frame_digest, proposal)
            .map_err(E::from)?;
        final_admission()?;
        self.commit_prepared_v2(prepared).map_err(E::from)
    }

    fn prepare_append_v2(
        &self,
        expected_predecessor_frame_digest: Digest32,
        proposal: ParameterProposalV2,
    ) -> Result<PreparedParameterAppend, DurableProposalRegistryError> {
        self.ensure_live_integrity()?;
        verify_parameter_proposal_v2(&proposal)?;
        if let Some(existing) = self.receipts.get(&proposal.proposal_id) {
            let stored = self
                .registry
                .get_v2_by_proposal_id(&proposal.proposal_id)
                .ok_or(DurableProposalRegistryError::Corrupt)?;
            if stored == &proposal {
                let mut observed = existing.clone();
                observed.disposition = AppendDisposition::Unchanged;
                return Ok(PreparedParameterAppend {
                    receipt: observed,
                    write: None,
                });
            }
        }
        let current = self.frame_digests.last().copied().unwrap_or(Digest32::ZERO);
        if current != expected_predecessor_frame_digest {
            return Err(DurableProposalRegistryError::Conflict);
        }
        if self.frame_digests.len() >= self.maximum_records {
            return Err(DurableProposalRegistryError::Capacity);
        }
        if self.registry.preflight_v2_append(&proposal)? != AppendDisposition::Inserted {
            return Err(DurableProposalRegistryError::Corrupt);
        }
        let sequence = self.frame_digests.len() as u64 + 1;
        let (frame, frame_digest) =
            encode_frame(sequence, expected_predecessor_frame_digest, &proposal)?;
        let next_file_bytes = self
            .expected_file_bytes
            .checked_add(4 + frame.len() as u64)
            .filter(|length| *length <= MAX_FILE_BYTES)
            .ok_or(DurableProposalRegistryError::Capacity)?;
        let receipt = DurableProposalAppendReceiptV1 {
            registry_scope_digest: self.registry_scope_digest,
            writer_fence: self.writer_fence,
            sequence,
            proposal_id: proposal.proposal_id.clone(),
            proposal_digest: proposal.proposal_digest,
            selected_artifact_digest: proposal.selected_artifact_digest,
            window_id: proposal.window.window_id.clone(),
            predecessor_frame_digest: expected_predecessor_frame_digest,
            frame_digest,
            disposition: AppendDisposition::Inserted,
            authority: AuthorityPosture::DENY_ALL,
        };
        Ok(PreparedParameterAppend {
            receipt,
            write: Some(PreparedParameterWrite {
                proposal,
                frame,
                next_file_bytes,
            }),
        })
    }

    fn commit_prepared_v2(
        &mut self,
        prepared: PreparedParameterAppend,
    ) -> Result<DurableProposalAppendReceiptV1, DurableProposalRegistryError> {
        let PreparedParameterAppend { receipt, write } = prepared;
        let Some(write) = write else {
            return Ok(receipt);
        };
        self.poisoned.store(true, Ordering::Release);
        self.file.seek(SeekFrom::End(0))?;
        self.file
            .write_all(&(write.frame.len() as u32).to_be_bytes())
            .and_then(|_| self.file.write_all(&write.frame))
            .and_then(|_| self.file.sync_data())
            .map_err(|_| DurableProposalRegistryError::Indeterminate)?;
        if self
            .registry
            .append_v2(write.proposal)
            .map_err(|_| DurableProposalRegistryError::Corrupt)?
            != AppendDisposition::Inserted
        {
            return Err(DurableProposalRegistryError::Corrupt);
        }
        self.frame_digests.push(receipt.frame_digest);
        self.receipts
            .insert(receipt.proposal_id.clone(), receipt.clone());
        self.expected_file_bytes = write.next_file_bytes;
        self.verify_live_file()?;
        self.poisoned.store(false, Ordering::Release);
        Ok(receipt)
    }
}
