//! Host current-generation checks for explicitly guarded Cell journals.
//! This port confers no authority. The host supplies its live Control owner;
//! the distinct header prevents reopening a guarded file as an ordinary V2.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::cell_generation_state::CellGenerationConfigV2;
use crate::cell_generation_state::GenerationState;
use crate::cell_generation_types::CellGenerationErrorV2;
use crate::cell_generation_types::CellGenerationScopeV2;
use crate::cell_generation_types::digest;

pub(crate) const GUARDED_MAGIC: &[u8; 8] = b"HPTACG03";

/// Complete immutable owner identity, including task, initial state and limits.
/// Deserialization is for stored Control facts, never an admission credential.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CellGenerationOwnerBindingV1 {
    scope: CellGenerationScopeV2,
    manifest_digest: [u8; 32],
    task_digest: [u8; 32],
    source_frontier: [u8; 32],
    initial_snapshot_digest: [u8; 32],
    generation: u64,
    writer_epoch: u64,
    config_digest: [u8; 32],
}

impl CellGenerationOwnerBindingV1 {
    pub fn new(
        config: &CellGenerationConfigV2,
        max_records: u64,
    ) -> Result<Self, CellGenerationErrorV2> {
        if !(6..=65_536).contains(&max_records) {
            return Err(CellGenerationErrorV2::Capacity);
        }
        GenerationState::new(config)?;
        Ok(Self {
            scope: config.initial.scope.clone(),
            manifest_digest: config.manifest.digest()?,
            task_digest: config.task_digest,
            source_frontier: config.source_frontier,
            initial_snapshot_digest: config.initial.digest()?,
            generation: config.initial.generation,
            writer_epoch: config.initial.writer_epoch,
            config_digest: digest(b"hepta.cell.generation-owner.v2\0", &(config, max_records))?,
        })
    }

    pub fn scope(&self) -> &CellGenerationScopeV2 {
        &self.scope
    }

    pub fn manifest_digest(&self) -> [u8; 32] {
        self.manifest_digest
    }

    pub fn task_digest(&self) -> [u8; 32] {
        self.task_digest
    }

    pub fn source_frontier(&self) -> [u8; 32] {
        self.source_frontier
    }

    pub fn initial_snapshot_digest(&self) -> [u8; 32] {
        self.initial_snapshot_digest
    }

    pub fn generation(&self) -> u64 {
        self.generation
    }

    pub fn writer_epoch(&self) -> u64 {
        self.writer_epoch
    }

    pub fn digest(&self) -> Result<[u8; 32], CellGenerationErrorV2> {
        for id in [
            &self.scope.agent_id,
            &self.scope.cell_id,
            &self.scope.run_id,
        ] {
            StableId::new(id).map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        }
        if self.generation == 0
            || self.writer_epoch == 0
            || [
                self.scope.principal_digest,
                self.manifest_digest,
                self.task_digest,
                self.source_frontier,
                self.initial_snapshot_digest,
                self.config_digest,
            ]
            .contains(&[0; 32])
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        digest(b"hepta.cell.generation-owner-binding.v1\0", self)
    }

    /// Predicted empty cut, not proof that a file has been created or synced.
    pub fn genesis_checkpoint(&self) -> Digest32 {
        continuity_checkpoint(&self.header(), /*head*/ None, /*length*/ 40)
    }

    pub(crate) fn header(&self) -> Vec<u8> {
        let mut header = GUARDED_MAGIC.to_vec();
        header.extend_from_slice(&self.config_digest);
        header
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellGenerationOpenModeV1 {
    Active,
    Preparing,
}

/// An independently held live Control current-generation service. Check every
/// open/recover and operation; cached startup approval is insufficient. A
/// Preparing binding permits only an empty, synced genesis, never dispatch.
/// The host must serialize replacement with exclusive ownership of the old
/// terminal, drained journal. Implementations must not synthesize authority
/// from a supplied digest, observation or qualification receipt.
pub trait CellGenerationCurrentV1: Send + Sync {
    fn check_open(
        &self,
        binding: &CellGenerationOwnerBindingV1,
    ) -> Result<CellGenerationOpenModeV1, CellGenerationErrorV2>;

    fn check_current(
        &self,
        binding: &CellGenerationOwnerBindingV1,
    ) -> Result<(), CellGenerationErrorV2>;
}

/// Actual empty-file readback made by the exclusive journal owner. No public
/// constructor or deserializer, and no mutation or dispatch authority.
#[derive(Debug, Eq, PartialEq)]
pub struct CellGenerationPreparedCheckpointV1 {
    pub(crate) binding: CellGenerationOwnerBindingV1,
    pub(crate) checkpoint: Digest32,
}

impl CellGenerationPreparedCheckpointV1 {
    pub fn binding(&self) -> &CellGenerationOwnerBindingV1 {
        &self.binding
    }

    pub fn checkpoint(&self) -> Digest32 {
        self.checkpoint
    }
}

pub(crate) fn continuity_checkpoint(
    header: &[u8],
    head: Option<crate::JournalAnchor>,
    length: u64,
) -> Digest32 {
    let (sequence, head) = head.map_or((0, Digest32::ZERO), |anchor| {
        (anchor.sequence, anchor.checkpoint_digest)
    });
    Digest32::of_parts(&[
        b"hepta.cell.generation-continuity.v2\0",
        header,
        &sequence.to_be_bytes(),
        head.as_array(),
        &length.to_be_bytes(),
    ])
}

#[cfg(test)]
#[path = "cell_generation_current_tests.rs"]
mod tests;
