//! Durable create-only snapshots for withdrawal and lifecycle state.
//!
//! These adapters mirror the V1 artifact registry storage boundary: callers
//! provide already-authorized file handles and retain receipts independently.
//! Reopening always replays the canonical state machine; no file content grants
//! authority, selection, activation, promotion, or release.

use std::fs::File;
use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::LogicalSequence;
use codex_hepta_types::StableId;

use crate::ArtifactLifecycleEventV1;
use crate::ArtifactLifecycleJournalRecordV2;
use crate::ArtifactLifecycleJournalSnapshotV2;
use crate::ArtifactLifecycleJournalV2;
use crate::ArtifactLifecycleStateV1;
use crate::ArtifactStorageError;
use crate::CreateOnlyArtifactFile;
use crate::DatasetWithdrawalNoticeV1;
use crate::DatasetWithdrawalRecordV1;
use crate::DatasetWithdrawalRegistry;
use crate::DatasetWithdrawalRegistryBindingV1;
use crate::DatasetWithdrawalRegistrySnapshotV1;
use crate::LifecycleActorEvidenceV2;
use crate::LifecycleActorRoleV2;
use crate::MAX_LIFECYCLE_RECORDS;
use crate::MAX_WITHDRAWAL_RECORDS;
use crate::storage::read_bounded;
use crate::storage::write_new;

