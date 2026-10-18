//! Read-only proposal preparation followed by one synchronous final admission.
//! Rejection leaves original file bytes and writer state unchanged. An identical
//! observation also requires current admission; it never receives a new frame.
use super::AppendDisposition;
use super::AuthorityPosture;
use super::Digest32;
use super::DurableTopologyAppendReceiptV1;
use super::DurableTopologyProposalRegistryV1;
use super::DurableTopologyRegistryErrorV1;
use super::GovernedTopologyProposalV1;
use super::MAX_FILE_BYTES;
use super::StableId;
use super::TopologySlotV1;
use super::admit_governed_topology_v1;
use super::encode_frame;
use super::insert_maps;
use std::collections::BTreeMap;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

enum PreparedAppend {
    Unchanged(DurableTopologyAppendReceiptV1),
    Insert(PreparedInsert),
}

struct PreparedInsert {
    frame: Vec<u8>,
    receipt: DurableTopologyAppendReceiptV1,
    candidate_slots: BTreeMap<TopologySlotV1, GovernedTopologyProposalV1>,
    candidate_ids: BTreeMap<StableId, TopologySlotV1>,
}

impl DurableTopologyProposalRegistryV1 {
    /// Prepare all proposal, conflict, capacity and encoding checks, then run
    /// the host's final admission immediately before the first write. The
    /// callback is synchronous and cannot carry a future across admission.
    /// This checks current observations as well as newly inserted records.
    pub fn append_after_admission<E, F>(
        &mut self,
        expected_predecessor_frame_digest: Digest32,
        record: GovernedTopologyProposalV1,
        final_admission: F,
    ) -> Result<DurableTopologyAppendReceiptV1, E>
    where
        E: From<DurableTopologyRegistryErrorV1>,
        F: FnOnce() -> Result<(), E>,
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
    ) -> Result<PreparedAppend, DurableTopologyRegistryErrorV1> {
        if self.poisoned {
            return Err(DurableTopologyRegistryErrorV1::Poisoned);
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
            return Ok(PreparedAppend::Unchanged(receipt));
        }
        let current = self.frame_digests.last().copied().unwrap_or(Digest32::ZERO);
        if current != expected_predecessor_frame_digest {
            return Err(DurableTopologyRegistryErrorV1::Conflict);
        }
        if self.frame_digests.len() >= self.maximum_records {
            return Err(DurableTopologyRegistryErrorV1::Capacity);
        }

        let mut candidate_slots = self.by_slot.clone();
        let mut candidate_ids = self.by_id.clone();
        insert_maps(
            &mut candidate_slots,
            &mut candidate_ids,
            record.clone(),
            self.maximum_records,
        )?;

        let sequence = self.frame_digests.len() as u64 + 1;
        let (frame, frame_digest) =
            encode_frame(sequence, expected_predecessor_frame_digest, &record)?;
        let offset = self.file.metadata()?.len();
        let next = offset
            .checked_add(4 + frame.len() as u64)
            .ok_or(DurableTopologyRegistryErrorV1::Capacity)?;
        if next > MAX_FILE_BYTES {
            return Err(DurableTopologyRegistryErrorV1::Capacity);
        }

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
        Ok(PreparedAppend::Insert(PreparedInsert {
            frame,
            receipt,
            candidate_slots,
            candidate_ids,
        }))
    }

    fn commit_prepared(
        &mut self,
        prepared: PreparedAppend,
    ) -> Result<DurableTopologyAppendReceiptV1, DurableTopologyRegistryErrorV1> {
        let PreparedInsert {
            frame,
            receipt,
            candidate_slots,
            candidate_ids,
        } = match prepared {
            PreparedAppend::Unchanged(receipt) => return Ok(receipt),
            PreparedAppend::Insert(insert) => insert,
        };
        self.poisoned = true;
        self.file.seek(SeekFrom::End(0))?;
        self.file
            .write_all(&(frame.len() as u32).to_be_bytes())
            .and_then(|_| self.file.write_all(&frame))
            .and_then(|_| self.file.sync_data())
            .map_err(|_| DurableTopologyRegistryErrorV1::Indeterminate)?;
        self.by_slot = candidate_slots;
        self.by_id = candidate_ids;
        self.receipts
            .insert(receipt.proposal_id.clone(), receipt.clone());
        self.frame_digests.push(receipt.frame_digest);
        self.poisoned = false;
        Ok(receipt)
    }
}
