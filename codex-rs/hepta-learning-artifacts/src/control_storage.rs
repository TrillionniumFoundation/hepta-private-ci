//! Create-only durable adapters for withdrawal and lifecycle control state.
//!
//! These formats are bounded, canonical snapshots used to prove that the
//! replayable control models survive real file persistence and process restart.
//! They do not discover the newest generation or grant mutation authority.

use std::fs::File;
use std::str::FromStr;

use codex_hepta_types::{Digest32, LogicalSequence, StableId};

use crate::{
    ArtifactLifecycleEventV1, ArtifactLifecycleJournalRecordV2, ArtifactLifecycleJournalSnapshotV2,
    ArtifactLifecycleJournalV2, ArtifactLifecycleStateV1, ArtifactStorageError,
    CreateOnlyArtifactFile, DatasetWithdrawalNoticeV1, DatasetWithdrawalRecordV1,
    DatasetWithdrawalRegistry, DatasetWithdrawalRegistrySnapshotV1, LifecycleActorEvidenceV2,
    LifecycleActorRoleV2, MAX_DURABLE_ARTIFACT_RECORDS, MAX_DURABLE_ARTIFACT_SNAPSHOT_BYTES,
    WithdrawalAuthorityDomainV1, withdrawal_authority_domain_digest_v1,
};
use crate::storage::{read_bounded, write_new};

