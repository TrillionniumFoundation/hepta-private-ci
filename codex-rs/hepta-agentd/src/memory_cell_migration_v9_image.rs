use std::collections::BTreeMap;
use std::fs::File;
use std::io::Read;
use std::os::unix::fs::PermissionsExt;
use std::path::Component;
use std::path::Path;

use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CognitiveRecoveryAnchor;
use codex_hepta_memory::MemoryCellOwnerSnapshotV1;
use serde::Deserialize;
use serde::Serialize;

use crate::LoadedMemoryCellBundleV1;

use super::MAX_HEADER_BYTES;
use super::MAX_IMAGE_BYTES;
use super::failure;

const MAGIC: &[u8] = b"HEPTA-MEMORY-IMAGE-V9\0";
const MAX_FILES: usize = 128;

/// Integrity pins from the actual source, never a deserialized access grant.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MemoryCellMigrationPinV9 {
    pub owner_agent_id: AgentId,
    pub scope: ContractIdV1,
    pub owner_cut_digest: ContractDigestV1,
    pub generation: ContractGenerationV1,
    pub bundle_digest: ContractDigestV1,
    pub cognitive_anchor: CognitiveRecoveryAnchor,
}

impl MemoryCellMigrationPinV9 {
    /// The image transport is payload agnostic. Inventory readers still
    /// independently load the inventory bundle and revalidate its owner cut;
    /// this pin neither selects that bundle nor creates destination authority.
    pub fn from_inventory_source(
        snapshot: &codex_hepta_memory::MemoryInventoryOwnerSnapshotV1,
        bundle: &crate::LoadedMemoryInventoryBundleV1,
        cognitive_anchor: CognitiveRecoveryAnchor,
    ) -> Result<Self, String> {
        bundle.validate_owner_snapshot(snapshot)?;
        if cognitive_anchor.owner_agent_id != *snapshot.owner_agent_id() {
            return Err("inventory migration cognitive witness owner mismatch".into());
        }
        Ok(Self {
            owner_agent_id: snapshot.owner_agent_id().clone(),
            scope: snapshot.scope().clone(),
            owner_cut_digest: snapshot.owner_cut_digest(),
            generation: bundle.generation(),
            bundle_digest: bundle.bundle_digest(),
            cognitive_anchor,
        })
    }

    pub fn from_source(
        snapshot: &MemoryCellOwnerSnapshotV1,
        bundle: &LoadedMemoryCellBundleV1,
        cognitive_anchor: CognitiveRecoveryAnchor,
    ) -> Result<Self, String> {
        bundle.validate_owner_snapshot(snapshot)?;
        if cognitive_anchor.owner_agent_id != *snapshot.owner_agent_id() {
            return Err("migration cognitive witness owner mismatch".into());
        }
        Ok(Self {
            owner_agent_id: snapshot.owner_agent_id().clone(),
            scope: snapshot.scope().clone(),
            owner_cut_digest: snapshot.owner_cut_digest(),
            generation: bundle.generation(),
            bundle_digest: bundle.bundle_digest(),
            cognitive_anchor,
        })
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ImageFile {
    pub path: String,
    pub bytes: u64,
    pub sha256: Sha256Digest,
    pub mode: u32,
}

/// One complete byte/mode inventory and source version. Transport generation
/// is independent of the selected model's generation.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MemoryCellMigrationManifestV9 {
    pub(super) schema: String,
    pub(super) destination: String,
    pub(super) generation: u64,
    pub(super) predecessor: Option<Sha256Digest>,
    pub(super) pin: MemoryCellMigrationPinV9,
    pub(super) files: Vec<ImageFile>,
}

impl MemoryCellMigrationManifestV9 {
    pub fn pin(&self) -> &MemoryCellMigrationPinV9 {
        &self.pin
    }

    pub fn generation(&self) -> u64 {
        self.generation
    }

    pub fn destination(&self) -> &str {
        &self.destination
    }

    pub fn digest(&self) -> Result<Sha256Digest, String> {
        serde_json::to_vec(self)
            .map(|raw| Sha256Digest::for_bytes(&raw))
            .map_err(failure)
    }

