//! Platform-specific publication of metadata-only lease state.

#[cfg(not(windows))]
use std::fs::File;
use std::io;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

#[cfg(windows)]
use codex_utils_path::windows_private::Access;
#[cfg(windows)]
use codex_utils_path::windows_private::PrivateDirectory;

use super::LeaseRegistryErrorV1;

pub(super) const MAX_STORE_BYTES: usize = 8 * 1024 * 1024;

pub(super) struct LeaseStorage {
    path: PathBuf,
    #[cfg(windows)]
    directory: PrivateDirectory,
    #[cfg(windows)]
    file_name: String,
}

impl LeaseStorage {
    pub(super) fn open(path: PathBuf) -> Result<Self, LeaseRegistryErrorV1> {
        #[cfg(windows)]
        let (directory, file_name) = {
            let parent = path.parent().ok_or(LeaseRegistryErrorV1::Unavailable)?;
            let name = path
                .file_name()
                .and_then(|name| name.to_str())
                .ok_or(LeaseRegistryErrorV1::Unavailable)?
                .to_string();
            let directory =
                PrivateDirectory::prepare(parent).map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
            // Validate the authoritative and staging leaf names before loading
            // or publishing anything. Existing unsafe entries remain untouched.
            directory
                .contains(&name)
                .and_then(|_| directory.contains(&format!("{name}.next")))
                .map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
            (directory, name)
        };
        Ok(Self {
            path,
            #[cfg(windows)]
            directory,
            #[cfg(windows)]
            file_name,
        })
    }

    pub(super) fn path(&self) -> &Path {
        &self.path
    }

    pub(super) fn read(&self) -> Result<Option<Vec<u8>>, LeaseRegistryErrorV1> {
        #[cfg(windows)]
        let file = self.directory.open(&self.file_name, Access::Read);
        #[cfg(not(windows))]
        let file = File::open(&self.path);
        let file = match file {
            Ok(file) => file,
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
            Err(_) => return Err(LeaseRegistryErrorV1::Unavailable),
        };
        let mut bytes = Vec::new();
        file.take(MAX_STORE_BYTES as u64 + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
        if bytes.len() > MAX_STORE_BYTES {
            return Err(LeaseRegistryErrorV1::CorruptState);
        }
        Ok(Some(bytes))
    }

    pub(super) fn persist(&self, bytes: &[u8]) -> Result<(), LeaseRegistryErrorV1> {
        self.persist_inner(bytes)
            .map_err(|_| LeaseRegistryErrorV1::Unavailable)
    }

    #[cfg(windows)]
    fn persist_inner(&self, bytes: &[u8]) -> io::Result<()> {
        let next = format!("{}.next", self.file_name);
        let mut file = self.directory.open(&next, Access::Create)?;
        file.set_len(0)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        self.directory.replace(&next, &self.file_name)?;
        self.directory.sync_all()
    }

    #[cfg(not(windows))]
    fn persist_inner(&self, bytes: &[u8]) -> io::Result<()> {
        let parent = self
            .path
            .parent()
            .ok_or_else(|| io::Error::other("registry has no parent"))?;
        std::fs::create_dir_all(parent)?;
        let file_name = self
            .path
            .file_name()
            .and_then(|name| name.to_str())
            .ok_or_else(|| io::Error::other("registry name is not UTF-8"))?;
        let next = parent.join(format!("{file_name}.next"));
        let mut file = File::create(&next)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        std::fs::rename(next, &self.path)?;
        File::open(parent)?.sync_all()
    }
}
