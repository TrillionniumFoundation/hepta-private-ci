//! Storage-v3 payload extent file under the existing exclusive registry owner.
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
use super::map_precommit_io;
use super::open_private;
use crate::PromptRegistry;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

pub(super) const FILE_NAME: &str = "registry.payloads";
const MAGIC: &[u8] = b"HEPTA-PROMPT-PAYLOADS-V1\0";
const MAX_PAYLOAD_BYTES: u64 = 32 * 1024 * 1024;

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
    // Existing V2 semantic image, hydrated before its unchanged restore checks.
    // Embedded payloads must be empty; there is only one physical payload copy.
    pub state: StoredV2,
    pub payload_references: Vec<PayloadReference>,
    /// Once set, reopening without the independently retained checkpoint is
    /// forbidden. Older V3 manifests omit this field and migrate on guarded open.
    #[serde(default)]
    pub recovery_checkpoint_required: bool,
}

#[derive(Clone)]
pub(super) struct PayloadState {
    references: BTreeMap<String, PayloadReference>,
    committed_end: u64,
    initialized: bool,
}

impl Default for PayloadState {
    fn default() -> Self {
        Self {
            references: BTreeMap::new(),
            committed_end: MAGIC.len() as u64,
            initialized: false,
        }
    }
}

impl PayloadState {
    pub fn is_initialized(&self) -> bool {
        self.initialized
    }

    pub fn references(&self) -> Vec<PayloadReference> {
        self.references.values().cloned().collect()
    }

    pub fn hydrate(
        directory: &File,
        mut stored: StoredV3,
    ) -> Result<(Self, StoredV2, bool), DurableRegistryError> {
        if stored.schema != 3
            || stored.state.schema != super::STORE_SCHEMA
            || !stored.state.payloads.is_empty()
            || stored.payload_references.len() > crate::MAX_RECORDS
        {
            return Err(DurableRegistryError::Corrupt);
        }
        let mut ordered = stored.payload_references;
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
        let mut file = open_private(directory, FILE_NAME, Access::Read)?;
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
            stored.state.payloads.push(StoredPayload {
                realization_id: reference.realization_id.clone(),
                payload,
            });
        }
        Ok((
            Self {
                references,
                committed_end,
                initialized: true,
            },
            stored.state,
            stored.recovery_checkpoint_required,
        ))
    }

    /// Only called after full V2 semantic/configuration validation succeeded.
    /// The selected manifest already proves the prefix; shortening that prefix
    /// is never recovery. No committed record or revoked payload is collected.
    pub fn discard_unselected_tail(&self, directory: &File) -> Result<(), DurableRegistryError> {
        let file = open_private(directory, FILE_NAME, Access::Create)?;
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
            let mut file = open_private(directory, FILE_NAME, Access::Read)?;
            require_header(&mut file)?;
            if file.metadata().map_err(map_precommit_io)?.len() < self.committed_end {
                return Err(DurableRegistryError::Corrupt);
            }
            return Ok(());
        }
        let mut file = open_private(directory, FILE_NAME, Access::Create)?;
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
