//! Canonical create-only durable snapshots for withdrawal and lifecycle state.
//!
//! These adapters use the same bounded, locked, create-only file capability as
//! the stable artifact registry. Recovery replays semantic records; it never
//! initializes missing history, repairs corrupt bytes, or substitutes an older
//! snapshot.

use std::fs::File;
use std::path::Path;
use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ArtifactLifecycleEventV1;
use crate::ArtifactLifecycleJournalV2;
use crate::ArtifactLifecycleStateV1;
use crate::ArtifactStorageError;
use crate::CreateOnlyArtifactFile;
use crate::DatasetWithdrawalNoticeV1;
use crate::DatasetWithdrawalRegistry;
use crate::DatasetWithdrawalScopeV1;
use crate::LifecycleActorEvidenceV2;
use crate::LifecycleActorRoleV2;
use crate::MAX_DURABLE_ARTIFACT_RECORDS;
use crate::storage::read_bounded;
use crate::storage::write_new;

const MAX_AUX_SNAPSHOT_BYTES: usize = 8 * 1024 * 1024;
const MAX_AUX_LINE_BYTES: usize = 4096;
const WITHDRAWAL_MAGIC: &str = "HEPTAW01";
const LIFECYCLE_MAGIC: &str = "HEPTAL02";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DatasetWithdrawalSnapshotReceiptV1 {
    pub binding: Digest32,
    pub scope_digest: Digest32,
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

pub fn write_dataset_withdrawal_snapshot_beneath(
    root: impl AsRef<Path>,
    relative: impl AsRef<Path>,
    registry: &DatasetWithdrawalRegistry,
    binding: Digest32,
) -> Result<DatasetWithdrawalSnapshotReceiptV1, ArtifactStorageError> {
    if binding.is_zero() {
        return Err(ArtifactStorageError::InvalidBinding);
    }
    let scope_digest = registry
        .scope_digest()
        .ok_or(ArtifactStorageError::Unscoped)?;
    let bytes = encode_withdrawal_snapshot(registry, binding)?;
    let receipt = DatasetWithdrawalSnapshotReceiptV1 {
        binding,
        scope_digest,
        head_digest: registry.head_digest(),
        file_digest: Digest32::of_bytes(&bytes),
        records: registry.snapshot().records().len(),
        encoded_bytes: bytes.len(),
    };
    write_new(
        CreateOnlyArtifactFile::create_beneath_trusted_root(root, relative)?,
        &bytes,
    )?;
    Ok(receipt)
}

pub fn write_dataset_withdrawal_snapshot(
    file: CreateOnlyArtifactFile,
    registry: &DatasetWithdrawalRegistry,
    binding: Digest32,
) -> Result<DatasetWithdrawalSnapshotReceiptV1, ArtifactStorageError> {
    if binding.is_zero() {
        return Err(ArtifactStorageError::InvalidBinding);
    }
    let scope_digest = registry
        .scope_digest()
        .ok_or(ArtifactStorageError::Unscoped)?;
    let bytes = encode_withdrawal_snapshot(registry, binding)?;
    let receipt = DatasetWithdrawalSnapshotReceiptV1 {
        binding,
        scope_digest,
        head_digest: registry.head_digest(),
        file_digest: Digest32::of_bytes(&bytes),
        records: registry.snapshot().records().len(),
        encoded_bytes: bytes.len(),
    };
    write_new(file, &bytes)?;
    Ok(receipt)
}

pub fn read_dataset_withdrawal_snapshot(
    file: File,
    expected: DatasetWithdrawalSnapshotReceiptV1,
) -> Result<DatasetWithdrawalRegistry, ArtifactStorageError> {
    if expected.binding.is_zero()
        || expected.scope_digest.is_zero()
        || expected.head_digest.is_zero()
        || expected.file_digest.is_zero()
        || expected.records > MAX_DURABLE_ARTIFACT_RECORDS
        || expected.encoded_bytes == 0
        || expected.encoded_bytes > MAX_AUX_SNAPSHOT_BYTES
    {
        return Err(ArtifactStorageError::InvalidReceipt);
    }
    let bytes = read_bounded(
        file,
        MAX_AUX_SNAPSHOT_BYTES,
        expected.encoded_bytes as u64,
        ArtifactStorageError::Corrupt,
    )?;
    if Digest32::of_bytes(&bytes) != expected.file_digest {
        return Err(ArtifactStorageError::Corrupt);
    }
    let registry = decode_withdrawal_snapshot(&bytes, expected.binding)?;
    if registry.scope_digest() != Some(expected.scope_digest) {
        return Err(ArtifactStorageError::ScopeMismatch);
    }
    if registry.snapshot().records().len() != expected.records
        || registry.head_digest() != expected.head_digest
        || encode_withdrawal_snapshot(&registry, expected.binding)? != bytes
    {
        return Err(ArtifactStorageError::Corrupt);
    }
    Ok(registry)
}

pub fn write_artifact_lifecycle_snapshot_beneath(
    root: impl AsRef<Path>,
    relative: impl AsRef<Path>,
    journal: &ArtifactLifecycleJournalV2,
    binding: Digest32,
) -> Result<ArtifactLifecycleSnapshotReceiptV2, ArtifactStorageError> {
    if binding.is_zero() {
        return Err(ArtifactStorageError::InvalidBinding);
    }
    let bytes = encode_lifecycle_snapshot(journal, binding)?;
    let receipt = ArtifactLifecycleSnapshotReceiptV2 {
        binding,
        head_digest: journal.head_digest(),
        file_digest: Digest32::of_bytes(&bytes),
        records: journal.records().len(),
        encoded_bytes: bytes.len(),
    };
    write_new(
        CreateOnlyArtifactFile::create_beneath_trusted_root(root, relative)?,
        &bytes,
    )?;
    Ok(receipt)
}

pub fn write_artifact_lifecycle_snapshot(
    file: CreateOnlyArtifactFile,
    journal: &ArtifactLifecycleJournalV2,
    binding: Digest32,
) -> Result<ArtifactLifecycleSnapshotReceiptV2, ArtifactStorageError> {
    if binding.is_zero() {
        return Err(ArtifactStorageError::InvalidBinding);
    }
    let bytes = encode_lifecycle_snapshot(journal, binding)?;
    let receipt = ArtifactLifecycleSnapshotReceiptV2 {
        binding,
        head_digest: journal.head_digest(),
        file_digest: Digest32::of_bytes(&bytes),
        records: journal.records().len(),
        encoded_bytes: bytes.len(),
    };
    write_new(file, &bytes)?;
    Ok(receipt)
}

pub fn read_artifact_lifecycle_snapshot(
    file: File,
    expected: ArtifactLifecycleSnapshotReceiptV2,
) -> Result<ArtifactLifecycleJournalV2, ArtifactStorageError> {
    if expected.binding.is_zero()
        || expected.file_digest.is_zero()
        || expected.records > MAX_DURABLE_ARTIFACT_RECORDS
        || expected.encoded_bytes == 0
        || expected.encoded_bytes > MAX_AUX_SNAPSHOT_BYTES
        || (expected.records == 0) != expected.head_digest.is_zero()
    {
        return Err(ArtifactStorageError::InvalidReceipt);
    }
    let bytes = read_bounded(
        file,
        MAX_AUX_SNAPSHOT_BYTES,
        expected.encoded_bytes as u64,
        ArtifactStorageError::Corrupt,
    )?;
    if Digest32::of_bytes(&bytes) != expected.file_digest {
        return Err(ArtifactStorageError::Corrupt);
    }
    let journal = decode_lifecycle_snapshot(&bytes, expected.binding)?;
    if journal.records().len() != expected.records
        || journal.head_digest() != expected.head_digest
        || encode_lifecycle_snapshot(&journal, expected.binding)? != bytes
    {
        return Err(ArtifactStorageError::Corrupt);
    }
    Ok(journal)
}

fn encode_withdrawal_snapshot(
    registry: &DatasetWithdrawalRegistry,
    binding: Digest32,
) -> Result<Vec<u8>, ArtifactStorageError> {
    let scope = registry.scope().ok_or(ArtifactStorageError::Unscoped)?;
    let records = registry.snapshot();
    if records.records().len() > MAX_DURABLE_ARTIFACT_RECORDS {
        return Err(ArtifactStorageError::Capacity);
    }
    let mut text = format!(
        "{WITHDRAWAL_MAGIC}\n{binding}\n{}\n{}\n{}\n{}\n",
        scope.authority_domain_id,
        scope.registry_id,
        scope.scope_id,
        records.records().len(),
    );
    for record in records.records() {
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
            notice.issued_at,
        ));
    }
    if text.len() > MAX_AUX_SNAPSHOT_BYTES {
        return Err(ArtifactStorageError::Capacity);
    }
    Ok(text.into_bytes())
}

