//! Fresh native installation's actual Root/Host filesystem boundary.
//! Original Fleet control files remain writable only by their controller;
//! the Host receives its private cognitive data and runtime file namespace.

use super::*;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetLayout;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;

const HOST: u32 = 60001;

pub(super) fn handoff_fresh(fleet: &HeptaFleetLayout, agent: &HeptaAgentLayout) -> io::Result<()> {
    // SAFETY: these identity queries take no pointer arguments.
    if unsafe { libc::geteuid() } != 0 || unsafe { libc::getegid() } != 0 {
        return Err(invalid(
            "fresh native namespace handoff requires actual Root",
        ));
    }
    for path in [
        fleet.fleet_root().as_path(),
        fleet.state_root(),
        fleet.run_root(),
        fleet.releases_root(),
        fleet.agents_root(),
        agent.agent_root(),
    ] {
        root_directory(path, 0o750)?;
    }
    for path in [
        agent.home_root(),
        agent.matrix_root(),
        agent.cognitive_root(),
    ] {
        private_owner_tree(path)?;
    }
    // Root owns the directory. Sticky mode protects each Root-created control
    // file; setgid gives new control files the explicit Host read group. The
    // original Registry's FD/owner check independently rejects a Host-created
    // future lifecycle file instead of interpreting its forged generation.
    root_directory(agent.run_root(), 0o3770)?;
    for entry in std::fs::read_dir(agent.run_root())? {
        root_file(&entry?.path())?;
    }
    root_file(agent.agent_config())?;
    root_readable_tree(agent.releases_root())?;
    for path in [
        agent.cognitive_root(),
        agent.home_root(),
        agent.matrix_root(),
    ] {
        verify(path, HOST, HOST, 0o700, true)?;
    }
    verify(agent.run_root(), 0, HOST, 0o3770, true)?;
    verify(agent.agent_root(), 0, HOST, 0o750, true)?;
    Ok(())
}

fn root_directory(path: &Path, mode: u32) -> io::Result<()> {
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.is_dir() || metadata.file_type().is_symlink() || metadata.uid() != 0 {
        return Err(invalid(
            "native control directory is not its fresh Root-owned inode",
        ));
    }
    std::os::unix::fs::chown(path, Some(0), Some(HOST))?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(mode))?;
    verify(path, 0, HOST, mode, true)
}

fn root_file(path: &Path) -> io::Result<()> {
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.is_file()
        || metadata.file_type().is_symlink()
        || metadata.uid() != 0
        || metadata.nlink() != 1
    {
        return Err(invalid(
            "fresh native control file is not exclusively Root-owned",
        ));
    }
    std::os::unix::fs::chown(path, Some(0), Some(HOST))?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o640))?;
    verify(path, 0, HOST, 0o640, false)
}

fn root_readable_tree(path: &Path) -> io::Result<()> {
    let metadata = std::fs::symlink_metadata(path)?;
    if metadata.is_dir() && !metadata.file_type().is_symlink() {
        root_directory(path, 0o750)?;
        for entry in std::fs::read_dir(path)? {
            root_readable_tree(&entry?.path())?;
        }
        Ok(())
    } else {
        root_file(path)
    }
}

fn private_owner_tree(path: &Path) -> io::Result<()> {
    let metadata = std::fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink()
        || (!metadata.is_dir() && (!metadata.is_file() || metadata.nlink() != 1))
        || (metadata.uid() != 0 && metadata.uid() != HOST)
    {
        return Err(invalid(
            "native owner data is not a private physical namespace",
        ));
    }
    std::os::unix::fs::chown(path, Some(HOST), Some(HOST))?;
    let mode = if metadata.is_dir() { 0o700 } else { 0o600 };
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(mode))?;
    verify(path, HOST, HOST, mode, metadata.is_dir())?;
    if metadata.is_dir() {
        for entry in std::fs::read_dir(path)? {
            private_owner_tree(&entry?.path())?;
        }
    }
    Ok(())
}

fn verify(path: &Path, uid: u32, gid: u32, mode: u32, directory: bool) -> io::Result<()> {
    let metadata = std::fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink()
        || metadata.uid() != uid
        || metadata.gid() != gid
        || metadata.mode() & 0o7777 != mode
        || metadata.is_dir() != directory
        || (!directory && (!metadata.is_file() || metadata.nlink() != 1))
    {
        return Err(invalid(format!(
            "actual native namespace handoff differs: {}",
            path.display()
        )));
    }
    Ok(())
}

#[cfg(test)]
#[path = "native_cpu_permissions_tests.rs"]
mod tests;
