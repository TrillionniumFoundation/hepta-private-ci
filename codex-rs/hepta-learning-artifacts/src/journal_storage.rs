//! Durable create-only storage for withdrawal and lifecycle journals.
//!
//! These adapters persist replayable journal snapshots without making the
//! resulting file current by themselves. The caller retains the returned
//! receipt independently and authenticates the selected file/path.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::LogicalSequence;
use codex_hepta_types::StableId;

use crate::ArtifactClosureError;
use crate::ArtifactLifecycleEventV1;
use crate::ArtifactLifecycleJournalError;
use crate::ArtifactLifecycleJournalRecordV2;
use crate::ArtifactLifecycleJournalSnapshotV2;
use crate::ArtifactLifecycleJournalV2;
use crate::ArtifactLifecycleStateV1;
use crate::ArtifactStorageError;
use crate::CreateOnlyArtifactFile;
use crate::DatasetWithdrawalNoticeV1;
use crate::DatasetWithdrawalRecordV1;
use crate::DatasetWithdrawalRegistry;
use crate::DatasetWithdrawalRegistrySnapshotV1;
use crate::LifecycleActorEvidenceV2;
use crate::LifecycleActorRoleV2;
use crate::storage::read_bounded_blob;
use crate::storage::write_create_only_blob;

const MAX_JOURNAL_SNAPSHOT: usize = 8 * 1024 * 1024;
const WITHDRAWAL_MAGIC: &str = "HEPTAWD1";
const LIFECYCLE_MAGIC: &str = "HEPTALJ2";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct JournalSnapshotReceiptV1 {
    pub binding: Digest32,
    pub head_digest: Digest32,
    pub file_digest: Digest32,
    pub records: usize,
    pub encoded_bytes: usize,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum JournalStorageError {
    Storage(ArtifactStorageError),
    Withdrawal(ArtifactClosureError),
    Lifecycle(ArtifactLifecycleJournalError),
    InvalidBinding,
    InvalidReceipt,
    Corrupt,
    Capacity,
}

impl fmt::Display for JournalStorageError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for JournalStorageError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Storage(error) => Some(error),
            Self::Withdrawal(error) => Some(error),
            Self::Lifecycle(error) => Some(error),
            Self::InvalidBinding | Self::InvalidReceipt | Self::Corrupt | Self::Capacity => None,
        }
    }
}

impl From<ArtifactStorageError> for JournalStorageError {
    fn from(value: ArtifactStorageError) -> Self {
        Self::Storage(value)
    }
}

impl From<ArtifactClosureError> for JournalStorageError {
    fn from(value: ArtifactClosureError) -> Self {
        Self::Withdrawal(value)
    }
}

impl From<ArtifactLifecycleJournalError> for JournalStorageError {
    fn from(value: ArtifactLifecycleJournalError) -> Self {
        Self::Lifecycle(value)
    }
}

pub fn write_dataset_withdrawal_snapshot(
    file: CreateOnlyArtifactFile,
    registry: &DatasetWithdrawalRegistry,
    binding: Digest32,
) -> Result<JournalSnapshotReceiptV1, JournalStorageError> {
    require_binding(binding)?;
    let snapshot = registry.snapshot();
    let bytes = encode_withdrawal_snapshot(&snapshot, binding)?;
    let receipt = receipt(
        binding,
        snapshot.head_digest,
        snapshot.records().len(),
        &bytes,
    );
    write_create_only_blob(file, &bytes)?;
    Ok(receipt)
}

pub fn read_dataset_withdrawal_snapshot(
    file: File,
    expected: JournalSnapshotReceiptV1,
) -> Result<DatasetWithdrawalRegistry, JournalStorageError> {
    let bytes = read_and_verify(file, expected)?;
    let snapshot = decode_withdrawal_snapshot(&bytes, expected)?;
    DatasetWithdrawalRegistry::from_snapshot(snapshot).map_err(Into::into)
}

pub fn write_lifecycle_journal_snapshot(
    file: CreateOnlyArtifactFile,
    journal: &ArtifactLifecycleJournalV2,
    binding: Digest32,
) -> Result<JournalSnapshotReceiptV1, JournalStorageError> {
    require_binding(binding)?;
    let snapshot = journal.snapshot();
    let bytes = encode_lifecycle_snapshot(&snapshot, binding)?;
    let receipt = receipt(
        binding,
        snapshot.head_digest,
        snapshot.records.len(),
        &bytes,
    );
    write_create_only_blob(file, &bytes)?;
    Ok(receipt)
}

