//! Durable deployment acknowledgement using the existing fenced host journal.
//!
//! The caller owns the file and its independent rollback domain. A checksum
//! cannot detect restoring both this journal and the caller's expected vector.

use std::fs::File;

use codex_hepta_types::Digest32;

use crate::plasticity_anchor_journal::AdaptiveAnchorJournalV1;
use crate::plasticity_anchor_journal::AdaptiveAnchorV1;

use super::MemoryCellNetworkVersionV1;

const MAGIC: [u8; 8] = *b"H7MEMN01";
const WRITER_FENCE: u64 = 1;

pub(super) struct NetworkAnchor {
    journal: AdaptiveAnchorJournalV1,
    scope: Digest32,
    available: bool,
}

impl NetworkAnchor {
    pub fn open(
        file: File,
        scope: Digest32,
        expected: MemoryCellNetworkVersionV1,
    ) -> Result<Self, String> {
        let mut journal =
            AdaptiveAnchorJournalV1::open(file, scope, MAGIC).map_err(|error| error.to_string())?;
        let state = journal.state();
        if state.writer_fence == 0 {
            if expected.generation.get() != 1 {
                return Err("new memory deployment journal requires generation one".to_string());
            }
            journal
                .issue_new_registry_fence()
                .map_err(|error| error.to_string())?;
        }
        if journal.state().writer_fence != WRITER_FENCE {
            return Err("memory deployment journal writer fence differs".to_string());
        }
        if journal.state().anchor.is_none() {
            // This includes a crash after the initial fence but before the
            // first anchor. No deployment has been acknowledged at that point.
            if expected.generation.get() != 1 || journal.state().previous_anchor.is_some() {
                return Err(
                    "uninitialized memory deployment journal cannot skip a generation".to_string(),
                );
            }
            journal
                .persist_anchor(scope, WRITER_FENCE, anchor(expected))
                .map_err(|error| error.to_string())?;
        }
        let result = Self {
            journal,
            scope,
            available: true,
        };
        result.require(expected)?;
        Ok(result)
    }

    pub fn require(&self, expected: MemoryCellNetworkVersionV1) -> Result<(), String> {
        if !self.available || self.journal.state().anchor != Some(anchor(expected)) {
            return Err("memory deployment journal is unavailable, rolled back or forked; reopen with its exact committed vector".to_string());
        }
        Ok(())
    }

    pub fn commit(
        &mut self,
        expected: MemoryCellNetworkVersionV1,
        successor: MemoryCellNetworkVersionV1,
    ) -> Result<(), String> {
        self.require(expected)?;
        if expected.generation.get().checked_add(1) != Some(successor.generation.get()) {
            return Err("memory deployment journal requires the exact successor".to_string());
        }
        // An I/O failure can occur after a complete frame reached the file.
        // Until reopen validates that durable state, neither retry nor recovery
        // in this object may assume the old in-memory anchor still owns it.
        self.available = false;
        self.journal
            .persist_anchor(self.scope, WRITER_FENCE, anchor(successor))
            .map_err(|error| error.to_string())?;
        self.available = true;
        Ok(())
    }
}

fn anchor(version: MemoryCellNetworkVersionV1) -> AdaptiveAnchorV1 {
    AdaptiveAnchorV1 {
        sequence: version.generation.get(),
        frame_digest: version.deployment_digest.digest(),
    }
}
