//! Real descriptor and witness-owner checks. These do not enroll a Cell or
//! create a captured decision, and do not substitute for the ordinary A test.

use std::fs::File;
use std::io::Write;
use std::os::fd::AsRawFd;
use std::os::unix::fs::PermissionsExt;

use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::JournalScope;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;
use tempfile::NamedTempFile;

use super::OriginalCellFiles;
use super::PreparedOriginalCellFiles;
use super::RootHistoricalCellInputsV1;

struct OriginalPair {
    journal: NamedTempFile,
    witness: NamedTempFile,
    scope: JournalScope,
    generation: Generation,
}

impl OriginalPair {
    fn new() -> anyhow::Result<Self> {
        Ok(Self {
            journal: NamedTempFile::new()?,
            witness: NamedTempFile::new()?,
            scope: JournalScope {
                scope_digest: Digest32::of_bytes(b"original Initial Cell custody scope"),
                objective_digest: Digest32::of_bytes(b"original Initial Cell custody objective"),
            },
            generation: Generation::new(1)?,
        })
    }

    fn inputs(&self) -> std::io::Result<RootHistoricalCellInputsV1> {
        Ok(RootHistoricalCellInputsV1 {
            journal: File::open(self.journal.path())?,
            witness: File::open(self.witness.path())?,
            witness_scope: self.scope,
            witness_generation: self.generation,
            witness_records: 8,
            maximum_records: 8,
        })
    }

    fn prepare(&self) -> anyhow::Result<PreparedOriginalCellFiles> {
        Ok(PreparedOriginalCellFiles::retain_before_enrollment(
            self.inputs()?,
            /*uid*/ 60001,
            /*gid*/ 60001,
        )?)
    }

    fn initialize(&self, scope: JournalScope) -> anyhow::Result<FileAnchorWitnessStore> {
        Ok(FileAnchorWitnessStore::open(
            self.witness.reopen()?,
            scope,
            self.generation,
            /*max_records*/ 8,
        )?)
    }
}

#[test]
#[ignore = "requires actual UID 0 for original Root descriptor custody"]
fn original_initial_cell_custody_waits_for_the_actual_witness_owner() -> anyhow::Result<()> {
    // SAFETY: geteuid only observes the real process credential.
    anyhow::ensure!(unsafe { libc::geteuid() } == 0, "actual Root UID required");
    let files = OriginalPair::new()?;
    assert!(
        OriginalCellFiles::retain_original_cell(
            files.inputs()?,
            /*uid*/ 60001,
            /*gid*/ 60001,
        )
        .is_err()
    );
    assert!(files.prepare()?.into_initialized().is_err());
    assert_eq!(std::fs::read(files.witness.path())?, Vec::<u8>::new());
    let prepared = files.prepare()?;
    let pins = prepared.files.pins.clone();
    let writer = files.initialize(files.scope)?;
    let initialized = prepared.into_initialized()?;
    assert_eq!(initialized.pins, pins);
    for file in [&initialized.inputs.journal, &initialized.inputs.witness] {
        // SAFETY: F_GETFL only observes flags on these live owned descriptors.
        let flags = unsafe { libc::fcntl(file.as_raw_fd(), libc::F_GETFL) };
        anyhow::ensure!(flags >= 0, "original file flags unavailable");
        assert_eq!(flags & libc::O_ACCMODE, libc::O_RDONLY);
    }
    // The actual witness owner still holds its exclusive description. Root's
    // independent observer must read its synced header without becoming a writer.
    initialized.require_original_cell_baseline()?;
    assert_eq!(writer.current()?, None);
    assert_eq!(files.journal.as_file().metadata()?.len(), 0);

    let mut partial = OriginalPair::new()?;
    let prepared = partial.prepare()?;
    partial.witness.write_all(b"partial")?;
    partial.witness.as_file().sync_all()?;
    assert!(
        prepared
            .into_initialized()?
            .require_original_cell_baseline()
            .is_err()
    );

    let wrong_scope = OriginalPair::new()?;
    let prepared = wrong_scope.prepare()?;
    let _wrong_writer = wrong_scope.initialize(JournalScope {
        scope_digest: Digest32::of_bytes(b"another original scope"),
        objective_digest: wrong_scope.scope.objective_digest,
    })?;
    assert!(
        prepared
            .into_initialized()?
            .require_original_cell_baseline()
            .is_err()
    );

    let committed = OriginalPair::new()?;
    let prepared = committed.prepare()?;
    let mut committed_writer = committed.initialize(committed.scope)?;
    committed_writer.compare_and_swap(
        /*expected*/ None,
        JournalAnchor {
            sequence: 1,
            checkpoint_digest: Digest32::of_bytes(b"an already committed Cell witness"),
        },
    )?;
    assert!(
        prepared
            .into_initialized()?
            .require_original_cell_baseline()
            .is_err()
    );

    let changed = OriginalPair::new()?;
    let prepared = changed.prepare()?;
    let _changed_writer = changed.initialize(changed.scope)?;
    changed
        .witness
        .as_file()
        .set_permissions(std::fs::Permissions::from_mode(0o640))?;
    assert!(prepared.into_initialized().is_err());
    Ok(())
}