pub fn read_lifecycle_journal_snapshot(
    file: File,
    expected: JournalSnapshotReceiptV1,
    now: u64,
) -> Result<ArtifactLifecycleJournalV2, JournalStorageError> {
    let bytes = read_and_verify(file, expected)?;
    let snapshot = decode_lifecycle_snapshot(&bytes, expected)?;
    ArtifactLifecycleJournalV2::from_snapshot(snapshot, now).map_err(Into::into)
}

fn require_binding(binding: Digest32) -> Result<(), JournalStorageError> {
    if binding.is_zero() {
        return Err(JournalStorageError::InvalidBinding);
    }
    Ok(())
}

fn receipt(
    binding: Digest32,
    head_digest: Digest32,
    records: usize,
    bytes: &[u8],
) -> JournalSnapshotReceiptV1 {
    JournalSnapshotReceiptV1 {
        binding,
        head_digest,
        file_digest: Digest32::of_bytes(bytes),
        records,
        encoded_bytes: bytes.len(),
    }
}

fn read_and_verify(
    file: File,
    expected: JournalSnapshotReceiptV1,
) -> Result<Vec<u8>, JournalStorageError> {
    require_binding(expected.binding)?;
    if expected.file_digest.is_zero()
        || expected.encoded_bytes == 0
        || expected.encoded_bytes > MAX_JOURNAL_SNAPSHOT
    {
        return Err(JournalStorageError::InvalidReceipt);
    }
    let bytes = read_bounded_blob(file, MAX_JOURNAL_SNAPSHOT, expected.encoded_bytes)?;
    if Digest32::of_bytes(&bytes) != expected.file_digest {
        return Err(JournalStorageError::InvalidReceipt);
    }
    Ok(bytes)
}

fn encode_withdrawal_snapshot(
    snapshot: &DatasetWithdrawalRegistrySnapshotV1,
    binding: Digest32,
) -> Result<Vec<u8>, JournalStorageError> {
    let mut text = format!(
        "{WITHDRAWAL_MAGIC}\n{binding}\n{}\n{}\n",
        snapshot.records().len(),
        snapshot.head_digest
    );
    for record in snapshot.records() {
        let notice = &record.notice;
        text.push_str(&format!(
            "W|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}\n",
            record.sequence.get(),
            record.predecessor_chain_digest,
            record.event_digest,
            record.chain_digest,
            encode_id(&notice.notice_id),
            notice.dataset_digest,
            notice.source_tombstone_digest,
            encode_id(&notice.authority_id),
            notice.credential_chain_digest,
            notice.signing_key_digest,
            notice.authority_epoch,
            notice.issued_at,
        ));
    }
    bounded_text(text)
}

fn decode_withdrawal_snapshot(
    bytes: &[u8],
    expected: JournalSnapshotReceiptV1,
) -> Result<DatasetWithdrawalRegistrySnapshotV1, JournalStorageError> {
    let text = std::str::from_utf8(bytes).map_err(|_| JournalStorageError::Corrupt)?;
    let mut lines = text.lines();
    let magic = lines.next().ok_or(JournalStorageError::Corrupt)?;
    let binding = parse_digest(lines.next().ok_or(JournalStorageError::Corrupt)?)?;
    let count = parse_usize(lines.next().ok_or(JournalStorageError::Corrupt)?)?;
    let head = parse_digest(lines.next().ok_or(JournalStorageError::Corrupt)?)?;
    if magic != WITHDRAWAL_MAGIC
        || binding != expected.binding
        || count != expected.records
        || head != expected.head_digest
    {
        return Err(JournalStorageError::InvalidReceipt);
    }

    let mut records = Vec::with_capacity(count);
    for line in lines {
        let fields: Vec<_> = line.split('|').collect();
        if fields.len() != 13 || fields[0] != "W" {
            return Err(JournalStorageError::Corrupt);
        }
        records.push(DatasetWithdrawalRecordV1 {
            sequence: LogicalSequence::new(parse_u64(fields[1])?)
                .map_err(|_| JournalStorageError::Corrupt)?,
            predecessor_chain_digest: parse_digest(fields[2])?,
            event_digest: parse_digest(fields[3])?,
            chain_digest: parse_digest(fields[4])?,
            notice: DatasetWithdrawalNoticeV1 {
                notice_id: decode_id(fields[5])?,
                dataset_digest: parse_digest(fields[6])?,
                source_tombstone_digest: parse_digest(fields[7])?,
                authority_id: decode_id(fields[8])?,
                credential_chain_digest: parse_digest(fields[9])?,
                signing_key_digest: parse_digest(fields[10])?,
                authority_epoch: parse_u64(fields[11])?,
                issued_at: parse_u64(fields[12])?,
            },
        });
    }
    if records.len() != count {
        return Err(JournalStorageError::Corrupt);
    }
    Ok(DatasetWithdrawalRegistrySnapshotV1::from_parts(
        records, head,
    ))
}

