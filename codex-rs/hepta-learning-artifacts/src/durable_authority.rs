//! Create-only durable snapshots for withdrawal and lifecycle authority state.
//!
//! These files are immutable distribution records. The caller owns directory
//! enrollment, parent-directory durability, retention, backup and the external
//! current-generation pointer. A successful write or read grants no selection,
//! activation, promotion or release authority.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ArtifactLifecycleEventV1;
use crate::ArtifactLifecycleJournalV2;
use crate::ArtifactLifecycleStateV1;
use crate::DatasetWithdrawalNoticeV1;
use crate::DatasetWithdrawalRegistry;
use crate::LifecycleActorEvidenceV2;
use crate::LifecycleActorRoleV2;
use crate::WithdrawalAuthorityDomainV1;

const WITHDRAWAL_MAGIC: &[u8; 8] = b"HPTWDR01";
const LIFECYCLE_MAGIC: &[u8; 8] = b"HPTLCJ02";
const MAX_AUTHORITY_SNAPSHOT_BYTES: usize = 64 * 1024 * 1024;
const MAX_AUTHORITY_RECORDS: usize = 1_000_000;

/// A file atomically reserved with create-new semantics for one immutable
/// authority snapshot. Existing regular files and symbolic links are never
/// overwritten.
pub struct CreateOnlyAuthorityFile(File);

impl fmt::Debug for CreateOnlyAuthorityFile {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("CreateOnlyAuthorityFile(<opaque>)")
    }
}