fn decode_withdrawal_snapshot(
    bytes: &[u8],
    expected_binding: Digest32,
) -> Result<DatasetWithdrawalRegistry, ArtifactStorageError> {
    let text = std::str::from_utf8(bytes).map_err(|_| ArtifactStorageError::Corrupt)?;
    let mut lines = text.lines();
    if lines.next() != Some(WITHDRAWAL_MAGIC)
        || lines.next() != Some(expected_binding.to_string().as_str())
    {
        return Err(ArtifactStorageError::Corrupt);
    }
    let scope = DatasetWithdrawalScopeV1 {
        authority_domain_id: parse_id(required_line(&mut lines)?)?,
        registry_id: parse_id(required_line(&mut lines)?)?,
        scope_id: parse_id(required_line(&mut lines)?)?,
    };
    let expected_records = parse_usize(required_line(&mut lines)?)?;
    if expected_records > MAX_DURABLE_ARTIFACT_RECORDS {
        return Err(ArtifactStorageError::Capacity);
    }

    let mut registry = DatasetWithdrawalRegistry::new_scoped(scope);
    let mut observed_records = 0usize;
    for line in lines {
        if line.len() > MAX_AUX_LINE_BYTES || observed_records >= expected_records {
            return Err(ArtifactStorageError::Corrupt);
        }
        let fields: Vec<_> = line.split('|').collect();
        let ["W", notice_id, dataset, tombstone, authority, credential, key, epoch, issued_at] =
            fields.as_slice()
        else {
            return Err(ArtifactStorageError::Corrupt);
        };
        registry
            .append(DatasetWithdrawalNoticeV1 {
                notice_id: parse_id(notice_id)?,
                dataset_digest: parse_digest(dataset)?,
                source_tombstone_digest: parse_digest(tombstone)?,
                authority_id: parse_id(authority)?,
                credential_chain_digest: parse_digest(credential)?,
                signing_key_digest: parse_digest(key)?,
                authority_epoch: parse_u64(epoch)?,
                issued_at: parse_u64(issued_at)?,
            })
            .map_err(|_| ArtifactStorageError::Semantic)?;
        observed_records += 1;
    }
    if observed_records != expected_records {
        return Err(ArtifactStorageError::Corrupt);
    }
    Ok(registry)
}

