//! Startup-only enrollment of immutable executables. Request admission checks
//! the opened Linux executable and its protected installation path against the
//! exact file that was hashed before the issuer socket became available.

use std::collections::BTreeSet;
use std::fs::File;
use std::fs::Metadata;
use std::io::Read;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;

use anyhow::Context;
use sha2::Digest;
use sha2::Sha256;

use super::store::protected_directory;

pub(super) const MAX_ENROLLED_EXECUTABLES: usize = 16;
const MAX_EXECUTABLE_BYTES: u64 = 512 * 1024 * 1024;

#[derive(Debug, Eq, PartialEq)]
struct FileIdentity {
    device: u64,
    inode: u64,
    length: u64,
    ctime_seconds: i64,
    ctime_nanoseconds: i64,
    mtime_seconds: i64,
    mtime_nanoseconds: i64,
    uid: u32,
    gid: u32,
    mode: u32,
    links: u64,
}

impl FileIdentity {
    fn capture(metadata: &Metadata) -> anyhow::Result<Self> {
        anyhow::ensure!(
            metadata.is_file()
                && metadata.uid() == 0
                && metadata.mode() & 0o022 == 0
                && metadata.nlink() == 1
                && (1..=MAX_EXECUTABLE_BYTES).contains(&metadata.len()),
            "model caller executable is not a bounded root-protected regular file"
        );
        Ok(Self {
            device: metadata.dev(),
            inode: metadata.ino(),
            length: metadata.len(),
            ctime_seconds: metadata.ctime(),
            ctime_nanoseconds: metadata.ctime_nsec(),
            mtime_seconds: metadata.mtime(),
            mtime_nanoseconds: metadata.mtime_nsec(),
            uid: metadata.uid(),
            gid: metadata.gid(),
            mode: metadata.mode(),
            links: metadata.nlink(),
        })
    }
}

struct EnrolledExecutable {
    path: PathBuf,
    identity: FileIdentity,
    sha256: String,
}

impl EnrolledExecutable {
    fn verify_path(&self) -> anyhow::Result<()> {
        protected_directory(self.path.parent().context("executable has no parent")?)?;
        anyhow::ensure!(
            FileIdentity::capture(&std::fs::symlink_metadata(&self.path)?)? == self.identity,
            "enrolled executable path or metadata changed; issuer restart is required"
        );
        Ok(())
    }
}

pub(super) struct ExecutableCache {
    entries: Vec<EnrolledExecutable>,
}

impl ExecutableCache {
    pub(super) fn prewarm(
        paths: &BTreeSet<PathBuf>,
        allowed_sha256: &BTreeSet<String>,
    ) -> anyhow::Result<Self> {
        anyhow::ensure!(
            (1..=MAX_ENROLLED_EXECUTABLES).contains(&paths.len())
                && (1..=MAX_ENROLLED_EXECUTABLES).contains(&allowed_sha256.len()),
            "immutable executable enrollment must contain 1..=16 paths and digests"
        );
        let mut entries = Vec::with_capacity(paths.len());
        for path in paths {
            anyhow::ensure!(
                path.is_absolute() && path.canonicalize()? == *path,
                "enrolled executable path must be absolute and canonical"
            );
            protected_directory(path.parent().context("executable has no parent")?)?;
            let mut file = File::options()
                .read(true)
                .custom_flags(libc::O_NOFOLLOW)
                .open(path)?;
            let identity = FileIdentity::capture(&file.metadata()?)?;
            let mut hasher = Sha256::new();
            let mut buffer = [0_u8; 65_536];
            let mut read_bytes = 0_u64;
            loop {
                let count = file.read(&mut buffer)?;
                if count == 0 {
                    break;
                }
                read_bytes += u64::try_from(count)?;
                anyhow::ensure!(
                    read_bytes <= MAX_EXECUTABLE_BYTES,
                    "executable grew past its bound"
                );
                hasher.update(&buffer[..count]);
            }
            let sha256 = format!("{:x}", hasher.finalize());
            anyhow::ensure!(
                allowed_sha256.contains(&sha256)
                    && read_bytes == identity.length
                    && FileIdentity::capture(&file.metadata()?)? == identity,
                "enrolled executable digest mismatched or file changed during startup"
            );
            let entry = EnrolledExecutable {
                path: path.clone(),
                identity,
                sha256,
            };
            entry.verify_path()?;
            entries.push(entry);
        }
        Ok(Self { entries })
    }

    pub(super) fn verify(&self, executable: &File) -> anyhow::Result<String> {
        let actual = FileIdentity::capture(&executable.metadata()?)?;
        let entry = self
            .entries
            .iter()
            .find(|entry| entry.identity == actual)
            .context("caller executable is not the exact immutable file enrolled at startup")?;
        entry.verify_path()?;
        anyhow::ensure!(
            FileIdentity::capture(&executable.metadata()?)? == actual,
            "caller executable changed during identity verification"
        );
        Ok(entry.sha256.clone())
    }
}

#[cfg(test)]
#[path = "local_model_executable_tests.rs"]
mod tests;
