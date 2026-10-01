//! The child joins an already protected cgroup before any executable effect.

use std::ffi::OsString;
use std::fs::File;
use std::fs::OpenOptions;
use std::os::fd::AsRawFd;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::process::CommandExt;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceVectorV1;
use codex_hepta_paths::HeptaAgentLayout;

use super::Policy;
use super::host_error;
use super::trust;
use crate::ProcessDriverError;

pub(crate) struct PreparedExecution {
    pub id: String,
    pub relative: String,
    membership: File,
    pub launch: Option<tokio::sync::OwnedMutexGuard<()>>,
    pub environment: Vec<(OsString, OsString)>,
}

pub(super) fn prepare_base(policy: &Policy) -> Result<(), ProcessDriverError> {
    if !policy.cgroup_root.starts_with("hepta-")
        || policy.cgroup_root.len() > 80
        || !policy
            .cgroup_root
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
    {
        return Err(ProcessDriverError::new(
            "local host cgroup base must be its dedicated hepta-* component",
        ));
    }
    let root = Path::new("/sys/fs/cgroup");
    trust::validate_root_directory(root)?;
    enable_controllers(root)?;
    let base = root.join(&policy.cgroup_root);
    std::fs::create_dir_all(&base)?;
    trust::validate_root_directory(&base)?;
    enable_controllers(&base)
}

fn enable_controllers(path: &Path) -> Result<(), ProcessDriverError> {
    let controllers = std::fs::read_to_string(path.join("cgroup.controllers"))?;
    for controller in ["cpu", "memory", "pids"] {
        if !controllers
            .split_whitespace()
            .any(|actual| actual == controller)
        {
            return Err(ProcessDriverError::new(format!(
                "required cgroup controller {controller} is unavailable"
            )));
        }
    }
    std::fs::write(path.join("cgroup.subtree_control"), b"+cpu +memory +pids")?;
    Ok(())
}

pub(super) fn create_execution(
    policy: &Policy,
    agent: &AgentId,
    kind: &str,
    execution: &str,
    resources: ResourceVectorV1,
) -> Result<PreparedExecution, ProcessDriverError> {
    let parent = Path::new("/sys/fs/cgroup")
        .join(&policy.cgroup_root)
        .join(format!("agent-{agent}"));
    std::fs::create_dir_all(&parent)?;
    trust::validate_root_directory(&parent)?;
    enable_controllers(&parent)?;
    let relative = format!("{}/agent-{agent}/{kind}-{execution}", policy.cgroup_root);
    let path = Path::new("/sys/fs/cgroup").join(&relative);
    std::fs::create_dir(&path)?;
    trust::validate_root_directory(&path)?;
    let quota = resources
        .cpu_millis
        .checked_mul(100)
        .ok_or_else(|| ProcessDriverError::new("CPU quota overflow"))?;
    std::fs::write(path.join("cpu.max"), format!("{quota} 100000"))?;
    std::fs::write(path.join("memory.max"), resources.memory_bytes.to_string())?;
    std::fs::write(path.join("memory.swap.max"), b"0")?;
    std::fs::write(path.join("memory.oom.group"), b"1")?;
    std::fs::write(
        path.join("pids.max"),
        resources
            .tool_processes
            .checked_add(policy.process_thread_reserve)
            .ok_or_else(|| ProcessDriverError::new("process quota overflow"))?
            .to_string(),
    )?;
    let membership = OpenOptions::new()
        .write(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path.join("cgroup.procs"))?;
    Ok(PreparedExecution {
        id: execution.into(),
        relative,
        membership,
        launch: None,
        environment: Vec::new(),
    })
}