const MAX_AUX_SNAPSHOT: usize = 16 * 1024 * 1024;
const WITHDRAWAL_MAGIC: &str = "HEPTAW01";
const LIFECYCLE_MAGIC: &str = "HEPTAL02";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DatasetWithdrawalSnapshotReceiptV1 {
    pub binding: Digest32,
    pub registry_binding_digest: Digest32,
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

pub fn write_dataset_withdrawal_snapshot(
    file: CreateOnlyArtifactFile,
    registry: &DatasetWithdrawalRegistry,
    binding: Digest32,
) -> Result<DatasetWithdrawalSnapshotReceiptV1, ArtifactStorageError> {
    if binding.is_zero() {
        return Err(ArtifactStorageError::InvalidBinding);
    }
    let snapshot = registry.snapshot();
    let bytes = encode_withdrawal_snapshot(&snapshot, binding)?;
    let receipt = DatasetWithdrawalSnapshotReceiptV1 {
        binding,
        registry_binding_digest: snapshot.binding.digest(),
        head_digest: snapshot.head_digest,
        file_digest: Digest32::of_bytes(&bytes),
        records: snapshot.records().len(),
        encoded_bytes: bytes.len(),
    };
    write_new(file, &bytes)?;
    Ok(receipt)
}

pub fn read_dataset_withdrawal_snapshot(
    file: File,
    expected: DatasetWithdrawalSnapshotReceiptV1,
) -> Result<DatasetWithdrawalRegistry, ArtifactStorageError> {
    validate_withdrawal_receipt(expected)?;
    let bytes = read_bounded(
        file,
        MAX_AUX_SNAPSHOT,
        expected.encoded_bytes as u64,
        ArtifactStorageError::Corrupt,
    )?;
    if bytes.len() != expected.encoded_bytes || Digest32::of_bytes(&bytes) != expected.file_digest {
        return Err(ArtifactStorageError::Corrupt);
    }
    let snapshot = decode_withdrawal_snapshot(&bytes, expected.binding)?;
    if snapshot.binding.digest() != expected.registry_binding_digest
        || snapshot.head_digest != expected.head_digest
        || snapshot.records().len() != expected.records
    {
        return Err(ArtifactStorageError::Corrupt);
    }
    let registry =
        DatasetWithdrawalRegistry::from_snapshot(snapshot).map_err(|_| ArtifactStorageError::Semantic)?;
    if encode_withdrawal_snapshot(&registry.snapshot(), expected.binding)? != bytes {
        return Err(ArtifactStorageError::Corrupt);
    }
    Ok(registry)
}

pub fn write_artifact_lifecycle_snapshot(
    file: CreateOnlyArtifactFile,
    journal: &ArtifactLifecycleJournalV2,
    binding: Digest32,
) -> Result<ArtifactLifecycleSnapshotReceiptV2, ArtifactStorageError> {
    if binding.is_zero() {
        return Err(ArtifactStorageError::InvalidBinding);
    }
    let snapshot = journal.snapshot();
    let bytes = encode_lifecycle_snapshot(&snapshot, binding)?;
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

pub fn read_artifact_lifecycle_snapshot(
    file: File,
    expected: ArtifactLifecycleSnapshotReceiptV2,
    now: u64,
) -> Result<ArtifactLifecycleJournalV2, ArtifactStorageError> {
    validate_lifecycle_receipt(expected)?;
    let bytes = read_bounded(
        file,
        MAX_AUX_SNAPSHOT,
        expected.encoded_bytes as u64,
        ArtifactStorageError::Corrupt,
    )?;
    if bytes.len() != expected.encoded_bytes || Digest32::of_bytes(&bytes) != expected.file_digest {
        return Err(ArtifactStorageError::Corrupt);
    }
    let snapshot = decode_lifecycle_snapshot(&bytes, expected.binding)?;
    if snapshot.head_digest != expected.head_digest || snapshot.records.len() != expected.records {
        return Err(ArtifactStorageError::Corrupt);
    }
    let journal = ArtifactLifecycleJournalV2::from_snapshot(snapshot, now)
        .map_err(|_| ArtifactStorageError::Semantic)?;
    if encode_lifecycle_snapshot(&journal.snapshot(), expected.binding)? != bytes {
        return Err(ArtifactStorageError::Corrupt);
    }
    Ok(journal)
}

fn validate_withdrawal_receipt(
    expected: DatasetWithdrawalSnapshotReceiptV1,
) -> Result<(), ArtifactStorageError> {
    if expected.binding.is_zero()
        || expected.registry_binding_digest.is_zero()
        || expected.file_digest.is_zero()
        || expected.records > MAX_WITHDRAWAL_RECORDS
        || expected.encoded_bytes == 0
        || expected.encoded_bytes > MAX_AUX_SNAPSHOT
        || (expected.records == 0) != expected.head_digest.is_zero()
    {
        return Err(ArtifactStorageError::InvalidReceipt);
    }
    Ok(())
}

fn validate_lifecycle_receipt(
    expected: ArtifactLifecycleSnapshotReceiptV2,
) -> Result<(), ArtifactStorageError> {
    if expected.binding.is_zero()
        || expected.file_digest.is_zero()
        || expected.records > MAX_LIFECYCLE_RECORDS
        || expected.encoded_bytes == 0
        || expected.encoded_bytes > MAX_AUX_SNAPSHOT
        || (expected.records == 0) != expected.head_digest.is_zero()
    {
        return Err(ArtifactStorageError::InvalidReceipt);
    }
    Ok(())
}

fn encode_withdrawal_snapshot(
    snapshot: &DatasetWithdrawalRegistrySnapshotV1,
    binding: Digest32,
) -> Result<Vec<u8>, ArtifactStorageError> {
    if snapshot.records().len() > MAX_WITHDRAWAL_RECORDS {
        return Err(ArtifactStorageError::Capacity);
    }
    snapshot
        .binding
        .validate()
        .map_err(|_| ArtifactStorageError::Semantic)?;
    let mut text = format!(
        "{WITHDRAWAL_MAGIC}\n{binding}\n{}\n{}\n{}\n{}\n{}\n",
        snapshot.binding.registry_id,
        snapshot.binding.scope_digest,
        snapshot.binding.authority_id,
        snapshot.records().len(),
        snapshot.head_digest,
    );
    for record in snapshot.records() {
        let notice = &record.notice;
        text.push_str(&format!(
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
        ));
    }
    if text.len() > MAX_AUX_SNAPSHOT {
        return Err(ArtifactStorageError::Capacity);
    }
    Ok(text.into_bytes())
}

fn decode_withdrawal_snapshot(
    bytes: &[u8],
    expected_binding: Digest32,
) -> Result<DatasetWithdrawalRegistrySnapshotV1, ArtifactStorageError> {
    let text = std::str::from_utf8(bytes).map_err(|_| ArtifactStorageError::Corrupt)?;
    let mut lines = text.lines();
    if lines.next() != Some(WITHDRAWAL_MAGIC)
        || lines.next() != Some(expected_binding.to_string().as_str())
    {
        return Err(ArtifactStorageError::Corrupt);
    }
    let registry_id = parse_id(lines.next())?;
    let scope_digest = parse_digest(lines.next())?;
    let authority_id = parse_id(lines.next())?;
    let count = parse_usize(lines.next())?;
    let head_digest = parse_digest(lines.next())?;
    if count > MAX_WITHDRAWAL_RECORDS {
        return Err(ArtifactStorageError::Capacity);
    }
    let mut records = Vec::with_capacity(count);
    for line in lines {
        if records.len() >= count || line.len() > 2_048 {
            return Err(ArtifactStorageError::Corrupt);
        }
        let fields: Vec<_> = line.split('|').collect();
        let [
            "W",
            sequence,
            predecessor,
            event_digest,
            chain_digest,
            notice_id,
            dataset_digest,
            source_tombstone_digest,
            notice_authority_id,
            credential_chain_digest,
            signing_key_digest,
            authority_epoch,
            issued_at,
        ] = fields.as_slice()
        else {
            return Err(ArtifactStorageError::Corrupt);
        };
        records.push(DatasetWithdrawalRecordV1 {
            sequence: LogicalSequence::new(parse_u64_value(sequence)?)
                .map_err(|_| ArtifactStorageError::Corrupt)?,
            predecessor_chain_digest: parse_digest_value(predecessor)?,
            event_digest: parse_digest_value(event_digest)?,
            chain_digest: parse_digest_value(chain_digest)?,
            notice: DatasetWithdrawalNoticeV1 {
                notice_id: parse_id_value(notice_id)?,
                dataset_digest: parse_digest_value(dataset_digest)?,
                source_tombstone_digest: parse_digest_value(source_tombstone_digest)?,
                authority_id: parse_id_value(notice_authority_id)?,
                credential_chain_digest: parse_digest_value(credential_chain_digest)?,
                signing_key_digest: parse_digest_value(signing_key_digest)?,
                authority_epoch: parse_u64_value(authority_epoch)?,
                issued_at: parse_u64_value(issued_at)?,
            },
        });
    }
    if records.len() != count {
        return Err(ArtifactStorageError::Corrupt);
    }
    Ok(DatasetWithdrawalRegistrySnapshotV1 {
        binding: DatasetWithdrawalRegistryBindingV1 {
            registry_id,
            scope_digest,
            authority_id,
        },
        records,
        head_digest,
    })
}

fn encode_lifecycle_snapshot(
    snapshot: &ArtifactLifecycleJournalSnapshotV2,
    binding: Digest32,
) -> Result<Vec<u8>, ArtifactStorageError> {
    if snapshot.records.len() > MAX_LIFECYCLE_RECORDS {
        return Err(ArtifactStorageError::Capacity);
    }
    let mut text = format!(
        "{LIFECYCLE_MAGIC}\n{binding}\n{}\n{}\n",
        snapshot.records.len(),
        snapshot.head_digest,
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
        ));
    }
    if text.len() > MAX_AUX_SNAPSHOT {
        return Err(ArtifactStorageError::Capacity);
    }
    Ok(text.into_bytes())
}

