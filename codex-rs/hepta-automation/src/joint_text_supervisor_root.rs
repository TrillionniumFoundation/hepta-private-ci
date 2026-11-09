//! Only the Joint transport uses this physical root pin. HCSN's original
//! transport/CLI remain unchanged. Configuration is admitted by the host owner.

use std::fs::File;
use std::fs::Metadata;
use std::os::fd::AsRawFd;
use std::os::unix::fs::MetadataExt;
use std::path::Path;
use std::path::PathBuf;

use super::FixedProcessError;
use crate::joint_text_job::JointTextRootIdentityV1;

pub(super) struct RootGuard {
    path: PathBuf,
    file: File,
    expected: JointTextRootIdentityV1,
}

impl RootGuard {
    pub(super) fn open(
        root: &Path,
        expected: &JointTextRootIdentityV1,
    ) -> Result<Self, FixedProcessError> {
        expected
            .validate()
            .map_err(|_| FixedProcessError::BeforeContact)?;
        let value = Self {
            path: root.to_path_buf(),
            // A trailing directory component makes a substituted FIFO/regular
            // file fail before open; the held directory and named path are
            // then checked against the signed tuple, including symlink refusal.
            file: File::open(root.join(".")).map_err(|_| FixedProcessError::BeforeContact)?,
            expected: expected.clone(),
        };
        value.validate()?;
        Ok(value)
    }

    pub(super) fn validate(&self) -> Result<(), FixedProcessError> {
        let named =
            std::fs::symlink_metadata(&self.path).map_err(|_| FixedProcessError::BeforeContact)?;
        let opened = self
            .file
            .metadata()
            .map_err(|_| FixedProcessError::BeforeContact)?;
        if !self.path.is_absolute()
            || std::fs::canonicalize(&self.path).map_err(|_| FixedProcessError::BeforeContact)?
                != self.path
            || named.file_type().is_symlink()
            || !self.matches(&named)
            || !self.matches(&opened)
        {
            return Err(FixedProcessError::BeforeContact);
        }
        Ok(())
    }

    pub(super) fn storage_path(&self) -> PathBuf {
        PathBuf::from(format!("/proc/self/fd/{}", self.file.as_raw_fd()))
    }

    fn matches(&self, metadata: &Metadata) -> bool {
        metadata.is_dir()
            && metadata.mode() & 0o7777 == 0o700
            && (metadata.dev(), metadata.ino(), metadata.uid())
                == (self.expected.device, self.expected.inode, self.expected.uid)
    }
}