const WITHDRAWAL_MAGIC: &str = "HEPTAW01";
const LIFECYCLE_MAGIC: &str = "HEPTAL02";
const MAX_CONTROL_LINE: usize = 4096;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DatasetWithdrawalSnapshotReceiptV1 {
    pub binding: Digest32,
    pub head_digest: Digest32,
    pub file_digest: Digest32,
    pub records: usize,
    pub encoded_bytes: usize,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ArtifactLifecycleSnapshotReceiptV2 {
    pub binding: Digest32,
    pub head_digest: Digest32,
    pub file_digest: Digest32,
    pub records: usize,
    pub encoded_bytes: usize,
}

pub fn write_dataset_withdrawal_snapshot_v1(
    file: CreateOnlyArtifactFile,
    snapshot: &DatasetWithdrawalRegistrySnapshotV1,
    binding: Digest32,
) -> Result<DatasetWithdrawalSnapshotReceiptV1, ArtifactStorageError> {
    let bytes = encode_withdrawal_snapshot(snapshot, binding)?;
    let receipt = DatasetWithdrawalSnapshotReceiptV1 {
        binding,
        head_digest: snapshot.head_digest,
        file_digest: Digest32::of_bytes(&bytes),
        records: snapshot.records().len(),
        encoded_bytes: bytes.len(),
    };
    write_new(file, &bytes)?;
    Ok(receipt)
}

pub fn write_dataset_withdrawal_snapshot_for_domain_v1(
    file: CreateOnlyArtifactFile,
    snapshot: &DatasetWithdrawalRegistrySnapshotV1,
    domain: &WithdrawalAuthorityDomainV1,
) -> Result<DatasetWithdrawalSnapshotReceiptV1, ArtifactStorageError> {
    let binding = withdrawal_authority_domain_digest_v1(domain)
        .map_err(|_| ArtifactStorageError::InvalidBinding)?;
    write_dataset_withdrawal_snapshot_v1(file, snapshot, binding)
}

pub fn read_dataset_withdrawal_snapshot_for_domain_v1(
    file: File,
    expected: DatasetWithdrawalSnapshotReceiptV1,
    domain: &WithdrawalAuthorityDomainV1,
) -> Result<DatasetWithdrawalRegistry, ArtifactStorageError> {
    let binding = withdrawal_authority_domain_digest_v1(domain)
        .map_err(|_| ArtifactStorageError::InvalidBinding)?;
    if expected.binding != binding {
        return Err(ArtifactStorageError::InvalidReceipt);
    }
    read_dataset_withdrawal_snapshot_v1(file, expected)
}

pub fn read_dataset_withdrawal_snapshot_v1(
    file: File,
    expected: DatasetWithdrawalSnapshotReceiptV1,
) -> Result<DatasetWithdrawalRegistry, ArtifactStorageError> {
    validate_receipt(
        expected.binding,
        expected.head_digest,
        expected.file_digest,
        expected.records,
        expected.encoded_bytes,
    )?;
    let bytes = read_bounded(
        file,
        MAX_DURABLE_ARTIFACT_SNAPSHOT_BYTES,
        expected.encoded_bytes as u64,
        ArtifactStorageError::Corrupt,
    )?;
    if Digest32::of_bytes(&bytes) != expected.file_digest {
        return Err(ArtifactStorageError::Corrupt);
    }
    let snapshot = decode_withdrawal_snapshot(&bytes, expected)?;
    let registry =
        DatasetWithdrawalRegistry::from_snapshot(snapshot).map_err(|_| ArtifactStorageError::Semantic)?;
    if encode_withdrawal_snapshot(&registry.snapshot(), expected.binding)? != bytes {
        return Err(ArtifactStorageError::Corrupt);
    }
    Ok(registry)
}

pub fn write_artifact_lifecycle_snapshot_v2(
    file: CreateOnlyArtifactFile,
    snapshot: &ArtifactLifecycleJournalSnapshotV2,
    binding: Digest32,
) -> Result<ArtifactLifecycleSnapshotReceiptV2, ArtifactStorageError> {
    let bytes = encode_lifecycle_snapshot(snapshot, binding)?;
    let receipt = ArtifactLifecycleSnapshotReceiptV2 {
        binding,
        head_digest: snapshot.head_digest,
        file_digest: Digest32::of_bytes(&bytes),
        records: snapshot.records.len(),
        encoded_bytes: bytes.len(),
    };
    write_new(file, &bytes)?;
    Ok(receipt)
}

pub fn read_artifact_lifecycle_snapshot_v2(
    file: File,
    expected: ArtifactLifecycleSnapshotReceiptV2,
    now: u64,
) -> Result<ArtifactLifecycleJournalV2, ArtifactStorageError> {
    validate_receipt(
        expected.binding,
        expected.head_digest,
        expected.file_digest,
        expected.records,
        expected.encoded_bytes,
    )?;
    let bytes = read_bounded(
        file,
        MAX_DURABLE_ARTIFACT_SNAPSHOT_BYTES,
        expected.encoded_bytes as u64,
        ArtifactStorageError::Corrupt,
    )?;
    if Digest32::of_bytes(&bytes) != expected.file_digest {
        return Err(ArtifactStorageError::Corrupt);
    }
    let snapshot = decode_lifecycle_snapshot(&bytes, expected)?;
    let journal =
        ArtifactLifecycleJournalV2::from_snapshot(snapshot, now).map_err(|_| ArtifactStorageError::Semantic)?;
    if encode_lifecycle_snapshot(&journal.snapshot(), expected.binding)? != bytes {
        return Err(ArtifactStorageError::Corrupt);
    }
    Ok(journal)
}

fn validate_receipt(
    binding: Digest32,
    head_digest: Digest32,
    file_digest: Digest32,
    records: usize,
    encoded_bytes: usize,
) -> Result<(), ArtifactStorageError> {
    if binding.is_zero()
        || file_digest.is_zero()
        || records > MAX_DURABLE_ARTIFACT_RECORDS
        || encoded_bytes == 0
        || encoded_bytes > MAX_DURABLE_ARTIFACT_SNAPSHOT_BYTES
        || (records == 0) != head_digest.is_zero()
    {
        return Err(ArtifactStorageError::InvalidReceipt);
    }
    Ok(())
}

fn encode_withdrawal_snapshot(
    snapshot: &DatasetWithdrawalRegistrySnapshotV1,
    binding: Digest32,
) -> Result<Vec<u8>, ArtifactStorageError> {
    if binding.is_zero()
        || snapshot.records().len() > MAX_DURABLE_ARTIFACT_RECORDS
        || (snapshot.records().is_empty() != snapshot.head_digest.is_zero())
    {
        return Err(ArtifactStorageError::Capacity);
    }
    let mut text = format!(
        "{WITHDRAWAL_MAGIC}\n{binding}\n{}\n{}\n",
        snapshot.records().len(),
        snapshot.head_digest
    );
    for record in snapshot.records() {
        let notice = &record.notice;
        let line = format!(
            "W|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}\n",
            record.sequence.get(),
            record.predecessor_chain_digest,
            record.event_digest,
            record.chain_digest,
            notice.notice_id,
            notice.dataset_digest,
            notice.source_tombstone_digest,
            notice.authority_id,
            notice.credential_chain_digest,
            notice.signing_key_digest,
            notice.authority_epoch,
            notice.issued_at,
        );
        if line.len() > MAX_CONTROL_LINE {
            return Err(ArtifactStorageError::Capacity);
        }
        text.push_str(&line);
    }
    if text.len() > MAX_DURABLE_ARTIFACT_SNAPSHOT_BYTES {
        return Err(ArtifactStorageError::Capacity);
    }
    Ok(text.into_bytes())
}

fn decode_withdrawal_snapshot(
    bytes: &[u8],
    expected: DatasetWithdrawalSnapshotReceiptV1,
) -> Result<DatasetWithdrawalRegistrySnapshotV1, ArtifactStorageError> {
    let text = std::str::from_utf8(bytes).map_err(|_| ArtifactStorageError::Corrupt)?;
    let mut lines = text.lines();
    if lines.next() != Some(WITHDRAWAL_MAGIC)
        || lines.next() != Some(expected.binding.to_string().as_str())
        || lines.next() != Some(expected.records.to_string().as_str())
        || lines.next() != Some(expected.head_digest.to_string().as_str())
    {
        return Err(ArtifactStorageError::Corrupt);
    }
    let mut records = Vec::with_capacity(expected.records);
    for line in lines {
        if records.len() >= expected.records || line.len() > MAX_CONTROL_LINE {
            return Err(ArtifactStorageError::Corrupt);
        }
        let fields: Vec<_> = line.split('|').collect();
        if fields.len() != 13 || fields[0] != "W" {
            return Err(ArtifactStorageError::Corrupt);
        }
        records.push(DatasetWithdrawalRecordV1 {
            sequence: LogicalSequence::new(parse_u64(fields[1])?)
                .map_err(|_| ArtifactStorageError::Corrupt)?,
            predecessor_chain_digest: parse_digest(fields[2])?,
            event_digest: parse_digest(fields[3])?,
            chain_digest: parse_digest(fields[4])?,
            notice: DatasetWithdrawalNoticeV1 {
                notice_id: parse_id(fields[5])?,
                dataset_digest: parse_digest(fields[6])?,
                source_tombstone_digest: parse_digest(fields[7])?,
                authority_id: parse_id(fields[8])?,
                credential_chain_digest: parse_digest(fields[9])?,
                signing_key_digest: parse_digest(fields[10])?,
                authority_epoch: parse_u64(fields[11])?,
                issued_at: parse_u64(fields[12])?,
            },
        });
    }
    if records.len() != expected.records {
        return Err(ArtifactStorageError::Corrupt);
    }
    Ok(DatasetWithdrawalRegistrySnapshotV1::from_records(
        records,
        expected.head_digest,
    ))
}

fn encode_lifecycle_snapshot(
    snapshot: &ArtifactLifecycleJournalSnapshotV2,
    binding: Digest32,
) -> Result<Vec<u8>, ArtifactStorageError> {
    if binding.is_zero()
        || snapshot.records.len() > MAX_DURABLE_ARTIFACT_RECORDS
        || (snapshot.records.is_empty() != snapshot.head_digest.is_zero())
    {
        return Err(ArtifactStorageError::Capacity);
    }
    let mut text = format!(
        "{LIFECYCLE_MAGIC}\n{binding}\n{}\n{}\n",
        snapshot.records.len(),
        snapshot.head_digest
    );
    for record in &snapshot.records {
        let actor = &record.actor;
        let event = &record.event;
        let line = format!(
            "L|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}\n",
            record.sequence,
            record.predecessor_head_digest,
            record.event_digest,
            record.chain_digest,
            record.producer_id,
            actor.actor_id,
            actor.credential_digest,
            role_tag(actor.role),
            actor.authority_epoch,
            actor.verified_at,
            actor.expires_at,
            event.event_id,
            event.artifact_id,
            state_tag(event.prior_state),
            state_tag(event.next_state),
            event.actor_id,
            event.actor_credential_digest,
            event.evidence_digest,
            event.authority_epoch,
            event.occurred_at,
        );
        if line.len() > MAX_CONTROL_LINE {
            return Err(ArtifactStorageError::Capacity);
        }
        text.push_str(&line);
    }
    if text.len() > MAX_DURABLE_ARTIFACT_SNAPSHOT_BYTES {
        return Err(ArtifactStorageError::Capacity);
    }
    Ok(text.into_bytes())
}

fn decode_lifecycle_snapshot(
    bytes: &[u8],
    expected: ArtifactLifecycleSnapshotReceiptV2,
) -> Result<ArtifactLifecycleJournalSnapshotV2, ArtifactStorageError> {
    let text = std::str::from_utf8(bytes).map_err(|_| ArtifactStorageError::Corrupt)?;
    let mut lines = text.lines();
    if lines.next() != Some(LIFECYCLE_MAGIC)
        || lines.next() != Some(expected.binding.to_string().as_str())
        || lines.next() != Some(expected.records.to_string().as_str())
        || lines.next() != Some(expected.head_digest.to_string().as_str())
    {
        return Err(ArtifactStorageError::Corrupt);
    }
    let mut records = Vec::with_capacity(expected.records);
    for line in lines {
        if records.len() >= expected.records || line.len() > MAX_CONTROL_LINE {
            return Err(ArtifactStorageError::Corrupt);
        }
        let fields: Vec<_> = line.split('|').collect();
        if fields.len() != 21 || fields[0] != "L" {
            return Err(ArtifactStorageError::Corrupt);
        }
        records.push(ArtifactLifecycleJournalRecordV2 {
            sequence: parse_u64(fields[1])?,
            predecessor_head_digest: parse_digest(fields[2])?,
            event_digest: parse_digest(fields[3])?,
            chain_digest: parse_digest(fields[4])?,
            producer_id: parse_id(fields[5])?,
            actor: LifecycleActorEvidenceV2 {
                actor_id: parse_id(fields[6])?,
                credential_digest: parse_digest(fields[7])?,
                role: parse_role(fields[8])?,
                authority_epoch: parse_u64(fields[9])?,
                verified_at: parse_u64(fields[10])?,
                expires_at: parse_u64(fields[11])?,
            },
            event: ArtifactLifecycleEventV1 {
                event_id: parse_id(fields[12])?,
                artifact_id: parse_id(fields[13])?,
                prior_state: parse_state(fields[14])?,
                next_state: parse_state(fields[15])?,
                actor_id: parse_id(fields[16])?,
                actor_credential_digest: parse_digest(fields[17])?,
                evidence_digest: parse_digest(fields[18])?,
                authority_epoch: parse_u64(fields[19])?,
                occurred_at: parse_u64(fields[20])?,
            },
        });
    }
    if records.len() != expected.records {
        return Err(ArtifactStorageError::Corrupt);
    }
    Ok(ArtifactLifecycleJournalSnapshotV2 {
        records,
        head_digest: expected.head_digest,
    })
}

fn parse_id(value: &str) -> Result<StableId, ArtifactStorageError> {
    StableId::new(value).map_err(|_| ArtifactStorageError::Corrupt)
}

fn parse_digest(value: &str) -> Result<Digest32, ArtifactStorageError> {
    Digest32::from_str(value).map_err(|_| ArtifactStorageError::Corrupt)
}

fn parse_u64(value: &str) -> Result<u64, ArtifactStorageError> {
    value.parse::<u64>().map_err(|_| ArtifactStorageError::Corrupt)
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

fn parse_role(value: &str) -> Result<LifecycleActorRoleV2, ArtifactStorageError> {
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
        _ => Err(ArtifactStorageError::Corrupt),
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

fn parse_state(value: &str) -> Result<ArtifactLifecycleStateV1, ArtifactStorageError> {
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
        _ => Err(ArtifactStorageError::Corrupt),
    }
}

#[cfg(test)]
mod tests {
    use std::fs::File;
    use std::path::PathBuf;
    use std::sync::atomic::{AtomicU64, Ordering};

    use super::*;

    static NEXT_PATH: AtomicU64 = AtomicU64::new(1);

    fn path(label: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "hepta-learning-artifacts-{label}-{}-{}",
            std::process::id(),
            NEXT_PATH.fetch_add(1, Ordering::Relaxed)
        ))
    }

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    #[test]
    fn withdrawal_snapshot_roundtrips_through_create_only_storage() {
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
            .unwrap();
        let snapshot = registry.snapshot();
        let target = path("withdrawal");
        let receipt = write_dataset_withdrawal_snapshot_v1(
            CreateOnlyArtifactFile::create(&target).unwrap(),
            &snapshot,
            digest("binding"),
        )
        .unwrap();
        let reopened =
            read_dataset_withdrawal_snapshot_v1(File::open(&target).unwrap(), receipt).unwrap();
        assert_eq!(reopened.snapshot(), snapshot);
        let _ = std::fs::remove_file(target);
    }

    #[test]
    fn withdrawal_snapshot_is_bound_to_authority_domain_and_epoch() {
        let mut registry = DatasetWithdrawalRegistry::new();
        registry
            .append(DatasetWithdrawalNoticeV1 {
                notice_id: id("domain-notice"),
                dataset_digest: digest("domain-dataset"),
                source_tombstone_digest: digest("domain-tombstone"),
                authority_id: id("withdrawal-authority"),
                credential_chain_digest: digest("domain-credential"),
                signing_key_digest: digest("domain-key"),
                authority_epoch: 7,
                issued_at: 20,
            })
            .unwrap();
        let domain = WithdrawalAuthorityDomainV1 {
            registry_id: id("withdrawal-registry"),
            scope_digest: digest("tenant-a"),
            authority_id: id("withdrawal-authority"),
            authority_epoch: 7,
        };
        let mut rotated = domain.clone();
        rotated.authority_epoch = 8;
        let target = path("withdrawal-domain");
        let receipt = write_dataset_withdrawal_snapshot_for_domain_v1(
            CreateOnlyArtifactFile::create(&target).unwrap(),
            &registry.snapshot(),
            &domain,
        )
        .unwrap();

        assert_eq!(
            read_dataset_withdrawal_snapshot_for_domain_v1(
                File::open(&target).unwrap(),
                receipt,
                &rotated,
            ),
            Err(ArtifactStorageError::InvalidReceipt)
        );
        let reopened = read_dataset_withdrawal_snapshot_for_domain_v1(
            File::open(&target).unwrap(),
            receipt,
            &domain,
        )
        .unwrap();
        assert_eq!(reopened.snapshot(), registry.snapshot());
        let _ = std::fs::remove_file(target);
    }

    #[test]
    fn lifecycle_snapshot_reopens_after_historical_actor_expiry() {
        let producer_id = id("producer");
        let artifact_id = id("artifact");
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
                    artifact_id,
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
            .unwrap();
        let snapshot = journal.snapshot();
        let target = path("lifecycle");
        let receipt = write_artifact_lifecycle_snapshot_v2(
            CreateOnlyArtifactFile::create(&target).unwrap(),
            &snapshot,
            digest("binding"),
        )
        .unwrap();
        let reopened =
            read_artifact_lifecycle_snapshot_v2(File::open(&target).unwrap(), receipt, 101).unwrap();
        assert_eq!(reopened.snapshot(), snapshot);
        let _ = std::fs::remove_file(target);
    }
}
