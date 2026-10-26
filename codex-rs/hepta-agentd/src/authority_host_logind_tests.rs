//! Explicit real Root/physical-login qualification. It creates no authority,
//! thread or model session and never claims native product completion.
use super::*;
use crate::text_session::AgentdTextSessionConfig;
use std::os::fd::FromRawFd;

#[test]
#[ignore = "requires actual Root and an explicitly selected active physical logind session"]
fn original_held_physical_login_matches_actual_logind_and_wrong_birth_or_uid_refuses()
-> Result<(), Box<dyn std::error::Error>> {
    let session = std::env::var("HEPTA_PHYSICAL_LOGIND_SESSION")?;
    let uid: u32 = std::env::var("HEPTA_PHYSICAL_LOGIND_UID")?.parse()?;
    let output = std::process::Command::new("/usr/bin/loginctl")
        .args(["show-session", &session, "--property=Leader", "--value"])
        .env_clear()
        .env("PATH", "/usr/bin:/bin")
        .env(
            "DBUS_SYSTEM_BUS_ADDRESS",
            "unix:path=/run/dbus/system_bus_socket",
        )
        .output()?;
    if !output.status.success() {
        return Err("actual original login is unavailable".into());
    }
    let pid: u32 = std::str::from_utf8(&output.stdout)?.trim().parse()?;
    // SAFETY: the original provider captures the actual queried leader, then
    // independently verifies its held lifetime against logind and process birth.
    let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
    if raw < 0 {
        return Err(io::Error::last_os_error().into());
    }
    // SAFETY: successful pidfd_open returns one fresh owned descriptor.
    let held = unsafe { OwnedFd::from_raw_fd(raw as i32) };
    let stat = std::fs::read_to_string(format!("/proc/{pid}/stat"))?;
    let ticks = stat
        .rsplit_once(") ")
        .and_then(|(_, fields)| fields.split_whitespace().nth(19))
        .ok_or("actual leader birth is missing")?;
    let boot = std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?;
    let machine = std::fs::read_to_string("/etc/machine-id")?;
    let mut profile = HostAuthorityNativeProfile {
        schema_version: 1,
        program: "/usr/bin/true".into(),
        program_sha256: String::new(),
        arguments: vec![],
        working_directory: "/".into(),
        environment: BTreeMap::new(),
        socket_path: "/run/unused-logind-qualification.sock".into(),
        principal_id: format!(
            "linux-user:{:x}:{uid}",
            Sha256::digest(machine.trim().as_bytes())
        ),
        session_id: format!("logind:{}:{session}:{ticks}", boot.trim()),
        permission_revision: 1,
        expires_at_ms: u64::MAX,
        route: AgentdTextSessionConfig {
            control_socket: "/run/unused-logind-qualification-control.sock".into(),
            agent_id: codex_hepta_contracts::AgentId::parse(
                "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12",
            )?,
            spawn_generation: 1,
            thread_id: "unused".into(),
            app_server_session_id: "unused".into(),
            codex_home: "/run/unused-logind-qualification-home".into(),
        },
        can_interrupt: false,
        can_resolve_approvals: false,
    };
    verify_original_login(&profile, uid, &held)?;
    let original = profile.session_id.clone();
    profile.session_id = format!("logind:{}:{session}:0", boot.trim());
    assert!(verify_original_login(&profile, uid, &held).is_err());
    profile.session_id = original;
    assert!(verify_original_login(&profile, uid + 1, &held).is_err());
    Ok(())
}
