//! First original Agent data handoff; Root retains every control mutation.

use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::os::fd::AsRawFd;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_paths::HeptaFleetRoot;

use crate::AgentdIdentity;

const MAX_FRESH_NODES: usize = 4096;

/// Only `PreparedHostAuthoritySession::initialize_fresh` exposes this operation.
/// Validate and pin the complete bounded scope before changing any ownership.
/// A failure leaves partial bytes and custody observable for Root diagnosis;
/// no caller may reinterpret it as fresh state or retry an authority genesis.
pub(super) fn handoff_fresh_filesystem(
    identity: &AgentdIdentity,
    uid: u32,
    gid: u32,
    protected_state: &Path,
) -> io::Result<PathBuf> {
    // SAFETY: getuid/geteuid only read actual process credentials.
    if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0
        || matches!(uid, 0 | u32::MAX) || matches!(gid, 0 | u32::MAX)
    {
        return Err(refused("actual Root and dedicated non-Root UID/GID required"));
    }
    let protected = RootAuthorityDirectory::open(protected_state).map_err(io::Error::other)?;
    if protected_state.canonicalize()? != protected_state
        || overlaps(protected_state, &identity.fleet_root)
        || overlaps(protected_state, &identity.workspace)
    {
        return Err(refused("protected authority state must be outside Agent data and control roots"));
    }
    let fleet = HeptaFleetRoot::parse(identity.fleet_root.clone()).map_err(io::Error::other)?;
    let registry = FleetRegistry::open_existing(fleet.clone()).map_err(io::Error::other)?;
    let snapshot = registry.load().map_err(io::Error::other)?;
    let record = snapshot.agent(&identity.agent_id)
        .ok_or_else(|| refused("original Agent is not registered"))?;
    if snapshot.agents.len() != 1 || record.lifecycle.lifecycle != AgentLifecycle::Starting
        || record.lifecycle.generation != identity.spawn_generation || record.layout != identity.layout
        || record.manifest.workspace.as_path() != identity.workspace
        || record.manifest.resources != identity.resources
    {
        return Err(refused("fresh filesystem composition requires one exact original Starting Agent"));
    }
    validate_outer_access(&identity.fleet_root, gid)?;
    validate_outer_access(&identity.workspace, gid)?;
    let geometry = fleet.layout();
    let mut control = Vec::new();
    for path in [geometry.fleet_root().as_path(), geometry.agents_root(),
        identity.layout.agent_root(), identity.layout.run_root(), identity.layout.releases_root()]
    {
        control.push(pin_root_node(path, /*directory*/ true)?);
    }
    let run = pin_root_node(geometry.run_root(), /*directory*/ true)?;
    let mut readable = vec![pin_root_node(identity.layout.agent_config(), /*directory*/ false)?];
    pin_original_generations(identity.layout.run_root(), "lifecycle-", &mut readable)?;
    pin_original_generations(identity.layout.releases_root(), "release-state-", &mut readable)?;
    let writer = pin_root_node(identity.layout.writer_lock(), /*directory*/ false)?;
    if writer.metadata()?.mode() & 0o7777 != 0o600 {
        return Err(refused("the original writer lock must retain Root0600 custody"));
    }
    let consumer_root = identity.layout.agent_root().join("final-use");
    match std::fs::symlink_metadata(&consumer_root) {
        Err(error) if error.kind() == io::ErrorKind::NotFound => {}
        Err(error) => return Err(error),
        Ok(_) => return Err(refused("fresh consumer parent already exists")),
    }
    let mut data = Vec::new();
    for path in [identity.layout.home_root(), identity.layout.logs_root(),
        identity.layout.cognitive_root(), identity.layout.matrix_root(), identity.layout.automation_root()]
    {
        collect_fresh_data(path, &mut data, /*depth*/ 0)?;
    }
    let workspace = pin_workspace(&identity.workspace, uid, gid)?;

    // Temporarily close traversal while changing exact prevalidated nodes.
    // The top-level Fleet directory is released last; control stays Root-owned.
    control[0].set_permissions(std::fs::Permissions::from_mode(0o700))?;
    std::fs::DirBuilder::new().mode(0o700).create(&consumer_root)?;
    let consumers = pin_root_node(&consumer_root, /*directory*/ true)?;
    for (file, directory) in &data {
        set_custody(file, uid, gid, if *directory { 0o700 } else { 0o600 })?;
    }
    if let Some(workspace) = workspace {
        set_custody(&workspace, uid, gid, /*mode*/ 0o700)?;
    }
    set_custody(&consumers, uid, gid, /*mode*/ 0o700)?;
    for file in &readable {
        set_custody(file, /*uid*/ 0, gid, /*mode*/ 0o640)?;
    }
    set_custody(&run, /*uid*/ 0, gid, /*mode*/ 0o2710)?;
    for directory in control.iter().rev() {
        set_custody(directory, /*uid*/ 0, gid, /*mode*/ 0o2750)?;
    }
    if registry.load_agent(&identity.agent_id).map_err(io::Error::other)? != *record {
        return Err(refused("original Registry changed during filesystem handoff"));
    }
    // Keep the protected directory pinned through every ownership change.
    drop(protected);
    Ok(consumer_root)
}

