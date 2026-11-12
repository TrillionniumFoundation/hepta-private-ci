//! Root reads an already completed freeze through its original two files.
//! The independent descriptions and shared locks live across the caller's
//! complete Root operation. This reader has no private key or writable owner.

use std::fs::File;
use std::io;
use std::os::unix::fs::FileExt;
use std::os::unix::fs::MetadataExt;
use std::time::Instant;

use codex_hepta_intelligence_eval::ProductEvaluationExecutionAnchorV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStateV1;
use codex_hepta_intelligence_eval::ReadOnlyProductEvaluationExecutionStoreV1;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::observe_original_file_anchor_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use serde::Deserialize;

use super::post_a_files::PostAFileData;
use super::post_a_files::PostAOriginalFile;
use super::require_end;
use crate::authority_host_service::generation_initial::original_root;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct PostAFreezeData {
    journal: PostAFileData,
    witness: PostAFileData,
    scope: [u8; 32],
    generation: u64,
    maximum_records: usize,
}

pub(super) struct PostAFreezeFiles {
    journal: PostAOriginalFile,
    witness: PostAOriginalFile,
    scope: JournalScope,
    generation: Generation,
    maximum_records: usize,
}

impl PostAFreezeFiles {
    pub(super) fn retain_original_freeze(
        data: PostAFreezeData,
        objective: Digest32,
        uid: u32,
        gid: u32,
    ) -> io::Result<Self> {
        original_root()?;
        if uid == 0
            || gid == 0
            || objective.is_zero()
            || data.scope == [0; 32]
            || !(3..=4096).contains(&data.maximum_records)
        {
            return Err(io::Error::other("original non-Root freeze owner required"));
        }
        let journal = PostAOriginalFile::retain_original_file(data.journal)?;
        let witness = PostAOriginalFile::retain_original_file(data.witness)?;
        if journal.same_file(&witness) {
            return Err(io::Error::other(
                "independent original freeze witness required",
            ));
        }
        for original in [&journal, &witness] {
            let file = PostAOriginalFile::read_handle(original)?;
            let metadata = file.metadata()?;
            if (metadata.uid(), metadata.gid(), metadata.mode() & 0o7777) != (uid, gid, 0o600) {
                return Err(io::Error::other("original freeze owner custody differs"));
            }
        }
        Ok(Self {
            journal,
            witness,
            scope: JournalScope {
                scope_digest: Digest32::from_array(data.scope),
                objective_digest: objective,
            },
            generation: Generation::new(data.generation).map_err(io::Error::other)?,
            maximum_records: data.maximum_records,
        })
    }

    pub(super) fn with_original_completion<T>(
        &self,
        key: &ProductEvaluationExecutionKeyV1,
        end: Instant,
        action: impl FnOnce(&[u8]) -> io::Result<T>,
    ) -> io::Result<T> {
        require_end(end)?;
        let journal = PostAOriginalFile::read_handle(&self.journal)?;
        let witness = PostAOriginalFile::read_handle(&self.witness)?;
        journal.try_lock_shared().map_err(io::Error::other)?;
        witness.try_lock_shared().map_err(io::Error::other)?;
        let before = [
            image(&journal, 32 * 1024 * 1024)?,
            image(&witness, 1024 * 1024)?,
        ];
        let anchor = self.read_anchor(&witness)?;
        // Header + one durable claim + its sole completed signature.
        if anchor.sequence != 3 {
            return Err(io::Error::other("one original completed freeze required"));
        }
        // The reader may unlock its own description without releasing either
        // actual Root lock held by journal and witness above.
        let reader_file = PostAOriginalFile::read_handle(&self.journal)?;
        let mut reader = ReadOnlyProductEvaluationExecutionStoreV1::open(
            reader_file,
            key.binding_digest,
            ProductEvaluationExecutionAnchorV1 {
                sequence: anchor.sequence - 1,
                history_digest: anchor.checkpoint_digest,
            },
        )
        .map_err(io::Error::other)?;
        let ProductEvaluationExecutionStateV1::Completed(bytes) =
            ReadOnlyProductEvaluationExecutionStoreV1::readback(&mut reader, key)
                .map_err(io::Error::other)?
        else {
            return Err(io::Error::other("original freeze remains pending"));
        };
        self.require_observation(&journal, &witness, &before, anchor)?;
        require_end(end)?;
        let result = action(&bytes)?;
        if ReadOnlyProductEvaluationExecutionStoreV1::readback(&mut reader, key)
            .map_err(io::Error::other)?
            != ProductEvaluationExecutionStateV1::Completed(bytes)
        {
            return Err(io::Error::other(
                "original freeze changed during Root action",
            ));
        }
        self.require_observation(&journal, &witness, &before, anchor)?;
        require_end(end)?;
        Ok(result)
    }

    fn read_anchor(&self, file: &File) -> io::Result<JournalAnchor> {
        observe_original_file_anchor_v1(file, self.scope, self.generation, self.maximum_records)
            .map_err(io::Error::other)?
            .ok_or_else(|| io::Error::other("original freeze witness is absent"))
    }

    fn require_observation(
        &self,
        journal: &File,
        witness: &File,
        expected: &[(u64, Digest32); 2],
        anchor: JournalAnchor,
    ) -> io::Result<()> {
        original_root()?;
        PostAOriginalFile::require_identity(&self.journal, journal)?;
        PostAOriginalFile::require_identity(&self.witness, witness)?;
        if self.read_anchor(witness)? != anchor
            || &[
                image(journal, 32 * 1024 * 1024)?,
                image(witness, 1024 * 1024)?,
            ] != expected
        {
            return Err(io::Error::other("original freeze physical cut changed"));
        }
        PostAOriginalFile::require_identity(&self.journal, journal)?;
        PostAOriginalFile::require_identity(&self.witness, witness)
    }
}

fn image(file: &File, bound: u64) -> io::Result<(u64, Digest32)> {
    let length = file.metadata()?.len();
    if length == 0 || length > bound {
        return Err(io::Error::other("bounded original freeze image required"));
    }
    let mut bytes = vec![0; length as usize];
    file.read_exact_at(&mut bytes, 0)?;
    if file.metadata()?.len() != length {
        return Err(io::Error::other("original freeze image length changed"));
    }
    Ok((length, Digest32::of_bytes(&bytes)))
}
