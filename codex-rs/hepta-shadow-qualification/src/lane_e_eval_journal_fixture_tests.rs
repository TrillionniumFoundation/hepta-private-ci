//! Private source fixture with separately retained file-backed attempt anchors.
//! Separate temporary directories exercise persistence and reopen semantics;
//! they do not certify independently administered production storage.
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_intelligence_eval::AnchoredProductEvaluationAttemptJournalV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptAnchorStoreV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptAnchorV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptJournalErrorV1;
use codex_hepta_types::Digest32;
use tempfile::TempDir;

type JournalError = ProductEvaluationAttemptJournalErrorV1;

pub(super) struct EvalJournalFixture {
    // Close both locked files before their temporary directories are removed.
    pub(super) journal: AnchoredProductEvaluationAttemptJournalV1<FixtureAnchor>,
    root: TempDir,
    anchor_root: TempDir,
    binding: Digest32,
}

impl EvalJournalFixture {
    pub(super) fn create(binding: Digest32) -> Self {
        let root = TempDir::new()
            .unwrap_or_else(|error| panic!("evaluation journal fixture directory: {error}"));
        let anchor_root = TempDir::new()
            .unwrap_or_else(|error| panic!("independent anchor fixture directory: {error}"));
        let authority =
            FixtureAnchor::new(create_file(&anchor_root.path().join("retained.anchor")));
        let journal = AnchoredProductEvaluationAttemptJournalV1::create(
            create_file(&root.path().join("attempt.journal")),
            binding,
            authority,
        )
        .unwrap_or_else(|error| panic!("create anchored evaluation journal: {error}"));
        for directory in [root.path(), anchor_root.path()] {
            File::open(directory)
                .and_then(|file| file.sync_all())
                .unwrap_or_else(|error| panic!("sync fixture directory: {error}"));
        }
        Self {
            journal,
            root,
            anchor_root,
            binding,
        }
    }

    pub(super) fn artifact_root(&self) -> PathBuf {
        self.root.path().join("artifacts")
    }

    pub(super) fn recover(self) -> Self {
        let Self {
            journal,
            root,
            anchor_root,
            binding,
        } = self;
        drop(journal);
        let authority =
            FixtureAnchor::new(reopen_file(&anchor_root.path().join("retained.anchor")));
        let journal = AnchoredProductEvaluationAttemptJournalV1::recover(
            reopen_file(&root.path().join("attempt.journal")),
            binding,
            authority,
        )
        .unwrap_or_else(|error| panic!("recover anchored evaluation journal: {error}"));
        Self {
            journal,
            root,
            anchor_root,
            binding,
        }
    }
}

pub(super) struct FixtureAnchor {
    file: File,
}

impl FixtureAnchor {
    fn new(file: File) -> Self {
        file.try_lock()
            .unwrap_or_else(|error| panic!("exclusive independent anchor fixture: {error}"));
        Self { file }
    }
}

impl ProductEvaluationAttemptAnchorStoreV1 for FixtureAnchor {
    fn load(
        &mut self,
        binding: Digest32,
    ) -> Result<Option<ProductEvaluationAttemptAnchorV1>, JournalError> {
        let length = self.file.metadata().map_err(io_error)?.len();
        if length == 0 {
            return Ok(None);
        }
        if length != 104 {
            return Err(JournalError::Corrupt);
        }
        self.file.seek(SeekFrom::Start(0)).map_err(io_error)?;
        let mut bytes = [0_u8; 104];
        self.file.read_exact(&mut bytes).map_err(io_error)?;
        if &bytes[72..] != Digest32::of_bytes(&bytes[..72]).as_array() {
            return Err(JournalError::Corrupt);
        }
        let anchor = ProductEvaluationAttemptAnchorV1 {
            binding: Digest32::from_array(
                bytes[..32]
                    .try_into()
                    .unwrap_or_else(|error| panic!("fixture binding width: {error}")),
            ),
            event_count: u64::from_be_bytes(
                bytes[32..40]
                    .try_into()
                    .unwrap_or_else(|error| panic!("fixture event count width: {error}")),
            ),
            state_digest: Digest32::from_array(
                bytes[40..72]
                    .try_into()
                    .unwrap_or_else(|error| panic!("fixture state digest width: {error}")),
            ),
        };
        if binding.is_zero() || anchor.binding != binding || anchor.state_digest.is_zero() {
            return Err(JournalError::Binding);
        }
        Ok(Some(anchor))
    }

    fn compare_and_swap(
        &mut self,
        binding: Digest32,
        expected: Option<ProductEvaluationAttemptAnchorV1>,
        next: ProductEvaluationAttemptAnchorV1,
    ) -> Result<(), JournalError> {
        if binding.is_zero()
            || next.binding != binding
            || next.state_digest.is_zero()
            || self.load(binding)? != expected
        {
            return Err(JournalError::Conflict);
        }
        if expected == Some(next) {
            return Ok(());
        }
        if expected.is_some_and(|old| old.event_count >= next.event_count) {
            return Err(JournalError::Conflict);
        }
        let mut bytes = Vec::with_capacity(104);
        bytes.extend_from_slice(next.binding.as_array());
        bytes.extend_from_slice(&next.event_count.to_be_bytes());
        bytes.extend_from_slice(next.state_digest.as_array());
        bytes.extend_from_slice(Digest32::of_bytes(&bytes).as_array());
        self.file
            .seek(SeekFrom::Start(0))
            .and_then(|_| self.file.write_all(&bytes))
            .and_then(|()| self.file.sync_all())
            .map_err(|_| JournalError::Indeterminate)
    }
}

fn create_file(path: &Path) -> File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(path)
        .unwrap_or_else(|error| panic!("create evaluation fixture file: {error}"))
}

fn reopen_file(path: &Path) -> File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)
        .unwrap_or_else(|error| panic!("reopen evaluation fixture file: {error}"))
}

fn io_error(error: std::io::Error) -> JournalError {
    JournalError::Io(error.kind())
}
