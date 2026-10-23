//! File-backed publication owner for `CellDefinitionV2`.
//!
//! `CellDefinitionOwnerV1` already enforces generation monotonicity and
//! computes the registry chain.  This wrapper gives that owner a durable
//! reload boundary.  The file is a versioned, length-delimited snapshot and
//! is replaced with a synced temporary file on each appended publication.
//! Definitions are decoded and re-published during open, so the in-memory
//! chain is rebuilt rather than trusting persisted digests.

use std::fmt;
use std::fs;
use std::fs::File;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::CellCapabilityProfileV1;
use codex_hepta_types::CellDefinitionV2;
use codex_hepta_types::CellPersistenceClassV1;
use codex_hepta_types::CellRoleV1;
use codex_hepta_types::CellUpdateModeV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::CellDefinitionOwnerV1;
use crate::CellDefinitionPublicationReceiptV1;
use crate::CellDefinitionRegistrySnapshotV1;
use crate::DefinitionPublicationDispositionV1;
use crate::ProductionOwnerError;

const MAGIC: &[u8] = b"HEPTA-CELL-DEFINITION-SNAPSHOT-V1\0";
const MAX_RECORDS: usize = 16_384;
const MAX_RECORD_BYTES: usize = 32 * 1024;
const MAX_FILE_BYTES: u64 = 128 * 1024 * 1024;

#[derive(Debug)]
pub enum DurableDefinitionOwnerError {
    Io(std::io::Error),
    InvalidSnapshot(&'static str),
    InvalidField(String),
    PredecessorMismatch {
        expected: Digest32,
        actual: Digest32,
    },
    Owner(ProductionOwnerError),
}

impl fmt::Display for DurableDefinitionOwnerError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for DurableDefinitionOwnerError {}

impl From<std::io::Error> for DurableDefinitionOwnerError {
    fn from(error: std::io::Error) -> Self {
        Self::Io(error)
    }
}

impl From<ProductionOwnerError> for DurableDefinitionOwnerError {
    fn from(error: ProductionOwnerError) -> Self {
        Self::Owner(error)
    }
}

/// Durable registry owner.  A missing path is initialized; an existing path
/// is fully verified before this function returns.
#[derive(Clone, Debug)]
pub struct DurableCellDefinitionOwnerV1 {
    path: PathBuf,
    owner: CellDefinitionOwnerV1,
}

impl DurableCellDefinitionOwnerV1 {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, DurableDefinitionOwnerError> {
        let path = path.as_ref().to_path_buf();
        reject_symlink(&path)?;
        if !path.exists() {
            let mut file = File::create(&path)?;
            file.write_all(MAGIC)?;
            file.write_all(&0_u32.to_be_bytes())?;
            file.sync_all()?;
        }
        let bytes = fs::read(&path)?;
        let owner = decode_snapshot(&bytes)?;
        Ok(Self { path, owner })
    }

    pub fn publish(
        &mut self,
        definition: CellDefinitionV2,
    ) -> Result<CellDefinitionPublicationReceiptV1, DurableDefinitionOwnerError> {
        let mut candidate = self.owner.clone();
        let receipt = candidate.publish(definition)?;
        if receipt.disposition == DefinitionPublicationDispositionV1::Appended {
            persist_snapshot(&self.path, &candidate)?;
            self.owner = candidate;
        }
        Ok(receipt)
    }

    /// Publish only when both the in-memory and persisted registry heads still
    /// equal `expected_head_digest`.  This is the registry predecessor fence
    /// used by callers holding a single-writer lease.
    pub fn publish_if_head(
        &mut self,
        definition: CellDefinitionV2,
        expected_head_digest: Digest32,
    ) -> Result<CellDefinitionPublicationReceiptV1, DurableDefinitionOwnerError> {
        let actual_memory_head = self.owner.head_digest();
        if actual_memory_head != expected_head_digest {
            return Err(DurableDefinitionOwnerError::PredecessorMismatch {
                expected: expected_head_digest,
                actual: actual_memory_head,
            });
        }
        let mut candidate = self.owner.clone();
        let receipt = candidate.publish(definition)?;
        if receipt.disposition == DefinitionPublicationDispositionV1::Appended {
            persist_snapshot_if_head(&self.path, &candidate, expected_head_digest)?;
            self.owner = candidate;
        }
        Ok(receipt)
    }

