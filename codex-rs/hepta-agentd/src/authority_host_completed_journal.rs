//! Fixed original receipt files, observed as data while their original owner
//! may still hold its writer lock. No writer is opened, recovered or unlocked.
//! The caller must enclose this entire operation in the actual Root refusal
//! attempt and independently verify every required signed completion.

use std::fs::File;
use std::io;
use std::os::fd::AsRawFd;
use std::os::unix::fs::FileExt;
use std::os::unix::fs::MetadataExt;
use std::time::Instant;

use codex_hepta_intelligence_eval::ProductEvaluationExecutionAnchorV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStateV1;
use codex_hepta_intelligence_eval::decode_original_product_evaluation_execution_records_v1;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::observe_original_file_anchor_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use serde::Deserialize;
use serde::Serialize;

use super::post_a_files::PostAFileData;
use super::post_a_files::PostAOriginalFile;
use super::require_end;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct CompletedJournalData {
    journal: PostAFileData,
    witness: PostAFileData,
    scope: [u8; 32],
    generation: u64,
    maximum_records: usize,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct CompletedJournalCut {
    files: [u8; 32],
    binding: [u8; 32],
    sequence: u64,
    history: [u8; 32],
    journal: [u8; 32],
    witness: [u8; 32],
}

pub(super) struct CompletedJournalFiles {
    journal: PostAOriginalFile,
    witness: PostAOriginalFile,
    scope: JournalScope,
    generation: Generation,
    maximum_records: usize,
    files: Digest32,
}

#[derive(Clone)]
pub(super) struct CompletedJournalObservation {
    pub(super) cut: CompletedJournalCut,
    pub(super) records: Vec<(
        ProductEvaluationExecutionKeyV1,
        ProductEvaluationExecutionStateV1,
    )>,
}

impl CompletedJournalFiles {
    pub(super) fn require_empty(&self) -> io::Result<()> {
        for original in [&self.journal, &self.witness] {
            let file = PostAOriginalFile::read_handle(original)?;
            if file.metadata()?.len() != 0 {
                return Err(io::Error::other(
                    "fresh completed-learning reservation must be empty",
                ));
            }
            PostAOriginalFile::require_identity(original, &file)?;
        }
        Ok(())
    }

    pub(super) fn aliases(&self, other: &Self) -> bool {
        [&self.journal, &self.witness].iter().any(|left| {
            [&other.journal, &other.witness]
                .iter()
                .any(|right| PostAOriginalFile::same_file(left, right))
        })
    }

    pub(super) fn require_same_files(
        &self,
        journal: &PostAOriginalFile,
        witness: &PostAOriginalFile,
        scope: JournalScope,
        generation: Generation,
        maximum_records: usize,
    ) -> io::Result<()> {
        if !PostAOriginalFile::same_file(&self.journal, journal)
            || !PostAOriginalFile::same_file(&self.witness, witness)
            || self.scope != scope
            || self.generation != generation
            || self.maximum_records != maximum_records
        {
            return Err(io::Error::other(
                "completed-learning original freeze differs",
            ));
        }
        Ok(())
    }
    pub(super) fn retain_original(
        data: CompletedJournalData,
        objective: Digest32,
    ) -> io::Result<Self> {
        if objective.is_zero()
            || data.scope == [0; 32]
            || !(3..=4096).contains(&data.maximum_records)
        {
            return Err(io::Error::other(
                "bounded original completed journal required",
            ));
        }
        let files = Digest32::of_parts(&[
            b"hepta.root.completed-learning.original-files.v1\0",
            &serde_json::to_vec(&data).map_err(io::Error::other)?,
            objective.as_array(),
        ]);
        let journal = PostAOriginalFile::retain_original_file(data.journal)?;
        let witness = PostAOriginalFile::retain_original_file(data.witness)?;
        if PostAOriginalFile::same_file(&journal, &witness) {
            return Err(io::Error::other("original receipt and witness alias"));
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
            files,
        })
    }

    pub(super) fn with_original_records<T>(
        &self,
        end: Instant,
        action: impl FnOnce(&CompletedJournalObservation) -> io::Result<T>,
    ) -> io::Result<T> {
        require_end(end)?;
        let journal = PostAOriginalFile::read_handle(&self.journal)?;
        let witness = PostAOriginalFile::read_handle(&self.witness)?;
        let (observation, before) = self.observe(&journal, &witness)?;
        require_end(end)?;
        let result = action(&observation);
        // Errors do not skip physical postchecks. The enclosing Root attempt
        // remains non-Ready on either an action failure or an observed change.
        let (after, images) = self.observe(&journal, &witness)?;
        if after.cut != observation.cut || images != before || after.records != observation.records
        {
            return Err(io::Error::other("original completed journal changed"));
        }
        require_end(end)?;
        result
    }

    fn observe(
        &self,
        journal: &File,
        witness: &File,
    ) -> io::Result<(CompletedJournalObservation, [Vec<u8>; 2])> {
        PostAOriginalFile::require_identity(&self.journal, journal)?;
        PostAOriginalFile::require_identity(&self.witness, witness)?;
        let anchor = self.anchor(witness)?;
        let images = [
            image(journal, 32 * 1024 * 1024)?,
            image(witness, 1024 * 1024)?,
        ];
        if self.anchor(witness)? != anchor {
            return Err(io::Error::other("original completed witness changed"));
        }
        let header: [u8; 32] = images[0]
            .get(8..40)
            .ok_or_else(|| io::Error::other("original completed header missing"))?
            .try_into()
            .map_err(io::Error::other)?;
        let binding = Digest32::from_array(header);
        let exact = ProductEvaluationExecutionAnchorV1 {
            sequence: anchor
                .sequence
                .checked_sub(1)
                .ok_or_else(|| io::Error::other("original completed witness sequence"))?,
            history_digest: anchor.checkpoint_digest,
        };
        let records =
            decode_original_product_evaluation_execution_records_v1(&images[0], binding, exact)
                .map_err(io::Error::other)?;
        PostAOriginalFile::require_identity(&self.journal, journal)?;
        PostAOriginalFile::require_identity(&self.witness, witness)?;
        if image(journal, 32 * 1024 * 1024)? != images[0]
            || image(witness, 1024 * 1024)? != images[1]
            || self.anchor(witness)? != anchor
        {
            return Err(io::Error::other(
                "original completed physical image differs",
            ));
        }
        let cut = CompletedJournalCut {
            files: self.files.into_array(),
            binding: header,
            sequence: exact.sequence,
            history: exact.history_digest.into_array(),
            journal: Digest32::of_bytes(&images[0]).into_array(),
            witness: Digest32::of_bytes(&images[1]).into_array(),
        };
        Ok((CompletedJournalObservation { cut, records }, images))
    }

    fn anchor(&self, witness: &File) -> io::Result<JournalAnchor> {
        observe_original_file_anchor_v1(witness, self.scope, self.generation, self.maximum_records)
            .map_err(io::Error::other)?
            .ok_or_else(|| io::Error::other("original completed witness missing"))
    }
}

