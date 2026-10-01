//! Reuse only digests read from an unchanged file in root custody. This cache
//! carries no per-Agent allowance, revocation, lease or operation authority.

use std::fs::File;
use std::io::Read;
use std::path::Path;

use sha2::Digest;
use sha2::Sha256;

use crate::FleetRegistryError;

#[cfg(unix)]
use std::collections::BTreeMap;
#[cfg(unix)]
use std::os::unix::fs::MetadataExt;
#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;
#[cfg(unix)]
use std::path::PathBuf;
#[cfg(unix)]
use std::sync::Mutex;

#[cfg(unix)]
const MAX_CACHED_PROGRAMS: usize = 256;

#[derive(Debug, Default)]
pub(crate) struct ReleaseDigestCache {
    #[cfg(unix)]
    entries: Mutex<BTreeMap<PathBuf, Entry>>,
}

/// Manifest bytes and identity acquired together by the registry reader.
/// No request can construct this private native identity proof.
pub(crate) struct ManifestRead {
    pub(crate) bytes: Vec<u8>,
    pub(crate) sha256: String,
    #[cfg(unix)]
    path: PathBuf,
    #[cfg(unix)]
    snapshot: Snapshot,
}

impl ManifestRead {
    #[cfg(unix)]
    pub(crate) fn verify_current(&self) -> Result<(), FleetRegistryError> {
        let file = File::options()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(&self.path)?;
        if Snapshot::capture(&self.path, &file)? != self.snapshot {
            return Err(changed(
                "release manifest changed during program validation",
            ));
        }
        Ok(())
    }
}

impl ReleaseDigestCache {
    pub(crate) fn manifest(
        &self,
        path: &Path,
        maximum: u64,
    ) -> Result<ManifestRead, FleetRegistryError> {
        let mut options = File::options();
        options.read(true);
        #[cfg(unix)]
        options.custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC);
        let file = options.open(path)?;
        #[cfg(unix)]
        let snapshot = Snapshot::capture(path, &file)?;
        if file.metadata()?.len() > maximum {
            return Err(changed("release manifest exceeds its read bound"));
        }
        let mut bytes = Vec::new();
        file.take(maximum + 1).read_to_end(&mut bytes)?;
        if bytes.len() as u64 > maximum {
            return Err(changed("release manifest grew beyond its read bound"));
        }
        let manifest = ManifestRead {
            sha256: format!("{:x}", Sha256::digest(&bytes)),
            bytes,
            #[cfg(unix)]
            path: path.to_path_buf(),
            #[cfg(unix)]
            snapshot,
        };
        #[cfg(unix)]
        manifest.verify_current()?;
        Ok(manifest)
    }

    pub(crate) fn sha256(
        &self,
        path: &Path,
        manifest: &ManifestRead,
    ) -> Result<String, FleetRegistryError> {
        self.digest(path, manifest, /*defer_cold_read*/ false)
    }

    pub(crate) fn sha256_prevalidated(
        &self,
        path: &Path,
        manifest: &ManifestRead,
    ) -> Result<String, FleetRegistryError> {
        self.digest(path, manifest, /*defer_cold_read*/ true)
    }

    fn digest(
        &self,
        path: &Path,
        manifest: &ManifestRead,
        defer_cold_read: bool,
    ) -> Result<String, FleetRegistryError> {
        #[cfg(unix)]
        {
            let file = File::options()
                .read(true)
                .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
                .open(path)?;
            self.opened_digest(path, manifest, file, defer_cold_read)
        }
        #[cfg(not(unix))]
        {
            let _ = (manifest, defer_cold_read);
            let mut file = File::open(path)?;
            let length = file.metadata()?.len();
            hash_file(&mut file, length)
        }
    }

    #[cfg(unix)]
    fn opened_digest(
        &self,
        path: &Path,
        manifest: &ManifestRead,
        mut file: File,
        defer_cold_read: bool,
    ) -> Result<String, FleetRegistryError> {
        manifest.verify_current()?;
        let before = Snapshot::capture(path, &file)?;
        let cacheable = before.root_custody.is_some() && manifest.snapshot.root_custody.is_some();
        if cacheable {
            let cached = self
                .entries
                .lock()
                .map_err(|_| changed("digest cache lock poisoned"))?
                .get(path)
                .filter(|entry| {
                    entry.snapshot == before
                        && entry.manifest_snapshot == manifest.snapshot
                        && entry.manifest_sha256 == manifest.sha256
                })
                .map(|entry| entry.sha256.clone());
            if let Some(sha256) = cached {
                if Snapshot::capture(path, &file)? != before {
                    return Err(changed("immutable program changed during cache lookup"));
                }
                manifest.verify_current()?;
                return Ok(sha256);
            }
            if defer_cold_read {
                return Err(FleetRegistryError::ReleasePrevalidationRequired);
            }
        }
        // The file descriptor and visible path must still name the exact file
        // that supplied all bytes. Never hold the cache mutex through disk I/O.
        let sha256 = hash_file(&mut file, before.file.length)?;
        if Snapshot::capture(path, &file)? != before {
            return Err(changed("immutable program changed during hashing"));
        }
        manifest.verify_current()?;
        if cacheable {
            let mut entries = self
                .entries
                .lock()
                .map_err(|_| changed("digest cache lock poisoned"))?;
            if !entries.contains_key(path) && entries.len() >= MAX_CACHED_PROGRAMS {
                entries.pop_first();
            }
            entries.insert(
                path.to_path_buf(),
                Entry {
                    snapshot: before,
                    manifest_sha256: manifest.sha256.clone(),
                    manifest_snapshot: manifest.snapshot.clone(),
                    sha256: sha256.clone(),
                },
            );
        }
        Ok(sha256)
    }

    #[cfg(all(test, unix))]
    fn opened_sha256(
        &self,
        path: &Path,
        manifest: &ManifestRead,
        file: File,
    ) -> Result<String, FleetRegistryError> {
        self.opened_digest(path, manifest, file, /*defer_cold_read*/ false)
    }
}