    #[must_use]
    pub fn latest(&self, cell_id: &StableId) -> Option<&CellDefinitionV2> {
        self.owner.latest(cell_id)
    }

    #[must_use]
    pub fn head_digest(&self) -> Digest32 {
        self.owner.head_digest()
    }

    #[must_use]
    pub fn snapshot(&self) -> CellDefinitionRegistrySnapshotV1 {
        self.owner.snapshot()
    }

    #[must_use]
    pub fn path(&self) -> &Path {
        &self.path
    }
}

fn reject_symlink(path: &Path) -> Result<(), DurableDefinitionOwnerError> {
    if let Ok(metadata) = fs::symlink_metadata(path) {
        if metadata.file_type().is_symlink() {
            return Err(DurableDefinitionOwnerError::InvalidSnapshot(
                "symlink registry path",
            ));
        }
        if !metadata.is_file() {
            return Err(DurableDefinitionOwnerError::InvalidSnapshot(
                "registry path is not a file",
            ));
        }
    }
    Ok(())
}

fn persist_snapshot_if_head(
    path: &Path,
    owner: &CellDefinitionOwnerV1,
    expected_head_digest: Digest32,
) -> Result<(), DurableDefinitionOwnerError> {
    reject_symlink(path)?;
    let actual_head_digest = if path.exists() {
        let bytes = fs::read(path)?;
        decode_snapshot(&bytes)?.head_digest()
    } else {
        Digest32::ZERO
    };
    if actual_head_digest != expected_head_digest {
        return Err(DurableDefinitionOwnerError::PredecessorMismatch {
            expected: expected_head_digest,
            actual: actual_head_digest,
        });
    }
    persist_snapshot(path, owner)
}

fn persist_snapshot(
    path: &Path,
    owner: &CellDefinitionOwnerV1,
) -> Result<(), DurableDefinitionOwnerError> {
    reject_symlink(path)?;
    let temp = path.with_extension("snapshot.tmp");
    reject_symlink(&temp)?;
    let bytes = encode_snapshot(owner.records())?;
    let mut file = fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temp)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    drop(file);
    fs::rename(&temp, path)?;
    if let Some(parent) = path.parent() {
        if parent.as_os_str().is_empty() {
            return Ok(());
        }
        if let Ok(directory) = File::open(parent) {
            let _ = directory.sync_all();
        }
    }
    Ok(())
}

fn encode_snapshot(
    records: &[crate::CellDefinitionRecordV1],
) -> Result<Vec<u8>, DurableDefinitionOwnerError> {
    if records.len() > MAX_RECORDS {
        return Err(DurableDefinitionOwnerError::InvalidSnapshot(
            "too many definitions",
        ));
    }
    let mut output = Vec::with_capacity(MAGIC.len() + 4 + records.len() * 512);
    output.extend_from_slice(MAGIC);
    put_u32(&mut output, records.len() as u32);
    for record in records {
        let payload = encode_record(record)?;
        if payload.len() > MAX_RECORD_BYTES {
            return Err(DurableDefinitionOwnerError::InvalidSnapshot(
                "definition record too large",
            ));
        }
        put_u32(&mut output, payload.len() as u32);
        output.extend_from_slice(&payload);
    }
    Ok(output)
}

