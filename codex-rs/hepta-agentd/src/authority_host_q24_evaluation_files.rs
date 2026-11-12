//! Original Root B descriptors. Opening a descriptor does not admit its data,
//! register a holdout, acquire an Evaluator role or create a missing file.

use std::collections::BTreeSet;
use std::fs::File;
use std::fs::Metadata;
use std::fs::OpenOptions;
use std::io;
use std::os::fd::AsRawFd;
use std::os::unix::fs::FileExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::super::generation_publication::deployment::files::DirectoryPin;
use super::super::generation_publication::deployment::files::parent;
use super::super::generation_publication::deployment::files::require_absolute;

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalBFileIdentity {
    device: u64,
    inode: u64,
}

impl OriginalBFileIdentity {
    fn capture(metadata: &Metadata) -> io::Result<Self> {
        if !metadata.is_file()
            || metadata.uid() != 0
            || metadata.mode() & 0o7777 != 0o600
            || metadata.nlink() != 1
        {
            return Err(io::Error::other("original Root0600 B file required"));
        }
        Ok(Self {
            device: metadata.dev(),
            inode: metadata.ino(),
        })
    }
}

#[derive(Clone, Copy)]
pub(super) enum OriginalBFileAccess {
    ReadOnly,
    OwnerWriter,
}

pub(super) struct OriginalBFile {
    path: PathBuf,
    parent: DirectoryPin,
    file: File,
    identity: OriginalBFileIdentity,
    access: OriginalBFileAccess,
    poisoned: AtomicBool,
}

/// One tracker spans every input, key and journal. Distinct path spellings do
/// not make two roles independent when they refer to the same physical file.
#[derive(Default)]
pub(super) struct OriginalBFiles {
    identities: BTreeSet<(u64, u64)>,
}

impl OriginalBFiles {
    pub(super) fn open(
        &mut self,
        path: &Path,
        access: OriginalBFileAccess,
    ) -> io::Result<OriginalBFile> {
        crate::authority_host_service::generation_initial::original_root()?;
        require_absolute(path)?;
        let directory = DirectoryPin::capture_root(parent(path)?)?;
        let file = OpenOptions::new()
            .read(true)
            .write(matches!(access, OriginalBFileAccess::OwnerWriter))
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK)
            .open(path)?;
        let identity = OriginalBFileIdentity::capture(&file.metadata()?)?;
        if !self.identities.insert((identity.device, identity.inode)) {
            return Err(io::Error::other("original B files alias another role"));
        }
        let held = OriginalBFile {
            path: path.to_owned(),
            parent: directory,
            file,
            identity,
            access,
            poisoned: AtomicBool::new(false),
        };
        held.require_original()?;
        Ok(held)
    }
}

impl OriginalBFile {
    pub(super) fn identity(&self) -> &OriginalBFileIdentity {
        &self.identity
    }

    pub(super) fn require_original(&self) -> io::Result<()> {
        if self.poisoned.load(Ordering::Acquire) {
            return Err(io::Error::other("original B file was refused"));
        }
        let result = (|| {
            self.parent.require_directory()?;
            if OriginalBFileIdentity::capture(&self.file.metadata()?)? != self.identity
                || OriginalBFileIdentity::capture(&std::fs::symlink_metadata(&self.path)?)?
                    != self.identity
            {
                return Err(io::Error::other("original B file was replaced"));
            }
            self.parent.require_directory()
        })();
        if result.is_err() {
            self.poisoned.store(true, Ordering::Release);
        }
        result
    }

    /// Registration may inspect an empty existing source without exposing a
    /// label. The durable Root registration separately records this identity.
    pub(super) fn require_empty(&self) -> io::Result<()> {
        self.require_original()?;
        if self.file.metadata()?.len() != 0 {
            self.poisoned.store(true, Ordering::Release);
            return Err(io::Error::other(
                "original B reservation requires an empty file",
            ));
        }
        self.require_original()
    }

    pub(super) fn require_nonempty(&self) -> io::Result<()> {
        self.require_original()?;
        if self.file.metadata()?.len() == 0 {
            self.poisoned.store(true, Ordering::Release);
            return Err(io::Error::other(
                "original B recovery cannot initialize missing content",
            ));
        }
        self.require_original()
    }

