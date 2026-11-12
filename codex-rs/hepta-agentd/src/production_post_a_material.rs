//! One original daemon-owned data file for Root's late publication reader.
//! The writer cannot enroll Root or create a signature. It is consumed once;
//! recovery only compares the existing complete material and never rewrites it.

use std::fs::File;
use std::fs::OpenOptions;
use std::os::fd::AsRawFd;
use std::os::unix::fs::FileExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::PathBuf;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Instant;

use serde::Deserialize;

use super::OriginalFiles;
use super::post_a_remaining;
use super::refused;
use crate::AgentdError;

#[derive(Clone, Copy, Deserialize)]
#[serde(rename_all = "snake_case")]
enum MaterialMode {
    Create,
    Recover,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct MaterialData {
    path: PathBuf,
    mode: MaterialMode,
}

#[derive(Clone, Copy, Eq, PartialEq)]
struct Pin {
    device: u64,
    inode: u64,
    uid: u32,
    gid: u32,
    mode: u32,
}

pub(super) struct OriginalMaterialWriter {
    data: MaterialData,
    file: File,
    pin: Pin,
    end: Instant,
}

pub(super) struct OriginalMaterialReadback {
    path: PathBuf,
    file: File,
    pin: Pin,
    bytes: Vec<u8>,
    end: Instant,
    fenced: AtomicBool,
}

impl MaterialData {
    pub(super) fn open_original(
        self,
        files: &mut OriginalFiles,
        end: Instant,
    ) -> Result<OriginalMaterialWriter, AgentdError> {
        post_a_remaining(end)?;
        let file = files.write(&self.path)?;
        file.try_lock().map_err(refused)?;
        let pin = Pin::read(&file.metadata()?)?;
        // SAFETY: both calls only read this process's actual kernel credentials.
        let actual_owner = unsafe { (libc::geteuid(), libc::getegid()) };
        if actual_owner.0 == 0 || (pin.uid, pin.gid) != actual_owner {
            return Err(refused(
                "original material belongs to another process owner",
            ));
        }
        let writer = OriginalMaterialWriter {
            data: self,
            file,
            pin,
            end,
        };
        writer.require_original()?;
        let length = writer.file.metadata()?.len();
        if match writer.data.mode {
            MaterialMode::Create => length != 0,
            MaterialMode::Recover => !(1..=65_536).contains(&length),
        } {
            return Err(refused("explicit original material mode differs"));
        }
        post_a_remaining(end)?;
        Ok(writer)
    }
}

impl OriginalMaterialWriter {
    fn require_original(&self) -> Result<(), AgentdError> {
        post_a_remaining(self.end)?;
        self.pin.require_file(&self.file, &self.data.path)?;
        post_a_remaining(self.end)?;
        Ok(())
    }

    pub(super) fn commit_original_material(
        self,
        target: &codex_hepta_neuron::CellGenerationObserverConfigV1,
        selection: &codex_hepta_learning_artifacts::SignedArtifactSelectionV1,
    ) -> Result<OriginalMaterialReadback, AgentdError> {
        self.require_original()?;
        let bytes = crate::RootGenerationPublicationDeploymentV1::encode_original_material(
            target, selection,
        )?;
        match self.data.mode {
            MaterialMode::Create => {
                if self.file.metadata()?.len() != 0 {
                    return Err(refused("original material was already written"));
                }
                // A failed write remains partial on this same inode. No
                // truncate, rename, replacement file or automatic retry.
                self.file.write_all_at(&bytes, /*offset*/ 0)?;
                self.file.sync_all()?;
            }
            MaterialMode::Recover => {}
        }
        self.require_original()?;
        require_exact_bytes(&self.file, &bytes)?;
        // Keep only a new read-only description of the same held inode. The
        // original exclusive writer is dropped before Root can take its SH lock.
        let read = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_CLOEXEC | libc::O_NONBLOCK)
            .open(format!("/proc/self/fd/{}", self.file.as_raw_fd()))?;
        self.pin.require_file(&read, &self.data.path)?;
        self.require_original()?;
        let observed = OriginalMaterialReadback {
            path: self.data.path,
            file: read,
            pin: self.pin,
            bytes,
            end: self.end,
            fenced: AtomicBool::new(false),
        };
        drop(self.file);
        OriginalMaterialReadback::require_unchanged(&observed)?;
        Ok(observed)
    }
}

impl OriginalMaterialReadback {
    pub(super) fn require_unchanged(&self) -> Result<(), AgentdError> {
        if self.fenced.load(Ordering::Acquire) {
            return Err(refused("original material readback is fenced"));
        }
        let result = (|| {
            post_a_remaining(self.end)?;
            self.pin.require_file(&self.file, &self.path)?;
            require_exact_bytes(&self.file, &self.bytes)?;
            self.pin.require_file(&self.file, &self.path)?;
            post_a_remaining(self.end)?;
            Ok(())
        })();
        if result.is_err() {
            self.fenced.store(true, Ordering::Release);
        }
        result
    }
}

impl Pin {
    fn read(metadata: &std::fs::Metadata) -> Result<Self, AgentdError> {
        if !metadata.is_file() || metadata.nlink() != 1 || metadata.mode() != 0o100600 {
            return Err(refused("original single-link private material required"));
        }
        Ok(Self {
            device: metadata.dev(),
            inode: metadata.ino(),
            uid: metadata.uid(),
            gid: metadata.gid(),
            mode: metadata.mode(),
        })
    }

    fn require_file(&self, file: &File, path: &std::path::Path) -> Result<(), AgentdError> {
        let parent = path
            .parent()
            .ok_or_else(|| refused("material parent absent"))?;
        if parent.canonicalize()? != parent
            || Self::read(&file.metadata()?)? != *self
            || Self::read(&std::fs::symlink_metadata(path)?)? != *self
            || parent.canonicalize()? != parent
        {
            return Err(refused("original material custody changed"));
        }
        Ok(())
    }
}

fn require_exact_bytes(file: &File, expected: &[u8]) -> Result<(), AgentdError> {
    if expected.is_empty() || expected.len() > 65_536 {
        return Err(refused("original material exceeds its bound"));
    }
    let stamp = |metadata: &std::fs::Metadata| {
        (
            metadata.len(),
            metadata.mtime(),
            metadata.mtime_nsec(),
            metadata.ctime(),
            metadata.ctime_nsec(),
        )
    };
    let original = stamp(&file.metadata()?);
    if original.0 != expected.len() as u64 {
        return Err(refused("original material length differs"));
    }
    for _ in 0..2 {
        if stamp(&file.metadata()?) != original {
            return Err(refused("original material changed before read"));
        }
        let mut bytes = vec![0; expected.len()];
        file.read_exact_at(&mut bytes, /*offset*/ 0)?;
        if bytes != expected || stamp(&file.metadata()?) != original {
            return Err(refused("original material changed during read"));
        }
    }
    Ok(())
}