fn decode_snapshot(bytes: &[u8]) -> Result<CellDefinitionOwnerV1, DurableDefinitionOwnerError> {
    if bytes.len() > MAX_FILE_BYTES as usize {
        return Err(DurableDefinitionOwnerError::InvalidSnapshot(
            "snapshot too large",
        ));
    }
    let mut cursor = Cursor::new(bytes);
    if cursor.take(MAGIC.len())? != MAGIC {
        return Err(DurableDefinitionOwnerError::InvalidSnapshot(
            "bad snapshot magic",
        ));
    }
    let count = cursor.u32()? as usize;
    if count > MAX_RECORDS {
        return Err(DurableDefinitionOwnerError::InvalidSnapshot(
            "too many definitions",
        ));
    }
    let mut owner = CellDefinitionOwnerV1::new();
    for _ in 0..count {
        let length = cursor.u32()? as usize;
        if length > MAX_RECORD_BYTES {
            return Err(DurableDefinitionOwnerError::InvalidSnapshot(
                "definition record too large",
            ));
        }
        let (definition, expected) = decode_record(cursor.take(length)?)?;
        owner.publish(definition)?;
        let actual = owner
            .records()
            .last()
            .ok_or(DurableDefinitionOwnerError::InvalidSnapshot(
                "missing record",
            ))?;
        if actual.sequence != expected.sequence
            || actual.predecessor_head_digest != expected.predecessor_head_digest
            || actual.definition_digest != expected.definition_digest
            || actual.event_digest != expected.event_digest
            || actual.chain_digest != expected.chain_digest
        {
            return Err(DurableDefinitionOwnerError::InvalidSnapshot(
                "definition chain receipt mismatch",
            ));
        }
    }
    if !cursor.is_empty() {
        return Err(DurableDefinitionOwnerError::InvalidSnapshot(
            "trailing snapshot bytes",
        ));
    }
    Ok(owner)
}

fn encode_definition(
    definition: &CellDefinitionV2,
) -> Result<Vec<u8>, DurableDefinitionOwnerError> {
    definition
        .validate()
        .map_err(|error| DurableDefinitionOwnerError::InvalidField(error.to_string()))?;
    let profile = &definition.capability_profile;
    let mut output = Vec::with_capacity(512);
    put_id(&mut output, &definition.cell_id)?;
    put_u64(&mut output, definition.generation.get());
    put_digest(&mut output, definition.scope_digest);
    put_digest(&mut output, definition.lineage_digest);
    put_role(&mut output, definition.role);
    put_digest(&mut output, definition.parameter_bundle_digest);
    put_digest(&mut output, definition.state_schema_digest);
    put_digest(&mut output, definition.port_abi_digest);
    put_id(&mut output, &definition.owner_module)?;
    put_digest(&mut output, definition.objective_digest);
    put_optional_role(&mut output, definition.fallback_role);
    put_id(&mut output, &definition.evidence_owner)?;
    put_role(&mut output, profile.role);
    for digest in [
        profile.observation_schema_digest,
        profile.output_schema_digest,
        profile.state_schema_digest,
        profile.input_port_digest,
        profile.output_port_digest,
        profile.termination_port_digest,
    ] {
        put_digest(&mut output, digest);
    }
    put_id(&mut output, &profile.owner_module)?;
    output.push(profile.persistence_class.tag());
    output.push(profile.update_mode.tag());
    put_optional_role(&mut output, profile.fallback_role);
    put_digest(&mut output, profile.objective_digest);
    put_digest(&mut output, profile.resource_budget_digest);
    put_digest(&mut output, profile.evaluation_profile_digest);
    Ok(output)
}

fn encode_record(
    record: &crate::CellDefinitionRecordV1,
) -> Result<Vec<u8>, DurableDefinitionOwnerError> {
    let definition = encode_definition(&record.definition)?;
    let mut output = Vec::with_capacity(definition.len() + 8 + 32 * 4 + 4);
    put_u32(&mut output, definition.len() as u32);
    output.extend_from_slice(&definition);
    put_u64(&mut output, record.sequence.get());
    put_digest(&mut output, record.predecessor_head_digest);
    put_digest(&mut output, record.definition_digest);
    put_digest(&mut output, record.event_digest);
    put_digest(&mut output, record.chain_digest);
    Ok(output)
}

struct RecordMetadata {
    sequence: codex_hepta_types::LogicalSequence,
    predecessor_head_digest: Digest32,
    definition_digest: Digest32,
    event_digest: Digest32,
    chain_digest: Digest32,
}

