//! One-way credential transition before any asynchronous worker is created.

use super::*;

impl PreparedRootAgentdConfig {
    /// Drop this same prepared child to its fixed original deployment UID/GID.
    /// Call before arg0 dispatch creates Tokio workers. A multi-threaded process
    /// is refused before any credential syscall, never partially downgraded.
    /// Failure consumes the preparation and must terminate this startup path.
    pub fn drop_to_owner(self) -> Result<Self, AgentdError> {
        if std::process::id() != self.process_id
            // SAFETY: these calls read only the actual process credentials.
            || unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0
        {
            return Err(root_error(
                "credential drop requires the same actual Root child",
            ));
        }
        drop_root_native_owner_credentials(self.expected_uid, self.expected_gid)?;
        Ok(self)
    }
}

/// Revoke Root credentials for an already kernel-authenticated native role,
/// before any runtime thread exists. This grants no role, writer or authority.
/// A Recovery role uses it before its future Supervisor generation exists.
pub fn drop_root_native_owner_credentials(
    expected_uid: u32,
    expected_gid: u32,
) -> Result<(), AgentdError> {
    // SAFETY: these functions read actual process credentials only.
    if unsafe { libc::getuid() } != 0
        || unsafe { libc::geteuid() } != 0
        || matches!(expected_uid, 0 | u32::MAX)
        || matches!(expected_gid, 0 | u32::MAX)
    {
        return Err(root_error(
            "native credential drop requires Root and fixed dedicated UID/GID",
        ));
    }
    require_single_thread()?;
    // SAFETY: these process attribute operations have scalar arguments and
    // are performed in the sole thread before any runtime worker exists.
    if unsafe { libc::prctl(libc::PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) } != 0
        || unsafe {
            libc::prctl(
                libc::PR_CAP_AMBIENT,
                libc::PR_CAP_AMBIENT_CLEAR_ALL,
                0,
                0,
                0,
            )
        } != 0
    {
        return Err(std::io::Error::last_os_error().into());
    }
    for capability in 0..64 {
        // SAFETY: PR_CAPBSET_READ/DROP take a scalar capability number.
        let current = unsafe { libc::prctl(libc::PR_CAPBSET_READ, capability, 0, 0, 0) };
        if current < 0 {
            let error = std::io::Error::last_os_error();
            if capability > 0 && error.raw_os_error() == Some(libc::EINVAL) {
                break;
            }
            return Err(error.into());
        }
        if current != 0 && unsafe { libc::prctl(libc::PR_CAPBSET_DROP, capability, 0, 0, 0) } != 0 {
            return Err(std::io::Error::last_os_error().into());
        }
    }
    // SAFETY: libc's process credential wrappers run with no other thread;
    // setgroups receives a zero count and no array. All real/effective/saved
    // IDs use the already validated dedicated owner, never a -1 sentinel.
    if unsafe { libc::setgroups(0, std::ptr::null()) } != 0
        || unsafe { libc::setresgid(expected_gid, expected_gid, expected_gid) } != 0
        || unsafe { libc::setresuid(expected_uid, expected_uid, expected_uid) } != 0
    {
        return Err(std::io::Error::last_os_error().into());
    }
    #[repr(C)]
    struct Header {
        version: u32,
        pid: i32,
    }
    #[repr(C)]
    struct Data {
        effective: u32,
        permitted: u32,
        inheritable: u32,
    }
    let header = Header {
        version: 0x2008_0522,
        pid: 0,
    };
    let data = [
        Data {
            effective: 0,
            permitted: 0,
            inheritable: 0,
        },
        Data {
            effective: 0,
            permitted: 0,
            inheritable: 0,
        },
    ];
    // SAFETY: Linux capability ABI v3 uses one Header and exactly two Data
    // records; both remain live through this synchronous sole-thread call.
    if unsafe { libc::syscall(libc::SYS_capset, &header, data.as_ptr()) } != 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    crate::authority_host_runtime::verify_process_credentials(
        std::process::id(),
        expected_uid,
        expected_gid,
    )?;
    require_single_thread()?;
    Ok(())
}

fn require_single_thread() -> Result<(), AgentdError> {
    let mut tasks = std::fs::read_dir("/proc/self/task")?;
    let first = tasks
        .next()
        .transpose()?
        .ok_or_else(|| root_error("current process task missing"))?;
    if first.file_name() != std::process::id().to_string().as_str()
        || tasks.next().transpose()?.is_some()
    {
        return Err(root_error(
            "Root credential drop must precede runtime thread creation",
        ));
    }
    Ok(())
}

#[cfg(test)]
#[path = "config_root_credentials_tests.rs"]
mod tests;