impl CompletedJournalCut {
    pub(super) fn data_digest(&self) -> io::Result<Digest32> {
        Ok(Digest32::of_parts(&[
            b"hepta.root.completed-learning.journal-cut.v1\0",
            &serde_json::to_vec(self).map_err(io::Error::other)?,
        ]))
    }
}

fn image(file: &File, maximum: u64) -> io::Result<Vec<u8>> {
    let access = unsafe { libc::fcntl(file.as_raw_fd(), libc::F_GETFL) };
    if access < 0 || access & libc::O_ACCMODE != libc::O_RDONLY {
        return Err(io::Error::other(
            "original completed read-only description required",
        ));
    }
    let before = file.metadata()?;
    if !before.is_file() || before.nlink() != 1 || before.len() == 0 || before.len() > maximum {
        return Err(io::Error::other("original bounded completed file required"));
    }
    let stamp = |value: &std::fs::Metadata| {
        (
            value.dev(),
            value.ino(),
            value.uid(),
            value.gid(),
            value.mode(),
            value.nlink(),
            value.len(),
            value.mtime(),
            value.mtime_nsec(),
            value.ctime(),
            value.ctime_nsec(),
        )
    };
    let mut bytes = vec![0; usize::try_from(before.len()).map_err(io::Error::other)?];
    file.read_exact_at(&mut bytes, /*offset*/ 0)?;
    if stamp(&before) != stamp(&file.metadata()?) {
        return Err(io::Error::other(
            "original completed file changed during read",
        ));
    }
    Ok(bytes)
}
