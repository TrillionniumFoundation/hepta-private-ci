use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_types::Digest32;

const STORE_MAGIC: &[u8; 8] = b"HCPSTR01";
const STORE_SCHEMA_VERSION: u32 = 1;
const HEADER_BYTES: usize = 12;
const FIXED_FRAME_BODY_BYTES: usize = 8 + 1 + 32 + 32 + 32 + 32;
const DEFAULT_MAX_RECORDS: usize = 4096;
const DEFAULT_MAX_PAYLOAD_BYTES: usize = 4 * 1024 * 1024;
const MAX_STORE_BYTES: u64 = 256 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum PlannerStoreRecordKindV1 {
    SnapshotEnvelope,
    PreparedPlanEnvelope,
    NduEvaluationEnvelope,
    DecisionEnvelope,
    GrantRequestEnvelope,
    AuthorityDecisionEnvelope,
    EffectTerminalEnvelope,
    ReconciliationEnvelope,
    ExternalCheckpoint,
    RotationAnchor,
}

impl PlannerStoreRecordKindV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::SnapshotEnvelope => 0,
            Self::PreparedPlanEnvelope => 1,
            Self::NduEvaluationEnvelope => 2,
            Self::DecisionEnvelope => 3,
            Self::GrantRequestEnvelope => 4,
            Self::AuthorityDecisionEnvelope => 5,
            Self::EffectTerminalEnvelope => 6,
            Self::ReconciliationEnvelope => 7,
            Self::ExternalCheckpoint => 8,
            Self::RotationAnchor => 9,
        }
    }

    fn from_tag(tag: u8) -> Result<Self, PlannerStoreError> {
        match tag {
            0 => Ok(Self::SnapshotEnvelope),
            1 => Ok(Self::PreparedPlanEnvelope),
            2 => Ok(Self::NduEvaluationEnvelope),
            3 => Ok(Self::DecisionEnvelope),
            4 => Ok(Self::GrantRequestEnvelope),
            5 => Ok(Self::AuthorityDecisionEnvelope),
            6 => Ok(Self::EffectTerminalEnvelope),
            7 => Ok(Self::ReconciliationEnvelope),
            8 => Ok(Self::ExternalCheckpoint),
            9 => Ok(Self::RotationAnchor),
            _ => Err(PlannerStoreError::UnknownRecordKind(tag)),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerStoreRecordV1 {
    sequence: u64,
    kind: PlannerStoreRecordKindV1,
    identity_digest: Digest32,
    payload_digest: Digest32,
    predecessor_record_digest: Digest32,
    record_digest: Digest32,
    payload: Vec<u8>,
}

impl PlannerStoreRecordV1 {
    #[must_use]
    pub const fn sequence(&self) -> u64 {
        self.sequence
    }

    #[must_use]
    pub const fn kind(&self) -> PlannerStoreRecordKindV1 {
        self.kind
    }

    #[must_use]
    pub const fn identity_digest(&self) -> Digest32 {
        self.identity_digest
    }

    #[must_use]
    pub const fn payload_digest(&self) -> Digest32 {
        self.payload_digest
    }

    #[must_use]
    pub const fn predecessor_record_digest(&self) -> Digest32 {
        self.predecessor_record_digest
    }

    #[must_use]
    pub const fn record_digest(&self) -> Digest32 {
        self.record_digest
    }

    #[must_use]
    pub fn payload(&self) -> &[u8] {
        &self.payload
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlannerStoreFailpointV1 {
    None,
    BeforeAppend,
    AfterAppendBeforeSync,
    AfterTemporarySyncBeforeRename,
    AfterRenameBeforeDirectorySync,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PlannerStoreOptionsV1 {
    pub maximum_records: usize,
    pub maximum_payload_bytes: usize,
    pub failpoint: PlannerStoreFailpointV1,
}

impl Default for PlannerStoreOptionsV1 {
    fn default() -> Self {
        Self {
            maximum_records: DEFAULT_MAX_RECORDS,
            maximum_payload_bytes: DEFAULT_MAX_PAYLOAD_BYTES,
            failpoint: PlannerStoreFailpointV1::None,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerStoreLegacyEnvelopeV0 {
    pub kind: PlannerStoreRecordKindV1,
    pub identity_digest: Digest32,
    pub canonical_payload: Vec<u8>,
}

#[derive(Debug)]
pub enum PlannerStoreError {
    Io(String),
    PathMustBeAbsolute,
    MissingParent,
    InvalidParent,
    SymlinkRejected,
    WriterBusy,
    LockCorrupt,
    StoreTooLarge,
    CorruptHeader,
    UnsupportedSchema(u32),
    CorruptFrame,
    UnknownRecordKind(u8),
    EmptyIdentity,
    RecordLimitExceeded,
    PayloadLimitExceeded,
    IdentityConflict,
    PoisonedAfterFailedDurabilityBoundary,
    InjectedFailure(PlannerStoreFailpointV1),
    InvalidBackup,
    InvalidMigrationSource,
}

impl fmt::Display for PlannerStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PlannerStoreError {}

impl From<std::io::Error> for PlannerStoreError {
    fn from(error: std::io::Error) -> Self {
        Self::Io(error.to_string())
    }
}

#[derive(Debug)]
struct PlannerStoreLockV1 {
    path: PathBuf,
    token: String,
    _file: File,
}

impl Drop for PlannerStoreLockV1 {
    fn drop(&mut self) {
        if std::fs::read_to_string(&self.path)
            .ok()
            .as_deref()
            == Some(self.token.as_str())
        {
            let _ = std::fs::remove_file(&self.path);
            if let Some(parent) = self.path.parent() {
                let _ = sync_directory(parent);
            }
        }
    }
}

#[derive(Debug)]
pub struct PlannerStoreV1 {
    path: PathBuf,
    _lock: PlannerStoreLockV1,
    file: File,
    records: Vec<PlannerStoreRecordV1>,
    identities: BTreeMap<Digest32, (PlannerStoreRecordKindV1, Digest32, usize)>,
    options: PlannerStoreOptionsV1,
    recovered_tail_bytes: u64,
    poisoned: bool,
}

impl PlannerStoreV1 {
    pub fn open(
        path: impl AsRef<Path>,
        options: PlannerStoreOptionsV1,
    ) -> Result<Self, PlannerStoreError> {
        validate_options(options)?;
        let path = validate_store_path(path.as_ref())?;
        let lock = acquire_lock(&path)?;
        let mut file = open_store_file(&path)?;
        if file.metadata()?.len() == 0 {
            write_header(&mut file)?;
            sync_directory(path.parent().ok_or(PlannerStoreError::MissingParent)?)?;
        }
        let (records, identities, recovered_tail_bytes) =
            read_and_recover(&mut file, options)?;
        Ok(Self {
            path,
            _lock: lock,
            file,
            records,
            identities,
            options,
            recovered_tail_bytes,
            poisoned: false,
        })
    }

    pub fn migrate_legacy_v0(
        path: impl AsRef<Path>,
        envelopes: &[PlannerStoreLegacyEnvelopeV0],
        options: PlannerStoreOptionsV1,
    ) -> Result<Self, PlannerStoreError> {
        let path = path.as_ref();
        if path.exists() && std::fs::metadata(path)?.len() != 0 {
            return Err(PlannerStoreError::InvalidMigrationSource);
        }
        let mut store = Self::open(path, options)?;
        for envelope in envelopes {
            store.append(
                envelope.kind,
                envelope.identity_digest,
                &envelope.canonical_payload,
            )?;
        }
        Ok(store)
    }

    #[must_use]
    pub fn records(&self) -> &[PlannerStoreRecordV1] {
        &self.records
    }

    #[must_use]
    pub const fn recovered_tail_bytes(&self) -> u64 {
        self.recovered_tail_bytes
    }

    #[must_use]
    pub fn head_digest(&self) -> Digest32 {
        self.records
            .last()
            .map_or(Digest32::ZERO, PlannerStoreRecordV1::record_digest)
    }

    pub fn append(
        &mut self,
        kind: PlannerStoreRecordKindV1,
        identity_digest: Digest32,
        canonical_payload: &[u8],
    ) -> Result<PlannerStoreRecordV1, PlannerStoreError> {
        if self.poisoned {
            return Err(PlannerStoreError::PoisonedAfterFailedDurabilityBoundary);
        }
        if identity_digest.is_zero() {
            return Err(PlannerStoreError::EmptyIdentity);
        }
        if canonical_payload.len() > self.options.maximum_payload_bytes {
            return Err(PlannerStoreError::PayloadLimitExceeded);
        }
        let payload_digest = Digest32::of_bytes(canonical_payload);
        if let Some((existing_kind, existing_payload, index)) =
            self.identities.get(&identity_digest)
        {
            if *existing_kind == kind && *existing_payload == payload_digest {
                return Ok(self.records[*index].clone());
            }
            return Err(PlannerStoreError::IdentityConflict);
        }
        if self.records.len() >= self.options.maximum_records {
            return Err(PlannerStoreError::RecordLimitExceeded);
        }
        if self.options.failpoint == PlannerStoreFailpointV1::BeforeAppend {
            return Err(PlannerStoreError::InjectedFailure(
                PlannerStoreFailpointV1::BeforeAppend,
            ));
        }
        let sequence = u64::try_from(self.records.len())
            .ok()
            .and_then(|value| value.checked_add(1))
            .ok_or(PlannerStoreError::RecordLimitExceeded)?;
        let predecessor_record_digest = self.head_digest();
        let record_digest = digest_record(
            sequence,
            kind,
            identity_digest,
            payload_digest,
            predecessor_record_digest,
            canonical_payload,
        );
        let record = PlannerStoreRecordV1 {
            sequence,
            kind,
            identity_digest,
            payload_digest,
            predecessor_record_digest,
            record_digest,
            payload: canonical_payload.to_vec(),
        };
        let frame = encode_record(&record)?;
        self.file.seek(SeekFrom::End(0))?;
        self.file.write_all(&frame)?;
        if self.options.failpoint == PlannerStoreFailpointV1::AfterAppendBeforeSync {
            self.poisoned = true;
            return Err(PlannerStoreError::InjectedFailure(
                PlannerStoreFailpointV1::AfterAppendBeforeSync,
            ));
        }
        if let Err(error) = self.file.sync_data() {
            self.poisoned = true;
            return Err(error.into());
        }
        let index = self.records.len();
        self.identities
            .insert(identity_digest, (kind, payload_digest, index));
        self.records.push(record.clone());
        Ok(record)
    }

    pub fn append_decision_envelope(
        &mut self,
        identity_digest: Digest32,
        canonical_envelope: &[u8],
    ) -> Result<PlannerStoreRecordV1, PlannerStoreError> {
        self.append(
            PlannerStoreRecordKindV1::DecisionEnvelope,
            identity_digest,
            canonical_envelope,
        )
    }

    pub fn append_effect_terminal_envelope(
        &mut self,
        identity_digest: Digest32,
        canonical_envelope: &[u8],
    ) -> Result<PlannerStoreRecordV1, PlannerStoreError> {
        self.append(
            PlannerStoreRecordKindV1::EffectTerminalEnvelope,
            identity_digest,
            canonical_envelope,
        )
    }

    pub fn append_reconciliation_envelope(
        &mut self,
        identity_digest: Digest32,
        canonical_envelope: &[u8],
    ) -> Result<PlannerStoreRecordV1, PlannerStoreError> {
        self.append(
            PlannerStoreRecordKindV1::ReconciliationEnvelope,
            identity_digest,
            canonical_envelope,
        )
    }

    pub fn record_external_checkpoint(
        &mut self,
        identity_digest: Digest32,
        anchor_digest: Digest32,
        signer_digest: Digest32,
        signature_digest: Digest32,
    ) -> Result<PlannerStoreRecordV1, PlannerStoreError> {
        if anchor_digest.is_zero() || signer_digest.is_zero() || signature_digest.is_zero() {
            return Err(PlannerStoreError::EmptyIdentity);
        }
        let mut payload = b"hepta.control.planner-external-checkpoint.v1\0".to_vec();
        payload.extend_from_slice(self.head_digest().as_array());
        payload.extend_from_slice(anchor_digest.as_array());
        payload.extend_from_slice(signer_digest.as_array());
        payload.extend_from_slice(signature_digest.as_array());
        self.append(
            PlannerStoreRecordKindV1::ExternalCheckpoint,
            identity_digest,
            &payload,
        )
    }

    pub fn compact(&mut self) -> Result<(), PlannerStoreError> {
        self.ensure_usable()?;
        let bytes = encode_store(&self.records)?;
        atomic_replace(
            &self.path,
            &bytes,
            self.options.failpoint,
            "compact",
        )?;
        self.file = open_store_file(&self.path)?;
        let (records, identities, recovered_tail_bytes) =
            read_and_recover(&mut self.file, self.options)?;
        self.records = records;
        self.identities = identities;
        self.recovered_tail_bytes = recovered_tail_bytes;
        Ok(())
    }

    pub fn backup_to(&mut self, backup: impl AsRef<Path>) -> Result<(), PlannerStoreError> {
        self.ensure_usable()?;
        self.file.sync_all()?;
        let mut bytes = Vec::new();
        self.file.seek(SeekFrom::Start(0))?;
        self.file.read_to_end(&mut bytes)?;
        validate_store_bytes(&bytes, self.options)?;
        let backup = validate_store_path(backup.as_ref())?;
        atomic_replace(
            &backup,
            &bytes,
            self.options.failpoint,
            "backup",
        )
    }

    pub fn restore_from_backup(
        &mut self,
        backup: impl AsRef<Path>,
    ) -> Result<(), PlannerStoreError> {
        self.ensure_usable()?;
        let backup = validate_store_path(backup.as_ref())?;
        let mut bytes = Vec::new();
        OpenOptions::new()
            .read(true)
            .open(&backup)?
            .take(MAX_STORE_BYTES.saturating_add(1))
            .read_to_end(&mut bytes)?;
        validate_store_bytes(&bytes, self.options).map_err(|_| PlannerStoreError::InvalidBackup)?;
        atomic_replace(
            &self.path,
            &bytes,
            self.options.failpoint,
            "restore",
        )?;
        self.file = open_store_file(&self.path)?;
        let (records, identities, recovered_tail_bytes) =
            read_and_recover(&mut self.file, self.options)?;
        self.records = records;
        self.identities = identities;
        self.recovered_tail_bytes = recovered_tail_bytes;
        Ok(())
    }

    pub fn rotate_to_archive(
        &mut self,
        archive: impl AsRef<Path>,
        rotation_identity: Digest32,
        external_anchor_digest: Digest32,
    ) -> Result<PlannerStoreRecordV1, PlannerStoreError> {
        self.ensure_usable()?;
        if rotation_identity.is_zero() || external_anchor_digest.is_zero() {
            return Err(PlannerStoreError::EmptyIdentity);
        }
        let predecessor_head = self.head_digest();
        self.backup_to(archive)?;
        let mut payload = b"hepta.control.planner-rotation-anchor.v1\0".to_vec();
        payload.extend_from_slice(predecessor_head.as_array());
        payload.extend_from_slice(external_anchor_digest.as_array());
        let payload_digest = Digest32::of_bytes(&payload);
        let record_digest = digest_record(
            1,
            PlannerStoreRecordKindV1::RotationAnchor,
            rotation_identity,
            payload_digest,
            Digest32::ZERO,
            &payload,
        );
        let anchor = PlannerStoreRecordV1 {
            sequence: 1,
            kind: PlannerStoreRecordKindV1::RotationAnchor,
            identity_digest: rotation_identity,
            payload_digest,
            predecessor_record_digest: Digest32::ZERO,
            record_digest,
            payload,
        };
        let bytes = encode_store(std::slice::from_ref(&anchor))?;
        atomic_replace(
            &self.path,
            &bytes,
            self.options.failpoint,
            "rotate",
        )?;
        self.file = open_store_file(&self.path)?;
        let (records, identities, recovered_tail_bytes) =
            read_and_recover(&mut self.file, self.options)?;
        self.records = records;
        self.identities = identities;
        self.recovered_tail_bytes = recovered_tail_bytes;
        Ok(anchor)
    }

    fn ensure_usable(&self) -> Result<(), PlannerStoreError> {
        if self.poisoned {
            Err(PlannerStoreError::PoisonedAfterFailedDurabilityBoundary)
        } else {
            Ok(())
        }
    }
}

fn validate_options(options: PlannerStoreOptionsV1) -> Result<(), PlannerStoreError> {
    if options.maximum_records == 0 || options.maximum_records > DEFAULT_MAX_RECORDS {
        return Err(PlannerStoreError::RecordLimitExceeded);
    }
    if options.maximum_payload_bytes == 0
        || options.maximum_payload_bytes > DEFAULT_MAX_PAYLOAD_BYTES
    {
        return Err(PlannerStoreError::PayloadLimitExceeded);
    }
    Ok(())
}

fn validate_store_path(path: &Path) -> Result<PathBuf, PlannerStoreError> {
    if !path.is_absolute() {
        return Err(PlannerStoreError::PathMustBeAbsolute);
    }
    let parent = path.parent().ok_or(PlannerStoreError::MissingParent)?;
    let metadata = std::fs::symlink_metadata(parent)?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(PlannerStoreError::InvalidParent);
    }
    if let Ok(metadata) = std::fs::symlink_metadata(path) {
        if metadata.file_type().is_symlink() || !metadata.is_file() {
            return Err(PlannerStoreError::SymlinkRejected);
        }
    }
    Ok(path.to_path_buf())
}

fn lock_path(path: &Path) -> PathBuf {
    let mut name = path
        .file_name()
        .map_or_else(|| "planner".into(), |value| value.to_os_string());
    name.push(".writer.lock");
    path.with_file_name(name)
}

fn acquire_lock(path: &Path) -> Result<PlannerStoreLockV1, PlannerStoreError> {
    let path = lock_path(path);
    let process = std::process::id();
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| PlannerStoreError::Io(error.to_string()))?
        .as_nanos();
    let token = format!("{process}:{timestamp}");
    for attempt in 0..3_u8 {
        let mut options = OpenOptions::new();
        options.create_new(true).read(true).write(true);
        match options.open(&path) {
            Ok(mut file) => {
                file.write_all(token.as_bytes())?;
                file.sync_all()?;
                sync_directory(path.parent().ok_or(PlannerStoreError::MissingParent)?)?;
                return Ok(PlannerStoreLockV1 {
                    path,
                    token,
                    _file: file,
                });
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                let existing = std::fs::read_to_string(&path)
                    .map_err(|_| PlannerStoreError::LockCorrupt)?;
                let owner = existing
                    .split(':')
                    .next()
                    .and_then(|value| value.parse::<u32>().ok())
                    .ok_or(PlannerStoreError::LockCorrupt)?;
                if process_is_alive(owner) {
                    return Err(PlannerStoreError::WriterBusy);
                }
                let stale = path.with_extension(format!("stale-{process}-{attempt}"));
                match std::fs::rename(&path, &stale) {
                    Ok(()) => {
                        let _ = std::fs::remove_file(stale);
                        sync_directory(
                            path.parent().ok_or(PlannerStoreError::MissingParent)?,
                        )?;
                    }
                    Err(error) if error.kind() == std::io::ErrorKind::NotFound => continue,
                    Err(error) => return Err(error.into()),
                }
            }
            Err(error) => return Err(error.into()),
        }
    }
    Err(PlannerStoreError::WriterBusy)
}

fn process_is_alive(process: u32) -> bool {
    #[cfg(target_os = "linux")]
    {
        Path::new("/proc").join(process.to_string()).exists()
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = process;
        true
    }
}

fn open_store_file(path: &Path) -> Result<File, PlannerStoreError> {
    let file = OpenOptions::new()
        .create(true)
        .read(true)
        .write(true)
        .open(path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file() || metadata.len() > MAX_STORE_BYTES {
        return Err(PlannerStoreError::StoreTooLarge);
    }
    Ok(file)
}

fn write_header(file: &mut File) -> Result<(), PlannerStoreError> {
    file.seek(SeekFrom::Start(0))?;
    file.write_all(STORE_MAGIC)?;
    file.write_all(&STORE_SCHEMA_VERSION.to_be_bytes())?;
    file.sync_all()?;
    Ok(())
}

fn read_and_recover(
    file: &mut File,
    options: PlannerStoreOptionsV1,
) -> Result<
    (
        Vec<PlannerStoreRecordV1>,
        BTreeMap<Digest32, (PlannerStoreRecordKindV1, Digest32, usize)>,
        u64,
    ),
    PlannerStoreError,
> {
    file.seek(SeekFrom::Start(0))?;
    let mut bytes = Vec::new();
    file.take(MAX_STORE_BYTES.saturating_add(1))
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > MAX_STORE_BYTES {
        return Err(PlannerStoreError::StoreTooLarge);
    }
    let decoded = decode_store(&bytes, options)?;
    let recovered_tail_bytes = bytes.len().saturating_sub(decoded.last_good_offset) as u64;
    if recovered_tail_bytes > 0 {
        file.set_len(decoded.last_good_offset as u64)?;
        file.sync_all()?;
    }
    file.seek(SeekFrom::End(0))?;
    Ok((decoded.records, decoded.identities, recovered_tail_bytes))
}

struct DecodedStore {
    records: Vec<PlannerStoreRecordV1>,
    identities: BTreeMap<Digest32, (PlannerStoreRecordKindV1, Digest32, usize)>,
    last_good_offset: usize,
}

fn validate_store_bytes(
    bytes: &[u8],
    options: PlannerStoreOptionsV1,
) -> Result<(), PlannerStoreError> {
    let decoded = decode_store(bytes, options)?;
    if decoded.last_good_offset != bytes.len() {
        return Err(PlannerStoreError::CorruptFrame);
    }
    Ok(())
}

fn decode_store(
    bytes: &[u8],
    options: PlannerStoreOptionsV1,
) -> Result<DecodedStore, PlannerStoreError> {
    if bytes.len() < HEADER_BYTES || &bytes[..8] != STORE_MAGIC {
        return Err(PlannerStoreError::CorruptHeader);
    }
    let schema = u32::from_be_bytes(
        bytes[8..12]
            .try_into()
            .map_err(|_| PlannerStoreError::CorruptHeader)?,
    );
    if schema != STORE_SCHEMA_VERSION {
        return Err(PlannerStoreError::UnsupportedSchema(schema));
    }
    let mut offset = HEADER_BYTES;
    let mut records = Vec::new();
    let mut identities = BTreeMap::new();
    let mut predecessor = Digest32::ZERO;
    while offset < bytes.len() {
        if bytes.len() - offset < 4 {
            break;
        }
        let body_len = u32::from_be_bytes(
            bytes[offset..offset + 4]
                .try_into()
                .map_err(|_| PlannerStoreError::CorruptFrame)?,
        ) as usize;
        if body_len < FIXED_FRAME_BODY_BYTES
            || body_len > FIXED_FRAME_BODY_BYTES + options.maximum_payload_bytes
        {
            return Err(PlannerStoreError::CorruptFrame);
        }
        let end = offset
            .checked_add(4)
            .and_then(|value| value.checked_add(body_len))
            .ok_or(PlannerStoreError::CorruptFrame)?;
        if end > bytes.len() {
            break;
        }
        if records.len() >= options.maximum_records {
            return Err(PlannerStoreError::RecordLimitExceeded);
        }
        let mut cursor = offset + 4;
        let sequence = read_u64(bytes, &mut cursor)?;
        let expected_sequence = u64::try_from(records.len())
            .ok()
            .and_then(|value| value.checked_add(1))
            .ok_or(PlannerStoreError::RecordLimitExceeded)?;
        if sequence != expected_sequence {
            return Err(PlannerStoreError::CorruptFrame);
        }
        let kind = PlannerStoreRecordKindV1::from_tag(read_u8(bytes, &mut cursor)?)?;
        let identity_digest = read_digest(bytes, &mut cursor)?;
        let payload_digest = read_digest(bytes, &mut cursor)?;
        let predecessor_record_digest = read_digest(bytes, &mut cursor)?;
        let record_digest = read_digest(bytes, &mut cursor)?;
        if identity_digest.is_zero() || predecessor_record_digest != predecessor {
            return Err(PlannerStoreError::CorruptFrame);
        }
        let payload = bytes[cursor..end].to_vec();
        if Digest32::of_bytes(&payload) != payload_digest
            || digest_record(
                sequence,
                kind,
                identity_digest,
                payload_digest,
                predecessor_record_digest,
                &payload,
            ) != record_digest
            || identities.contains_key(&identity_digest)
        {
            return Err(PlannerStoreError::CorruptFrame);
        }
        let index = records.len();
        records.push(PlannerStoreRecordV1 {
            sequence,
            kind,
            identity_digest,
            payload_digest,
            predecessor_record_digest,
            record_digest,
            payload,
        });
        identities.insert(identity_digest, (kind, payload_digest, index));
        predecessor = record_digest;
        offset = end;
    }
    Ok(DecodedStore {
        records,
        identities,
        last_good_offset: offset,
    })
}

fn encode_store(records: &[PlannerStoreRecordV1]) -> Result<Vec<u8>, PlannerStoreError> {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(STORE_MAGIC);
    bytes.extend_from_slice(&STORE_SCHEMA_VERSION.to_be_bytes());
    for record in records {
        bytes.extend_from_slice(&encode_record(record)?);
    }
    Ok(bytes)
}

fn encode_record(record: &PlannerStoreRecordV1) -> Result<Vec<u8>, PlannerStoreError> {
    let body_len = FIXED_FRAME_BODY_BYTES
        .checked_add(record.payload.len())
        .ok_or(PlannerStoreError::PayloadLimitExceeded)?;
    let body_len = u32::try_from(body_len).map_err(|_| PlannerStoreError::PayloadLimitExceeded)?;
    let mut bytes = Vec::with_capacity(4 + body_len as usize);
    bytes.extend_from_slice(&body_len.to_be_bytes());
    bytes.extend_from_slice(&record.sequence.to_be_bytes());
    bytes.push(record.kind.tag());
    bytes.extend_from_slice(record.identity_digest.as_array());
    bytes.extend_from_slice(record.payload_digest.as_array());
    bytes.extend_from_slice(record.predecessor_record_digest.as_array());
    bytes.extend_from_slice(record.record_digest.as_array());
    bytes.extend_from_slice(&record.payload);
    Ok(bytes)
}

fn digest_record(
    sequence: u64,
    kind: PlannerStoreRecordKindV1,
    identity_digest: Digest32,
    payload_digest: Digest32,
    predecessor_record_digest: Digest32,
    payload: &[u8],
) -> Digest32 {
    let mut bytes = b"hepta.control.planner-store-record.v1\0".to_vec();
    bytes.extend_from_slice(&sequence.to_be_bytes());
    bytes.push(kind.tag());
    bytes.extend_from_slice(identity_digest.as_array());
    bytes.extend_from_slice(payload_digest.as_array());
    bytes.extend_from_slice(predecessor_record_digest.as_array());
    bytes.extend_from_slice(&(payload.len() as u64).to_be_bytes());
    bytes.extend_from_slice(payload);
    Digest32::of_bytes(&bytes)
}

fn atomic_replace(
    path: &Path,
    bytes: &[u8],
    failpoint: PlannerStoreFailpointV1,
    operation: &str,
) -> Result<(), PlannerStoreError> {
    let parent = path.parent().ok_or(PlannerStoreError::MissingParent)?;
    let mut temporary_name = path
        .file_name()
        .map_or_else(|| "planner-store".into(), |value| value.to_os_string());
    temporary_name.push(format!(".{operation}.tmp"));
    let temporary = path.with_file_name(temporary_name);
    let _ = std::fs::remove_file(&temporary);
    let mut file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(&temporary)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    if failpoint == PlannerStoreFailpointV1::AfterTemporarySyncBeforeRename {
        let _ = std::fs::remove_file(temporary);
        return Err(PlannerStoreError::InjectedFailure(failpoint));
    }
    std::fs::rename(&temporary, path)?;
    if failpoint == PlannerStoreFailpointV1::AfterRenameBeforeDirectorySync {
        return Err(PlannerStoreError::InjectedFailure(failpoint));
    }
    sync_directory(parent)
}

fn sync_directory(path: &Path) -> Result<(), PlannerStoreError> {
    File::open(path)?.sync_all()?;
    Ok(())
}

fn read_u8(bytes: &[u8], cursor: &mut usize) -> Result<u8, PlannerStoreError> {
    let value = *bytes.get(*cursor).ok_or(PlannerStoreError::CorruptFrame)?;
    *cursor += 1;
    Ok(value)
}

fn read_u64(bytes: &[u8], cursor: &mut usize) -> Result<u64, PlannerStoreError> {
    let end = cursor.checked_add(8).ok_or(PlannerStoreError::CorruptFrame)?;
    let value = u64::from_be_bytes(
        bytes
            .get(*cursor..end)
            .ok_or(PlannerStoreError::CorruptFrame)?
            .try_into()
            .map_err(|_| PlannerStoreError::CorruptFrame)?,
    );
    *cursor = end;
    Ok(value)
}

fn read_digest(bytes: &[u8], cursor: &mut usize) -> Result<Digest32, PlannerStoreError> {
    let end = cursor.checked_add(32).ok_or(PlannerStoreError::CorruptFrame)?;
    let value: [u8; 32] = bytes
        .get(*cursor..end)
        .ok_or(PlannerStoreError::CorruptFrame)?
        .try_into()
        .map_err(|_| PlannerStoreError::CorruptFrame)?;
    *cursor = end;
    Ok(Digest32::from_array(value))
}

#[cfg(test)]
#[path = "planner_store_tests.rs"]
mod tests;
