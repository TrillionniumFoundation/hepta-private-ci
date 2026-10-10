use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;

use crate::FeasiblePlanReceiptV1;
use crate::GlobalStateSnapshotV1;

const MAGIC: &[u8; 8] = b"HCPJNL01";
const MAX_RECORDS: usize = 4096;
const RECORD_BYTES: usize = 8 + 1 + 32 + 32 + 32 + 32;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum PlannerJournalKindV1 {
    Snapshot,
    Decision,
    SelectedPlan,
    Revocation,
}

impl PlannerJournalKindV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Snapshot => 0,
            Self::Decision => 1,
            Self::SelectedPlan => 2,
            Self::Revocation => 3,
        }
    }

    fn from_tag(value: u8) -> Result<Self, PlannerJournalError> {
        match value {
            0 => Ok(Self::Snapshot),
            1 => Ok(Self::Decision),
            2 => Ok(Self::SelectedPlan),
            3 => Ok(Self::Revocation),
            _ => Err(PlannerJournalError::UnknownKind(value)),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerJournalEntryV1 {
    pub sequence: u64,
    pub kind: PlannerJournalKindV1,
    pub identity_digest: Digest32,
    pub payload_digest: Digest32,
    pub predecessor_entry_digest: Digest32,
    pub entry_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerJournalV1 {
    entries: Vec<PlannerJournalEntryV1>,
    identities: BTreeMap<Digest32, (PlannerJournalKindV1, Digest32)>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlannerJournalError {
    EmptyDigest,
    RecordLimitExceeded,
    IdentityConflict,
    DuplicateSerializedIdentity,
    CorruptHeader,
    Truncated,
    CorruptSequence,
    CorruptPredecessor,
    CorruptEntryDigest,
    UnknownKind(u8),
    DecisionNotRecorded,
    RevokedPlan,
}

impl fmt::Display for PlannerJournalError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PlannerJournalError {}

impl Default for PlannerJournalV1 {
    fn default() -> Self {
        Self::new()
    }
}

impl PlannerJournalV1 {
    #[must_use]
    pub fn new() -> Self {
        Self {
            entries: Vec::new(),
            identities: BTreeMap::new(),
        }
    }

    #[must_use]
    pub fn entries(&self) -> &[PlannerJournalEntryV1] {
        &self.entries
    }

    pub fn record_snapshot(
        &mut self,
        snapshot: &GlobalStateSnapshotV1,
    ) -> Result<PlannerJournalEntryV1, PlannerJournalError> {
        self.append(
            PlannerJournalKindV1::Snapshot,
            snapshot.snapshot_digest(),
            snapshot.snapshot_digest(),
        )
    }

    pub fn record_decision(
        &mut self,
        receipt: &FeasiblePlanReceiptV1,
    ) -> Result<PlannerJournalEntryV1, PlannerJournalError> {
        self.append(
            PlannerJournalKindV1::Decision,
            receipt.receipt_digest(),
            receipt.receipt_digest(),
        )
    }

    pub fn select_plan(
        &mut self,
        operation_identity_digest: Digest32,
        receipt: &FeasiblePlanReceiptV1,
    ) -> Result<PlannerJournalEntryV1, PlannerJournalError> {
        if !self.entries.iter().any(|entry| {
            entry.kind == PlannerJournalKindV1::Decision
                && entry.payload_digest == receipt.receipt_digest()
        }) {
            return Err(PlannerJournalError::DecisionNotRecorded);
        }
        if self.revoked_digests().contains(&receipt.receipt_digest()) {
            return Err(PlannerJournalError::RevokedPlan);
        }
        self.append(
            PlannerJournalKindV1::SelectedPlan,
            operation_identity_digest,
            receipt.receipt_digest(),
        )
    }

    pub fn revoke(
        &mut self,
        revocation_identity_digest: Digest32,
        target_digest: Digest32,
    ) -> Result<PlannerJournalEntryV1, PlannerJournalError> {
        self.append(
            PlannerJournalKindV1::Revocation,
            revocation_identity_digest,
            target_digest,
        )
    }

    #[must_use]
    pub fn selected_plan_digest(&self) -> Option<Digest32> {
        let revoked = self.revoked_digests();
        let mut selected = None;
        for entry in &self.entries {
            match entry.kind {
                PlannerJournalKindV1::SelectedPlan => {
                    selected =
                        (!revoked.contains(&entry.payload_digest)).then_some(entry.payload_digest);
                }
                PlannerJournalKindV1::Revocation if selected == Some(entry.payload_digest) => {
                    selected = None;
                }
                _ => {}
            }
        }
        selected.filter(|digest| !revoked.contains(digest))
    }

    pub fn append(
        &mut self,
        kind: PlannerJournalKindV1,
        identity_digest: Digest32,
        payload_digest: Digest32,
    ) -> Result<PlannerJournalEntryV1, PlannerJournalError> {
        if identity_digest.is_zero() || payload_digest.is_zero() {
            return Err(PlannerJournalError::EmptyDigest);
        }
        if let Some((existing_kind, existing_payload)) = self.identities.get(&identity_digest) {
            if *existing_kind == kind && *existing_payload == payload_digest {
                return self
                    .entries
                    .iter()
                    .find(|entry| entry.identity_digest == identity_digest)
                    .cloned()
                    .ok_or(PlannerJournalError::CorruptEntryDigest);
            }
            return Err(PlannerJournalError::IdentityConflict);
        }
        if self.entries.len() >= MAX_RECORDS {
            return Err(PlannerJournalError::RecordLimitExceeded);
        }
        let sequence = u64::try_from(self.entries.len())
            .ok()
            .and_then(|value| value.checked_add(1))
            .ok_or(PlannerJournalError::RecordLimitExceeded)?;
        let predecessor_entry_digest = self
            .entries
            .last()
            .map_or(Digest32::ZERO, |entry| entry.entry_digest);
        let entry_digest = digest_entry(
            sequence,
            kind,
            identity_digest,
            payload_digest,
            predecessor_entry_digest,
        );
        let entry = PlannerJournalEntryV1 {
            sequence,
            kind,
            identity_digest,
            payload_digest,
            predecessor_entry_digest,
            entry_digest,
        };
        self.identities
            .insert(identity_digest, (kind, payload_digest));
        self.entries.push(entry.clone());
        Ok(entry)
    }

    #[must_use]
    pub fn export_bytes(&self) -> Vec<u8> {
        let mut bytes = Vec::with_capacity(12 + self.entries.len() * RECORD_BYTES);
        bytes.extend_from_slice(MAGIC);
        bytes.extend_from_slice(
            &u32::try_from(self.entries.len())
                .unwrap_or(u32::MAX)
                .to_be_bytes(),
        );
        for entry in &self.entries {
            bytes.extend_from_slice(&entry.sequence.to_be_bytes());
            bytes.push(entry.kind.tag());
            bytes.extend_from_slice(entry.identity_digest.as_array());
            bytes.extend_from_slice(entry.payload_digest.as_array());
            bytes.extend_from_slice(entry.predecessor_entry_digest.as_array());
            bytes.extend_from_slice(entry.entry_digest.as_array());
        }
        bytes
    }

    pub fn reopen(bytes: &[u8]) -> Result<Self, PlannerJournalError> {
        if bytes.len() < 12 {
            return Err(PlannerJournalError::Truncated);
        }
        if &bytes[..8] != MAGIC {
            return Err(PlannerJournalError::CorruptHeader);
        }
        let count_u32 = u32::from_be_bytes(
            bytes[8..12]
                .try_into()
                .map_err(|_| PlannerJournalError::Truncated)?,
        );
        let count =
            usize::try_from(count_u32).map_err(|_| PlannerJournalError::RecordLimitExceeded)?;
        if count > MAX_RECORDS {
            return Err(PlannerJournalError::RecordLimitExceeded);
        }
        let expected = 12_usize
            .checked_add(
                count
                    .checked_mul(RECORD_BYTES)
                    .ok_or(PlannerJournalError::Truncated)?,
            )
            .ok_or(PlannerJournalError::Truncated)?;
        if bytes.len() != expected {
            return Err(PlannerJournalError::Truncated);
        }

        let mut journal = Self::new();
        let mut offset = 12;
        for index in 0..count {
            let sequence = read_u64(bytes, &mut offset)?;
            let kind = PlannerJournalKindV1::from_tag(read_u8(bytes, &mut offset)?)?;
            let identity_digest = read_digest(bytes, &mut offset)?;
            let payload_digest = read_digest(bytes, &mut offset)?;
            let predecessor_entry_digest = read_digest(bytes, &mut offset)?;
            let entry_digest = read_digest(bytes, &mut offset)?;
            let expected_sequence = u64::try_from(index)
                .ok()
                .and_then(|value| value.checked_add(1))
                .ok_or(PlannerJournalError::CorruptSequence)?;
            if sequence != expected_sequence {
                return Err(PlannerJournalError::CorruptSequence);
            }
            let expected_predecessor = journal
                .entries
                .last()
                .map_or(Digest32::ZERO, |entry| entry.entry_digest);
            if predecessor_entry_digest != expected_predecessor {
                return Err(PlannerJournalError::CorruptPredecessor);
            }
            let expected_digest = digest_entry(
                sequence,
                kind,
                identity_digest,
                payload_digest,
                predecessor_entry_digest,
            );
            if entry_digest != expected_digest {
                return Err(PlannerJournalError::CorruptEntryDigest);
            }
            if identity_digest.is_zero() || payload_digest.is_zero() {
                return Err(PlannerJournalError::EmptyDigest);
            }
            if journal.identities.contains_key(&identity_digest) {
                return Err(PlannerJournalError::DuplicateSerializedIdentity);
            }
            journal
                .identities
                .insert(identity_digest, (kind, payload_digest));
            journal.entries.push(PlannerJournalEntryV1 {
                sequence,
                kind,
                identity_digest,
                payload_digest,
                predecessor_entry_digest,
                entry_digest,
            });
        }
        Ok(journal)
    }

    fn revoked_digests(&self) -> BTreeSet<Digest32> {
        self.entries
            .iter()
            .filter(|entry| entry.kind == PlannerJournalKindV1::Revocation)
            .map(|entry| entry.payload_digest)
            .collect()
    }
}

fn digest_entry(
    sequence: u64,
    kind: PlannerJournalKindV1,
    identity_digest: Digest32,
    payload_digest: Digest32,
    predecessor_entry_digest: Digest32,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.control.planner-journal-entry.v1");
    bytes.extend_from_slice(&sequence.to_be_bytes());
    bytes.push(kind.tag());
    bytes.extend_from_slice(identity_digest.as_array());
    bytes.extend_from_slice(payload_digest.as_array());
    bytes.extend_from_slice(predecessor_entry_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn read_u8(bytes: &[u8], offset: &mut usize) -> Result<u8, PlannerJournalError> {
    let value = *bytes.get(*offset).ok_or(PlannerJournalError::Truncated)?;
    *offset += 1;
    Ok(value)
}

fn read_u64(bytes: &[u8], offset: &mut usize) -> Result<u64, PlannerJournalError> {
    let end = (*offset)
        .checked_add(8)
        .ok_or(PlannerJournalError::Truncated)?;
    let value = u64::from_be_bytes(
        bytes
            .get(*offset..end)
            .ok_or(PlannerJournalError::Truncated)?
            .try_into()
            .map_err(|_| PlannerJournalError::Truncated)?,
    );
    *offset = end;
    Ok(value)
}

fn read_digest(bytes: &[u8], offset: &mut usize) -> Result<Digest32, PlannerJournalError> {
    let end = (*offset)
        .checked_add(32)
        .ok_or(PlannerJournalError::Truncated)?;
    let array: [u8; 32] = bytes
        .get(*offset..end)
        .ok_or(PlannerJournalError::Truncated)?
        .try_into()
        .map_err(|_| PlannerJournalError::Truncated)?;
    *offset = end;
    Ok(Digest32::from_array(array))
}

#[cfg(test)]
#[path = "planner_journal_tests.rs"]
mod tests;