pub(super) fn constrain(command: &mut Command, prepared: &PreparedExecution, policy: &Policy) {
    command
        .env("HEPTA_FLEET_EXECUTION_ID", &prepared.id)
        .process_group(0);
    let fd = prepared.membership.as_raw_fd();
    let uid = policy.workload_uid;
    let gid = policy.workload_gid;
    // Only async-signal-safe syscalls run between fork and exec. The parent
    // retains the opened protected descriptor until spawn returns; CLOEXEC
    // closes it before the unprivileged executable can observe it.
    unsafe {
        command.pre_exec(move || {
            if libc::write(fd, b"0".as_ptr().cast(), 1) != 1 {
                return Err(std::io::Error::last_os_error());
            }
            if libc::setgroups(0, std::ptr::null()) != 0
                || libc::setresgid(gid, gid, gid) != 0
                || libc::setresuid(uid, uid, uid) != 0
                || libc::prctl(libc::PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0
            {
                return Err(std::io::Error::last_os_error());
            }
            Ok(())
        });
    }
}

pub(super) fn protect_registry(
    registry: &FleetRegistry,
    policy: &Policy,
) -> Result<(), ProcessDriverError> {
    let layout = registry.layout();
    trust::validate_root_directory(layout.fleet_root().as_path())?;
    if policy
        .resource_authority_frontier
        .starts_with(layout.fleet_root().as_path())
    {
        return Err(ProcessDriverError::new(
            "resource anti-rollback frontier must be outside the fleet state root",
        ));
    }
    set_owner(layout.fleet_root().as_path(), 0, policy.workload_gid, 0o750)?;
    set_owner(layout.state_root(), 0, 0, 0o700)?;
    set_owner(layout.run_root(), 0, 0, 0o711)?;
    set_owner(layout.agents_root(), 0, policy.workload_gid, 0o750)?;
    protect_tree(
        layout.releases_root(),
        policy.workload_gid,
        /*executable*/ true,
        /*private_history*/ None,
    )?;
    for record in registry.load().map_err(host_error)?.agents.into_values() {
        prepare_workload(&record.layout, policy)?;
    }
    Ok(())
}

fn protect_agent_metadata(
    layout: &HeptaAgentLayout,
    policy: &Policy,
) -> Result<(), ProcessDriverError> {
    set_owner(layout.agent_root(), 0, policy.workload_gid, 0o750)?;
    set_owner(layout.agent_config(), 0, policy.workload_gid, 0o640)?;
    protect_tree(
        layout.owner_run_root(),
        policy.workload_gid,
        /*executable*/ false,
        Some(
            &layout
                .owner_run_root()
                .join(crate::mutation_history::HISTORY),
        ),
    )?;
    protect_tree(
        layout.releases_root(),
        policy.workload_gid,
        /*executable*/ false,
        /*private_history*/ None,
    )
}

pub(super) fn prepare_workload(
    layout: &HeptaAgentLayout,
    policy: &Policy,
) -> Result<(), ProcessDriverError> {
    protect_agent_metadata(layout, policy)?;
    for path in [
        layout.home_root(),
        layout.run_root(),
        layout.logs_root(),
        layout.cognitive_root(),
        layout.matrix_root(),
        layout.automation_root(),
    ] {
        if std::fs::symlink_metadata(path)?.uid() != policy.workload_uid {
            workload_tree(path, policy, &mut 0)?;
        }
    }
    let socket_root = layout
        .agentd_control_socket()
        .parent()
        .expect("typed socket parent");
    match std::fs::create_dir(socket_root) {
        Ok(()) => {}
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {}
        Err(error) => return Err(error.into()),
    }
    let metadata = std::fs::symlink_metadata(socket_root)?;
    if !metadata.is_dir()
        || metadata.file_type().is_symlink()
        || ![0, policy.workload_uid].contains(&metadata.uid())
    {
        return Err(ProcessDriverError::new(
            "workload socket root has unsafe ownership",
        ));
    }
    set_owner(socket_root, policy.workload_uid, policy.workload_gid, 0o700)
}

fn protect_tree(
    path: &Path,
    gid: u32,
    executable: bool,
    private_history: Option<&Path>,
) -> Result<(), ProcessDriverError> {
    let metadata = std::fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink()
        || !(metadata.is_dir() || metadata.is_file())
        || metadata.uid() != 0
    {
        return Err(ProcessDriverError::new(
            "protected owner tree contains an untrusted entry",
        ));
    }
    if private_history == Some(path) {
        // This native owner alone validates the bounded archive descendants.
        // Shared launch metadata must still become readable by the workload.
        if !metadata.is_dir() || metadata.mode() & 0o7777 != 0o700 {
            return Err(ProcessDriverError::new(
                "private mutation history has unsafe permissions",
            ));
        }
        return Ok(());
    }
    if metadata.is_dir() {
        // Immutable catalog subdirectories must keep every write bit absent;
        // the existing release verifier treats writability as tampering.
        set_owner(
            path,
            0,
            gid,
            if metadata.mode() & 0o200 == 0 {
                0o550
            } else {
                0o750
            },
        )?;
        for entry in std::fs::read_dir(path)? {
            protect_tree(&entry?.path(), gid, executable, private_history)?;
        }
    } else {
        set_owner(
            path,
            0,
            gid,
            if executable && metadata.mode() & 0o111 != 0 {
                0o550
            } else if metadata.mode() & 0o200 == 0 {
                0o440
            } else {
                0o640
            },
        )?;
    }
    Ok(())
}

fn workload_tree(
    path: &Path,
    policy: &Policy,
    count: &mut usize,
) -> Result<(), ProcessDriverError> {
    *count += 1;
    if *count > 100_000 {
        return Err(ProcessDriverError::new(
            "install ownership migration exceeds its bounded batch",
        ));
    }
    let metadata = std::fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink()
        || !(metadata.is_dir() || metadata.is_file())
        || ![0, policy.workload_uid].contains(&metadata.uid())
    {
        return Err(ProcessDriverError::new(
            "workload tree contains a foreign or linked entry",
        ));
    }
    if metadata.is_dir() {
        for entry in std::fs::read_dir(path)? {
            workload_tree(&entry?.path(), policy, count)?;
        }
    }
    set_owner(
        path,
        policy.workload_uid,
        policy.workload_gid,
        if metadata.is_dir() { 0o700 } else { 0o600 },
    )
}

fn set_owner(path: &Path, uid: u32, gid: u32, mode: u32) -> Result<(), ProcessDriverError> {
    let metadata = std::fs::symlink_metadata(path)?;
    if metadata.uid() == uid && metadata.gid() == gid && metadata.mode() & 0o7777 == mode {
        return Ok(());
    }
    let path_bytes =
        std::ffi::CString::new(path.as_os_str().as_encoded_bytes()).map_err(host_error)?;
    if unsafe { libc::chown(path_bytes.as_ptr(), uid, gid) } != 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(mode))?;
    Ok(())
}

pub(super) fn remove_empty_execution(relative: &str) -> Result<(), ProcessDriverError> {
    let path: PathBuf = Path::new("/sys/fs/cgroup").join(relative);
    trust::validate_root_directory(&path)?;
    std::fs::remove_dir(path)?;
    Ok(())
}