fn hash_file(file: &mut File, length: u64) -> Result<String, FleetRegistryError> {
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    let mut read_bytes = 0_u64;
    loop {
        let count = file.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        read_bytes = read_bytes
            .checked_add(count as u64)
            .ok_or_else(|| changed("program size overflow"))?;
        if read_bytes > length {
            return Err(changed("immutable program grew during hashing"));
        }
        hasher.update(&buffer[..count]);
    }
    if read_bytes != length {
        return Err(changed("immutable program length changed during hashing"));
    }
    Ok(format!("{:x}", hasher.finalize()))
}

fn changed(message: &str) -> FleetRegistryError {
    FleetRegistryError::Corrupt(message.into())
}

#[cfg(unix)]
#[derive(Clone, Debug, Eq, PartialEq)]
struct FileIdentity {
    device: u64,
    inode: u64,
    length: u64,
    uid: u32,
    gid: u32,
    mode: u32,
    links: u64,
    ctime_seconds: i64,
    ctime_nanoseconds: i64,
    mtime_seconds: i64,
    mtime_nanoseconds: i64,
}

#[cfg(unix)]
impl FileIdentity {
    fn capture(metadata: &std::fs::Metadata) -> Result<Self, FleetRegistryError> {
        if !metadata.is_file() || metadata.mode() & 0o222 != 0 {
            return Err(changed("immutable program has unsafe type or mode"));
        }
        Ok(Self {
            device: metadata.dev(),
            inode: metadata.ino(),
            length: metadata.len(),
            uid: metadata.uid(),
            gid: metadata.gid(),
            mode: metadata.mode(),
            links: metadata.nlink(),
            ctime_seconds: metadata.ctime(),
            ctime_nanoseconds: metadata.ctime_nsec(),
            mtime_seconds: metadata.mtime(),
            mtime_nanoseconds: metadata.mtime_nsec(),
        })
    }
}

#[cfg(unix)]
#[derive(Clone, Debug, Eq, PartialEq)]
struct DirectoryIdentity {
    path: PathBuf,
    device: u64,
    inode: u64,
    uid: u32,
    gid: u32,
    mode: u32,
}

#[cfg(unix)]
#[derive(Clone, Debug, Eq, PartialEq)]
struct Snapshot {
    file: FileIdentity,
    root_custody: Option<Vec<DirectoryIdentity>>,
}

#[cfg(unix)]
impl Snapshot {
    fn capture(path: &Path, file: &File) -> Result<Self, FleetRegistryError> {
        let identity = FileIdentity::capture(&file.metadata()?)?;
        if FileIdentity::capture(&std::fs::symlink_metadata(path)?)? != identity {
            return Err(changed(
                "immutable program path differs from its opened file",
            ));
        }
        let mut root_custody = None;
        // Other installations keep the original full hashing behavior. Root
        // owns this optimization; it cannot be enabled by a request or marker.
        if identity.uid == 0 && identity.links == 1 && path.is_absolute() {
            let mut directories = Vec::new();
            let mut protected = true;
            for ancestor in path.parent().into_iter().flat_map(Path::ancestors) {
                let metadata = std::fs::symlink_metadata(ancestor)?;
                if !metadata.is_dir() || metadata.uid() != 0 || metadata.mode() & 0o022 != 0 {
                    protected = false;
                    break;
                }
                directories.push(DirectoryIdentity {
                    path: ancestor.to_path_buf(),
                    device: metadata.dev(),
                    inode: metadata.ino(),
                    uid: metadata.uid(),
                    gid: metadata.gid(),
                    mode: metadata.mode(),
                });
            }
            if protected && !directories.is_empty() && path.canonicalize()? == path {
                root_custody = Some(directories);
            }
        }
        Ok(Self {
            file: identity,
            root_custody,
        })
    }
}

#[cfg(unix)]
#[derive(Debug)]
struct Entry {
    snapshot: Snapshot,
    manifest_sha256: String,
    manifest_snapshot: Snapshot,
    sha256: String,
}

#[cfg(all(test, unix))]
#[path = "release_digest_cache_tests.rs"]
mod tests;
