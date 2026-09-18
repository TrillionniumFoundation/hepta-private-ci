//! Create-only durable snapshots for withdrawal and lifecycle sidecar state.
//!
//! These formats provide the same reopen proof shape as the stable V1 registry:
//! exact canonical bytes, an independently retained receipt, bounded history and
//! semantic replay on read. They do not discover the newest generation or grant
//! selection/activation authority.

use std::fs::File;

use codex_hepta_types::{Digest32, StableId};

use crate::storage::{read_bounded, write_new};
use crate::{
    ArtifactLifecycleEventV1, ArtifactLifecycleJournalRecordV2,
    ArtifactLifecycleJournalSnapshotV2, ArtifactLifecycleJournalV2, ArtifactLifecycleStateV1,
    ArtifactStorageError, CreateOnlyArtifactFile, DatasetWithdrawalNoticeV1,
    DatasetWithdrawalRegistry, LifecycleActorEvidenceV2, LifecycleActorRoleV2,
    WithdrawalRegistryBindingV1,
};

const AUX_MAX_BYTES: usize = 8 * 1024 * 1024;
const WITHDRAWAL_MAGIC: &str = "HEPTAW01";
const LIFECYCLE_MAGIC: &str = "HEPTAL02";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct WithdrawalRegistrySnapshotReceipt {
    pub storage_binding: Digest32,
    pub registry_binding_digest: Digest32,
    pub head_digest: Digest32,
    pub file_digest: Digest32,
    pub records: usize,
    pub encoded_bytes: usize,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LifecycleJournalSnapshotReceipt {
    pub storage_binding: Digest32,
    pub head_digest: Digest32,
    pub file_digest: Digest32,
    pub records: usize,
    pub encoded_bytes: usize,
}

pub fn write_withdrawal_registry_snapshot(
    file: CreateOnlyArtifactFile,
    registry: &DatasetWithdrawalRegistry,
    storage_binding: Digest32,
) -> Result<WithdrawalRegistrySnapshotReceipt, ArtifactStorageError> {
    if storage_binding.is_zero() {
        return Err(ArtifactStorageError::InvalidBinding);
    }
    let scoped = registry.binding().ok_or(ArtifactStorageError::Semantic)?;
    let bytes = encode_withdrawal_registry(registry, storage_binding)?;
    let snapshot = registry.snapshot();
    let receipt = WithdrawalRegistrySnapshotReceipt {
        storage_binding,
        registry_binding_digest: scoped.binding_digest(),
        head_digest: snapshot.head_digest,
        file_digest: Digest32::of_bytes(&bytes),
        records: snapshot.records().len(),
        encoded_bytes: bytes.len(),
    };
    write_new(file, &bytes)?;
    Ok(receipt)
}

pub fn read_withdrawal_registry_snapshot(
    file: File,
    expected: WithdrawalRegistrySnapshotReceipt,
) -> Result<DatasetWithdrawalRegistry, ArtifactStorageError> {
    validate_withdrawal_receipt(expected)?;
    let bytes = read_bounded(
        file,
        AUX_MAX_BYTES,
        expected.encoded_bytes as u64,
        ArtifactStorageError::Corrupt,
    )?;
    if bytes.len() != expected.encoded_bytes || Digest32::of_bytes(&bytes) != expected.file_digest {
        return Err(ArtifactStorageError::Corrupt);
    }
    let text = std::str::from_utf8(&bytes).map_err(|_| ArtifactStorageError::Corrupt)?;
    let mut lines = text.lines();
    if lines.next() != Some(WITHDRAWAL_MAGIC)
        || lines.next() != Some(expected.storage_binding.to_string().as_str())
    {
        return Err(ArtifactStorageError::Corrupt);
    }
    let registry_id = parse_id(lines.next().ok_or(ArtifactStorageError::Corrupt)?)?;
    let scope_digest = parse_digest(lines.next().ok_or(ArtifactStorageError::Corrupt)?)?;
    let binding =
        WithdrawalRegistryBindingV1::new(registry_id, scope_digest).map_err(|_| ArtifactStorageError::Semantic)?;
    if binding.binding_digest() != expected.registry_binding_digest {
        return Err(ArtifactStorageError::Corrupt);
    }
    let count = parse_usize(lines.next().ok_or(ArtifactStorageError::Corrupt)?)?;
    if count != expected.records || count > crate::MAX_DURABLE_HISTORY_RECORDS {
        return Err(ArtifactStorageError::Corrupt);
    }
    let mut registry =
        DatasetWithdrawalRegistry::new_scoped(binding).map_err(|_| ArtifactStorageError::Semantic)?;
    for _ in 0..count {
        let line = lines.next().ok_or(ArtifactStorageError::Corrupt)?;
        if line.len() > 2048 {
            return Err(ArtifactStorageError::Corrupt);
        }
        registry
            .append(decode_withdrawal_notice(line)?)
            .map_err(|_| ArtifactStorageError::Semantic)?;
    }
    if lines.next().is_some()
        || registry.snapshot().head_digest != expected.head_digest
        || encode_withdrawal_registry(&registry, expected.storage_binding)? != bytes
    {
        return Err(ArtifactStorageError::Corrupt);
    }
    Ok(registry)
}

pub fn write_lifecycle_journal_snapshot(
    file: CreateOnlyArtifactFile,
    journal: &ArtifactLifecycleJournalV2,
    storage_binding: Digest32,
) -> Result<LifecycleJournalSnapshotReceipt, ArtifactStorageError> {
    if storage_binding.is_zero() {
        return Err(ArtifactStorageError::InvalidBinding);
    }
    let bytes = encode_lifecycle_journal(journal, storage_binding)?;
    let receipt = LifecycleJournalSnapshotReceipt {
        storage_binding,
        head_digest: journal.head_digest(),
        file_digest: Digest32::of_bytes(&bytes),
        records: journal.records().len(),
        encoded_bytes: bytes.len(),
    };
    write_new(file, &bytes)?;
    Ok(receipt)
}

pub fn read_lifecycle_journal_snapshot(
    file: File,
    expected: LifecycleJournalSnapshotReceipt,
    now: u64,
) -> Result<ArtifactLifecycleJournalV2, ArtifactStorageError> {
    validate_lifecycle_receipt(expected)?;
    let bytes = read_bounded(
        file,
        AUX_MAX_BYTES,
        expected.encoded_bytes as u64,
        ArtifactStorageError::Corrupt,
    )?;
    if bytes.len() != expected.encoded_bytes || Digest32::of_bytes(&bytes) != expected.file_digest {
        return Err(ArtifactStorageError::Corrupt);
    }
    let text = std::str::from_utf8(&bytes).map_err(|_| ArtifactStorageError::Corrupt)?;
    let mut lines = text.lines();
    if lines.next() != Some(LIFECYCLE_MAGIC)
        || lines.next() != Some(expected.storage_binding.to_string().as_str())
    {
        return Err(ArtifactStorageError::Corrupt);
    }
    let count = parse_usize(lines.next().ok_or(ArtifactStorageError::Corrupt)?)?;
    let encoded_head = parse_digest(lines.next().ok_or(ArtifactStorageError::Corrupt)?)?;
    if count != expected.records
        || count > crate::MAX_DURABLE_HISTORY_RECORDS
        || encoded_head != expected.head_digest
    {
        return Err(ArtifactStorageError::Corrupt);
    }
    let mut records = Vec::with_capacity(count);
    for _ in 0..count {
        let line = lines.next().ok_or(ArtifactStorageError::Corrupt)?;
        if line.len() > 4096 {
            return Err(ArtifactStorageError::Corrupt);
        }
        records.push(decode_lifecycle_record(line)?);
    }
    if lines.next().is_some() {
        return Err(ArtifactStorageError::Corrupt);
    }
    let journal = ArtifactLifecycleJournalV2::from_snapshot(
        ArtifactLifecycleJournalSnapshotV2 {
            records,
            head_digest: expected.head_digest,
        },
        now,
    )
    .map_err(|_| ArtifactStorageError::Semantic)?;
    if encode_lifecycle_journal(&journal, expected.storage_binding)? != bytes {
        return Err(ArtifactStorageError::Corrupt);
    }
    Ok(journal)
}

fn validate_withdrawal_receipt(
    receipt: WithdrawalRegistrySnapshotReceipt,
) -> Result<(), ArtifactStorageError> {
    if receipt.storage_binding.is_zero()
        || receipt.registry_binding_digest.is_zero()
        || receipt.file_digest.is_zero()
        || receipt.records > crate::MAX_DURABLE_HISTORY_RECORDS
        || receipt.encoded_bytes == 0
        || receipt.encoded_bytes > AUX_MAX_BYTES
        || (receipt.records == 0) != receipt.head_digest.is_zero()
    {
        return Err(ArtifactStorageError::InvalidReceipt);
    }
    Ok(())
}

fn validate_lifecycle_receipt(
    receipt: LifecycleJournalSnapshotReceipt,
) -> Result<(), ArtifactStorageError> {
    if receipt.storage_binding.is_zero()
        || receipt.file_digest.is_zero()
        || receipt.records > crate::MAX_DURABLE_HISTORY_RECORDS
        || receipt.encoded_bytes == 0
        || receipt.encoded_bytes > AUX_MAX_BYTES
        || (receipt.records == 0) != receipt.head_digest.is_zero()
    {
        return Err(ArtifactStorageError::InvalidReceipt);
    }
    Ok(())
}

fn encode_withdrawal_registry(
    registry: &DatasetWithdrawalRegistry,
    storage_binding: Digest32,
) -> Result<Vec<u8>, ArtifactStorageError> {
    let scoped = registry.binding().ok_or(ArtifactStorageError::Semantic)?;
    let snapshot = registry.snapshot();
    if snapshot.records().len() > crate::MAX_DURABLE_HISTORY_RECORDS {
        return Err(ArtifactStorageError::Capacity);
    }
    let mut text = format!(
        "{WITHDRAWAL_MAGIC}\n{storage_binding}\n{}\n{}\n{}\n",
        scoped.registry_id,
        scoped.scope_digest,
        snapshot.records().len()
    );
    for record in snapshot.records() {
        let notice = &record.notice;
        text.push_str(&format!(
            "W|{}|{}|{}|{}|{}|{}|{}|{}\n",
            notice.notice_id,
            notice.dataset_digest,
            notice.source_tombstone_digest,
            notice.authority_id,
            notice.credential_chain_digest,
            notice.signing_key_digest,
            notice.authority_epoch,
            notice.issued_at
        ));
    }
    if text.len() > AUX_MAX_BYTES {
        return Err(ArtifactStorageError::Capacity);
    }
    Ok(text.into_bytes())
}

fn decode_withdrawal_notice(line: &str) -> Result<DatasetWithdrawalNoticeV1, ArtifactStorageError> {
    let fields: Vec<&str> = line.split('|').collect();
    let [
        "W",
        notice_id,
        dataset_digest,
        source_tombstone_digest,
        authority_id,
        credential_chain_digest,
        signing_key_digest,
        authority_epoch,
        issued_at,
    ] = fields.as_slice()
    else {
        return Err(ArtifactStorageError::Corrupt);
    };
    Ok(DatasetWithdrawalNoticeV1 {
        notice_id: parse_id(notice_id)?,
        dataset_digest: parse_digest(dataset_digest)?,
        source_tombstone_digest: parse_digest(source_tombstone_digest)?,
        authority_id: parse_id(authority_id)?,
        credential_chain_digest: parse_digest(credential_chain_digest)?,
        signing_key_digest: parse_digest(signing_key_digest)?,
        authority_epoch: parse_u64(authority_epoch)?,
        issued_at: parse_u64(issued_at)?,
    })
}

fn encode_lifecycle_journal(
    journal: &ArtifactLifecycleJournalV2,
    storage_binding: Digest32,
) -> Result<Vec<u8>, ArtifactStorageError> {
    if journal.records().len() > crate::MAX_DURABLE_HISTORY_RECORDS {
        return Err(ArtifactStorageError::Capacity);
    }
    let mut text = format!(
        "{LIFECYCLE_MAGIC}\n{storage_binding}\n{}\n{}\n",
        journal.records().len(),
        journal.head_digest()
    );
    for record in journal.records() {
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
            event.occurred_at
        ));
    }
    if text.len() > AUX_MAX_BYTES {
        return Err(ArtifactStorageError::Capacity);
    }
    Ok(text.into_bytes())
}