fn decode_record(
    bytes: &[u8],
) -> Result<(CellDefinitionV2, RecordMetadata), DurableDefinitionOwnerError> {
    let mut cursor = Cursor::new(bytes);
    let definition_length = cursor.u32()? as usize;
    let definition = decode_definition(cursor.take(definition_length)?)?;
    let sequence = codex_hepta_types::LogicalSequence::new(cursor.u64()?)
        .map_err(|error| DurableDefinitionOwnerError::InvalidField(error.to_string()))?;
    let predecessor_head_digest = cursor.digest()?;
    let definition_digest = cursor.digest()?;
    let event_digest = cursor.digest()?;
    let chain_digest = cursor.digest()?;
    if !cursor.is_empty() {
        return Err(DurableDefinitionOwnerError::InvalidSnapshot(
            "trailing record bytes",
        ));
    }
    Ok((
        definition,
        RecordMetadata {
            sequence,
            predecessor_head_digest,
            definition_digest,
            event_digest,
            chain_digest,
        },
    ))
}

fn decode_definition(bytes: &[u8]) -> Result<CellDefinitionV2, DurableDefinitionOwnerError> {
    let mut cursor = Cursor::new(bytes);
    let cell_id = cursor.id()?;
    let generation = Generation::new(cursor.u64()?)
        .map_err(|error| DurableDefinitionOwnerError::InvalidField(error.to_string()))?;
    let scope_digest = cursor.digest()?;
    let lineage_digest = cursor.digest()?;
    let role = cursor.role()?;
    let parameter_bundle_digest = cursor.digest()?;
    let state_schema_digest = cursor.digest()?;
    let port_abi_digest = cursor.digest()?;
    let owner_module = cursor.id()?;
    let objective_digest = cursor.digest()?;
    let fallback_role = cursor.optional_role()?;
    let evidence_owner = cursor.id()?;
    let capability_role = cursor.role()?;
    let observation_schema_digest = cursor.digest()?;
    let output_schema_digest = cursor.digest()?;
    let capability_state_schema_digest = cursor.digest()?;
    let input_port_digest = cursor.digest()?;
    let output_port_digest = cursor.digest()?;
    let termination_port_digest = cursor.digest()?;
    let capability_owner_module = cursor.id()?;
    let persistence_class = persistence(cursor.byte()?)?;
    let update_mode = update_mode(cursor.byte()?)?;
    let capability_fallback = cursor.optional_role()?;
    let capability_objective_digest = cursor.digest()?;
    let resource_budget_digest = cursor.digest()?;
    let evaluation_profile_digest = cursor.digest()?;
    if !cursor.is_empty() {
        return Err(DurableDefinitionOwnerError::InvalidSnapshot(
            "trailing definition bytes",
        ));
    }
    let definition = CellDefinitionV2 {
        cell_id,
        generation,
        scope_digest,
        lineage_digest,
        role,
        capability_profile: CellCapabilityProfileV1 {
            role: capability_role,
            observation_schema_digest,
            output_schema_digest,
            state_schema_digest: capability_state_schema_digest,
            input_port_digest,
            output_port_digest,
            termination_port_digest,
            owner_module: capability_owner_module,
            persistence_class,
            update_mode,
            fallback_role: capability_fallback,
            objective_digest: capability_objective_digest,
            resource_budget_digest,
            evaluation_profile_digest,
            authority: AuthorityPosture::DENY_ALL,
        },
        parameter_bundle_digest,
        state_schema_digest,
        port_abi_digest,
        owner_module,
        objective_digest,
        fallback_role,
        evidence_owner,
        authority: AuthorityPosture::DENY_ALL,
    };
    definition
        .validate()
        .map_err(|error| DurableDefinitionOwnerError::InvalidField(error.to_string()))?;
    Ok(definition)
}

fn put_u32(output: &mut Vec<u8>, value: u32) {
    output.extend_from_slice(&value.to_be_bytes());
}

fn put_u64(output: &mut Vec<u8>, value: u64) {
    output.extend_from_slice(&value.to_be_bytes());
}

fn put_digest(output: &mut Vec<u8>, digest: Digest32) {
    output.extend_from_slice(digest.as_array());
}

fn put_id(output: &mut Vec<u8>, id: &StableId) -> Result<(), DurableDefinitionOwnerError> {
    let bytes = id.as_str().as_bytes();
    if bytes.len() > u16::MAX as usize {
        return Err(DurableDefinitionOwnerError::InvalidField(
            "identifier too large".to_string(),
        ));
    }
    output.extend_from_slice(&(bytes.len() as u16).to_be_bytes());
    output.extend_from_slice(bytes);
    Ok(())
}

