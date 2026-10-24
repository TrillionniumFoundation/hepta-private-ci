//! Files belonging to the original Agent control-directory owner.
//! Host runtime files may share a sticky run directory. They cannot replace
//! the Registry's controller identity by supplying a higher-numbered file.

use crate::FleetRegistryError;
use serde::Deserialize;
use serde::Serialize;
use std::fs::File;
#[cfg(not(unix))]
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;

#[cfg(unix)]
use rustix::fs::Mode;
#[cfg(unix)]
use rustix::fs::OFlags;
#[cfg(unix)]
use std::os::unix::fs::MetadataExt;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

#[derive(Clone, Copy)]
pub(crate) struct ControlOwner {
    #[cfg(unix)]
    uid: u32,
    #[cfg(unix)]
    gid: u32,
    #[cfg(unix)]
    group_reader: bool,
}

impl ControlOwner {
    pub(crate) fn at(agent_root: &Path) -> Result<Self, FleetRegistryError> {
        #[cfg(not(unix))]
        {
            let metadata = std::fs::symlink_metadata(agent_root)?;
            if !metadata.is_dir() || metadata.file_type().is_symlink() {
                return Err(corrupt("Agent control root is not a physical directory"));
            }
            Ok(Self {})
        }
        #[cfg(unix)]
        {
            let directory: File = rustix::fs::open(
                agent_root,
                OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
                Mode::empty(),
            )
            .map_err(std::io::Error::from)?
            .into();
            let metadata = directory.metadata()?;
            if !metadata.is_dir() {
                return Err(corrupt("Agent control root is not a physical directory"));
            }
            if metadata.mode() & 0o022 != 0 {
                return Err(corrupt(
                    "Agent control root is writable by another principal",
                ));
            }
            Ok(Self {
                uid: metadata.uid(),
                gid: metadata.gid(),
                group_reader: metadata.mode() & 0o077 == 0o050,
            })
        }
    }

    pub(crate) fn for_child(child: &Path) -> Result<Self, FleetRegistryError> {
        Self::at(
            child
                .parent()
                .ok_or_else(|| corrupt("Agent control child has no parent"))?,
        )
    }

    pub(crate) fn open(&self, path: &Path) -> Result<File, FleetRegistryError> {
        let file = open_regular(path)?;
        #[cfg(unix)]
        {
            let metadata = file.metadata()?;
            if metadata.uid() != self.uid || metadata.mode() & 0o022 != 0 {
                return Err(corrupt(
                    "control file differs from the original Agent directory owner",
                ));
            }
        }
        Ok(file)
    }

    pub(crate) fn read_text(&self, path: &Path) -> Result<String, FleetRegistryError> {
        let mut file = self.open(path)?;
        let mut text = String::new();
        // Read the SAME descriptor that was checked above. A path replacement
        // cannot change the inode whose bytes the Registry now interprets.
        file.read_to_string(&mut text)?;
        Ok(text)
    }

    pub(crate) fn read_json<T: for<'de> Deserialize<'de>>(
        &self,
        path: &Path,
        max_bytes: u64,
    ) -> Result<T, FleetRegistryError> {
        read_json(self.open(path)?, max_bytes)
    }

    pub(crate) fn write_new(&self, path: &Path, bytes: &[u8]) -> Result<(), FleetRegistryError> {
        #[cfg(unix)]
        {
            // An unprivileged Host cannot use the public Registry API to
            // publish controller state. The crate remains free of unsafe code.
            let caller = rustix::process::geteuid().as_raw();
            if caller != self.uid && caller != 0 {
                return Err(corrupt(
                    "only the original control owner may publish Registry state",
                ));
            }
        }
        #[cfg(unix)]
        let mut file: File = rustix::fs::open(
            path,
            OFlags::WRONLY | OFlags::CREATE | OFlags::EXCL | OFlags::NOFOLLOW | OFlags::CLOEXEC,
            // Deny non-owner write at inode creation: a later chmod cannot
            // revoke a writable descriptor already opened by another UID.
            Mode::from_bits_truncate(0o644),
        )
        .map_err(std::io::Error::from)?
        .into();
        #[cfg(not(unix))]
        let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
        #[cfg(all(test, target_os = "linux"))]
        creation_tests::observe_created(&file, path)?;
        #[cfg(unix)]
        {
            let metadata = file.metadata()?;
            if metadata.uid() != self.uid || metadata.gid() != self.gid {
                // A privileged controller operating an existing user's Fleet
                // preserves that original owner. No path is reopened for chown.
                rustix::fs::fchown(
                    &file,
                    Some(rustix::process::Uid::from_raw(self.uid)),
                    Some(rustix::process::Gid::from_raw(self.gid)),
                )
                .map_err(std::io::Error::from)?;
            }
            let mode = if self.group_reader {
                0o640
            } else {
                file.metadata()?.mode() & 0o777 & !0o022
            };
            file.set_permissions(std::fs::Permissions::from_mode(mode))?;
        }
        file.write_all(bytes)?;
        file.sync_all()?;
        Ok(())
    }

    pub(crate) fn write_json<T: Serialize>(
        &self,
        path: &Path,
        value: &T,
    ) -> Result<(), FleetRegistryError> {
        let mut bytes = serde_json::to_vec(value)
            .map_err(|error| corrupt(format!("encode control JSON: {error}")))?;
        bytes.push(b'\n');
        self.write_new(path, &bytes)
    }
}

pub(crate) fn open_regular(path: &Path) -> Result<File, FleetRegistryError> {
    #[cfg(not(unix))]
    {
        let metadata = std::fs::symlink_metadata(path)?;
        if !metadata.is_file() || metadata.file_type().is_symlink() {
            return Err(corrupt("control path is not a physical regular file"));
        }
    }
    #[cfg(unix)]
    let file: File = rustix::fs::open(
        path,
        OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::CLOEXEC | OFlags::NONBLOCK,
        Mode::empty(),
    )
    .map_err(std::io::Error::from)?
    .into();
    #[cfg(not(unix))]
    let file = OpenOptions::new().read(true).open(path)?;
    if !file.metadata()?.is_file() {
        return Err(corrupt("control path is not a regular file"));
    }
    Ok(file)
}

pub(crate) fn read_json<T: for<'de> Deserialize<'de>>(
    file: File,
    max_bytes: u64,
) -> Result<T, FleetRegistryError> {
    if file.metadata()?.len() > max_bytes {
        return Err(corrupt("control file exceeds its original bound"));
    }
    let limit = max_bytes
        .checked_add(1)
        .ok_or_else(|| corrupt("control byte bound overflow"))?;
    let mut bytes = Vec::new();
    file.take(limit).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > max_bytes {
        return Err(corrupt("control file grew beyond its original bound"));
    }
    serde_json::from_slice(&bytes)
        .map_err(|error| corrupt(format!("invalid control JSON: {error}")))
}

fn corrupt(message: impl Into<String>) -> FleetRegistryError {
    FleetRegistryError::Corrupt(message.into())
}

#[cfg(all(test, target_os = "linux"))]
#[path = "control_file_create_tests.rs"]
mod creation_tests;