fn decode_lifecycle_record(
    line: &str,
) -> Result<ArtifactLifecycleJournalRecordV2, ArtifactStorageError> {
    let fields: Vec<&str> = line.split('|').collect();
    let [
        "L",
        sequence,
        predecessor_head_digest,
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
        event_evidence_digest,
        event_authority_epoch,
        occurred_at,
    ] = fields.as_slice()
    else {
        return Err(ArtifactStorageError::Corrupt);
    };
    Ok(ArtifactLifecycleJournalRecordV2 {
        sequence: parse_u64(sequence)?,
        predecessor_head_digest: parse_digest(predecessor_head_digest)?,
        event_digest: parse_digest(event_digest)?,
        chain_digest: parse_digest(chain_digest)?,
        producer_id: parse_id(producer_id)?,
        actor: LifecycleActorEvidenceV2 {
            actor_id: parse_id(actor_id)?,
            credential_digest: parse_digest(actor_credential_digest)?,
            role: parse_role(actor_role)?,
            authority_epoch: parse_u64(actor_authority_epoch)?,
            verified_at: parse_u64(actor_verified_at)?,
            expires_at: parse_u64(actor_expires_at)?,
        },
        event: ArtifactLifecycleEventV1 {
            event_id: parse_id(event_id)?,
            artifact_id: parse_id(artifact_id)?,
            prior_state: parse_state(prior_state)?,
            next_state: parse_state(next_state)?,
            actor_id: parse_id(event_actor_id)?,
            actor_credential_digest: parse_digest(event_actor_credential_digest)?,
            evidence_digest: parse_digest(event_evidence_digest)?,
            authority_epoch: parse_u64(event_authority_epoch)?,
            occurred_at: parse_u64(occurred_at)?,
        },
    })
}

