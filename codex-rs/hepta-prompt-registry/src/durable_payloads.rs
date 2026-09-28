//! Storage-v4 payload extent file under the existing exclusive registry owner.
//!
//! The atomic metadata snapshot selects the committed extents. New bytes are
//! synced before publication; an unselected trailing write is never a fact.
//! Recovery verifies every referenced byte before trimming only an orphan tail.
//! This reduces payload write amplification, not metadata or hot-memory growth.

use std::collections::BTreeMap;
use std::fs::File;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use serde::Deserialize;
use serde::Serialize;

use super::Access;
use super::DurableRegistryError;
use super::StoredPayload;
use super::StoredV2;
use super::StoredV4 as StoredStateV4;
use super::map_precommit_io;
use super::open_private;
use crate::PromptRegistry;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

pub(super) const FILE_NAME: &str = "registry.payloads";
pub(super) const ALTERNATE_FILE_NAME: &str = "registry.payloads.alternate";

/// Only these two private basenames can ever be selected. No path from a
/// checkpoint is opened directly and staging space cannot grow by generations.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum PayloadSlot {
    Primary,
    Alternate,
}

impl PayloadSlot {
    pub const fn file_name(self) -> &'static str {
        match self {
            Self::Primary => FILE_NAME,
            Self::Alternate => ALTERNATE_FILE_NAME,
        }
    }

    pub const fn other(self) -> Self {
        match self {
            Self::Primary => Self::Alternate,
            Self::Alternate => Self::Primary,
        }
    }
}
const MAGIC: &[u8] = b"HEPTA-PROMPT-PAYLOADS-V1\0";
pub(super) const MAX_PAYLOAD_BYTES: u64 = 32 * 1024 * 1024;
pub(super) const MAX_PHYSICAL_PAYLOAD_FILE_BYTES: u64 = MAX_PAYLOAD_BYTES + MAGIC.len() as u64;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct PayloadReference {
    realization_id: String,
    offset: u64,
    length: u64,
    digest: [u8; 32],
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct StoredV3 {
    pub schema: u32,
    // Legacy V3 (and transitional V4) embedded the V2 semantic image.
    // Embedded payloads must be empty; there is only one physical payload copy.
    pub state: StoredV2,
    pub payload_references: Vec<PayloadReference>,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct StoredV4 {
    pub schema: u32,
    // Strict V4 requires the embedded semantic image to declare schema 4 and
    // requires relations to be present rather than defaulted.
    pub state: StoredStateV4,
    pub payload_references: Vec<PayloadReference>,
}

/// V5 selects one payload slot atomically with the unchanged V4 semantic
/// image. Older binaries reject the outer version rather than guessing a file.
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct StoredV5 {
    pub schema: u32,
    pub state: StoredStateV4,
    pub payload_slot: PayloadSlot,
    pub payload_references: Vec<PayloadReference>,
}

#[derive(Clone)]
pub(super) struct PayloadState {
    slot: PayloadSlot,
    generation_manifest: bool,
    references: BTreeMap<String, PayloadReference>,
    committed_end: u64,
    initialized: bool,
}

impl Default for PayloadState {
    fn default() -> Self {
        Self {
            slot: PayloadSlot::Primary,
            generation_manifest: false,
            references: BTreeMap::new(),
            committed_end: MAGIC.len() as u64,
            initialized: false,
        }
    }
}

impl PayloadState {
    pub const fn slot(&self) -> PayloadSlot {
        self.slot
    }

    pub const fn file_name(&self) -> &'static str {
        self.slot.file_name()
    }

    pub const fn uses_generation_manifest(&self) -> bool {
        self.generation_manifest
    }

    pub fn next_generation(&self) -> Self {
        Self {
            slot: self.slot.other(),
            generation_manifest: true,
            ..Self::default()
        }
    }

    pub fn hydrate_v5(
        directory: &File,
        mut stored: StoredV5,
    ) -> Result<(Self, StoredStateV4), DurableRegistryError> {
        if stored.schema != 5 || stored.state.schema != super::STORE_SCHEMA_V4 {
            return Err(DurableRegistryError::Corrupt);
        }
        let mut payloads = Self::hydrate_payloads(
            directory,
            &mut stored.state.payloads,
            stored.payload_references,
            stored.payload_slot,
        )?;
        payloads.generation_manifest = true;
        Ok((payloads, stored.state))
    }

    pub fn selected_file_bytes(&self) -> u64 {
        self.committed_end
    }

    pub fn is_initialized(&self) -> bool {
        self.initialized
    }

    pub fn references(&self) -> Vec<PayloadReference> {
        self.references.values().cloned().collect()
    }

    pub fn hydrate_v3(
        directory: &File,
        mut stored: StoredV3,
    ) -> Result<(Self, StoredV2), DurableRegistryError> {
        if stored.schema != 3 && stored.schema != 4 {
            return Err(DurableRegistryError::Corrupt);
        }
        let payloads = Self::hydrate_payloads(
            directory,
            &mut stored.state.payloads,
            stored.payload_references,
            PayloadSlot::Primary,
        )?;
        Ok((payloads, stored.state))
    }

    pub fn hydrate_v4(
        directory: &File,
        mut stored: StoredV4,
    ) -> Result<(Self, StoredStateV4), DurableRegistryError> {
        if stored.schema != 4 || stored.state.schema != super::STORE_SCHEMA_V4 {
            return Err(DurableRegistryError::Corrupt);
        }
        let payloads = Self::hydrate_payloads(
            directory,
            &mut stored.state.payloads,
            stored.payload_references,
            PayloadSlot::Primary,
        )?;
        Ok((payloads, stored.state))
    }

    fn hydrate_payloads(
        directory: &File,
        embedded_payloads: &mut Vec<StoredPayload>,
        payload_references: Vec<PayloadReference>,
        slot: PayloadSlot,
    ) -> Result<Self, DurableRegistryError> {
        if !embedded_payloads.is_empty() || payload_references.len() > crate::MAX_RECORDS {
            return Err(DurableRegistryError::Corrupt);
        }
        let mut ordered = payload_references;
        ordered.sort_by_key(|reference| reference.offset);
        let mut committed_end = MAGIC.len() as u64;
        let mut references = BTreeMap::new();
        for reference in ordered {
            if reference.offset != committed_end
                || reference.length == 0
                || reference.length > crate::MAX_REALIZATION_PAYLOAD_BYTES as u64
                || references.contains_key(&reference.realization_id)
            {
                return Err(DurableRegistryError::Corrupt);
            }
            committed_end = committed_end
                .checked_add(reference.length)
                .filter(|end| *end <= MAX_PAYLOAD_BYTES + MAGIC.len() as u64)
                .ok_or(DurableRegistryError::Corrupt)?;
            references.insert(reference.realization_id.clone(), reference);
        }
        let mut file = open_private(directory, slot.file_name(), Access::Read)?;
        require_header(&mut file)?;
        if file.metadata().map_err(map_precommit_io)?.len() < committed_end {
            return Err(DurableRegistryError::Corrupt);
        }
        for reference in references.values() {
            file.seek(SeekFrom::Start(reference.offset))
                .map_err(map_precommit_io)?;
            let mut payload = vec![0; reference.length as usize];
            file.read_exact(&mut payload)
                .map_err(|_| DurableRegistryError::Corrupt)?;
            if Digest32::of_bytes(&payload).into_array() != reference.digest {
                return Err(DurableRegistryError::Corrupt);
            }
            embedded_payloads.push(StoredPayload {
                realization_id: reference.realization_id.clone(),
                payload,
            });
        }
        Ok(Self {
            slot,
            generation_manifest: false,
            references,
            committed_end,
            initialized: true,
        })
    }

    /// Only called after full V2 semantic/configuration validation succeeded.
    /// The selected manifest already proves the prefix; shortening that prefix
    /// is never recovery. No committed record or revoked payload is collected.
    pub fn discard_unselected_tail(&self, directory: &File) -> Result<(), DurableRegistryError> {
        let file = open_private(directory, self.file_name(), Access::Create)?;
        let length = file.metadata().map_err(map_precommit_io)?.len();
        if length < self.committed_end {
            return Err(DurableRegistryError::Corrupt);
        }
        if length > self.committed_end {
            file.set_len(self.committed_end).map_err(map_precommit_io)?;
            file.sync_all().map_err(map_precommit_io)?;
        }
        Ok(())
    }

    /// Pure admission before any storage writes. Existing IDs are immutable.
    pub fn successor(&self, registry: &PromptRegistry) -> Result<Self, DurableRegistryError> {
        for name in self.references.keys() {
            let id = StableId::new(name).map_err(|_| DurableRegistryError::Corrupt)?;
            if !registry.realization_payloads.contains_key(&id) {
                return Err(DurableRegistryError::Corrupt);
            }
        }
        let mut next = self.clone();
        for (id, payload) in &registry.realization_payloads {
            let binding = registry
                .realization_bindings
                .get(id)
                .ok_or(DurableRegistryError::Corrupt)?;
            if payload.is_empty() || payload.len() > crate::MAX_REALIZATION_PAYLOAD_BYTES {
                return Err(DurableRegistryError::Corrupt);
            }
            let digest = binding.payload_digest.into_array();
            if let Some(previous) = next.references.get(id.as_str()) {
                if previous.length != payload.len() as u64 || previous.digest != digest {
                    return Err(DurableRegistryError::Corrupt);
                }
                continue;
            }
            if Digest32::of_bytes(payload).into_array() != digest {
                return Err(DurableRegistryError::Corrupt);
            }
            let reference = PayloadReference {
                realization_id: id.to_string(),
                offset: next.committed_end,
                length: payload.len() as u64,
                digest,
            };
            next.committed_end = next
                .committed_end
                .checked_add(reference.length)
                .filter(|end| *end <= MAX_PAYLOAD_BYTES + MAGIC.len() as u64)
                .ok_or(DurableRegistryError::CapacityExceeded)?;
            next.references.insert(id.to_string(), reference);
        }
        next.initialized = true;
        Ok(next)
    }

    /// Append only newly referenced extents, then make their names and bytes
    /// durable BEFORE the metadata rename. Errors leave the old manifest valid.
    pub fn stage(
        &self,
        successor: &Self,
        registry: &PromptRegistry,
        directory: &File,
    ) -> Result<(), DurableRegistryError> {
        if self.initialized && successor.committed_end == self.committed_end {
            let mut file = open_private(directory, self.file_name(), Access::Read)?;
            require_header(&mut file)?;
            if file.metadata().map_err(map_precommit_io)?.len() < self.committed_end {
                return Err(DurableRegistryError::Corrupt);
            }
            return Ok(());
        }
        let mut file = open_private(directory, self.file_name(), Access::Create)?;
        if self.initialized {
            require_header(&mut file)?;
            if file.metadata().map_err(map_precommit_io)?.len() < self.committed_end {
                return Err(DurableRegistryError::Corrupt);
            }
        } else {
            // Only legacy V1/V2 or first initialization selects this case.
            // Any old extent file is unreferenced by that selected snapshot.
            file.set_len(0).map_err(map_precommit_io)?;
            file.write_all(MAGIC).map_err(map_precommit_io)?;
        }
        file.set_len(self.committed_end).map_err(map_precommit_io)?;
        let mut appended: Vec<_> = successor
            .references
            .values()
            .filter(|reference| reference.offset >= self.committed_end)
            .collect();
        appended.sort_by_key(|reference| reference.offset);
        for reference in appended {
            let id = StableId::new(&reference.realization_id)
                .map_err(|_| DurableRegistryError::Corrupt)?;
            let payload = registry
                .realization_payloads
                .get(&id)
                .ok_or(DurableRegistryError::Corrupt)?;
            file.seek(SeekFrom::Start(reference.offset))
                .map_err(map_precommit_io)?;
            file.write_all(payload).map_err(map_precommit_io)?;
        }
        file.sync_all().map_err(map_precommit_io)?;
        directory.sync_all().map_err(map_precommit_io)?;
        Ok(())
    }
}

fn require_header(file: &mut File) -> Result<(), DurableRegistryError> {
    file.seek(SeekFrom::Start(0)).map_err(map_precommit_io)?;
    let mut magic = [0; MAGIC.len()];
    file.read_exact(&mut magic)
        .map_err(|_| DurableRegistryError::Corrupt)?;
    if magic != MAGIC {
        return Err(DurableRegistryError::Corrupt);
    }
    Ok(())
}
