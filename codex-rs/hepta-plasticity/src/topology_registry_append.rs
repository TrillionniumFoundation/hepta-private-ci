//! Topology append preparation and its final admission boundary.

use super::*;

struct PreparedTopologyAppend {
    receipt: DurableTopologyAppendReceiptV1,
    write: Option<PreparedTopologyWrite>,
}

struct PreparedTopologyWrite {
    record: GovernedTopologyProposalV1,
    frame: Vec<u8>,
    next_file_bytes: u64,
}

impl DurableTopologyProposalRegistryV1 {
    pub fn append(
        &mut self,
        expected_predecessor_frame_digest: Digest32,
        record: GovernedTopologyProposalV1,
    ) -> Result<DurableTopologyAppendReceiptV1, DurableTopologyRegistryErrorV1> {
        self.append_with_final_admission(expected_predecessor_frame_digest, record, || Ok(()))
    }

    /// Invoke final admission exactly once after live-history verification,
    /// governed-proposal checks, conflicts, capacity and frame encoding.
    /// Rejection writes nothing and leaves an otherwise healthy registry usable.
    /// An identical retry also crosses this gate before its unchanged receipt.
    /// The host retains exclusive file-description ownership during the call.
    pub fn append_with_final_admission<E>(
        &mut self,
        expected_predecessor_frame_digest: Digest32,
        record: GovernedTopologyProposalV1,
        final_admission: impl FnOnce() -> Result<(), E>,
    ) -> Result<DurableTopologyAppendReceiptV1, E>
    where
        E: From<DurableTopologyRegistryErrorV1>,
    {
        let prepared = self
            .prepare_append(expected_predecessor_frame_digest, record)
            .map_err(E::from)?;
        final_admission()?;
        self.commit_prepared(prepared).map_err(E::from)
    }

    fn prepare_append(
        &self,
        expected_predecessor_frame_digest: Digest32,
        record: GovernedTopologyProposalV1,
    ) -> Result<PreparedTopologyAppend, DurableTopologyRegistryErrorV1> {
        self.ensure_live_integrity()?;
        // Borrowed bounds checks precede cloning the caller's governed record.
        crate::verify_topology_proposal_v2(&record.proposal)
            .map_err(TopologyGovernanceErrorV1::from)?;
        if record.handoffs.len() > record.proposal.candidates.len().saturating_sub(1) {
            return Err(DurableTopologyRegistryErrorV1::Governance(
                TopologyGovernanceErrorV1::UnexpectedHandoff(
                    "handoff count exceeds update candidate count".to_string(),
                ),
            ));
        }
        let verified = admit_governed_topology_v1(
            record.proposal.clone(),
            record.handoffs.clone(),
            record.source_authentication_digest,
            record.evaluation_authentication_digest,
        )?;
        if verified != record {
            return Err(DurableTopologyRegistryErrorV1::Corrupt);
        }
        if let Some(slot) = self.by_id.get(&record.proposal.proposal_id)
            && let Some(existing) = self.by_slot.get(slot)
            && existing == &record
        {
            let mut receipt = self
                .receipts
                .get(&record.proposal.proposal_id)
                .cloned()
                .ok_or(DurableTopologyRegistryErrorV1::Corrupt)?;
            receipt.disposition = AppendDisposition::Unchanged;
            return Ok(PreparedTopologyAppend {
                receipt,
                write: None,
            });
        }
        let current = self.frame_digests.last().copied().unwrap_or(Digest32::ZERO);
        if current != expected_predecessor_frame_digest {
            return Err(DurableTopologyRegistryErrorV1::Conflict);
        }
        if self.frame_digests.len() >= self.maximum_records {
            return Err(DurableTopologyRegistryErrorV1::Capacity);
        }
        if preflight_maps(&self.by_slot, &self.by_id, &record, self.maximum_records)?
            != AppendDisposition::Inserted
        {
            return Err(DurableTopologyRegistryErrorV1::Corrupt);
        }
        let sequence = self.frame_digests.len() as u64 + 1;
        let (frame, frame_digest) =
            encode_frame(sequence, expected_predecessor_frame_digest, &record)?;
        let next_file_bytes = self
            .expected_file_bytes
            .checked_add(4 + frame.len() as u64)
            .filter(|length| *length <= MAX_FILE_BYTES)
            .ok_or(DurableTopologyRegistryErrorV1::Capacity)?;
        let receipt = DurableTopologyAppendReceiptV1 {
            sequence,
            proposal_id: record.proposal.proposal_id.clone(),
            proposal_digest: record.proposal.proposal_digest,
            admission_digest: record.admission_digest,
            frame_digest,
            predecessor_frame_digest: expected_predecessor_frame_digest,
            disposition: AppendDisposition::Inserted,
            authority: AuthorityPosture::DENY_ALL,
        };
        Ok(PreparedTopologyAppend {
            receipt,
            write: Some(PreparedTopologyWrite {
                record,
                frame,
                next_file_bytes,
            }),
        })
    }

    fn commit_prepared(
        &mut self,
        prepared: PreparedTopologyAppend,
    ) -> Result<DurableTopologyAppendReceiptV1, DurableTopologyRegistryErrorV1> {
        let PreparedTopologyAppend { receipt, write } = prepared;
        let Some(write) = write else {
            return Ok(receipt);
        };
        self.poisoned.store(true, Ordering::Release);
        self.file.seek(SeekFrom::End(0))?;
        self.file
            .write_all(&(write.frame.len() as u32).to_be_bytes())
            .and_then(|_| self.file.write_all(&write.frame))
            .and_then(|_| self.file.sync_data())
            .map_err(|_| DurableTopologyRegistryErrorV1::Indeterminate)?;
        if self
            .insert_memory(write.record)
            .map_err(|_| DurableTopologyRegistryErrorV1::Corrupt)?
            != AppendDisposition::Inserted
        {
            return Err(DurableTopologyRegistryErrorV1::Corrupt);
        }
        self.receipts
            .insert(receipt.proposal_id.clone(), receipt.clone());
        self.frame_digests.push(receipt.frame_digest);
        self.expected_file_bytes = write.next_file_bytes;
        self.verify_live_file()?;
        self.poisoned.store(false, Ordering::Release);
        Ok(receipt)
    }
}