impl CreateOnlyAuthorityFile {
    pub fn create(path: impl AsRef<Path>) -> Result<Self, DurableAuthorityError> {
        let mut options = OpenOptions::new();
        options.read(true).write(true).create_new(true);
        #[cfg(unix)]
        options.mode(0o600);
        match options.open(path) {
            Ok(file) => Ok(Self(file)),
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
                Err(DurableAuthorityError::AlreadyExists)
            }
            Err(error) => Err(error.into()),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AuthoritySnapshotKindV1 {
    DatasetWithdrawal,
    ArtifactLifecycle,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AuthoritySnapshotReceiptV1 {
    pub kind: AuthoritySnapshotKindV1,
    pub binding_digest: Digest32,
    pub head_digest: Digest32,
    pub file_digest: Digest32,
    pub records: usize,
    pub encoded_bytes: usize,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DurableAuthorityError {
    InvalidBinding,
    InvalidReceipt,
    AlreadyExists,
    NotRegular,
    Busy,
    Capacity,
    Corrupt,
    Semantic,
    Indeterminate,
    Io(io::ErrorKind),
}

impl fmt::Display for DurableAuthorityError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for DurableAuthorityError {}

impl From<io::Error> for DurableAuthorityError {
    fn from(value: io::Error) -> Self {
        Self::Io(value.kind())
    }
}

pub fn write_withdrawal_registry_snapshot(
    file: CreateOnlyAuthorityFile,
    registry: &DatasetWithdrawalRegistry,
    domain: &WithdrawalAuthorityDomainV1,
) -> Result<AuthoritySnapshotReceiptV1, DurableAuthorityError> {
    let binding_digest = withdrawal_domain_digest(domain)?;
    let snapshot = registry.snapshot();
    let records = snapshot.records();
    if records.len() > MAX_AUTHORITY_RECORDS {
        return Err(DurableAuthorityError::Capacity);
    }
    let mut bytes = Vec::new();
    bytes.extend_from_slice(WITHDRAWAL_MAGIC);
    push_digest(&mut bytes, binding_digest);
    push_count(&mut bytes, records.len())?;
    for record in records {
        encode_withdrawal_notice(&mut bytes, &record.notice)?;
    }
    let receipt = authority_receipt(
        AuthoritySnapshotKindV1::DatasetWithdrawal,
        binding_digest,
        snapshot.head_digest,
        records.len(),
        &bytes,
    )?;
    write_new(file, &bytes)?;
    Ok(receipt)
}

pub fn read_withdrawal_registry_snapshot(
    file: File,
    expected: AuthoritySnapshotReceiptV1,
    domain: &WithdrawalAuthorityDomainV1,
) -> Result<DatasetWithdrawalRegistry, DurableAuthorityError> {
    let binding_digest = withdrawal_domain_digest(domain)?;
    validate_receipt(
        expected,
        AuthoritySnapshotKindV1::DatasetWithdrawal,
        binding_digest,
    )?;
    let bytes = read_exact_snapshot(file, expected)?;
    let mut decoder = Decoder::new(&bytes);
    decoder.expect_magic(WITHDRAWAL_MAGIC)?;
    if decoder.digest()? != binding_digest {
        return Err(DurableAuthorityError::Corrupt);
    }
    let records = decoder.count()?;
    if records != expected.records {
        return Err(DurableAuthorityError::Corrupt);
    }
    let mut registry = DatasetWithdrawalRegistry::new();
    for _ in 0..records {
        registry
            .append(decode_withdrawal_notice(&mut decoder)?)
            .map_err(|_| DurableAuthorityError::Semantic)?;
    }
    decoder.finish()?;
    if registry.snapshot().head_digest != expected.head_digest {
        return Err(DurableAuthorityError::Corrupt);
    }
    Ok(registry)
}

pub fn write_lifecycle_journal_snapshot(
    file: CreateOnlyAuthorityFile,
    journal: &ArtifactLifecycleJournalV2,
    lifecycle_scope_digest: Digest32,
) -> Result<AuthoritySnapshotReceiptV1, DurableAuthorityError> {
    if lifecycle_scope_digest.is_zero() {
        return Err(DurableAuthorityError::InvalidBinding);
    }
    let records = journal.records();
    if records.len() > MAX_AUTHORITY_RECORDS {
        return Err(DurableAuthorityError::Capacity);
    }
    let mut bytes = Vec::new();
    bytes.extend_from_slice(LIFECYCLE_MAGIC);
    push_digest(&mut bytes, lifecycle_scope_digest);
    push_count(&mut bytes, records.len())?;
    for record in records {
        push_id(&mut bytes, &record.producer_id)?;
        encode_actor(&mut bytes, &record.actor)?;
        encode_lifecycle_event(&mut bytes, &record.event)?;
    }
    let receipt = authority_receipt(
        AuthoritySnapshotKindV1::ArtifactLifecycle,
        lifecycle_scope_digest,
        journal.head_digest(),
        records.len(),
        &bytes,
    )?;
    write_new(file, &bytes)?;
    Ok(receipt)
}

pub fn read_lifecycle_journal_snapshot(
    file: File,
    expected: AuthoritySnapshotReceiptV1,
    lifecycle_scope_digest: Digest32,
    now: u64,
) -> Result<ArtifactLifecycleJournalV2, DurableAuthorityError> {
    if lifecycle_scope_digest.is_zero() {
        return Err(DurableAuthorityError::InvalidBinding);
    }
    validate_receipt(
        expected,
        AuthoritySnapshotKindV1::ArtifactLifecycle,
        lifecycle_scope_digest,
    )?;
    let bytes = read_exact_snapshot(file, expected)?;
    let mut decoder = Decoder::new(&bytes);
    decoder.expect_magic(LIFECYCLE_MAGIC)?;
    if decoder.digest()? != lifecycle_scope_digest {
        return Err(DurableAuthorityError::Corrupt);
    }
    let records = decoder.count()?;
    if records != expected.records {
        return Err(DurableAuthorityError::Corrupt);
    }
    let mut journal = ArtifactLifecycleJournalV2::new();
    for _ in 0..records {
        let producer_id = decoder.id()?;
        let actor = decode_actor(&mut decoder)?;
        let event = decode_lifecycle_event(&mut decoder)?;
        // Historical reconstruction is validated at the immutable event time;
        // current credential expiry gates only fresh mutation. The final
        // from-snapshot-equivalent head check below proves deterministic replay.
        journal
            .append(
                journal.head_digest(),
                &producer_id,
                actor,
                event.clone(),
                event.occurred_at,
            )
            .map_err(|_| DurableAuthorityError::Semantic)?;
    }
    decoder.finish()?;
    if journal.head_digest() != expected.head_digest {
        return Err(DurableAuthorityError::Corrupt);
    }
    // Keep `now` in the API as an explicit recovery-time input so callers do
    // not accidentally infer that this function grants a fresh mutation lease.
    let _ = now;
    Ok(journal)
}

fn withdrawal_domain_digest(
    domain: &WithdrawalAuthorityDomainV1,
) -> Result<Digest32, DurableAuthorityError> {
    if domain.scope_digest.is_zero() || domain.authority_epoch == 0 {
        return Err(DurableAuthorityError::InvalidBinding);
    }
    let mut bytes = b"hepta.learning-artifacts.withdrawal-authority-domain.v1".to_vec();
    push_id(&mut bytes, &domain.registry_id)?;
    push_digest(&mut bytes, domain.scope_digest);
    push_id(&mut bytes, &domain.authority_id)?;
    bytes.extend_from_slice(&domain.authority_epoch.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

fn authority_receipt(
    kind: AuthoritySnapshotKindV1,
    binding_digest: Digest32,
    head_digest: Digest32,
    records: usize,
    bytes: &[u8],
) -> Result<AuthoritySnapshotReceiptV1, DurableAuthorityError> {
    if binding_digest.is_zero()
        || records > MAX_AUTHORITY_RECORDS
        || bytes.is_empty()
        || bytes.len() > MAX_AUTHORITY_SNAPSHOT_BYTES
    {
        return Err(DurableAuthorityError::Capacity);
    }
    Ok(AuthoritySnapshotReceiptV1 {
        kind,
        binding_digest,
        head_digest,
        file_digest: Digest32::of_bytes(bytes),
        records,
        encoded_bytes: bytes.len(),
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn validate_receipt(
    receipt: AuthoritySnapshotReceiptV1,
    kind: AuthoritySnapshotKindV1,
    binding_digest: Digest32,
) -> Result<(), DurableAuthorityError> {
    if receipt.kind != kind
        || receipt.binding_digest != binding_digest
        || receipt.binding_digest.is_zero()
        || receipt.file_digest.is_zero()
        || receipt.records > MAX_AUTHORITY_RECORDS
        || receipt.encoded_bytes == 0
        || receipt.encoded_bytes > MAX_AUTHORITY_SNAPSHOT_BYTES
        || receipt.authority.grants_any()
    {
        return Err(DurableAuthorityError::InvalidReceipt);
    }
    Ok(())
}

fn write_new(file: CreateOnlyAuthorityFile, bytes: &[u8]) -> Result<(), DurableAuthorityError> {
    if bytes.len() > MAX_AUTHORITY_SNAPSHOT_BYTES {
        return Err(DurableAuthorityError::Capacity);
    }
    let mut file = lock(file.0, LockKind::Exclusive)?;
    if file.metadata()?.len() != 0 {
        return Err(DurableAuthorityError::Indeterminate);
    }
    file.seek(SeekFrom::Start(0))?;
    file.write_all(bytes)
        .and_then(|()| file.sync_all())
        .map_err(|_| DurableAuthorityError::Indeterminate)
}

fn read_exact_snapshot(
    file: File,
    expected: AuthoritySnapshotReceiptV1,
) -> Result<Vec<u8>, DurableAuthorityError> {
    let mut file = lock(file, LockKind::Shared)?;
    let observed = file.metadata()?.len();
    if observed != expected.encoded_bytes as u64
        || observed > MAX_AUTHORITY_SNAPSHOT_BYTES as u64
    {
        return Err(DurableAuthorityError::Corrupt);
    }
    file.seek(SeekFrom::Start(0))?;
    let mut bytes = Vec::with_capacity(expected.encoded_bytes);
    (&mut file)
        .take(expected.encoded_bytes as u64 + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() != expected.encoded_bytes
        || file.metadata()?.len() != observed
        || Digest32::of_bytes(&bytes) != expected.file_digest
    {
        return Err(DurableAuthorityError::Corrupt);
    }
    Ok(bytes)
}

enum LockKind {
    Shared,
    Exclusive,
}

fn lock(file: File, kind: LockKind) -> Result<File, DurableAuthorityError> {
    if !file.metadata()?.is_file() {
        return Err(DurableAuthorityError::NotRegular);
    }
    let result = match kind {
        LockKind::Shared => file.try_lock_shared(),
        LockKind::Exclusive => file.try_lock(),
    };
    match result {
        Ok(()) => Ok(file),
        Err(TryLockError::WouldBlock) => Err(DurableAuthorityError::Busy),
        Err(TryLockError::Error(error)) => Err(error.into()),
    }
}

fn push_count(bytes: &mut Vec<u8>, count: usize) -> Result<(), DurableAuthorityError> {
    let count = u32::try_from(count).map_err(|_| DurableAuthorityError::Capacity)?;
    bytes.extend_from_slice(&count.to_be_bytes());
    Ok(())
}

fn push_digest(bytes: &mut Vec<u8>, digest: Digest32) {
    bytes.extend_from_slice(digest.as_array());
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), DurableAuthorityError> {
    let raw = value.as_str().as_bytes();
    let length = u16::try_from(raw.len()).map_err(|_| DurableAuthorityError::Capacity)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

fn encode_withdrawal_notice(
    bytes: &mut Vec<u8>,
    notice: &DatasetWithdrawalNoticeV1,
) -> Result<(), DurableAuthorityError> {
    push_id(bytes, &notice.notice_id)?;
    push_digest(bytes, notice.dataset_digest);
    push_digest(bytes, notice.source_tombstone_digest);
    push_id(bytes, &notice.authority_id)?;
    push_digest(bytes, notice.credential_chain_digest);
    push_digest(bytes, notice.signing_key_digest);
    bytes.extend_from_slice(&notice.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&notice.issued_at.to_be_bytes());
    Ok(())
}

fn decode_withdrawal_notice(
    decoder: &mut Decoder<'_>,
) -> Result<DatasetWithdrawalNoticeV1, DurableAuthorityError> {
    Ok(DatasetWithdrawalNoticeV1 {
        notice_id: decoder.id()?,
        dataset_digest: decoder.digest()?,
        source_tombstone_digest: decoder.digest()?,
        authority_id: decoder.id()?,
        credential_chain_digest: decoder.digest()?,
        signing_key_digest: decoder.digest()?,
        authority_epoch: decoder.u64()?,
        issued_at: decoder.u64()?,
    })
}

fn encode_actor(
    bytes: &mut Vec<u8>,
    actor: &LifecycleActorEvidenceV2,
) -> Result<(), DurableAuthorityError> {
    push_id(bytes, &actor.actor_id)?;
    push_digest(bytes, actor.credential_digest);
    bytes.push(role_tag(actor.role));
    bytes.extend_from_slice(&actor.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&actor.verified_at.to_be_bytes());
    bytes.extend_from_slice(&actor.expires_at.to_be_bytes());
    Ok(())
}

fn decode_actor(decoder: &mut Decoder<'_>) -> Result<LifecycleActorEvidenceV2, DurableAuthorityError> {
    Ok(LifecycleActorEvidenceV2 {
        actor_id: decoder.id()?,
        credential_digest: decoder.digest()?,
        role: role_from_tag(decoder.u8()?)?,
        authority_epoch: decoder.u64()?,
        verified_at: decoder.u64()?,
        expires_at: decoder.u64()?,
    })
}

fn encode_lifecycle_event(
    bytes: &mut Vec<u8>,
    event: &ArtifactLifecycleEventV1,
) -> Result<(), DurableAuthorityError> {
    push_id(bytes, &event.event_id)?;
    push_id(bytes, &event.artifact_id)?;
    bytes.push(state_tag(event.prior_state));
    bytes.push(state_tag(event.next_state));
    push_id(bytes, &event.actor_id)?;
    push_digest(bytes, event.actor_credential_digest);
    push_digest(bytes, event.evidence_digest);
    bytes.extend_from_slice(&event.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&event.occurred_at.to_be_bytes());
    Ok(())
}

fn decode_lifecycle_event(
    decoder: &mut Decoder<'_>,
) -> Result<ArtifactLifecycleEventV1, DurableAuthorityError> {
    Ok(ArtifactLifecycleEventV1 {
        event_id: decoder.id()?,
        artifact_id: decoder.id()?,
        prior_state: state_from_tag(decoder.u8()?)?,
        next_state: state_from_tag(decoder.u8()?)?,
        actor_id: decoder.id()?,
        actor_credential_digest: decoder.digest()?,
        evidence_digest: decoder.digest()?,
        authority_epoch: decoder.u64()?,
        occurred_at: decoder.u64()?,
    })
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

fn role_from_tag(tag: u8) -> Result<LifecycleActorRoleV2, DurableAuthorityError> {
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
        _ => Err(DurableAuthorityError::Corrupt),
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

fn state_from_tag(tag: u8) -> Result<ArtifactLifecycleStateV1, DurableAuthorityError> {
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
        _ => Err(DurableAuthorityError::Corrupt),
    }
}

struct Decoder<'a> {
    bytes: &'a [u8],
    offset: usize,
}

impl<'a> Decoder<'a> {
    const fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, offset: 0 }
    }

    fn take(&mut self, count: usize) -> Result<&'a [u8], DurableAuthorityError> {
        let end = self
            .offset
            .checked_add(count)
            .ok_or(DurableAuthorityError::Corrupt)?;
        let slice = self
            .bytes
            .get(self.offset..end)
            .ok_or(DurableAuthorityError::Corrupt)?;
        self.offset = end;
        Ok(slice)
    }

    fn expect_magic(&mut self, magic: &[u8; 8]) -> Result<(), DurableAuthorityError> {
        if self.take(magic.len())? != magic {
            return Err(DurableAuthorityError::Corrupt);
        }
        Ok(())
    }

    fn u8(&mut self) -> Result<u8, DurableAuthorityError> {
        Ok(*self.take(1)?.first().ok_or(DurableAuthorityError::Corrupt)?)
    }

    fn u16(&mut self) -> Result<u16, DurableAuthorityError> {
        let mut raw = [0_u8; 2];
        raw.copy_from_slice(self.take(2)?);
        Ok(u16::from_be_bytes(raw))
    }

    fn u32(&mut self) -> Result<u32, DurableAuthorityError> {
        let mut raw = [0_u8; 4];
        raw.copy_from_slice(self.take(4)?);
        Ok(u32::from_be_bytes(raw))
    }

    fn u64(&mut self) -> Result<u64, DurableAuthorityError> {
        let mut raw = [0_u8; 8];
        raw.copy_from_slice(self.take(8)?);
        Ok(u64::from_be_bytes(raw))
    }

    fn count(&mut self) -> Result<usize, DurableAuthorityError> {
        let count = usize::try_from(self.u32()?).map_err(|_| DurableAuthorityError::Capacity)?;
        if count > MAX_AUTHORITY_RECORDS {
            return Err(DurableAuthorityError::Capacity);
        }
        Ok(count)
    }

    fn digest(&mut self) -> Result<Digest32, DurableAuthorityError> {
        let mut raw = [0_u8; 32];
        raw.copy_from_slice(self.take(32)?);
        Ok(Digest32::from_array(raw))
    }

    fn id(&mut self) -> Result<StableId, DurableAuthorityError> {
        let length = usize::from(self.u16()?);
        let raw = self.take(length)?;
        let value = std::str::from_utf8(raw).map_err(|_| DurableAuthorityError::Corrupt)?;
        StableId::new(value.to_owned()).map_err(|_| DurableAuthorityError::Corrupt)
    }

    fn finish(self) -> Result<(), DurableAuthorityError> {
        if self.offset != self.bytes.len() {
            return Err(DurableAuthorityError::Corrupt);
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::sync::atomic::AtomicU64;
    use std::sync::atomic::Ordering;

    static NEXT_FILE: AtomicU64 = AtomicU64::new(1);

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("valid id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn path(label: &str) -> std::path::PathBuf {
        std::env::temp_dir().join(format!(
            "hepta-learning-artifacts-{label}-{}-{}",
            std::process::id(),
            NEXT_FILE.fetch_add(1, Ordering::Relaxed)
        ))
    }

    fn domain() -> WithdrawalAuthorityDomainV1 {
        WithdrawalAuthorityDomainV1 {
            registry_id: id("withdrawal-registry"),
            scope_digest: digest("scope"),
            authority_id: id("withdrawal-authority"),
            authority_epoch: 4,
        }
    }

    #[test]
    fn art_07_withdrawal_registry_durable_roundtrip_rebuilds_exact_head() {
        let mut registry = DatasetWithdrawalRegistry::new();
        registry
            .append(DatasetWithdrawalNoticeV1 {
                notice_id: id("notice"),
                dataset_digest: digest("dataset"),
                source_tombstone_digest: digest("tombstone"),
                authority_id: id("authority"),
                credential_chain_digest: digest("credential"),
                signing_key_digest: digest("key"),
                authority_epoch: 2,
                issued_at: 20,
            })
            .expect("valid withdrawal");
        let snapshot_path = path("withdrawal");
        let receipt = write_withdrawal_registry_snapshot(
            CreateOnlyAuthorityFile::create(&snapshot_path).expect("reserve snapshot"),
            &registry,
            &domain(),
        )
        .expect("persist withdrawal registry");
        let reopened = read_withdrawal_registry_snapshot(
            File::open(&snapshot_path).expect("open snapshot"),
            receipt,
            &domain(),
        )
        .expect("reopen withdrawal registry");
        assert_eq!(reopened.snapshot().head_digest, registry.snapshot().head_digest);
        assert!(reopened.is_withdrawn(digest("dataset")));
        fs::remove_file(snapshot_path).expect("cleanup");
    }

    #[test]
    fn art_07_lifecycle_durable_roundtrip_survives_actor_expiry() {
        let producer_id = id("producer");
        let artifact_id = id("artifact");
        let actor = LifecycleActorEvidenceV2 {
            actor_id: producer_id.clone(),
            credential_digest: digest("credential"),
            role: LifecycleActorRoleV2::Producer,
            authority_epoch: 3,
            verified_at: 10,
            expires_at: 100,
        };
        let event = ArtifactLifecycleEventV1 {
            event_id: id("trained"),
            artifact_id,
            prior_state: ArtifactLifecycleStateV1::Proposed,
            next_state: ArtifactLifecycleStateV1::Trained,
            actor_id: actor.actor_id.clone(),
            actor_credential_digest: actor.credential_digest,
            evidence_digest: digest("evidence"),
            authority_epoch: actor.authority_epoch,
            occurred_at: 20,
        };
        let mut journal = ArtifactLifecycleJournalV2::new();
        journal
            .append(Digest32::ZERO, &producer_id, actor, event, 20)
            .expect("valid lifecycle event");
        let snapshot_path = path("lifecycle");
        let scope = digest("lifecycle-scope");
        let receipt = write_lifecycle_journal_snapshot(
            CreateOnlyAuthorityFile::create(&snapshot_path).expect("reserve snapshot"),
            &journal,
            scope,
        )
        .expect("persist lifecycle journal");
        let reopened = read_lifecycle_journal_snapshot(
            File::open(&snapshot_path).expect("open snapshot"),
            receipt,
            scope,
            101,
        )
        .expect("historical journal remains recoverable after actor expiry");
        assert_eq!(reopened.head_digest(), journal.head_digest());
        assert_eq!(reopened.records(), journal.records());
        fs::remove_file(snapshot_path).expect("cleanup");
    }
}
