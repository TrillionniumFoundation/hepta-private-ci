//! Original administrator-reserved data files. Their physical identities are
//! fixed before Root/daemon startup; none of these values is an owner or grant.

use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;

use serde::Serialize;

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub(super) struct OriginalFileData {
    pub(super) path: PathBuf,
    device: u64,
    inode: u64,
    uid: u32,
    gid: u32,
    mode: u32,
}

impl OriginalFileData {
    pub(super) fn reserve(path: PathBuf, uid: u32, gid: u32) -> anyhow::Result<Self> {
        let file = super::super::private_file(&path)?;
        super::super::owned_mode(&path, uid, gid, 0o600)?;
        file.sync_all()?;
        File::open(
            path.parent()
                .ok_or_else(|| anyhow::anyhow!("original reserved file parent"))?,
        )?
        .sync_all()?;
        let declared = Self::capture(&path)?;
        declared.require_file(&file)?;
        anyhow::ensure!(
            file.metadata()?.len() == 0,
            "new original input is not empty"
        );
        Ok(declared)
    }

    pub(super) fn capture(path: &Path) -> anyhow::Result<Self> {
        let metadata = std::fs::symlink_metadata(path)?;
        anyhow::ensure!(
            path.is_absolute()
                && metadata.is_file()
                && metadata.nlink() == 1
                && metadata.mode() == 0o100600,
            "original private regular file required"
        );
        Ok(Self {
            path: path.to_path_buf(),
            device: metadata.dev(),
            inode: metadata.ino(),
            uid: metadata.uid(),
            gid: metadata.gid(),
            mode: metadata.mode(),
        })
    }

    pub(super) fn write_original_once(&self, bytes: &[u8]) -> anyhow::Result<()> {
        anyhow::ensure!(
            (1..=1_048_576).contains(&bytes.len()),
            "bounded original input data required"
        );
        let mut file = self.open_empty_writer()?;
        file.write_all(bytes)?;
        file.sync_all()?;
        self.require_file(&file)?;
        anyhow::ensure!(
            file.metadata()?.len() == bytes.len() as u64,
            "original input length"
        );
        drop(file);
        File::open(
            self.path
                .parent()
                .ok_or_else(|| anyhow::anyhow!("original input parent absent"))?,
        )?
        .sync_all()?;
        Ok(())
    }

    pub(super) fn open_empty_writer(&self) -> anyhow::Result<File> {
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
            .open(&self.path)?;
        file.try_lock()?;
        self.require_file(&file)?;
        anyhow::ensure!(
            file.metadata()?.len() == 0,
            "original input already contains history"
        );
        Ok(file)
    }

    pub(super) fn read_original(&self, maximum: usize) -> anyhow::Result<Vec<u8>> {
        let mut file = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
            .open(&self.path)?;
        file.try_lock_shared()?;
        self.require_file(&file)?;
        let length = file.metadata()?.len();
        anyhow::ensure!(length <= maximum as u64, "bounded original input read");
        let mut bytes = Vec::new();
        Read::by_ref(&mut file)
            .take(maximum as u64 + 1)
            .read_to_end(&mut bytes)?;
        self.require_file(&file)?;
        anyhow::ensure!(
            bytes.len() as u64 == length,
            "original input changed while reading"
        );
        Ok(bytes)
    }

    pub(super) fn require_file(&self, file: &File) -> anyhow::Result<()> {
        let metadata = file.metadata()?;
        anyhow::ensure!(
            Self::capture(&self.path)? == *self
                && metadata.is_file()
                && metadata.nlink() == 1
                && (
                    metadata.dev(),
                    metadata.ino(),
                    metadata.uid(),
                    metadata.gid(),
                    metadata.mode()
                ) == (self.device, self.inode, self.uid, self.gid, self.mode),
            "original input descriptor or path identity changed"
        );
        Ok(())
    }
}