fn decode_lifecycle_snapshot(
    bytes: &[u8],
    expected_binding: Digest32,
) -> Result<ArtifactLifecycleJournalSnapshotV2, ArtifactStorageError> {
    let text = std::str::from_utf8(bytes).map_err(|_| ArtifactStorageError::Corrupt)?;
    let mut lines = text.lines();
    if lines.next() != Some(LIFECYCLE_MAGIC)
        || lines.next() != Some(expected_binding.to_string().as_str())
    {
        return Err(ArtifactStorageError::Corrupt);
    }
    let count = parse_usize(lines.next())?;
    let head_digest = parse_digest(lines.next())?;
    if count > MAX_LIFECYCLE_RECORDS {
        return Err(ArtifactStorageError::Capacity);
    }
    let mut records = Vec::with_capacity(count);
    for line in lines {
        if records.len() >= count || line.len() > 4_096 {
            return Err(ArtifactStorageError::Corrupt);
        }
        let fields: Vec<_> = line.split('|').collect();
        let [
            "L",
            sequence,
            predecessor,
            event_digest,
            chain_digest,
            producer_id,
            actor_id,
            actor_credential_digest,
            actor_role,
            actor_authority_epoch,
            actor_verified_at,
            actor_expires_at,
            event_id,
            artifact_id,
            prior_state,
            next_state,
            event_actor_id,
            event_actor_credential_digest,
            evidence_digest,
            event_authority_epoch,
            occurred_at,
        ] = fields.as_slice()
        else {
            return Err(ArtifactStorageError::Corrupt);
        };
        records.push(ArtifactLifecycleJournalRecordV2 {
            sequence: parse_u64_value(sequence)?,
            predecessor_head_digest: parse_digest_value(predecessor)?,
            event_digest: parse_digest_value(event_digest)?,
            chain_digest: parse_digest_value(chain_digest)?,
            producer_id: parse_id_value(producer_id)?,
            actor: LifecycleActorEvidenceV2 {
                actor_id: parse_id_value(actor_id)?,
                credential_digest: parse_digest_value(actor_credential_digest)?,
                role: parse_role(parse_u8_value(actor_role)?)?,
                authority_epoch: parse_u64_value(actor_authority_epoch)?,
                verified_at: parse_u64_value(actor_verified_at)?,
                expires_at: parse_u64_value(actor_expires_at)?,
            },
            event: ArtifactLifecycleEventV1 {
                event_id: parse_id_value(event_id)?,
                artifact_id: parse_id_value(artifact_id)?,
                prior_state: parse_state(parse_u8_value(prior_state)?)?,
                next_state: parse_state(parse_u8_value(next_state)?)?,
                actor_id: parse_id_value(event_actor_id)?,
                actor_credential_digest: parse_digest_value(event_actor_credential_digest)?,
                evidence_digest: parse_digest_value(evidence_digest)?,
                authority_epoch: parse_u64_value(event_authority_epoch)?,
                occurred_at: parse_u64_value(occurred_at)?,
            },
        });
    }
    if records.len() != count {
        return Err(ArtifactStorageError::Corrupt);
    }
    Ok(ArtifactLifecycleJournalSnapshotV2 {
        records,
        head_digest,
    })
}