const fn role_tag(role: LifecycleActorRoleV2) -> &'static str {
    match role {
        LifecycleActorRoleV2::Producer => "producer",
        LifecycleActorRoleV2::Evaluator => "evaluator",
        LifecycleActorRoleV2::ShadowOperator => "shadow",
        LifecycleActorRoleV2::CanaryOperator => "canary",
        LifecycleActorRoleV2::HumanOperator => "human",
        LifecycleActorRoleV2::Selector => "selector",
        LifecycleActorRoleV2::QuarantineAuthority => "quarantine",
        LifecycleActorRoleV2::RevocationAuthority => "revocation",
        LifecycleActorRoleV2::RetirementAuthority => "retirement",
    }
}

fn parse_role(value: &str) -> Result<LifecycleActorRoleV2, ArtifactStorageError> {
    match value {
        "producer" => Ok(LifecycleActorRoleV2::Producer),
        "evaluator" => Ok(LifecycleActorRoleV2::Evaluator),
        "shadow" => Ok(LifecycleActorRoleV2::ShadowOperator),
        "canary" => Ok(LifecycleActorRoleV2::CanaryOperator),
        "human" => Ok(LifecycleActorRoleV2::HumanOperator),
        "selector" => Ok(LifecycleActorRoleV2::Selector),
        "quarantine" => Ok(LifecycleActorRoleV2::QuarantineAuthority),
        "revocation" => Ok(LifecycleActorRoleV2::RevocationAuthority),
        "retirement" => Ok(LifecycleActorRoleV2::RetirementAuthority),
        _ => Err(ArtifactStorageError::Corrupt),
    }
}

