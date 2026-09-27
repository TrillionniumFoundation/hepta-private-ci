//! One-way durable stop intent under the existing owner fence.
//! Host-protected directories are required; this is not an authentication token.

use std::fs;
use std::fs::File;
#[cfg(unix)]
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

    fn open_record(&self) -> io::Result<Option<File>> {
        let path = self.directory.join(RECORD_NAME);
        let metadata = match fs::symlink_metadata(&path) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(error),
        };
        if !metadata.is_file() || metadata.len() > MAX_RECORD_BYTES {
            return Err(io::Error::new(io::ErrorKind::InvalidData, "invalid drain record"));
        }
        let file = File::open(path)?;
        if !file.metadata()?.is_file() {
            return Err(io::Error::new(io::ErrorKind::InvalidData, "drain is not a file"));
        }
        Ok(Some(file))
    }

    pub(super) fn requested(&self) -> io::Result<bool> {
        let Some(file) = self.open_record()? else {
            return Ok(false);
        };
        let mut bytes = Vec::new();
        file.take(MAX_RECORD_BYTES + 1).read_to_end(&mut bytes)?;
        if bytes != self.expected {
            return Err(io::Error::new(io::ErrorKind::InvalidData, "corrupt or foreign drain record"));
        }
        Ok(true)
    }

    pub(super) fn persist(&self) -> io::Result<()> {
        #[cfg(not(unix))]
        {
            Err(io::Error::new(io::ErrorKind::Unsupported, "directory durability is not qualified"))
        }
        #[cfg(unix)]
        {
            if !fs::symlink_metadata(&self.directory)?.is_dir() {
                return Err(io::Error::new(io::ErrorKind::InvalidData, "invalid control directory"));
            }
            let mut options = OpenOptions::new();
            options.write(true).create_new(true).mode(0o600);
            match options.open(self.directory.join(RECORD_NAME)) {
                Ok(mut file) => {
                    file.write_all(&self.expected)?;
                    file.sync_all()?;
                }
                Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
                    if !self.requested()? {
                        return Err(io::Error::new(io::ErrorKind::InvalidData, "drain disappeared"));
                    }
                    // Re-establish durability after an uncertain previous sync.
                    self.open_record()?.ok_or_else(|| {
                        io::Error::new(io::ErrorKind::InvalidData, "drain disappeared")
                    })?.sync_all()?;
                }
                Err(error) => return Err(error),
            }
            File::open(&self.directory)?.sync_all()?;
            let parent = self.directory.parent().ok_or_else(|| {
                io::Error::new(io::ErrorKind::InvalidInput, "control directory has no parent")
            })?;
            File::open(parent)?.sync_all()
        }
    }
}