fn parse_id(value: Option<&str>) -> Result<StableId, ArtifactStorageError> {
    parse_id_value(value.ok_or(ArtifactStorageError::Corrupt)?)
}

fn parse_id_value(value: &str) -> Result<StableId, ArtifactStorageError> {
    StableId::new(value.to_owned()).map_err(|_| ArtifactStorageError::Corrupt)
}

fn parse_digest(value: Option<&str>) -> Result<Digest32, ArtifactStorageError> {
    parse_digest_value(value.ok_or(ArtifactStorageError::Corrupt)?)
}

fn parse_digest_value(value: &str) -> Result<Digest32, ArtifactStorageError> {
    Digest32::from_str(value).map_err(|_| ArtifactStorageError::Corrupt)
}

fn parse_usize(value: Option<&str>) -> Result<usize, ArtifactStorageError> {
    value
        .ok_or(ArtifactStorageError::Corrupt)?
        .parse::<usize>()
        .map_err(|_| ArtifactStorageError::Corrupt)
}

fn parse_u64_value(value: &str) -> Result<u64, ArtifactStorageError> {
    value.parse::<u64>().map_err(|_| ArtifactStorageError::Corrupt)
}

fn parse_u8_value(value: &str) -> Result<u8, ArtifactStorageError> {
    value.parse::<u8>().map_err(|_| ArtifactStorageError::Corrupt)
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

fn parse_role(tag: u8) -> Result<LifecycleActorRoleV2, ArtifactStorageError> {
    match tag {
        0 => Ok(LifecycleActorRoleV2::Producer),
        1 => Ok(LifecycleActorRoleV2::Evaluator),
        2 => Ok(LifecycleActorRoleV2::ShadowOperator),
        3 => Ok(LifecycleActorRoleV2::CanaryOperator),
        4 => Ok(LifecycleActorRoleV2::HumanOperator),
        5 => Ok(LifecycleActorRoleV2::Selector),
        6 => Ok(LifecycleActorRoleV2::QuarantineAuthority),
        7 => Ok(LifecycleActorRoleV2::RevocationAuthority),
        8 => Ok(LifecycleActorRoleV2::RetirementAuthority),
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

fn parse_state(tag: u8) -> Result<ArtifactLifecycleStateV1, ArtifactStorageError> {
    match tag {
        0 => Ok(ArtifactLifecycleStateV1::Proposed),
        1 => Ok(ArtifactLifecycleStateV1::Trained),
        2 => Ok(ArtifactLifecycleStateV1::Evaluated),
        3 => Ok(ArtifactLifecycleStateV1::Shadow),
        4 => Ok(ArtifactLifecycleStateV1::Canary),
        5 => Ok(ArtifactLifecycleStateV1::OperatorAccepted),
        6 => Ok(ArtifactLifecycleStateV1::Selected),
        7 => Ok(ArtifactLifecycleStateV1::Quarantined),
        8 => Ok(ArtifactLifecycleStateV1::Revoked),
        9 => Ok(ArtifactLifecycleStateV1::Retired),
        _ => Err(ArtifactStorageError::Corrupt),
    }
}

#[cfg(test)]
mod tests {
    use std::fs::File;
    use std::path::PathBuf;
    use std::sync::atomic::AtomicU64;
    use std::sync::atomic::Ordering;

    use super::*;

    static NEXT: AtomicU64 = AtomicU64::new(0);

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("valid test id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    struct TestFile(PathBuf);

    impl TestFile {
        fn new(label: &str) -> Self {
            let serial = NEXT.fetch_add(1, Ordering::Relaxed);
            let path = std::env::temp_dir().join(format!(
                "hepta-artifact-aux-{label}-{}-{serial}",
                std::process::id()
            ));
            Self(path)
        }

        fn create(&self) -> CreateOnlyArtifactFile {
            CreateOnlyArtifactFile::create(&self.0).expect("create-only file")
        }

        fn open(&self) -> File {
            File::open(&self.0).expect("open durable file")
        }
    }

    impl Drop for TestFile {
        fn drop(&mut self) {
            let _ = std::fs::remove_file(&self.0);
        }
    }

    fn withdrawal_registry() -> DatasetWithdrawalRegistry {
        DatasetWithdrawalRegistry::new(DatasetWithdrawalRegistryBindingV1 {
            registry_id: id("withdrawal-registry"),
            scope_digest: digest("tenant-a"),
            authority_id: id("dataset-owner"),
        })
        .expect("valid withdrawal registry")
    }

    #[test]
    fn durable_withdrawal_snapshot_roundtrips_bound_scope() {
        let dataset = digest("dataset");
        let mut registry = withdrawal_registry();
        registry
            .append(DatasetWithdrawalNoticeV1 {
                notice_id: id("notice-1"),
                dataset_digest: dataset,
                source_tombstone_digest: digest("tombstone"),
                authority_id: id("dataset-owner"),
                credential_chain_digest: digest("credential"),
                signing_key_digest: digest("key"),
                authority_epoch: 1,
                issued_at: 20,
            })
            .expect("withdrawal append");
        let file = TestFile::new("withdrawal");
        let store_binding = digest("store-binding");
        let receipt =
            write_dataset_withdrawal_snapshot(file.create(), &registry, store_binding)
                .expect("write withdrawal snapshot");
        let reopened = read_dataset_withdrawal_snapshot(file.open(), receipt)
            .expect("read withdrawal snapshot");
        assert_eq!(reopened.snapshot(), registry.snapshot());
        assert_eq!(reopened.binding_digest(), registry.binding_digest());
    }

    #[test]
    fn durable_lifecycle_snapshot_reopens_after_actor_expiry() {
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
            .expect("lifecycle append");
        let file = TestFile::new("lifecycle");
        let receipt =
            write_artifact_lifecycle_snapshot(file.create(), &journal, digest("store-binding"))
                .expect("write lifecycle snapshot");
        let reopened = read_artifact_lifecycle_snapshot(file.open(), receipt, 101)
            .expect("expired historical actor does not block durable recovery");
        assert_eq!(reopened.snapshot(), journal.snapshot());
    }
}
