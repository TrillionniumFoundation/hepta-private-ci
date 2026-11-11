//! Descriptor checks for one Root-created, Worker-owned journal directory.
//! No public constructor or caller-selected fallback reaches a journal owner.

use super::WorkerRootRegistrationV1;
use super::journal_wire::WORKER_ROOT_JOURNAL_V1;
use super::journal_wire::WorkerJournalDirectoryPinV1;
use super::journal_wire::journal_basename;
use super::refused;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::Sha256Digest;
use rustix::fs::Mode;
use rustix::fs::OFlags;
use std::fs::File;
use std::io;
use std::os::fd::AsRawFd;
use std::os::unix::fs::MetadataExt;
use std::path::Component;
use std::path::Path;

pub(crate) struct WorkerJournalDirectory {
    parent: File,
    directory: File,
    pin: WorkerJournalDirectoryPinV1,
}

impl WorkerJournalDirectory {
    /// Only the retained actual Root/Child protocol invokes this. Root creates
    /// an empty directory, then transfers its UID/GID to the actual Worker.
    /// It does not write authority.lock/json/claims or claim an initialized DB.
    pub(crate) fn create_root_fresh(
        parent_path: &Path,
        registration: &WorkerRootRegistrationV1,
        slot_sequence: u64,
        initial_frontier: FinalUseFrontier,
    ) -> io::Result<Self> {
        if rustix::process::getuid().as_raw() != 0
            || rustix::process::geteuid().as_raw() != 0
            || registration.root.pid != std::process::id()
            || slot_sequence == 0
        {
            return Err(refused(
                "actual Root producer and reserved Worker slot required",
            ));
        }
        registration.validate()?;
        let parent = open_root_parent(parent_path)?;
        // Root alone needs a readable descriptor for the parent fsync below.
        // Reopen the already verified directory itself; Worker traversal keeps
        // an O_PATH descriptor and does not require read access to Root 0711.
        let parent = open_child(&parent, Path::new("."))?;
        let name = journal_basename(&registration.registered_agent_id)?;
        rustix::fs::mkdirat(&parent, name.as_str(), Mode::RWXU).map_err(io::Error::from)?;
        let directory = open_child(&parent, Path::new(&name))?;
        // SAFETY: this is the newly created, owned directory FD; the target
        // credentials are from the original actual Child observation.
        if unsafe {
            libc::fchown(
                directory.as_raw_fd(),
                registration.worker.uid,
                registration.worker.gid,
            )
        } != 0
        {
            return Err(io::Error::last_os_error());
        }
        rustix::fs::fchmod(&directory, Mode::RWXU).map_err(io::Error::from)?;
        directory.sync_all()?;
        parent.sync_all()?;
        let parent_meta = parent.metadata()?;
        let child_meta = directory.metadata()?;
        let pin = WorkerJournalDirectoryPinV1 {
            schema_version: 1,
            purpose: WORKER_ROOT_JOURNAL_V1.into(),
            registration_sha256: Sha256Digest::for_bytes(
                &serde_json::to_vec(registration).map_err(io::Error::other)?,
            ),
            slot_sequence,
            parent: parent_path.to_path_buf(),
            directory: parent_path.join(name),
            parent_device: parent_meta.dev(),
            parent_inode: parent_meta.ino(),
            directory_device: child_meta.dev(),
            directory_inode: child_meta.ino(),
            worker_uid: registration.worker.uid,
            worker_gid: registration.worker.gid,
            initial_frontier,
        };
        let value = Self {
            parent,
            directory,
            pin,
        };
        value.check()?;
        if std::fs::read_dir(&value.pin.directory)?.next().is_some() {
            return Err(refused(
                "fresh Worker journal directory was populated before sealed handoff",
            ));
        }
        value.check()?;
        Ok(value)
    }

    /// Internal receiver uses only the exact pin recovered from the real
    /// sealed Root handoff. It never creates/chowns/chmods a missing directory.
    pub(crate) fn open_from_root_pin(pin: &WorkerJournalDirectoryPinV1) -> io::Result<Self> {
        let parent = open_root_parent(&pin.parent)?;
        let name = pin
            .directory
            .file_name()
            .ok_or_else(|| refused("Worker journal basename missing"))?;
        let directory = open_child(&parent, Path::new(name))?;
        let value = Self {
            parent,
            directory,
            pin: pin.clone(),
        };
        value.check()?;
        Ok(value)
    }

    pub(crate) fn observation(&self) -> &WorkerJournalDirectoryPinV1 {
        &self.pin
    }

    pub(crate) fn check(&self) -> io::Result<()> {
        let named_parent = open_root_parent(&self.pin.parent)?;
        let parent = self.parent.metadata()?;
        let named_parent_meta = named_parent.metadata()?;
        if (parent.dev(), parent.ino()) != (self.pin.parent_device, self.pin.parent_inode)
            || (named_parent_meta.dev(), named_parent_meta.ino()) != (parent.dev(), parent.ino())
        {
            return Err(refused("Worker journal Root parent inode changed"));
        }
        check_root_parent(&self.parent)?;
        let name = self
            .pin
            .directory
            .file_name()
            .ok_or_else(|| refused("Worker journal basename missing"))?;
        let named = open_child(&named_parent, Path::new(name))?;
        for file in [&self.directory, &named] {
            let metadata = file.metadata()?;
            if !metadata.is_dir()
                || metadata.uid() != self.pin.worker_uid
                || metadata.gid() != self.pin.worker_gid
                || metadata.mode() & 0o7777 != 0o700
                || (metadata.dev(), metadata.ino())
                    != (self.pin.directory_device, self.pin.directory_inode)
            {
                return Err(refused(
                    "Worker journal exact UID/GID/mode or directory inode changed",
                ));
            }
        }
        Ok(())
    }
}

fn open_child(parent: &File, name: &Path) -> io::Result<File> {
    rustix::fs::openat(
        parent,
        name,
        OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
        Mode::empty(),
    )
    .map(File::from)
    .map_err(io::Error::from)
}

fn open_search_child(parent: &File, name: &Path) -> io::Result<File> {
    rustix::fs::openat(
        parent,
        name,
        OFlags::PATH | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
        Mode::empty(),
    )
    .map(File::from)
    .map_err(io::Error::from)
}

fn check_root_parent(directory: &File) -> io::Result<()> {
    let metadata = directory.metadata()?;
    if !metadata.is_dir()
        || metadata.uid() != 0
        || metadata.mode() & 0o022 != 0
        || metadata.mode() & 0o001 == 0
    {
        return Err(refused(
            "Root-owned non-writable traversable journal ancestor required",
        ));
    }
    Ok(())
}

fn open_root_parent(path: &Path) -> io::Result<File> {
    if !path.is_absolute() || path.to_str().is_none_or(|value| value.len() > 4096) {
        return Err(refused("bounded absolute Root journal parent required"));
    }
    let mut current: File = rustix::fs::open(
        "/",
        OFlags::PATH | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
        Mode::empty(),
    )
    .map_err(io::Error::from)?
    .into();
    check_root_parent(&current)?;
    for component in path.components() {
        match component {
            Component::RootDir => {}
            Component::Normal(name) => {
                current = open_search_child(&current, Path::new(name))?;
                check_root_parent(&current)?;
            }
            _ => {
                return Err(refused(
                    "journal path traversal, aliases and symlinks are refused",
                ));
            }
        }
    }
    Ok(current)
}
