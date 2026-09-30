//! Local withdrawal high-water marks, not a withdrawal authority.
//!
//! The existing owner fence must be held and the host must protect ancestors.
//! Expected chains come ONLY from a separately authenticated supplied frontier.
//! Restoring the whole directory still needs an independent external floor.

#[cfg(unix)]
use std::fs;
#[cfg(unix)]
use std::fs::File;
#[cfg(unix)]
use std::fs::OpenOptions;
use std::io;
#[cfg(unix)]
use std::io::Read;
#[cfg(unix)]
use std::io::Write;
#[cfg(unix)]
use std::os::unix::fs::DirBuilderExt;
#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::DatasetWithdrawalRegistry;
use crate::MAX_DURABLE_ARTIFACT_RECORDS;

#[cfg(unix)]
const MAX_RECORD_BYTES: u64 = 4096;

fn invalid(message: &'static str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message)
}

#[derive(Debug)]
pub(super) struct DurableWithdrawalFloor {
    directory: PathBuf,
    registry_id: StableId,
    scope: Digest32,
    binding: Digest32,
}

impl DurableWithdrawalFloor {
    pub(super) fn new(
        root: &Path,
        registry_id: &StableId,
        scope: Digest32,
        binding: Digest32,
    ) -> Self {
        Self {
            directory: root.join("writer").join("withdrawal-floor-v1"),
            registry_id: registry_id.clone(),
            scope,
            binding,
        }
    }

    fn expected(&self, frontier: &DatasetWithdrawalRegistry) -> io::Result<Vec<Vec<u8>>> {
        let snapshot = frontier.snapshot();
        if snapshot.scope_digest() != Some(self.scope)
            || snapshot.records().len() > MAX_DURABLE_ARTIFACT_RECORDS
        {
            return Err(invalid("foreign or oversized withdrawal frontier"));
        }
        let scope = snapshot
            .scope()
            .ok_or_else(|| invalid("unscoped withdrawal frontier"))?;
        let genesis = DatasetWithdrawalRegistry::new_scoped(scope.clone()).head_digest();
        Ok(std::iter::once(genesis)
            .chain(snapshot.records().iter().map(|record| record.chain_digest))
            .enumerate()
            .map(|(sequence, head)| {
                format!(
                    "HEPTA-ARTIFACT-WITHDRAWAL-FLOOR-V1\n{}\n{}\n{}\n{sequence}\n{head}\n",
                    self.registry_id, self.scope, self.binding
                )
                .into_bytes()
            })
            .collect())
    }

    #[cfg(unix)]
    fn validated_file(&self, sequence: usize, expected: &[u8]) -> io::Result<File> {
        let path = self.directory.join(format!("{sequence:04}.v1"));
        let metadata = fs::symlink_metadata(&path)?;
        if !metadata.is_file() || metadata.len() > MAX_RECORD_BYTES {
            return Err(invalid("invalid withdrawal floor file"));
        }
        // No bytes are written through this reconciliation handle. Synchronize
        // this exact validated handle, not a second path lookup.
        let mut file = OpenOptions::new().read(true).write(true).open(path)?;
        if !file.metadata()?.is_file() {
            return Err(invalid("withdrawal floor is not a regular file"));
        }
        let mut bytes = Vec::new();
        (&mut file)
            .take(MAX_RECORD_BYTES + 1)
            .read_to_end(&mut bytes)?;
        if bytes != expected {
            return Err(invalid("withdrawal floor is corrupt, forked or foreign"));
        }
        Ok(file)
    }

    #[cfg(unix)]
    fn validate_prefix(&self, expected: &[Vec<u8>]) -> io::Result<()> {
        let mut names = Vec::new();
        for entry in fs::read_dir(&self.directory)? {
            if names.len() > MAX_DURABLE_ARTIFACT_RECORDS {
                return Err(invalid("withdrawal floor directory exceeds its budget"));
            }
            names.push(entry?.file_name());
        }
        names.sort();
        if names.len() > expected.len() {
            return Err(invalid(
                "supplied withdrawal frontier is behind the durable floor",
            ));
        }
        for (sequence, name) in names.iter().enumerate() {
            if name != &std::ffi::OsString::from(format!("{sequence:04}.v1")) {
                return Err(invalid("withdrawal floor has a gap or an unknown entry"));
            }
            self.validated_file(sequence, &expected[sequence])?;
        }
        Ok(())
    }

    /// Persist before acknowledging installation. A full but unsynced exact
    /// retry is re-synced; a truncated record is never overwritten or adopted.
    pub(super) fn persist(&self, frontier: &DatasetWithdrawalRegistry) -> io::Result<()> {
        #[cfg(not(unix))]
        {
            let _ = &self.directory;
            let _ = self.expected(frontier)?;
            Err(io::Error::new(
                io::ErrorKind::Unsupported,
                "withdrawal floor directory durability is not qualified",
            ))
        }
        #[cfg(unix)]
        {
            self.persist_with_hook(frontier, |_, _| Ok(()))
        }
    }

    #[cfg(unix)]
    fn persist_with_hook(
        &self,
        frontier: &DatasetWithdrawalRegistry,
        mut boundary: impl FnMut(usize, &'static str) -> io::Result<()>,
    ) -> io::Result<()> {
        // Validate semantic inputs before creating any path.
        let expected = self.expected(frontier)?;
        let parent = self
            .directory
            .parent()
            .ok_or_else(|| invalid("withdrawal floor has no control parent"))?;
        if !fs::symlink_metadata(parent)?.is_dir() {
            return Err(invalid("invalid withdrawal control parent"));
        }
        match fs::DirBuilder::new().mode(0o700).create(&self.directory) {
            Ok(()) => {}
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {}
            Err(error) => return Err(error),
        }
        if !fs::symlink_metadata(&self.directory)?.is_dir() {
            return Err(invalid("invalid withdrawal floor directory"));
        }
        self.validate_prefix(&expected)?;
        let directory = File::open(&self.directory)?;
        for (sequence, bytes) in expected.iter().enumerate() {
            let mut options = OpenOptions::new();
            options.write(true).create_new(true).mode(0o600);
            match options.open(self.directory.join(format!("{sequence:04}.v1"))) {
                Ok(mut file) => {
                    boundary(sequence, "created")?;
                    file.write_all(bytes)?;
                    boundary(sequence, "written")?;
                    file.sync_all()?;
                    boundary(sequence, "file_synced")?;
                }
                Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
                    self.validated_file(sequence, bytes)?.sync_all()?;
                }
                Err(error) => return Err(error),
            }
            directory.sync_all()?;
            boundary(sequence, "directory_synced")?;
        }
        File::open(parent)?.sync_all()?;
        let root = parent
            .parent()
            .ok_or_else(|| invalid("control parent has no store root"))?;
        File::open(root)?.sync_all()
    }
}

#[cfg(all(test, unix))]
#[path = "withdrawal_floor_tests.rs"]
mod tests;
