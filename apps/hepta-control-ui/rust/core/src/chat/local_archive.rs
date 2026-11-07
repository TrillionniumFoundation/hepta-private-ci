//! Local text persistence only. Principal names are partition routing tags, not
//! authenticated identities; restoring never activates a named partition.
use super::ChatWorkspace;
use super::DraftPartition;
use super::MAX_DRAFT_BYTES;
use super::MAX_LOCAL_DRAFTS;
use serde::Deserialize;
use serde::Serialize;
use std::collections::BTreeSet;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LocalDraftArchive {
    version: u8,
    partitions: Vec<LocalPartition>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct LocalPartition {
    principal: Option<String>,
    rooms: Vec<String>,
    active: usize,
}

impl LocalDraftArchive {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.version != 1 || self.partitions.is_empty() || self.partitions.len() > 5 {
            return Err("Invalid local draft partition count or version");
        }
        let mut seen = BTreeSet::new();
        for partition in &self.partitions {
            if !seen.insert(&partition.principal)
                || partition.principal.as_ref().is_some_and(|principal| {
                    principal.is_empty()
                        || principal.len() > 192
                        || !principal
                            .bytes()
                            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
                })
                || partition.rooms.is_empty()
                || partition.rooms.len() > MAX_LOCAL_DRAFTS
                || partition.active >= partition.rooms.len()
                || partition
                    .rooms
                    .iter()
                    .any(|text| text.len() > MAX_DRAFT_BYTES || text.contains('\0'))
            {
                return Err("Invalid local draft partition, selection or text");
            }
        }
        if !self
            .partitions
            .iter()
            .any(|partition| partition.principal.is_none())
        {
            return Err("Local draft archive lacks its unauthenticated partition");
        }
        Ok(())
    }
}

impl ChatWorkspace {
    /// Snapshot all local text partitions, including those parked by original
    /// owner rotation. No owner, signature, thread, history or delivery is saved.
    pub fn archive_local_drafts(&self) -> Result<LocalDraftArchive, &'static str> {
        if self.composing {
            return Err("IME composition is active; checkpoint deferred");
        }
        let mut partitions = Vec::with_capacity(self.parked_drafts.len() + 1);
        for (principal, active, drafts) in
            std::iter::once((&self.draft_principal, self.active, &self.drafts)).chain(
                self.parked_drafts
                    .iter()
                    .map(|(principal, partition)| (principal, partition.active, &partition.drafts)),
            )
        {
            let mut selected = None;
            let mut rooms = Vec::with_capacity(drafts.len());
            for (id, draft) in drafts {
                if *id == active {
                    selected = Some(rooms.len());
                }
                rooms.push(draft.text.clone());
            }
            partitions.push(LocalPartition {
                principal: principal.clone(),
                rooms,
                active: selected.ok_or("Missing local draft selection")?,
            });
        }
        partitions.sort_by(|left, right| left.principal.cmp(&right.principal));
        let archive = LocalDraftArchive {
            version: 1,
            partitions,
        };
        archive.validate()?;
        Ok(archive)
    }

    /// Creates a fresh unauthenticated workspace. Named partitions remain
    /// parked until a later, independently authenticated `install_owner` selects
    /// that exact principal through the original owner path.
    pub fn from_local_draft_archive(archive: LocalDraftArchive) -> Result<Self, &'static str> {
        archive.validate()?;
        let mut workspace = Self::default();
        for saved in archive.partitions {
            let mut rebuilt = Self::default();
            for (index, text) in saved.rooms.into_iter().enumerate() {
                if index != 0 && !rebuilt.new_draft() {
                    return Err("Original workspace refused restored room");
                }
                if !rebuilt.edit(text) {
                    return Err("Original workspace refused restored text");
                }
            }
            if !rebuilt.select(saved.active as u64) {
                return Err("Original workspace refused restored selection");
            }
            if saved.principal.is_none() {
                workspace.active = rebuilt.active;
                workspace.next = rebuilt.next;
                workspace.drafts = rebuilt.drafts;
            } else {
                workspace.parked_drafts.insert(
                    saved.principal,
                    DraftPartition {
                        active: rebuilt.active,
                        next: rebuilt.next,
                        drafts: rebuilt.drafts,
                    },
                );
            }
        }
        Ok(workspace)
    }
}

#[cfg(test)]
#[path = "local_archive_tests.rs"]
mod tests;