fn encode_lifecycle_snapshot(
    snapshot: &ArtifactLifecycleJournalSnapshotV2,
    binding: Digest32,
) -> Result<Vec<u8>, JournalStorageError> {
    let mut text = format!(
        "{LIFECYCLE_MAGIC}\n{binding}\n{}\n{}\n",
        snapshot.records.len(),
        snapshot.head_digest
    );
    for record in &snapshot.records {
        let actor = &record.actor;
        let event = &record.event;
        text.push_str(&format!(
            "L|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}\n",
            record.sequence,
            record.predecessor_head_digest,
            record.event_digest,
            record.chain_digest,
            encode_id(&record.producer_id),
            encode_id(&actor.actor_id),
            actor.credential_digest,
            role_tag(actor.role),
            actor.authority_epoch,
            actor.verified_at,
            actor.expires_at,
            encode_id(&event.event_id),
            encode_id(&event.artifact_id),
            state_tag(event.prior_state),
            state_tag(event.next_state),
            encode_id(&event.actor_id),
            event.actor_credential_digest,
            event.evidence_digest,
            event.authority_epoch,
            event.occurred_at,
        ));
    }
    bounded_text(text)
}

fn decode_lifecycle_snapshot(
    bytes: &[u8],
    expected: JournalSnapshotReceiptV1,
) -> Result<ArtifactLifecycleJournalSnapshotV2, JournalStorageError> {
    let text = std::str::from_utf8(bytes).map_err(|_| JournalStorageError::Corrupt)?;
    let mut lines = text.lines();
    let magic = lines.next().ok_or(JournalStorageError::Corrupt)?;
    let binding = parse_digest(lines.next().ok_or(JournalStorageError::Corrupt)?)?;
    let count = parse_usize(lines.next().ok_or(JournalStorageError::Corrupt)?)?;
    let head = parse_digest(lines.next().ok_or(JournalStorageError::Corrupt)?)?;
    if magic != LIFECYCLE_MAGIC
        || binding != expected.binding
        || count != expected.records
        || head != expected.head_digest
    {
        return Err(JournalStorageError::InvalidReceipt);
    }

    let mut records = Vec::with_capacity(count);
    for line in lines {
        let fields: Vec<_> = line.split('|').collect();
        if fields.len() != 21 || fields[0] != "L" {
            return Err(JournalStorageError::Corrupt);
        }
        records.push(ArtifactLifecycleJournalRecordV2 {
            sequence: parse_u64(fields[1])?,
            predecessor_head_digest: parse_digest(fields[2])?,
            event_digest: parse_digest(fields[3])?,
            chain_digest: parse_digest(fields[4])?,
            producer_id: decode_id(fields[5])?,
            actor: LifecycleActorEvidenceV2 {
                actor_id: decode_id(fields[6])?,
                credential_digest: parse_digest(fields[7])?,
                role: parse_role(fields[8])?,
                authority_epoch: parse_u64(fields[9])?,
                verified_at: parse_u64(fields[10])?,
                expires_at: parse_u64(fields[11])?,
            },
            event: ArtifactLifecycleEventV1 {
                event_id: decode_id(fields[12])?,
                artifact_id: decode_id(fields[13])?,
                prior_state: parse_state(fields[14])?,
                next_state: parse_state(fields[15])?,
                actor_id: decode_id(fields[16])?,
                actor_credential_digest: parse_digest(fields[17])?,
                evidence_digest: parse_digest(fields[18])?,
                authority_epoch: parse_u64(fields[19])?,
                occurred_at: parse_u64(fields[20])?,
            },
        });
    }
    if records.len() != count {
        return Err(JournalStorageError::Corrupt);
    }
    Ok(ArtifactLifecycleJournalSnapshotV2 {
        records,
        head_digest: head,
    })
}