const fn state_tag(state: ArtifactLifecycleStateV1) -> &'static str {
    match state {
        ArtifactLifecycleStateV1::Proposed => "proposed",
        ArtifactLifecycleStateV1::Trained => "trained",
        ArtifactLifecycleStateV1::Evaluated => "evaluated",
        ArtifactLifecycleStateV1::Shadow => "shadow",
        ArtifactLifecycleStateV1::Canary => "canary",
        ArtifactLifecycleStateV1::OperatorAccepted => "operator-accepted",
        ArtifactLifecycleStateV1::Selected => "selected",
        ArtifactLifecycleStateV1::Quarantined => "quarantined",
        ArtifactLifecycleStateV1::Revoked => "revoked",
        ArtifactLifecycleStateV1::Retired => "retired",
    }
}

fn parse_state(value: &str) -> Result<ArtifactLifecycleStateV1, ArtifactStorageError> {
    match value {
        "proposed" => Ok(ArtifactLifecycleStateV1::Proposed),
        "trained" => Ok(ArtifactLifecycleStateV1::Trained),
        "evaluated" => Ok(ArtifactLifecycleStateV1::Evaluated),
        "shadow" => Ok(ArtifactLifecycleStateV1::Shadow),
        "canary" => Ok(ArtifactLifecycleStateV1::Canary),
        "operator-accepted" => Ok(ArtifactLifecycleStateV1::OperatorAccepted),
        "selected" => Ok(ArtifactLifecycleStateV1::Selected),
        "quarantined" => Ok(ArtifactLifecycleStateV1::Quarantined),
        "revoked" => Ok(ArtifactLifecycleStateV1::Revoked),
        "retired" => Ok(ArtifactLifecycleStateV1::Retired),
        _ => Err(ArtifactStorageError::Corrupt),
    }
}

