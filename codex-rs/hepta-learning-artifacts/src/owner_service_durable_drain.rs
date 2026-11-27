//! An exact, create-only stop record for the owner already holding the store fence.

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::io::Read;
#[cfg(unix)]
use std::io::Write;
#[cfg(unix)]
use std::os::unix::fs::MetadataExt;
#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const RECORD_NAME: &str = "DRAIN.v1";

pub(super) struct DurableDrain {
    directory: PathBuf,
    expected: Vec<u8>,
}

impl DurableDrain {
    pub(super) fn new(
        root: &Path,
        registry_id: &StableId,
        scope: Digest32,
        binding: Digest32,
    ) -> Self {
        Self {
            directory: root.join("writer"),
            expected: format!("HEPTA-ARTIFACT-DRAIN-V1\n{registry_id}\n{scope}\n{binding}\n")
                .into_bytes(),
        }
    }

    fn validated_record(&self, writable: bool) -> io::Result<Option<File>> {
        let path = self.directory.join(RECORD_NAME);
        let metadata = match fs::symlink_metadata(&path) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(error),
        };
        let expected_length = self.expected.len() as u64;
        if !metadata.is_file() || metadata.len() != expected_length {
            return Err(invalid_record());
        }
        let mut file = OpenOptions::new().read(true).write(writable).open(path)?;
        let opened = file.metadata()?;
        if !opened.is_file() || opened.len() != expected_length {
            return Err(invalid_record());
        }
        #[cfg(unix)]
        if opened.nlink() != 1 || (opened.dev(), opened.ino()) != (metadata.dev(), metadata.ino()) {
            return Err(invalid_record());
        }
        let mut bytes = Vec::new();
        (&mut file)
            .take(expected_length + 1)
            .read_to_end(&mut bytes)?;
        if bytes != self.expected {
            return Err(invalid_record());
        }
        Ok(Some(file))
    }

    pub(super) fn requested(&self) -> io::Result<bool> {
        Ok(self.validated_record(/*writable*/ false)?.is_some())
    }

    #[cfg(not(unix))]
    pub(super) fn persist(&self) -> io::Result<()> {
        Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "drain directory durability is not qualified on this platform",
        ))
    }

    #[cfg(unix)]
    pub(super) fn persist(&self) -> io::Result<()> {
        if !fs::symlink_metadata(&self.directory)?.is_dir() {
            return Err(invalid_record());
        }
        let path = self.directory.join(RECORD_NAME);
        let mut options = OpenOptions::new();
        options.write(true).create_new(true).mode(0o600);
        match options.open(path) {
            Ok(mut file) => {
                file.write_all(&self.expected)?;
                file.sync_all()?;
            }
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
                let file = self
                    .validated_record(/*writable*/ true)?
                    .ok_or_else(invalid_record)?;
                file.sync_all()?;
            }
            Err(error) => return Err(error),
        }
        File::open(&self.directory)?.sync_all()?;
        let parent = self.directory.parent().ok_or_else(invalid_record)?;
        File::open(parent)?.sync_all()
    }
}

fn invalid_record() -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, "invalid artifact drain record")
}
