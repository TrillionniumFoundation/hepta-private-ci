//! Fixed Root deployment locators retain actual original read-only files.
//! Reopening /proc/self/fd obtains an independent open description, not a new
//! path-selected owner or a duplicate cursor whose unlock could release ours.

use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::os::fd::AsRawFd;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::PathBuf;

use serde::Deserialize;

use super::super::generation_publication::deployment::files::OriginalFile;
use crate::CellQ24ModelFilesV1;
use crate::LoadedCellQ24ModelV1;
use crate::authority_host_service::generation_initial::original_root;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct PostAFileData {
    path: PathBuf,
    device: u64,
    inode: u64,
    uid: u32,
    gid: u32,
    mode: u32,
}

pub(super) struct PostAOriginalFile {
    original: OriginalFile,
    expected: PostAFileData,
}

impl PostAOriginalFile {
    pub(super) fn retain_original_file(expected: PostAFileData) -> io::Result<Self> {
        original_root()?;
        if expected.device == 0
            || expected.inode == 0
            || expected.mode & 0o170000 != 0o100000
            || expected.mode & 0o022 != 0
        {
            return Err(io::Error::other(
                "fixed original post-A file identity required",
            ));
        }
        let held = Self {
            original: OriginalFile::open_original(&expected.path)?,
            expected,
        };
        held.read_handle()?;
        Ok(held)
    }

    pub(super) fn same_file(&self, other: &Self) -> bool {
        (self.expected.device, self.expected.inode) == (other.expected.device, other.expected.inode)
    }

    pub(super) fn read_handle(&self) -> io::Result<File> {
        original_root()?;
        self.original.require_original_file()?;
        let descriptor = self.original.original_descriptor()?;
        self.require_identity(&descriptor)?;
        let file = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_CLOEXEC | libc::O_NONBLOCK)
            .open(format!("/proc/self/fd/{}", descriptor.as_raw_fd()))?;
        self.require_identity(&file)?;
        self.original.require_original_file()?;
        Ok(file)
    }

    pub(super) fn require_identity(&self, file: &File) -> io::Result<()> {
        original_root()?;
        self.original.require_original_file()?;
        let actual = file.metadata()?;
        if !actual.is_file()
            || actual.nlink() != 1
            || (
                actual.dev(),
                actual.ino(),
                actual.uid(),
                actual.gid(),
                actual.mode(),
            ) != (
                self.expected.device,
                self.expected.inode,
                self.expected.uid,
                self.expected.gid,
                self.expected.mode,
            )
        {
            return Err(io::Error::other("original post-A file custody changed"));
        }
        self.original.require_original_file()
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct PostABaselineData {
    base: PostAFileData,
    encoder: PostAFileData,
    heads: PostAFileData,
    organ_adapter: Option<PostAFileData>,
    cell_adapter: Option<PostAFileData>,
}

pub(super) struct PostABaselineFiles {
    base: PostAOriginalFile,
    encoder: PostAOriginalFile,
    heads: PostAOriginalFile,
    organ_adapter: Option<PostAOriginalFile>,
    cell_adapter: Option<PostAOriginalFile>,
}

impl PostABaselineFiles {
    pub(super) fn retain_original_baseline(data: PostABaselineData) -> io::Result<Self> {
        original_root()?;
        Ok(Self {
            base: PostAOriginalFile::retain_original_file(data.base)?,
            encoder: PostAOriginalFile::retain_original_file(data.encoder)?,
            heads: PostAOriginalFile::retain_original_file(data.heads)?,
            organ_adapter: data
                .organ_adapter
                .map(PostAOriginalFile::retain_original_file)
                .transpose()?,
            cell_adapter: data
                .cell_adapter
                .map(PostAOriginalFile::retain_original_file)
                .transpose()?,
        })
    }

    pub(super) fn read_model(&self) -> io::Result<LoadedCellQ24ModelV1> {
        original_root()?;
        LoadedCellQ24ModelV1::open_files(CellQ24ModelFilesV1 {
            base: self.base.read_handle()?,
            encoder: self.encoder.read_handle()?,
            heads: self.heads.read_handle()?,
            organ_adapter: self
                .organ_adapter
                .as_ref()
                .map(PostAOriginalFile::read_handle)
                .transpose()?,
            cell_adapter: self
                .cell_adapter
                .as_ref()
                .map(PostAOriginalFile::read_handle)
                .transpose()?,
        })
        .map_err(io::Error::other)
    }
}
