//! Recover an explicit bounded journal chain through the original journal API.
//! The final acknowledgement is an input from an independent host witness.

use std::collections::BTreeSet;
use std::fs::{File, OpenOptions};
use std::path::{Path, PathBuf};

use codex_hepta_neuron::{JournalAnchor, JournalError, JournalScope, SparseConfig, SparseJournal};
use serde::Deserialize;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct NeuronSegmentDescriptorV1 {
    pub journal_path: PathBuf,
    pub max_records: usize,
}

/// Preserve the original single-file descriptor, or require an explicit chain.
/// Supplying both representations, including an empty chain, is an error.
pub(super) fn select_neuron_segments_v1(
    journal_path: Option<&Path>,
    max_records: Option<usize>,
    segment_chain: Option<&[NeuronSegmentDescriptorV1]>,
) -> Result<Vec<NeuronSegmentDescriptorV1>> {
    match (journal_path, max_records, segment_chain) {
        (Some(path), Some(capacity), None) => Ok(vec![NeuronSegmentDescriptorV1 {
            journal_path: path.to_path_buf(),
            max_records: capacity,
        }]),
        (None, None, Some(segments)) if !segments.is_empty() => Ok(segments.to_vec()),
        _ => Err("choose exactly one complete neuron journal source: single file or segment_chain".into()),
    }
}

/// Recover every segment in order, requiring full intermediate segments and an
/// exact final anchor. A single segment retains native open_anchored semantics.
pub(super) fn recover_neuron_chain_v1(
    segments: &[NeuronSegmentDescriptorV1],
    config: SparseConfig,
    scope: JournalScope,
    acknowledged: JournalAnchor,
) -> Result<SparseJournal> {
    if segments.is_empty() {
        return Err("empty neuron segment chain".into());
    }
    let mut prefix_capacity = 0_u64;
    for segment in &segments[..segments.len() - 1] {
        prefix_capacity = prefix_capacity
            .checked_add(u64::try_from(segment.max_records)?)
            .ok_or("neuron segment capacity overflow")?;
    }
    let final_capacity = u64::try_from(segments.last().ok_or("empty chain")?.max_records)?;
    let end_capacity = prefix_capacity.checked_add(final_capacity).ok_or("neuron segment capacity overflow")?;
    if segments.iter().any(|segment| segment.max_records == 0)
        || acknowledged.sequence == 0
        || acknowledged.checkpoint_digest.is_zero()
        || acknowledged.sequence <= prefix_capacity
        || acknowledged.sequence > end_capacity
    {
        return Err(JournalError::InvalidAnchor.into());
    }
    // Open every existing file before recovery. No create/truncate flags and no
    // empty-file bootstrap are permitted; retain the handles actually checked.
    let mut files = checked_files(segments)?.into_iter();
    let first = files.next().ok_or("empty neuron segment chain")?;
    if segments.len() == 1 {
        return Ok(SparseJournal::open_anchored(first, config, scope, segments[0].max_records, acknowledged)?);
    }
    let mut current = SparseJournal::open(first, config, scope, segments[0].max_records)?;
    let mut expected_end = u64::try_from(segments[0].max_records)?;
    require_sequence(&current, expected_end)?;
    for (index, (segment, file)) in segments.iter().skip(1).zip(files).enumerate() {
        expected_end = expected_end.checked_add(u64::try_from(segment.max_records)?)
            .ok_or("neuron segment capacity overflow")?;
        if index + 2 == segments.len() {
            current = current.recover_successor(file, segment.max_records, acknowledged)?;
            let recovered = current.current()?.ok_or(JournalError::AcknowledgedHistoryMissing)?;
            if recovered.sequence() != acknowledged.sequence || recovered.digest() != acknowledged.checkpoint_digest {
                return Err(JournalError::AnchorMismatch.into());
            }
        } else {
            current = current.start_successor(file, segment.max_records)?;
            require_sequence(&current, expected_end)?;
        }
    }
    Ok(current)
}

fn require_sequence(journal: &SparseJournal, sequence: u64) -> Result<()> {
    if journal.current()?.map(|checkpoint| checkpoint.sequence()) != Some(sequence) {
        return Err(JournalError::AcknowledgedHistoryMissing.into());
    }
    Ok(())
}

fn checked_files(segments: &[NeuronSegmentDescriptorV1]) -> Result<Vec<File>> {
    let mut paths = BTreeSet::new();
    let mut files = Vec::with_capacity(segments.len());
    #[cfg(unix)]
    let mut identities = BTreeSet::new();
    for segment in segments {
        let path = &segment.journal_path;
        if !path.is_absolute() {
            return Err("neuron journal paths must be absolute".into());
        }
        let metadata = std::fs::symlink_metadata(path)?;
        if metadata.file_type().is_symlink() || !metadata.is_file() || metadata.len() == 0 {
            return Err("neuron recovery requires an existing nonempty regular non-symlink file".into());
        }
        if !paths.insert(path.canonicalize()?) {
            return Err("duplicate neuron segment path".into());
        }
        let file = OpenOptions::new().read(true).write(true).open(path)?;
        let opened = file.metadata()?;
        if !opened.is_file() || opened.len() == 0 {
            return Err("neuron journal changed while opening".into());
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            let identity = (opened.dev(), opened.ino());
            if identity != (metadata.dev(), metadata.ino()) || !identities.insert(identity) {
                return Err("neuron segment file changed or aliases another segment".into());
            }
        }
        files.push(file);
    }
    Ok(files)
}
