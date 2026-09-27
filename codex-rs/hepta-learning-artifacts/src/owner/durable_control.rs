//! One-way durable stop intent under the existing owner fence.
//! Host-protected directories are required; this is not an authentication token.

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::io::Read;
#[cfg(unix)]
use std::io::Write;
#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const RECORD_NAME: &str = "DRAIN.v1";
const MAX_RECORD_BYTES: u64 = 4096;

fn invalid_record(message: &'static str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message)
}

#[derive(Debug)]
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

    fn validated_record(&self) -> io::Result<Option<File>> {
        let path = self.directory.join(RECORD_NAME);
        let metadata = match fs::symlink_metadata(&path) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(error),
        };
        if !metadata.is_file() || metadata.len() > MAX_RECORD_BYTES {
            return Err(invalid_record("invalid drain record"));
        }
        // This is an existing-record reconciliation handle, never a create-only
        // capability and never used to overwrite bytes. The host protects paths.
        let mut file = OpenOptions::new().read(true).write(true).open(path)?;
        if !file.metadata()?.is_file() {
            return Err(invalid_record("drain is not a file"));
        }
        let mut bytes = Vec::new();
        (&mut file)
            .take(MAX_RECORD_BYTES + 1)
            .read_to_end(&mut bytes)?;
        if bytes != self.expected {
            return Err(invalid_record("corrupt or foreign drain record"));
        }
        Ok(Some(file))
    }

    pub(super) fn requested(&self) -> io::Result<bool> {
        Ok(self.validated_record()?.is_some())
    }

    pub(super) fn persist(&self) -> io::Result<()> {
        #[cfg(not(unix))]
        {
            Err(io::Error::new(
                io::ErrorKind::Unsupported,
                "directory durability is not qualified",
            ))
        }
        #[cfg(unix)]
        {
            if !fs::symlink_metadata(&self.directory)?.is_dir() {
                return Err(invalid_record("invalid control directory"));
            }
            let mut options = OpenOptions::new();
            options.write(true).create_new(true).mode(0o600);
            match options.open(self.directory.join(RECORD_NAME)) {
                Ok(mut file) => {
                    file.write_all(&self.expected)?;
                    file.sync_all()?;
                }
                Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
                    let file = self
                        .validated_record()?
                        .ok_or_else(|| invalid_record("drain disappeared"))?;
                    // Reconcile an uncertain sync on the exact validated handle.
                    file.sync_all()?;
                }
                Err(error) => return Err(error),
            }
            File::open(&self.directory)?.sync_all()?;
            let parent = self
                .directory
                .parent()
                .ok_or_else(|| invalid_record("control directory has no parent"))?;
            File::open(parent)?.sync_all()
        }
    }
}
