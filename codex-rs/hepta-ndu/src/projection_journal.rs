use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;

const MAGIC: &[u8; 8] = b"HNDUPJ01";
const MAX_RECORDS: usize = 4096;
const RECORD_BYTES: usize = 8 + 1 + 32 + 32 + 32 + 32 + 32 + 32;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum NduProjectionKindV1 {
    Preference,
    Utility,
    SelectedProjection,
    Revocation,
}

impl NduProjectionKindV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Preference => 0,
            Self::Utility => 1,
            Self::SelectedProjection => 2,
            Self::Revocation => 3,
        }
    }

    fn from_tag(value: u8) -> Result<Self, NduProjectionJournalError> {
        match value {
            0 => Ok(Self::Preference),
            1 => Ok(Self::Utility),
            2 => Ok(Self::SelectedProjection),
            3 => Ok(Self::Revocation),
            _ => Err(NduProjectionJournalError::UnknownKind(value)),
        }
    }

    const fn is_projection(self) -> bool {
        matches!(self, Self::Preference | Self::Utility)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduProjectionEntryV1 {
    pub sequence: u64,
    pub kind: NduProjectionKindV1,
    pub identity_digest: Digest32,
    pub objective_digest: Digest32,
    pub subject_digest: Digest32,
    pub payload_digest: Digest32,
    pub predecessor_entry_digest: Digest32,
    pub entry_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduProjectionJournalV1 {
    entries: Vec<NduProjectionEntryV1>,
    identities: BTreeMap<Digest32, (NduProjectionKindV1, Digest32, Digest32, Digest32)>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduProjectionJournalError {
    EmptyDigest,
    RecordLimitExceeded,
    IdentityConflict,
    DuplicateSerializedIdentity,
    ProjectionNotRecorded,
    RevokedProjection,
    CorruptHeader,
    Truncated,
    CorruptSequence,
    CorruptPredecessor,
    CorruptEntryDigest,
    UnknownKind(u8),
}

impl fmt::Display for NduProjectionJournalError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduProjectionJournalError {}

impl Default for NduProjectionJournalV1 {
    fn default() -> Self {
        Self::new()
    }
}

impl NduProjectionJournalV1 {
    #[must_use]
    pub fn new() -> Self {
        Self {
            entries: Vec::new(),
            identities: BTreeMap::new(),
        }
    }

    #[must_use]
    pub fn entries(&self) -> &[NduProjectionEntryV1] {
        &self.entries
    }

    pub fn append_projection(
        &mut self,
        kind: NduProjectionKindV1,
        identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        payload_digest: Digest32,
    ) -> Result<NduProjectionEntryV1, NduProjectionJournalError> {
        if !kind.is_projection() {
            return Err(NduProjectionJournalError::IdentityConflict);
        }
        self.append(
            kind,
            identity_digest,
            objective_digest,
            subject_digest,
            payload_digest,
        )
    }

    pub fn select_projection(
        &mut self,
        operation_identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        projection_digest: Digest32,
    ) -> Result<NduProjectionEntryV1, NduProjectionJournalError> {
        if !self.entries.iter().any(|entry| {
            entry.kind.is_projection()
                && entry.objective_digest == objective_digest
                && entry.subject_digest == subject_digest
                && entry.payload_digest == projection_digest
        }) {
            return Err(NduProjectionJournalError::ProjectionNotRecorded);
        }
        if self.revoked_digests().contains(&projection_digest) {
            return Err(NduProjectionJournalError::RevokedProjection);
        }
        self.append(
            NduProjectionKindV1::SelectedProjection,
            operation_identity_digest,
            objective_digest,
            subject_digest,
            projection_digest,
        )
    }

    pub fn revoke_projection(
        &mut self,
        revocation_identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        projection_digest: Digest32,
    ) -> Result<NduProjectionEntryV1, NduProjectionJournalError> {
        self.append(
            NduProjectionKindV1::Revocation,
            revocation_identity_digest,
            objective_digest,
            subject_digest,
            projection_digest,
        )
    }

    #[must_use]
    pub fn selected_projection_digest(
        &self,
        objective_digest: Digest32,
        subject_digest: Digest32,
    ) -> Option<Digest32> {
        let revoked = self.revoked_digests();
        let mut selected = None;
        for entry in &self.entries {
            if entry.objective_digest != objective_digest || entry.subject_digest != subject_digest {
                continue;
            }
            match entry.kind {
                NduProjectionKindV1::SelectedProjection => {
                    selected = (!revoked.contains(&entry.payload_digest))
                        .then_some(entry.payload_digest);
                }
                NduProjectionKindV1::Revocation if selected == Some(entry.payload_digest) => {
                    selected = None;
                }
                _ => {}
            }
        }
        selected.filter(|digest| !revoked.contains(digest))
    }

    fn append(
        &mut self,
        kind: NduProjectionKindV1,
        identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        payload_digest: Digest32,
    ) -> Result<NduProjectionEntryV1, NduProjectionJournalError> {
        if identity_digest.is_zero()
            || objective_digest.is_zero()
            || subject_digest.is_zero()
            || payload_digest.is_zero()
        {
            return Err(NduProjectionJournalError::EmptyDigest);
        }
        if let Some((existing_kind, existing_objective, existing_subject, existing_payload)) =
            self.identities.get(&identity_digest)
        {
            if *existing_kind == kind
                && *existing_objective == objective_digest
                && *existing_subject == subject_digest
                && *existing_payload == payload_digest
            {
                return self
                    .entries
                    .iter()
                    .find(|entry| entry.identity_digest == identity_digest)
                    .cloned()
                    .ok_or(NduProjectionJournalError::CorruptEntryDigest);
            }
            return Err(NduProjectionJournalError::IdentityConflict);
        }
        if self.entries.len() >= MAX_RECORDS {
            return Err(NduProjectionJournalError::RecordLimitExceeded);
        }
        let sequence = u64::try_from(self.entries.len())
            .ok()
            .and_then(|value| value.checked_add(1))
            .ok_or(NduProjectionJournalError::RecordLimitExceeded)?;
        let predecessor_entry_digest = self
            .entries
            .last()
            .map_or(Digest32::ZERO, |entry| entry.entry_digest);
        let entry_digest = digest_entry(
            sequence,
            kind,
            identity_digest,
            objective_digest,
            subject_digest,
            payload_digest,
            predecessor_entry_digest,
        );
        let entry = NduProjectionEntryV1 {
            sequence,
            kind,
            identity_digest,
            objective_digest,
            subject_digest,
            payload_digest,
            predecessor_entry_digest,
            entry_digest,
        };
        self.identities.insert(
            identity_digest,
            (kind, objective_digest, subject_digest, payload_digest),
        );
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
            bytes.extend_from_slice(entry.objective_digest.as_array());
            bytes.extend_from_slice(entry.subject_digest.as_array());
            bytes.extend_from_slice(entry.payload_digest.as_array());
            bytes.extend_from_slice(entry.predecessor_entry_digest.as_array());
            bytes.extend_from_slice(entry.entry_digest.as_array());
        }
        bytes
    }

    pub fn reopen(bytes: &[u8]) -> Result<Self, NduProjectionJournalError> {
        if bytes.len() < 12 {
            return Err(NduProjectionJournalError::Truncated);
        }
        if &bytes[..8] != MAGIC {
            return Err(NduProjectionJournalError::CorruptHeader);
        }
        let count_u32 = u32::from_be_bytes(
            bytes[8..12]
                .try_into()
                .map_err(|_| NduProjectionJournalError::Truncated)?,
        );
        let count = usize::try_from(count_u32)
            .map_err(|_| NduProjectionJournalError::RecordLimitExceeded)?;
        if count > MAX_RECORDS {
            return Err(NduProjectionJournalError::RecordLimitExceeded);
        }
        let expected = 12_usize
            .checked_add(
                count
                    .checked_mul(RECORD_BYTES)
                    .ok_or(NduProjectionJournalError::Truncated)?,
            )
            .ok_or(NduProjectionJournalError::Truncated)?;
        if bytes.len() != expected {
            return Err(NduProjectionJournalError::Truncated);
        }

        let mut journal = Self::new();
        let mut offset = 12;
        for index in 0..count {
            let sequence = read_u64(bytes, &mut offset)?;
            let kind = NduProjectionKindV1::from_tag(read_u8(bytes, &mut offset)?)?;
            let identity_digest = read_digest(bytes, &mut offset)?;
            let objective_digest = read_digest(bytes, &mut offset)?;
            let subject_digest = read_digest(bytes, &mut offset)?;
            let payload_digest = read_digest(bytes, &mut offset)?;
            let predecessor_entry_digest = read_digest(bytes, &mut offset)?;
            let entry_digest = read_digest(bytes, &mut offset)?;
            let expected_sequence = u64::try_from(index)
                .ok()
                .and_then(|value| value.checked_add(1))
                .ok_or(NduProjectionJournalError::CorruptSequence)?;
            if sequence != expected_sequence {
                return Err(NduProjectionJournalError::CorruptSequence);
            }
            let expected_predecessor = journal
                .entries
                .last()
                .map_or(Digest32::ZERO, |entry| entry.entry_digest);
            if predecessor_entry_digest != expected_predecessor {
                return Err(NduProjectionJournalError::CorruptPredecessor);
            }
            let expected_digest = digest_entry(
                sequence,
                kind,
                identity_digest,
                objective_digest,
                subject_digest,
                payload_digest,
                predecessor_entry_digest,
            );
            if entry_digest != expected_digest {
                return Err(NduProjectionJournalError::CorruptEntryDigest);
            }
            if identity_digest.is_zero()
                || objective_digest.is_zero()
                || subject_digest.is_zero()
                || payload_digest.is_zero()
            {
                return Err(NduProjectionJournalError::EmptyDigest);
            }
            if journal.identities.contains_key(&identity_digest) {
                return Err(NduProjectionJournalError::DuplicateSerializedIdentity);
            }
            journal.identities.insert(
                identity_digest,
                (kind, objective_digest, subject_digest, payload_digest),
            );
            journal.entries.push(NduProjectionEntryV1 {
                sequence,
                kind,
                identity_digest,
                objective_digest,
                subject_digest,
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
            .filter(|entry| entry.kind == NduProjectionKindV1::Revocation)
            .map(|entry| entry.payload_digest)
            .collect()
    }
}

fn digest_entry(
    sequence: u64,
    kind: NduProjectionKindV1,
    identity_digest: Digest32,
    objective_digest: Digest32,
    subject_digest: Digest32,
    payload_digest: Digest32,
    predecessor_entry_digest: Digest32,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.ndu.projection-journal-entry.v1");
    bytes.extend_from_slice(&sequence.to_be_bytes());
    bytes.push(kind.tag());
    bytes.extend_from_slice(identity_digest.as_array());
    bytes.extend_from_slice(objective_digest.as_array());
    bytes.extend_from_slice(subject_digest.as_array());
    bytes.extend_from_slice(payload_digest.as_array());
    bytes.extend_from_slice(predecessor_entry_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn read_u8(bytes: &[u8], offset: &mut usize) -> Result<u8, NduProjectionJournalError> {
    let value = *bytes
        .get(*offset)
        .ok_or(NduProjectionJournalError::Truncated)?;
    *offset += 1;
    Ok(value)
}

fn read_u64(bytes: &[u8], offset: &mut usize) -> Result<u64, NduProjectionJournalError> {
    let end = (*offset)
        .checked_add(8)
        .ok_or(NduProjectionJournalError::Truncated)?;
    let value = u64::from_be_bytes(
        bytes
            .get(*offset..end)
            .ok_or(NduProjectionJournalError::Truncated)?
            .try_into()
            .map_err(|_| NduProjectionJournalError::Truncated)?,
    );
    *offset = end;
    Ok(value)
}

fn read_digest(
    bytes: &[u8],
    offset: &mut usize,
) -> Result<Digest32, NduProjectionJournalError> {
    let end = (*offset)
        .checked_add(32)
        .ok_or(NduProjectionJournalError::Truncated)?;
    let array: [u8; 32] = bytes
        .get(*offset..end)
        .ok_or(NduProjectionJournalError::Truncated)?
        .try_into()
        .map_err(|_| NduProjectionJournalError::Truncated)?;
    *offset = end;
    Ok(Digest32::from_array(array))
}

#[cfg(test)]
#[path = "projection_journal_tests.rs"]
mod tests;