fn encode_lifecycle_snapshot(
    journal: &ArtifactLifecycleJournalV2,
    binding: Digest32,
) -> Result<Vec<u8>, ArtifactStorageError> {
    if journal.records().len() > MAX_DURABLE_ARTIFACT_RECORDS {
        return Err(ArtifactStorageError::Capacity);
    }
    let mut text = format!(
        "{LIFECYCLE_MAGIC}\n{binding}\n{}\n",
        journal.records().len()
    );
    for record in journal.records() {
        let actor = &record.actor;
        let event = &record.event;
        text.push_str(&format!(
            "L|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}\n",
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
    if text.len() > MAX_AUX_SNAPSHOT_BYTES {
        return Err(ArtifactStorageError::Capacity);
    }
    Ok(text.into_bytes())
}

fn decode_lifecycle_snapshot(
    bytes: &[u8],
    expected_binding: Digest32,
) -> Result<ArtifactLifecycleJournalV2, ArtifactStorageError> {
    let text = std::str::from_utf8(bytes).map_err(|_| ArtifactStorageError::Corrupt)?;
    let mut lines = text.lines();
    if lines.next() != Some(LIFECYCLE_MAGIC)
        || lines.next() != Some(expected_binding.to_string().as_str())
    {
        return Err(ArtifactStorageError::Corrupt);
    }
    let expected_records = parse_usize(required_line(&mut lines)?)?;
    if expected_records > MAX_DURABLE_ARTIFACT_RECORDS {
        return Err(ArtifactStorageError::Capacity);
    }

    let mut journal = ArtifactLifecycleJournalV2::new();
    let mut observed_records = 0usize;
    for line in lines {
        if line.len() > MAX_AUX_LINE_BYTES || observed_records >= expected_records {
            return Err(ArtifactStorageError::Corrupt);
        }
        let fields: Vec<_> = line.split('|').collect();
        let [
            "L",
            producer_id,
            actor_id,
            actor_credential,
            role,
            actor_epoch,
            verified_at,
            expires_at,
            event_id,
            artifact_id,
            prior_state,
            next_state,
            event_actor_id,
            event_actor_credential,
            evidence,
            event_epoch,
            occurred_at,
        ] = fields.as_slice()
        else {
            return Err(ArtifactStorageError::Corrupt);
        };
        let actor = LifecycleActorEvidenceV2 {
            actor_id: parse_id(actor_id)?,
            credential_digest: parse_digest(actor_credential)?,
            role: parse_role(role)?,
            authority_epoch: parse_u64(actor_epoch)?,
            verified_at: parse_u64(verified_at)?,
            expires_at: parse_u64(expires_at)?,
        };
        let event = ArtifactLifecycleEventV1 {
            event_id: parse_id(event_id)?,
            artifact_id: parse_id(artifact_id)?,
            prior_state: parse_state(prior_state)?,
            next_state: parse_state(next_state)?,
            actor_id: parse_id(event_actor_id)?,
            actor_credential_digest: parse_digest(event_actor_credential)?,
            evidence_digest: parse_digest(evidence)?,
            authority_epoch: parse_u64(event_epoch)?,
            occurred_at: parse_u64(occurred_at)?,
        };
        journal
            .append(
                journal.head_digest(),
                &parse_id(producer_id)?,
                actor,
                event.clone(),
                event.occurred_at,
            )
            .map_err(|_| ArtifactStorageError::Semantic)?;
        observed_records += 1;
    }
    if observed_records != expected_records {
        return Err(ArtifactStorageError::Corrupt);
    }
    Ok(journal)
}

fn required_line<'a>(
    lines: &mut impl Iterator<Item = &'a str>,
) -> Result<&'a str, ArtifactStorageError> {
    lines.next().ok_or(ArtifactStorageError::Corrupt)
}

fn parse_id(value: &str) -> Result<StableId, ArtifactStorageError> {
    StableId::new(value.to_owned()).map_err(|_| ArtifactStorageError::Corrupt)
}

fn parse_digest(value: &str) -> Result<Digest32, ArtifactStorageError> {
    Digest32::from_str(value).map_err(|_| ArtifactStorageError::Corrupt)
}

fn parse_u64(value: &str) -> Result<u64, ArtifactStorageError> {
    value
        .parse::<u64>()
        .map_err(|_| ArtifactStorageError::Corrupt)
}

fn parse_usize(value: &str) -> Result<usize, ArtifactStorageError> {
    value
        .parse::<usize>()
        .map_err(|_| ArtifactStorageError::Corrupt)
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
    use super::*;

    use std::fs;
    use std::fs::OpenOptions;
    use std::path::PathBuf;
    use std::sync::atomic::AtomicU64;
    use std::sync::atomic::Ordering;

    static COUNTER: AtomicU64 = AtomicU64::new(0);

    struct TestFile(PathBuf);

    impl TestFile {
        fn new(label: &str) -> Self {
            let sequence = COUNTER.fetch_add(1, Ordering::Relaxed);
            let process = std::process::id();
            let time = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_else(|error| panic!("clock before epoch: {error:?}"))
                .as_nanos();
            Self(
                std::env::temp_dir()
                    .join(format!("hepta-artifact-{label}-{process}-{time}-{sequence}")),
            )
        }

        fn create(&self) -> CreateOnlyArtifactFile {
            CreateOnlyArtifactFile::create(&self.0)
                .unwrap_or_else(|error| panic!("create-only fixture failed: {error:?}"))
        }

        fn open(&self) -> File {
            OpenOptions::new()
                .read(true)
                .open(&self.0)
                .unwrap_or_else(|error| panic!("open fixture failed: {error:?}"))
        }
    }

    impl Drop for TestFile {
        fn drop(&mut self) {
            let _ = fs::remove_file(&self.0);
        }
    }

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned())
            .unwrap_or_else(|error| panic!("invalid test id {value}: {error:?}"))
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn scope(name: &str) -> DatasetWithdrawalScopeV1 {
        DatasetWithdrawalScopeV1 {
            authority_domain_id: id(&format!("authority-{name}")),
            registry_id: id(&format!("registry-{name}")),
            scope_id: id(&format!("tenant-{name}")),
        }
    }

    #[test]
    fn art_08_scoped_withdrawal_snapshot_round_trips_and_rejects_cross_scope_receipt() {
        let mut registry = DatasetWithdrawalRegistry::new_scoped(scope("a"));
        registry
            .append(DatasetWithdrawalNoticeV1 {
                notice_id: id("notice-a"),
                dataset_digest: digest("dataset-a"),
                source_tombstone_digest: digest("tombstone-a"),
                authority_id: id("dataset-owner"),
                credential_chain_digest: digest("credential"),
                signing_key_digest: digest("key"),
                authority_epoch: 3,
                issued_at: 20,
            })
            .unwrap_or_else(|error| panic!("withdrawal append failed: {error}"));

        let file = TestFile::new("withdrawal");
        let receipt = write_dataset_withdrawal_snapshot(file.create(), &registry, digest("binding"))
            .unwrap_or_else(|error| panic!("withdrawal persistence failed: {error:?}"));
        let recovered = read_dataset_withdrawal_snapshot(file.open(), receipt)
            .unwrap_or_else(|error| panic!("withdrawal recovery failed: {error:?}"));
        assert_eq!(recovered.snapshot(), registry.snapshot());

        let mut wrong_scope = receipt;
        wrong_scope.scope_digest = scope("b").digest();
        assert_eq!(
            read_dataset_withdrawal_snapshot(file.open(), wrong_scope),
            Err(ArtifactStorageError::ScopeMismatch)
        );
    }

    fn actor() -> LifecycleActorEvidenceV2 {
        LifecycleActorEvidenceV2 {
            actor_id: id("producer"),
            credential_digest: digest("producer-credential"),
            role: LifecycleActorRoleV2::Producer,
            authority_epoch: 4,
            verified_at: 10,
            expires_at: 100,
        }
    }

    fn trained_event(actor: &LifecycleActorEvidenceV2) -> ArtifactLifecycleEventV1 {
        ArtifactLifecycleEventV1 {
            event_id: id("trained"),
            artifact_id: id("artifact"),
            prior_state: ArtifactLifecycleStateV1::Proposed,
            next_state: ArtifactLifecycleStateV1::Trained,
            actor_id: actor.actor_id.clone(),
            actor_credential_digest: actor.credential_digest,
            evidence_digest: digest("training-evidence"),
            authority_epoch: actor.authority_epoch,
            occurred_at: 20,
        }
    }

    #[test]
    fn art_08_lifecycle_snapshot_recovers_after_historical_actor_expiry() {
        let actor = actor();
        let mut journal = ArtifactLifecycleJournalV2::new();
        journal
            .append(
                Digest32::ZERO,
                &id("producer"),
                actor.clone(),
                trained_event(&actor),
                20,
            )
            .unwrap_or_else(|error| panic!("lifecycle append failed: {error}"));

        let file = TestFile::new("lifecycle");
        let receipt =
            write_artifact_lifecycle_snapshot(file.create(), &journal, digest("binding"))
                .unwrap_or_else(|error| panic!("lifecycle persistence failed: {error:?}"));
        let mut recovered = read_artifact_lifecycle_snapshot(file.open(), receipt)
            .unwrap_or_else(|error| panic!("lifecycle recovery failed: {error:?}"));
        assert_eq!(recovered.snapshot(), journal.snapshot());

        let next = ArtifactLifecycleEventV1 {
            event_id: id("trained-late"),
            artifact_id: id("artifact-late"),
            ..trained_event(&actor)
        };
        assert_eq!(
            recovered.append(recovered.head_digest(), &id("producer"), actor, next, 101),
            Err(crate::ArtifactLifecycleJournalError::InvalidActorEvidence)
        );
    }
}