fn parse_id(value: &str) -> Result<StableId, ArtifactStorageError> {
    StableId::new(value).map_err(|_| ArtifactStorageError::Corrupt)
}

fn parse_digest(value: &str) -> Result<Digest32, ArtifactStorageError> {
    value.parse().map_err(|_| ArtifactStorageError::Corrupt)
}

fn parse_u64(value: &str) -> Result<u64, ArtifactStorageError> {
    value.parse().map_err(|_| ArtifactStorageError::Corrupt)
}

fn parse_usize(value: &str) -> Result<usize, ArtifactStorageError> {
    value.parse().map_err(|_| ArtifactStorageError::Corrupt)
}

#[cfg(test)]
mod tests {
    use std::fs::{File, remove_file};
    use std::time::{SystemTime, UNIX_EPOCH};

    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn unique_path(label: &str) -> std::path::PathBuf {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock after epoch")
            .as_nanos();
        std::env::temp_dir().join(format!(
            "hepta-learning-artifacts-{label}-{}-{nanos}",
            std::process::id()
        ))
    }

    #[test]
    fn art_08_withdrawal_registry_reopens_from_create_only_snapshot() {
        let binding =
            WithdrawalRegistryBindingV1::new(id("withdrawal-registry"), digest("tenant-a"))
                .expect("binding");
        let mut registry = DatasetWithdrawalRegistry::new_scoped(binding).expect("registry");
        registry
            .append(DatasetWithdrawalNoticeV1 {
                notice_id: id("notice-1"),
                dataset_digest: digest("dataset"),
                source_tombstone_digest: digest("tombstone"),
                authority_id: id("authority"),
                credential_chain_digest: digest("credential"),
                signing_key_digest: digest("key"),
                authority_epoch: 1,
                issued_at: 20,
            })
            .expect("append");

        let path = unique_path("withdrawal");
        let receipt = write_withdrawal_registry_snapshot(
            CreateOnlyArtifactFile::create(&path).expect("create"),
            &registry,
            digest("storage-binding"),
        )
        .expect("write");
        let reopened = read_withdrawal_registry_snapshot(
            File::open(&path).expect("open"),
            receipt,
        )
        .expect("reopen");
        assert_eq!(reopened.snapshot(), registry.snapshot());
        remove_file(path).expect("remove");
    }

    #[test]
    fn art_08_lifecycle_snapshot_reopens_after_actor_expiry() {
        let producer = LifecycleActorEvidenceV2 {
            actor_id: id("producer"),
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
                &id("producer"),
                producer.clone(),
                ArtifactLifecycleEventV1 {
                    event_id: id("trained"),
                    artifact_id: id("artifact"),
                    prior_state: ArtifactLifecycleStateV1::Proposed,
                    next_state: ArtifactLifecycleStateV1::Trained,
                    actor_id: producer.actor_id.clone(),
                    actor_credential_digest: producer.credential_digest,
                    evidence_digest: digest("evidence"),
                    authority_epoch: producer.authority_epoch,
                    occurred_at: 20,
                },
                20,
            )
            .expect("append");

        let path = unique_path("lifecycle");
        let receipt = write_lifecycle_journal_snapshot(
            CreateOnlyArtifactFile::create(&path).expect("create"),
            &journal,
            digest("storage-binding"),
        )
        .expect("write");
        let reopened = read_lifecycle_journal_snapshot(
            File::open(&path).expect("open"),
            receipt,
            101,
        )
        .expect("historical replay survives expiry");
        assert_eq!(reopened.snapshot(), journal.snapshot());
        remove_file(path).expect("remove");
    }
}
