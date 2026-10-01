//! Test-only disk anchor and crash cut. This fixture has real process/file I/O
//! but lives in the test directory, NOT an independently authenticated host.
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use super::eval_fixture::FinalHoldoutCasAnchorV1;
use super::eval_fixture::ProductEvaluationAttemptAnchorStoreV1;
use super::eval_fixture::ProductEvaluationAttemptAnchorV1;
use super::eval_fixture::ProductEvaluationAttemptJournalErrorV1;
use super::types_fixture::Digest32;

pub struct DiskAnchor {
    root: PathBuf,
    _lock: File,
    crash_at: Option<u64>,
}

impl DiskAnchor {
    pub fn new(root: &Path, crash_at: Option<u64>) -> Self {
        fs::create_dir_all(root)
            .unwrap_or_else(|error| panic!("fixture anchor directory: {error:?}"));
        let lock = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(root.join("anchor.lock"))
            .unwrap_or_else(|error| panic!("fixture anchor lock: {error:?}"));
        lock.try_lock()
            .unwrap_or_else(|error| panic!("exclusive fixture anchor: {error:?}"));
        Self {
            root: root.to_owned(),
            _lock: lock,
            crash_at,
        }
    }
}

impl ProductEvaluationAttemptAnchorStoreV1 for DiskAnchor {
    fn load(
        &mut self,
        binding: Digest32,
    ) -> Result<Option<ProductEvaluationAttemptAnchorV1>, ProductEvaluationAttemptJournalErrorV1>
    {
        let path = self.root.join("retained");
        let file = match File::open(path) {
            Ok(value) => value,
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
        let anchor = ProductEvaluationAttemptAnchorV1 {
            binding: Digest32::from_array(
                bytes[..32]
                    .try_into()
                    .unwrap_or_else(|error| panic!("binding width: {error:?}")),
            ),
            event_count: u64::from_be_bytes(
                bytes[32..40]
                    .try_into()
                    .unwrap_or_else(|error| panic!("count width: {error:?}")),
            ),
            state_digest: Digest32::from_array(
                bytes[40..72]
                    .try_into()
                    .unwrap_or_else(|error| panic!("digest width: {error:?}")),
            ),
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
        if self.crash_at == Some(next.event_count) {
            // The native wrapper has fsynced its journal frame, but this anchor
            // has not acknowledged it. Exit does not run Rust destructors.
            std::process::exit(73);
        }
        let mut bytes = Vec::new();
        bytes.extend_from_slice(next.binding.as_array());
        bytes.extend_from_slice(&next.event_count.to_be_bytes());
        bytes.extend_from_slice(next.state_digest.as_array());
        bytes.extend_from_slice(Digest32::of_bytes(&bytes).as_array());
        let temporary = self.root.join(format!("anchor-{}.tmp", std::process::id()));
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

pub fn create(path: &Path) -> File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(path)
        .unwrap_or_else(|error| panic!("create fixture file: {error:?}"))
}

pub fn reopen(path: &Path) -> File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)
        .unwrap_or_else(|error| panic!("open fixture file: {error:?}"))
}

pub fn retain_holdout_anchor(path: &Path, anchor: FinalHoldoutCasAnchorV1) {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(&anchor.fence_generation.to_be_bytes());
    bytes.extend_from_slice(&anchor.record_count.to_be_bytes());
    bytes.extend_from_slice(anchor.state_digest.as_array());
    let mut file = create(path);
    file.write_all(&bytes)
        .unwrap_or_else(|error| panic!("write holdout anchor: {error:?}"));
    file.sync_all()
        .unwrap_or_else(|error| panic!("sync holdout anchor: {error:?}"));
    File::open(path.parent().unwrap_or_else(|| panic!("anchor parent")))
        .unwrap_or_else(|error| panic!("parent: {error:?}"))
        .sync_all()
        .unwrap_or_else(|error| panic!("sync parent: {error:?}"));
}

pub fn load_holdout_anchor(path: &Path) -> FinalHoldoutCasAnchorV1 {
    let bytes = fs::read(path).unwrap_or_else(|error| panic!("holdout anchor: {error:?}"));
    assert_eq!(bytes.len(), 48);
    FinalHoldoutCasAnchorV1 {
        fence_generation: u64::from_be_bytes(
            bytes[..8]
                .try_into()
                .unwrap_or_else(|error| panic!("generation: {error:?}")),
        ),
        record_count: u64::from_be_bytes(
            bytes[8..16]
                .try_into()
                .unwrap_or_else(|error| panic!("count: {error:?}")),
        ),
        state_digest: Digest32::from_array(
            bytes[16..]
                .try_into()
                .unwrap_or_else(|error| panic!("digest: {error:?}")),
        ),
    }
}