fn bounded_text(text: String) -> Result<Vec<u8>, JournalStorageError> {
    if text.len() > MAX_JOURNAL_SNAPSHOT {
        return Err(JournalStorageError::Capacity);
    }
    Ok(text.into_bytes())
}

fn encode_id(value: &StableId) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(value.as_str().len() * 2);
    for byte in value.as_str().as_bytes() {
        output.push(HEX[(byte >> 4) as usize] as char);
        output.push(HEX[(byte & 0x0f) as usize] as char);
    }
    output
}

fn decode_id(value: &str) -> Result<StableId, JournalStorageError> {
    if !value.len().is_multiple_of(2) {
        return Err(JournalStorageError::Corrupt);
    }
    let mut bytes = Vec::with_capacity(value.len() / 2);
    for pair in value.as_bytes().chunks_exact(2) {
        let high = hex_nibble(pair[0])?;
        let low = hex_nibble(pair[1])?;
        bytes.push((high << 4) | low);
    }
    let value = String::from_utf8(bytes).map_err(|_| JournalStorageError::Corrupt)?;
    StableId::new(value).map_err(|_| JournalStorageError::Corrupt)
}

fn hex_nibble(value: u8) -> Result<u8, JournalStorageError> {
    match value {
        b'0'..=b'9' => Ok(value - b'0'),
        b'a'..=b'f' => Ok(value - b'a' + 10),
        b'A'..=b'F' => Ok(value - b'A' + 10),
        _ => Err(JournalStorageError::Corrupt),
    }
}

fn parse_digest(value: &str) -> Result<Digest32, JournalStorageError> {
    Digest32::from_str(value).map_err(|_| JournalStorageError::Corrupt)
}

fn parse_u64(value: &str) -> Result<u64, JournalStorageError> {
    value.parse().map_err(|_| JournalStorageError::Corrupt)
}

fn parse_usize(value: &str) -> Result<usize, JournalStorageError> {
    value.parse().map_err(|_| JournalStorageError::Corrupt)
}

const fn role_tag(role: LifecycleActorRoleV2) -> u8 {
    match role {
        LifecycleActorRoleV2::Producer => 0,
        LifecycleActorRoleV2::Evaluator => 1,
        LifecycleActorRoleV2::ShadowOperator => 2,
        LifecycleActorRoleV2::CanaryOperator => 3,
        LifecycleActorRoleV2::HumanOperator => 4,
        LifecycleActorRoleV2::Selector => 5,
        LifecycleActorRoleV2::QuarantineAuthority => 6,
        LifecycleActorRoleV2::RevocationAuthority => 7,
        LifecycleActorRoleV2::RetirementAuthority => 8,
    }
}

fn parse_role(value: &str) -> Result<LifecycleActorRoleV2, JournalStorageError> {
    match value {
        "0" => Ok(LifecycleActorRoleV2::Producer),
        "1" => Ok(LifecycleActorRoleV2::Evaluator),
        "2" => Ok(LifecycleActorRoleV2::ShadowOperator),
        "3" => Ok(LifecycleActorRoleV2::CanaryOperator),
        "4" => Ok(LifecycleActorRoleV2::HumanOperator),
        "5" => Ok(LifecycleActorRoleV2::Selector),
        "6" => Ok(LifecycleActorRoleV2::QuarantineAuthority),
        "7" => Ok(LifecycleActorRoleV2::RevocationAuthority),
        "8" => Ok(LifecycleActorRoleV2::RetirementAuthority),
        _ => Err(JournalStorageError::Corrupt),
    }
}

const fn state_tag(state: ArtifactLifecycleStateV1) -> u8 {
    match state {
        ArtifactLifecycleStateV1::Proposed => 0,
        ArtifactLifecycleStateV1::Trained => 1,
        ArtifactLifecycleStateV1::Evaluated => 2,
        ArtifactLifecycleStateV1::Shadow => 3,
        ArtifactLifecycleStateV1::Canary => 4,
        ArtifactLifecycleStateV1::OperatorAccepted => 5,
        ArtifactLifecycleStateV1::Selected => 6,
        ArtifactLifecycleStateV1::Quarantined => 7,
        ArtifactLifecycleStateV1::Revoked => 8,
        ArtifactLifecycleStateV1::Retired => 9,
    }
}