fn put_role(output: &mut Vec<u8>, role: CellRoleV1) {
    output.push(role.tag());
}

fn put_optional_role(output: &mut Vec<u8>, role: Option<CellRoleV1>) {
    output.push(role.map_or(u8::MAX, CellRoleV1::tag));
}

fn role(tag: u8) -> Result<CellRoleV1, DurableDefinitionOwnerError> {
    [
        CellRoleV1::Representation,
        CellRoleV1::MemoryRead,
        CellRoleV1::Predictor,
        CellRoleV1::Value,
        CellRoleV1::Decision,
        CellRoleV1::Evaluator,
        CellRoleV1::Planner,
        CellRoleV1::Router,
        CellRoleV1::ActionProposal,
        CellRoleV1::Plasticity,
        CellRoleV1::Communication,
    ]
    .into_iter()
    .find(|candidate| candidate.tag() == tag)
    .ok_or(DurableDefinitionOwnerError::InvalidSnapshot("unknown role"))
}

fn optional_role(tag: u8) -> Result<Option<CellRoleV1>, DurableDefinitionOwnerError> {
    if tag == u8::MAX {
        Ok(None)
    } else {
        role(tag).map(Some)
    }
}

fn persistence(tag: u8) -> Result<CellPersistenceClassV1, DurableDefinitionOwnerError> {
    match tag {
        0 => Ok(CellPersistenceClassV1::Ephemeral),
        1 => Ok(CellPersistenceClassV1::Checkpointed),
        2 => Ok(CellPersistenceClassV1::Durable),
        3 => Ok(CellPersistenceClassV1::LedgerBacked),
        _ => Err(DurableDefinitionOwnerError::InvalidSnapshot(
            "unknown persistence class",
        )),
    }
}

fn update_mode(tag: u8) -> Result<CellUpdateModeV1, DurableDefinitionOwnerError> {
    match tag {
        0 => Ok(CellUpdateModeV1::InferenceOnly),
        1 => Ok(CellUpdateModeV1::OutcomeProposal),
        2 => Ok(CellUpdateModeV1::OnlineConstrained),
        3 => Ok(CellUpdateModeV1::BatchCandidate),
        _ => Err(DurableDefinitionOwnerError::InvalidSnapshot(
            "unknown update mode",
        )),
    }
}

struct Cursor<'a> {
    bytes: &'a [u8],
    position: usize,
}