    pub(super) fn validate(&self) -> Result<(), String> {
        if self.schema != "hepta.memory.migration.image.v9"
            || self.destination.is_empty()
            || self.destination.len() > 128
            || self.generation == 0
            || (self.generation == 1) != self.predecessor.is_none()
            || self.files.is_empty()
            || self.files.len() > MAX_FILES
            || self.pin.owner_agent_id != self.pin.cognitive_anchor.owner_agent_id
        {
            return Err("migration manifest schema, owner, generation or inventory".into());
        }
        if let Some(digest) = &self.predecessor {
            Sha256Digest::parse(digest.as_str().to_string()).map_err(failure)?;
        }
        let mut previous: Option<&str> = None;
        let mut bytes = 0_u64;
        for file in &self.files {
            validate_path(&file.path)?;
            Sha256Digest::parse(file.sha256.as_str().to_string()).map_err(failure)?;
            bytes = bytes
                .checked_add(file.bytes)
                .ok_or("migration inventory size overflow")?;
            if previous.is_some_and(|prior| prior >= file.path.as_str())
                || !matches!(file.mode, 0o400 | 0o444 | 0o600 | 0o644)
                || bytes > MAX_IMAGE_BYTES as u64
            {
                return Err("migration file order, duplicate, mode or inventory size".into());
            }
            previous = Some(&file.path);
        }
        Ok(())
    }
}

/// Exact TaskFlow payload. Capture only closed/quiesced source descriptors;
/// byte hashes do not prove that a live SQLite database was copied atomically.
pub struct MemoryCellMigrationImageV9 {
    manifest: MemoryCellMigrationManifestV9,
    bytes: Vec<u8>,
}

impl MemoryCellMigrationImageV9 {
    pub fn capture(
        destination: String,
        generation: u64,
        predecessor: Option<Sha256Digest>,
        pin: MemoryCellMigrationPinV9,
        files: BTreeMap<String, File>,
    ) -> Result<Self, String> {
        if destination.is_empty()
            || destination.len() > 128
            || generation == 0
            || (generation == 1) != predecessor.is_none()
            || files.is_empty()
            || files.len() > MAX_FILES
        {
            return Err("migration destination, generation or file inventory bound".into());
        }
        let mut inventory = Vec::new();
        let mut contents = Vec::new();
        for (path, mut file) in files {
            validate_path(&path)?;
            let before = file.metadata().map_err(failure)?;
            let mode = before.permissions().mode() & 0o777;
            if !before.is_file()
                || before.len() > MAX_IMAGE_BYTES as u64
                || !matches!(mode, 0o400 | 0o444 | 0o600 | 0o644)
            {
                return Err("migration requires bounded regular non-executable data files".into());
            }
            let start = contents.len();
            file.by_ref()
                .take((MAX_IMAGE_BYTES - start + 1) as u64)
                .read_to_end(&mut contents)
                .map_err(failure)?;
            let after = file.metadata().map_err(failure)?;
            if contents.len() > MAX_IMAGE_BYTES
                || (contents.len() - start) as u64 != before.len()
                || after.len() != before.len()
                || after.modified().map_err(failure)? != before.modified().map_err(failure)?
            {
                return Err("migration source changed or image bound exceeded".into());
            }
            inventory.push(ImageFile {
                path,
                bytes: before.len(),
                sha256: Sha256Digest::for_bytes(&contents[start..]),
                mode,
            });
        }
        let manifest = MemoryCellMigrationManifestV9 {
            schema: "hepta.memory.migration.image.v9".into(),
            destination,
            generation,
            predecessor,
            pin,
            files: inventory,
        };
        let header = serde_json::to_vec(&manifest).map_err(failure)?;
        if header.len() > MAX_HEADER_BYTES
            || MAGIC.len() + 4 + header.len() + contents.len() > MAX_IMAGE_BYTES
        {
            return Err("migration encoded image bound exceeded".into());
        }
        let mut bytes = MAGIC.to_vec();
        bytes.extend_from_slice(&(header.len() as u32).to_be_bytes());
        bytes.extend_from_slice(&header);
        bytes.extend_from_slice(&contents);
        Ok(Self { manifest, bytes })
    }

    pub fn manifest(&self) -> &MemoryCellMigrationManifestV9 {
        &self.manifest
    }
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }
    pub fn digest(&self) -> Sha256Digest {
        Sha256Digest::for_bytes(&self.bytes)
    }
}

pub(super) fn decode(raw: &[u8]) -> Result<(MemoryCellMigrationManifestV9, Vec<&[u8]>), String> {
    if raw.len() > MAX_IMAGE_BYTES || !raw.starts_with(MAGIC) || raw.len() < MAGIC.len() + 4 {
        return Err("migration image framing".into());
    }
    let size = u32::from_be_bytes(
        raw[MAGIC.len()..MAGIC.len() + 4]
            .try_into()
            .map_err(failure)?,
    ) as usize;
    let offset = MAGIC.len() + 4;
    if size > MAX_HEADER_BYTES || offset + size > raw.len() {
        return Err("migration header bound".into());
    }
    let manifest: MemoryCellMigrationManifestV9 =
        serde_json::from_slice(&raw[offset..offset + size]).map_err(failure)?;
    manifest.validate()?;
    let mut offset = offset + size;
    let mut contents = Vec::new();
    for file in &manifest.files {
        let length = usize::try_from(file.bytes).map_err(failure)?;
        let end = offset
            .checked_add(length)
            .ok_or("migration length overflow")?;
        let value = raw.get(offset..end).ok_or("migration truncated contents")?;
        if Sha256Digest::for_bytes(value) != file.sha256 {
            return Err("migration file digest mismatch".into());
        }
        contents.push(value);
        offset = end;
    }
    if offset != raw.len() {
        return Err("migration trailing contents".into());
    }
    Ok((manifest, contents))
}

pub(super) fn validate_path(value: &str) -> Result<(), String> {
    if value.is_empty()
        || value.len() > 256
        || value
            .split('/')
            .any(|part| part.is_empty() || part.ends_with(".hepta-v9-tmp"))
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"/._:-".contains(&byte))
        || Path::new(value)
            .components()
            .any(|part| !matches!(part, Component::Normal(_)))
    {
        return Err("migration path must be a bounded normal relative data path".into());
    }
    Ok(())
}