    /// The private B executor retains this file's original exclusive native
    /// writer while observing its read-only identity pin. Acquiring a second
    /// shared flock would conflict with that already-held original owner.
    /// This returns data only; it does not authenticate or acquire a writer.
    pub(super) fn observe_owned_output(&self) -> io::Result<Digest32> {
        self.require_original()?;
        if !matches!(self.access, OriginalBFileAccess::ReadOnly) {
            return Err(io::Error::other(
                "original B output owner has not taken custody",
            ));
        }
        let result = (|| {
            let mut previous = None;
            for _ in 0..2 {
                let before = self.file.metadata()?;
                if before.len() == 0 || before.len() > 32 * 1024 * 1024 {
                    return Err(io::Error::other("original bounded B output is missing"));
                }
                let mut bytes = vec![0; usize::try_from(before.len()).map_err(io::Error::other)?];
                self.file.read_exact_at(&mut bytes, /*offset*/ 0)?;
                let digest = Digest32::of_bytes(&bytes);
                if stamp(&before) != stamp(&self.file.metadata()?)
                    || previous.is_some_and(|old| old != digest)
                {
                    return Err(io::Error::other(
                        "original B output changed during observation",
                    ));
                }
                self.require_original()?;
                previous = Some(digest);
            }
            previous.ok_or_else(|| io::Error::other("original B output was not read"))
        })();
        if result.is_err() {
            self.poisoned.store(true, Ordering::Release);
        }
        result
    }

    /// Private, data-only physical observation. The Root durable attempt and
    /// original holdout consumption must surround any production label read.
    pub(super) fn read_stable(&self, maximum: usize) -> io::Result<Vec<u8>> {
        self.require_original()?;
        if maximum == 0 || maximum > 1_048_576 {
            return Err(io::Error::other("bounded original B read required"));
        }
        self.file.try_lock_shared().map_err(io::Error::other)?;
        let result = (|| {
            let mut previous = None;
            for _ in 0..2 {
                self.require_original()?;
                let before = self.file.metadata()?;
                let length = usize::try_from(before.len()).map_err(io::Error::other)?;
                if length == 0 || length > maximum {
                    return Err(io::Error::other("original B data is absent or oversized"));
                }
                let mut bytes = vec![0; length];
                self.file.read_exact_at(&mut bytes, /*offset*/ 0)?;
                let after = self.file.metadata()?;
                if stamp(&before) != stamp(&after)
                    || previous.as_ref().is_some_and(|old| old != &bytes)
                {
                    return Err(io::Error::other(
                        "original B image changed during observation",
                    ));
                }
                previous = Some(bytes);
            }
            self.require_original()?;
            previous.ok_or_else(|| io::Error::other("original B image unavailable"))
        })();
        let unlocked = self.file.unlock();
        if result.is_err() || unlocked.is_err() {
            self.poisoned.store(true, Ordering::Release);
        }
        let bytes = result?;
        unlocked?;
        Ok(bytes)
    }

    /// A writer is transferred once, never cloned into a daemon or provider.
    pub(super) fn take_original_writer(&mut self) -> io::Result<File> {
        self.require_original()?;
        if !matches!(self.access, OriginalBFileAccess::OwnerWriter) {
            return Err(io::Error::other("original B writer custody is absent"));
        }
        let readonly = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_CLOEXEC)
            .open(format!("/proc/self/fd/{}", self.file.as_raw_fd()))?;
        if OriginalBFileIdentity::capture(&readonly.metadata()?)? != self.identity {
            return Err(io::Error::other(
                "original B writer changed during transfer",
            ));
        }
        self.require_original()?;
        self.access = OriginalBFileAccess::ReadOnly;
        Ok(std::mem::replace(&mut self.file, readonly))
    }

    pub(super) fn original_readonly(&self) -> io::Result<File> {
        self.require_original()?;
        if !matches!(self.access, OriginalBFileAccess::ReadOnly) {
            return Err(io::Error::other("original B read-only custody is required"));
        }
        let file = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_CLOEXEC)
            .open(format!("/proc/self/fd/{}", self.file.as_raw_fd()))?;
        if OriginalBFileIdentity::capture(&file.metadata()?)? != self.identity {
            return Err(io::Error::other("original B read-only identity differs"));
        }
        self.require_original()?;
        Ok(file)
    }

    pub(super) fn require_digest(&self, expected: Digest32, maximum: usize) -> io::Result<Vec<u8>> {
        let bytes = self.read_stable(maximum)?;
        if expected.is_zero() || Digest32::of_bytes(&bytes) != expected {
            self.poisoned.store(true, Ordering::Release);
            return Err(io::Error::other(
                "original B bytes differ from registration",
            ));
        }
        Ok(bytes)
    }
}

fn stamp(metadata: &Metadata) -> (u64, i64, i64, i64, i64) {
    (
        metadata.len(),
        metadata.mtime(),
        metadata.mtime_nsec(),
        metadata.ctime(),
        metadata.ctime_nsec(),
    )
}
