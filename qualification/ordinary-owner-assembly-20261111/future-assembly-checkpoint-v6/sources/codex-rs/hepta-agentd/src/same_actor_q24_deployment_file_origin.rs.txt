//! One-shot metadata custody for an original Initial file that changes under
//! its real owner. This retains the parent, not an alias of the writer file.
//! Reopening supplies no completion proof; the actual C driver must verify the
//! original completed predecessor and acquire its original exclusive lock.

use std::fs::File;
use std::fs::OpenOptions;
use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use crate::AgentdError;
use crate::root_production_inputs::same_actor_phase::OriginalSameActorRootContext;
use super::{OriginalDeploymentFiles, PhysicalPin, directory_identity, open_original_parent};
use super::super::deployment_refused;

pub(in super::super) struct OriginalOwnerFileOrigin {
    path: PathBuf,
    identity: (u64, u64, u32, u32, u32, u64),
    parent: File,
    parent_path: PathBuf,
    parent_identity: (u64, u64, u32, u32, u32),
    context: Arc<OriginalSameActorRootContext>,
}
impl OriginalOwnerFileOrigin {
    pub(super) fn capture_original(
        file: &File, path: &Path, files: &mut OriginalDeploymentFiles,
    ) -> Result<Self, AgentdError> {
        files.require_original_context()?;
        let metadata = file.metadata()?;
        let inode = (metadata.dev(), metadata.ino());
        if !files.claimed.contains(&inode) || files.immutable.contains_key(&inode)
            || !files.origins.insert(inode) || !metadata.is_file()
            || metadata.uid() != files.uid || metadata.nlink() != 1
            || metadata.mode() & 0o7777 != 0o600
            || PhysicalPin::of(&std::fs::symlink_metadata(path)?) != PhysicalPin::of(&metadata)
        {
            return Err(deployment_refused("one actual Initial owner file is required"));
        }
        let (parent_path, parent) = open_original_parent(path)?;
        let parent_identity = directory_identity(&parent.metadata()?);
        let result = Self {
            path: path.to_owned(),
            identity: (metadata.dev(), metadata.ino(), metadata.uid(), metadata.gid(), metadata.mode(), metadata.nlink()),
            parent, parent_path, parent_identity, context: Arc::clone(&files.context),
        };
        result.require_original_parent()?;
        Ok(result)
    }

    pub(in super::super) fn reopen_original(
        self, files: &mut OriginalDeploymentFiles,
    ) -> Result<File, AgentdError> {
        if !Arc::ptr_eq(&self.context, &files.context) {
            return Err(deployment_refused("Initial file origin belongs to another live context"));
        }
        files.require_original_context()?;
        self.require_original_parent()?;
        let file = OpenOptions::new().read(true).write(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC)
            .open(&self.path)?;
        let metadata = file.metadata()?;
        let actual = (metadata.dev(), metadata.ino(), metadata.uid(), metadata.gid(), metadata.mode(), metadata.nlink());
        if actual != self.identity || !metadata.is_file() || metadata.len() == 0
            || PhysicalPin::of(&std::fs::symlink_metadata(&self.path)?) != PhysicalPin::of(&metadata)
        {
            return Err(deployment_refused("actual completed Initial file was replaced or lost"));
        }
        self.require_original_parent()?;
        files.require_original_context()?;
        Ok(file)
    }

    fn require_original_parent(&self) -> Result<(), AgentdError> {
        if directory_identity(&self.parent.metadata()?) != self.parent_identity
            || directory_identity(&std::fs::symlink_metadata(&self.parent_path)?) != self.parent_identity
            || self.parent_path.canonicalize()? != self.parent_path
        {
            return Err(deployment_refused("original Initial parent changed"));
        }
        Ok(())
    }
}
