//! Test-only disk anchor adapted from learning.eval's cold-storage fixture.
//! This uses real locking/fsync/reopen, but is NOT an independently authenticated
//! host authority: its bytes share the test process and temporary filesystem.

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_intelligence_eval::ProductEvaluationAttemptAnchorStoreV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptAnchorV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptJournalErrorV1;
use codex_hepta_types::Digest32;

pub(super) struct DiskAnchorFixture {
    root: PathBuf,
    _lock: File,
}

impl DiskAnchorFixture {
    pub(super) fn new(root: &Path) -> Self {
        fs::create_dir_all(root)
            .unwrap_or_else(|error| panic!("fixture anchor directory: {error}"));
        let lock = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(root.join("anchor.lock"))
            .unwrap_or_else(|error| panic!("fixture anchor lock file: {error}"));
        lock.try_lock()
            .unwrap_or_else(|error| panic!("exclusive fixture anchor: {error}"));
        Self {
            root: root.to_owned(),
            _lock: lock,
        }
    }
}

impl ProductEvaluationAttemptAnchorStoreV1 for DiskAnchorFixture {
    fn load(
        &mut self,
        binding: Digest32,
    ) -> Result<Option<ProductEvaluationAttemptAnchorV1>, ProductEvaluationAttemptJournalErrorV1>
    {
        let file = match File::open(self.root.join("retained")) {
            Ok(file) => file,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(ProductEvaluationAttemptJournalErrorV1::Io(error.kind())),
        };
        let mut bytes = Vec::new();
        file.take(105)
            .read_to_end(&mut bytes)
            .map_err(|error| ProductEvaluationAttemptJournalErrorV1::Io(error.kind()))?;
        if bytes.len() != 104 || bytes[72..] != Digest32::of_bytes(&bytes[..72]).as_array()[..] {
            return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
        }
        let mut stored_binding = [0; 32];
        stored_binding.copy_from_slice(&bytes[..32]);
        let mut event_count = [0; 8];
        event_count.copy_from_slice(&bytes[32..40]);
        let mut state_digest = [0; 32];
        state_digest.copy_from_slice(&bytes[40..72]);
        let anchor = ProductEvaluationAttemptAnchorV1 {
            binding: Digest32::from_array(stored_binding),
            event_count: u64::from_be_bytes(event_count),
            state_digest: Digest32::from_array(state_digest),
        };
        if anchor.binding != binding {
            return Err(ProductEvaluationAttemptJournalErrorV1::Binding);
        }
        Ok(Some(anchor))
    }

    fn compare_and_swap(
        &mut self,
        binding: Digest32,
        expected: Option<ProductEvaluationAttemptAnchorV1>,
        next: ProductEvaluationAttemptAnchorV1,
    ) -> Result<(), ProductEvaluationAttemptJournalErrorV1> {
        if binding.is_zero()
            || next.binding != binding
            || next.state_digest.is_zero()
            || self.load(binding)? != expected
        {
            return Err(ProductEvaluationAttemptJournalErrorV1::Conflict);
        }
        if expected == Some(next) {
            return Ok(());
        }
        if expected.is_some_and(|old| next.event_count <= old.event_count) {
            return Err(ProductEvaluationAttemptJournalErrorV1::Conflict);
        }
        let mut bytes = Vec::new();
        bytes.extend_from_slice(next.binding.as_array());
        bytes.extend_from_slice(&next.event_count.to_be_bytes());
        bytes.extend_from_slice(next.state_digest.as_array());
        bytes.extend_from_slice(Digest32::of_bytes(&bytes).as_array());
        let temporary = self.root.join("anchor.tmp");
        let result = (|| -> std::io::Result<()> {
            let mut file = OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&temporary)?;
            file.write_all(&bytes)?;
            file.sync_all()?;
            fs::rename(&temporary, self.root.join("retained"))?;
            File::open(&self.root)?.sync_all()
        })();
        let _ = fs::remove_file(temporary);
        result.map_err(|_| ProductEvaluationAttemptJournalErrorV1::Indeterminate)
    }
}

pub(super) fn create(path: &Path) -> File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(path)
        .unwrap_or_else(|error| panic!("create fixture journal: {error}"))
}

pub(super) fn reopen(path: &Path) -> File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)
        .unwrap_or_else(|error| panic!("reopen fixture journal: {error}"))
}