impl<'a> Cursor<'a> {
    const fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, position: 0 }
    }

    fn take(&mut self, length: usize) -> Result<&'a [u8], DurableDefinitionOwnerError> {
        let end = self.position.checked_add(length).ok_or(
            DurableDefinitionOwnerError::InvalidSnapshot("cursor overflow"),
        )?;
        if end > self.bytes.len() {
            return Err(DurableDefinitionOwnerError::InvalidSnapshot(
                "truncated snapshot",
            ));
        }
        let value = &self.bytes[self.position..end];
        self.position = end;
        Ok(value)
    }

    fn byte(&mut self) -> Result<u8, DurableDefinitionOwnerError> {
        Ok(self.take(1)?[0])
    }

    fn u32(&mut self) -> Result<u32, DurableDefinitionOwnerError> {
        let mut bytes = [0; 4];
        bytes.copy_from_slice(self.take(4)?);
        Ok(u32::from_be_bytes(bytes))
    }

    fn u64(&mut self) -> Result<u64, DurableDefinitionOwnerError> {
        let mut bytes = [0; 8];
        bytes.copy_from_slice(self.take(8)?);
        Ok(u64::from_be_bytes(bytes))
    }

    fn digest(&mut self) -> Result<Digest32, DurableDefinitionOwnerError> {
        let mut bytes = [0; 32];
        bytes.copy_from_slice(self.take(32)?);
        Ok(Digest32::from_array(bytes))
    }

    fn id(&mut self) -> Result<StableId, DurableDefinitionOwnerError> {
        let length = {
            let mut bytes = [0; 2];
            bytes.copy_from_slice(self.take(2)?);
            u16::from_be_bytes(bytes) as usize
        };
        let value = std::str::from_utf8(self.take(length)?).map_err(|_| {
            DurableDefinitionOwnerError::InvalidSnapshot("invalid identifier UTF-8")
        })?;
        StableId::new(value)
            .map_err(|error| DurableDefinitionOwnerError::InvalidField(error.to_string()))
    }

    fn role(&mut self) -> Result<CellRoleV1, DurableDefinitionOwnerError> {
        role(self.byte()?)
    }

    fn optional_role(&mut self) -> Result<Option<CellRoleV1>, DurableDefinitionOwnerError> {
        optional_role(self.byte()?)
    }

    fn is_empty(&self) -> bool {
        self.position == self.bytes.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_types::CellPersistenceClassV1;
    use codex_hepta_types::CellRoleV1;
    use codex_hepta_types::CellUpdateModeV1;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn definition(generation: u64) -> CellDefinitionV2 {
        let digest = Digest32::of_bytes(&[generation as u8]);
        CellDefinitionV2 {
            cell_id: id("cell.durable"),
            generation: Generation::new(generation).expect("generation"),
            scope_digest: digest,
            lineage_digest: Digest32::of_bytes(b"lineage"),
            role: CellRoleV1::Representation,
            capability_profile: CellCapabilityProfileV1 {
                role: CellRoleV1::Representation,
                observation_schema_digest: digest,
                output_schema_digest: digest,
                state_schema_digest: digest,
                input_port_digest: digest,
                output_port_digest: digest,
                termination_port_digest: digest,
                owner_module: id("hepta.neuron"),
                persistence_class: CellPersistenceClassV1::Checkpointed,
                update_mode: CellUpdateModeV1::InferenceOnly,
                fallback_role: None,
                objective_digest: digest,
                resource_budget_digest: digest,
                evaluation_profile_digest: digest,
                authority: AuthorityPosture::DENY_ALL,
            },
            parameter_bundle_digest: digest,
            state_schema_digest: digest,
            port_abi_digest: digest,
            owner_module: id("hepta.neuron"),
            objective_digest: digest,
            fallback_role: None,
            evidence_owner: id("hepta.observer"),
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    #[test]
    fn publication_survives_reopen_and_rejects_tamper() {
        let path = std::env::temp_dir().join(format!(
            "hepta-cell-definition-{}-{}.bin",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock")
                .as_nanos()
        ));
        let mut owner = DurableCellDefinitionOwnerV1::open(&path).expect("open");
        owner.publish(definition(1)).expect("publish");
        owner.publish(definition(2)).expect("publish");
        let restored = DurableCellDefinitionOwnerV1::open(&path).expect("reload");
        assert_eq!(restored.head_digest(), owner.head_digest());
        assert_eq!(
            restored.latest(&id("cell.durable")),
            owner.latest(&id("cell.durable"))
        );
        let mut bytes = fs::read(&path).expect("read");
        *bytes.last_mut().expect("bytes") ^= 0x80;
        fs::write(&path, bytes).expect("tamper");
        assert!(DurableCellDefinitionOwnerV1::open(&path).is_err());
        let _ = fs::remove_file(path);
    }

    #[test]
    fn fenced_publication_rejects_stale_registry_head() {
        let path = std::env::temp_dir().join(format!(
            "hepta-cell-definition-fence-{}-{}.bin",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock")
                .as_nanos()
        ));
        let mut owner = DurableCellDefinitionOwnerV1::open(&path).expect("open");
        let first = owner
            .publish_if_head(definition(1), Digest32::ZERO)
            .expect("first");
        assert_eq!(first.sequence.get(), 1);
        let stale = owner.publish_if_head(definition(2), Digest32::ZERO);
        assert!(matches!(
            stale,
            Err(DurableDefinitionOwnerError::PredecessorMismatch {
                expected,
                actual
            }) if expected == Digest32::ZERO && actual == owner.head_digest()
        ));
        owner
            .publish_if_head(definition(2), owner.head_digest())
            .expect("successor");
        let _ = fs::remove_file(path);
    }
}