fn parse_state(value: &str) -> Result<ArtifactLifecycleStateV1, JournalStorageError> {
    match value {
        "0" => Ok(ArtifactLifecycleStateV1::Proposed),
        "1" => Ok(ArtifactLifecycleStateV1::Trained),
        "2" => Ok(ArtifactLifecycleStateV1::Evaluated),
        "3" => Ok(ArtifactLifecycleStateV1::Shadow),
        "4" => Ok(ArtifactLifecycleStateV1::Canary),
        "5" => Ok(ArtifactLifecycleStateV1::OperatorAccepted),
        "6" => Ok(ArtifactLifecycleStateV1::Selected),
        "7" => Ok(ArtifactLifecycleStateV1::Quarantined),
        "8" => Ok(ArtifactLifecycleStateV1::Revoked),
        "9" => Ok(ArtifactLifecycleStateV1::Retired),
        _ => Err(JournalStorageError::Corrupt),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs::File;

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("valid fixture id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn path(name: &str) -> std::path::PathBuf {
        std::env::temp_dir().join(format!(
            "hepta-learning-journal-{}-{name}",
            std::process::id()
        ))
    }

    #[test]
    fn withdrawal_snapshot_round_trips_through_durable_bytes() {
        let file_path = path("withdrawal");
        let _ = std::fs::remove_file(&file_path);
        let mut registry = DatasetWithdrawalRegistry::new();
        registry
            .append(DatasetWithdrawalNoticeV1 {
                notice_id: id("notice"),
                dataset_digest: digest("dataset"),
                source_tombstone_digest: digest("tombstone"),
                authority_id: id("authority"),
                credential_chain_digest: digest("credential"),
                signing_key_digest: digest("key"),
                authority_epoch: 1,
                issued_at: 20,
            })
            .expect("valid withdrawal");
        let receipt = write_dataset_withdrawal_snapshot(
            CreateOnlyArtifactFile::create(&file_path).expect("create-only file"),
            &registry,
            digest("withdrawal-binding"),
        )
        .expect("write withdrawal snapshot");
        let reopened = read_dataset_withdrawal_snapshot(
            File::open(&file_path).expect("open snapshot"),
            receipt,
        )
        .expect("reopen withdrawal snapshot");
        assert_eq!(reopened.snapshot(), registry.snapshot());
        let _ = std::fs::remove_file(file_path);
    }

    #[test]
    fn lifecycle_snapshot_round_trips_after_actor_expiry() {
        let file_path = path("lifecycle");
        let _ = std::fs::remove_file(&file_path);
        let producer_id = id("producer");
        let actor = LifecycleActorEvidenceV2 {
            actor_id: producer_id.clone(),
            credential_digest: digest("credential"),
            role: LifecycleActorRoleV2::Producer,
            authority_epoch: 1,
            verified_at: 10,
            expires_at: 100,
        };
        let mut journal = ArtifactLifecycleJournalV2::new();
        journal
            .append(
                Digest32::ZERO,
                &producer_id,
                actor.clone(),
                ArtifactLifecycleEventV1 {
                    event_id: id("trained"),
                    artifact_id: id("artifact"),
                    prior_state: ArtifactLifecycleStateV1::Proposed,
                    next_state: ArtifactLifecycleStateV1::Trained,
                    actor_id: actor.actor_id.clone(),
                    actor_credential_digest: actor.credential_digest,
                    evidence_digest: digest("evidence"),
                    authority_epoch: actor.authority_epoch,
                    occurred_at: 20,
                },
                20,
            )
            .expect("valid lifecycle event");
        let receipt = write_lifecycle_journal_snapshot(
            CreateOnlyArtifactFile::create(&file_path).expect("create-only file"),
            &journal,
            digest("lifecycle-binding"),
        )
        .expect("write lifecycle snapshot");
        let reopened = read_lifecycle_journal_snapshot(
            File::open(&file_path).expect("open snapshot"),
            receipt,
            101,
        )
        .expect("historical snapshot reopens after credential expiry");
        assert_eq!(reopened.snapshot(), journal.snapshot());
        let _ = std::fs::remove_file(file_path);
    }
}