fn pin_root_node(path: &Path, directory: bool) -> io::Result<File> {
    let original = std::fs::symlink_metadata(path)?;
    if original.uid() != 0 || original.mode() & 0o022 != 0
        || (directory && !original.is_dir())
        || (!directory && (!original.is_file() || original.nlink() != 1))
    {
        return Err(refused("fresh scope requires physical Root nodes without shared writes or hard links"));
    }
    let flags = libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK
        | if directory { libc::O_DIRECTORY } else { 0 };
    let file = OpenOptions::new().read(true).custom_flags(flags).open(path)?;
    let pinned = file.metadata()?;
    if pinned.dev() != original.dev() || pinned.ino() != original.ino()
        || pinned.uid() != 0 || pinned.mode() & 0o022 != 0
        || (!directory && pinned.nlink() != 1)
        || path.canonicalize()? != path
    {
        return Err(refused("fresh scope changed or contains a path alias"));
    }
    Ok(file)
}

fn collect_fresh_data(path: &Path, nodes: &mut Vec<(File, bool)>, depth: usize) -> io::Result<()> {
    if nodes.len() >= MAX_FRESH_NODES || depth > 32 {
        return Err(refused("fresh data scope exceeds its fixed bound"));
    }
    let directory = std::fs::symlink_metadata(path)?.is_dir();
    let pinned = pin_root_node(path, directory)?;
    if directory {
        for entry in std::fs::read_dir(path)? {
            collect_fresh_data(&entry?.path(), nodes, depth + 1)?;
        }
    }
    if nodes.len() >= MAX_FRESH_NODES {
        return Err(refused("fresh data scope exceeds its fixed bound"));
    }
    // Descendants precede their directory, so an exposed directory's content
    // is never subsequently traversed by Root during this handoff.
    nodes.push((pinned, directory));
    Ok(())
}

fn pin_original_generations(parent: &Path, prefix: &str, files: &mut Vec<File>) -> io::Result<()> {
    for entry in std::fs::read_dir(parent)? {
        let entry = entry?;
        let name = entry.file_name();
        let name = name.to_str().ok_or_else(|| refused("non-UTF-8 control generation"))?;
        if !name.starts_with(prefix) {
            continue;
        }
        let digits = name.strip_prefix(prefix).and_then(|value| value.strip_suffix(".json"))
            .filter(|value| value.len() == 20 && value.bytes().all(|byte| byte.is_ascii_digit()))
            .ok_or_else(|| refused("invalid original control generation name"))?;
        digits.parse::<u64>().map_err(io::Error::other)?;
        if files.len() >= MAX_FRESH_NODES {
            return Err(refused("fresh control history exceeds its fixed bound"));
        }
        files.push(pin_root_node(&entry.path(), /*directory*/ false)?);
    }
    Ok(())
}

fn pin_workspace(path: &Path, uid: u32, gid: u32) -> io::Result<Option<File>> {
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.is_dir() || path.canonicalize()? != path || metadata.mode() & 0o7777 != 0o700 {
        return Err(refused("workspace must already be a canonical private directory"));
    }
    if metadata.uid() == uid && metadata.gid() == gid {
        return Ok(None);
    }
    let pinned = pin_root_node(path, /*directory*/ true)?;
    if std::fs::read_dir(path)?.next().is_some() {
        return Err(refused("existing nonempty Root workspace requires explicit provisioning"));
    }
    Ok(Some(pinned))
}

fn validate_outer_access(path: &Path, gid: u32) -> io::Result<()> {
    let parent = path.parent().ok_or_else(|| refused("missing scope parent"))?;
    for ancestor in parent.ancestors() {
        let metadata = std::fs::symlink_metadata(ancestor)?;
        if !metadata.is_dir() || metadata.uid() != 0 || metadata.mode() & 0o022 != 0
            || (metadata.mode() & 0o001 == 0 && (metadata.gid() != gid || metadata.mode() & 0o010 == 0))
        {
            return Err(refused("outer ancestor must retain Root custody and allow dedicated peer traversal"));
        }
    }
    Ok(())
}

fn set_custody(file: &File, uid: u32, gid: u32, mode: u32) -> io::Result<()> {
    // SAFETY: the live pinned descriptor is owned here. fchown changes exactly
    // that node; no path is resolved after data becomes peer-writable.
    if unsafe { libc::fchown(file.as_raw_fd(), uid, gid) } != 0 {
        return Err(io::Error::last_os_error());
    }
    file.set_permissions(std::fs::Permissions::from_mode(mode))?;
    file.sync_all()?;
    let observed = file.metadata()?;
    if observed.uid() != uid || observed.gid() != gid || observed.mode() & 0o7777 != mode {
        return Err(refused("exact filesystem custody was not established"));
    }
    Ok(())
}

fn overlaps(left: &Path, right: &Path) -> bool {
    left.starts_with(right) || right.starts_with(left)
}

fn refused(message: &str) -> io::Error {
    io::Error::other(format!("original Root filesystem handoff: {message}"))
}

#[cfg(test)]
#[path = "root_agentd_filesystem_tests.rs"]
mod tests;
