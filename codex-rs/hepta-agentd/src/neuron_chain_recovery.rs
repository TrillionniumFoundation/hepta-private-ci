use std::fs::File;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_neuron::SparseJournal;
use serde::Deserialize;

use super::open_existing_rw;
use crate::AgentdError;

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct NeuronSegmentDescriptorV1 {
    pub journal_path: PathBuf,
    pub max_records: usize,
}

pub(super) fn select_neuron_segments_v1(
    journal_path: Option<&Path>,
    max_records: Option<usize>,
    segment_chain: Option<&[NeuronSegmentDescriptorV1]>,
) -> Result<Vec<NeuronSegmentDescriptorV1>, AgentdError> {
    match (journal_path, max_records, segment_chain) {
        (Some(path), Some(capacity), None) => Ok(vec![NeuronSegmentDescriptorV1 {
            journal_path: path.to_path_buf(),
            max_records: capacity,
        }]),
        (None, None, Some(segments))
            if (2..=SparseJournal::MAX_CHAIN_SEGMENTS).contains(&segments.len()) =>
        {
            Ok(segments.to_vec())
        }
        _ => Err(AgentdError::Invalid(
            "choose one neuron journal file or a bounded chain of at least two files".to_string(),
        )),
    }
}

pub(super) fn recover_neuron_chain_v1(
    segments: &[NeuronSegmentDescriptorV1],
    config: SparseConfig,
    scope: JournalScope,
    acknowledged: JournalAnchor,
) -> Result<SparseJournal, AgentdError> {
    let recovery = if let [segment] = segments {
        let file = open_existing_rw(&segment.journal_path, "neuron journal")?;
        SparseJournal::open_anchored(file, config, scope, segment.max_records, acknowledged)
    } else {
        let files = segments
            .iter()
            .map(|segment| {
                let file = open_chain_file(&segment.journal_path)?;
                Ok((file, segment.max_records))
            })
            .collect::<Result<Vec<_>, AgentdError>>()?;
        SparseJournal::recover_exact_chain(files, config, scope, acknowledged)
    };
    recovery
        .map_err(|error| AgentdError::Invalid(format!("invalid anchored neuron journal: {error}")))
}

#[cfg(unix)]
fn open_chain_file(path: &Path) -> Result<File, AgentdError> {
    use std::os::unix::fs::MetadataExt;

    use rustix::fs::Mode;
    use rustix::fs::OFlags;

    if !path.is_absolute() {
        return Err(invalid_chain_file());
    }
    let descriptor = rustix::fs::open(
        path,
        OFlags::RDWR | OFlags::NOFOLLOW | OFlags::NONBLOCK | OFlags::CLOEXEC,
        Mode::empty(),
    )
    .map_err(std::io::Error::from)?;
    let file = File::from(descriptor);
    let metadata = file.metadata()?;
    if !metadata.is_file() || metadata.nlink() != 1 || metadata.len() == 0 {
        return Err(invalid_chain_file());
    }
    Ok(file)
}

#[cfg(windows)]
fn open_chain_file(path: &Path) -> Result<File, AgentdError> {
    use std::fs::OpenOptions;
    use std::os::windows::fs::OpenOptionsExt;

    const FILE_FLAG_OPEN_REPARSE_POINT: u32 = 0x0020_0000;
    const FILE_ATTRIBUTE_DIRECTORY: u64 = 0x0010;
    const FILE_ATTRIBUTE_REPARSE_POINT: u64 = 0x0400;

    if !path.is_absolute() {
        return Err(invalid_chain_file());
    }
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT)
        .open(path)?;
    let information = winapi_util::file::information(&file)?;
    if information.file_attributes() & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)
        != 0
        || information.file_size() == 0
        || information.number_of_links() != 1
        || !file.metadata()?.is_file()
    {
        return Err(invalid_chain_file());
    }
    Ok(file)
}

#[cfg(not(any(unix, windows)))]
fn open_chain_file(_path: &Path) -> Result<File, AgentdError> {
    Err(invalid_chain_file())
}

fn invalid_chain_file() -> AgentdError {
    AgentdError::Invalid(
        "neuron chain requires absolute, existing nonempty regular files with one link".to_string(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn selects_legacy_file_or_only_a_bounded_chain() {
        let legacy = Path::new("legacy");
        let segment = NeuronSegmentDescriptorV1 {
            journal_path: legacy.to_path_buf(),
            max_records: 4,
        };
        let chain = vec![segment; SparseJournal::MAX_CHAIN_SEGMENTS + 1];
        assert!(select_neuron_segments_v1(Some(legacy), Some(4), None).is_ok());
        assert!(select_neuron_segments_v1(None, None, Some(&chain[..2])).is_ok());
        assert!(select_neuron_segments_v1(None, None, Some(&chain[..1])).is_err());
        assert!(select_neuron_segments_v1(None, None, Some(&chain)).is_err());
        assert!(select_neuron_segments_v1(Some(legacy), Some(4), Some(&[])).is_err());
    }

    #[cfg(any(unix, windows))]
    #[test]
    fn chain_admission_requires_an_owned_regular_file() -> std::io::Result<()> {
        let root = tempfile::tempdir()?;
        let root = root.path().canonicalize()?;
        let segment = root.join("segment");
        std::fs::write(&segment, b"journal")?;
        assert!(open_chain_file(&segment).is_ok());
        let alias = root.join("alias");
        std::fs::hard_link(&segment, &alias)?;
        assert!(open_chain_file(&segment).is_err());
        assert!(open_chain_file(&alias).is_err());
        assert_eq!(std::fs::read(&segment)?, b"journal");
        Ok(())
    }
}
