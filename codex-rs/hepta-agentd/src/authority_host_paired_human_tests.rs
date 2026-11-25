//! Synthetic UI/login metadata and actual held self-pidfds. This fixture does
//! not call the Root installer or authenticate an actual physical login.
use super::*;
use crate::HostAuthorityTextUiRegistration;
use crate::authority_host_service::OriginalHumanLifetime;
use crate::text_session::AgentdTextSessionConfig;
use std::os::fd::FromRawFd;

pub(crate) struct SyntheticOriginalHuman {
    human: (HostAuthorityTextUiRegistration, OwnedFd),
    login: OriginalLogindSession,
}

impl SyntheticOriginalHuman {
    pub(crate) fn new(
        route: AgentdTextSessionConfig,
        principal: String,
        permission_revision: u64,
        expires_at_ms: u64,
    ) -> io::Result<Self> {
        let pidfd = || {
            // SAFETY: this only opens a new descriptor for this actual test
            // process; it neither selects nor signals another process.
            let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, std::process::id(), 0) };
            if raw < 0 {
                return Err(io::Error::last_os_error());
            }
            // SAFETY: successful pidfd_open returns one fresh owned descriptor.
            Ok(unsafe { OwnedFd::from_raw_fd(raw as i32) })
        };
        let registration = HostAuthorityTextUiRegistration {
            schema_version: 1,
            socket_path: "/synthetic/unused-ui.sock".into(),
            peer_uid: 1000,
            peer_gid: 1000,
            peer_pid: std::process::id(),
            boot_id: "synthetic-not-a-physical-login".into(),
            process_start_ticks: 1,
            principal_id: principal,
            session_id: "synthetic-held-login".into(),
            permission_revision,
            expires_at_ms,
            route,
            can_interrupt: false,
            can_resolve_approvals: false,
        };
        let login = OriginalLogindSession {
            held: pidfd()?,
            binding: registration.human_binding(),
        };
        Ok(Self {
            human: (registration, pidfd()?),
            login,
        })
    }

    pub(crate) fn lifetime(&self, end: Instant) -> io::Result<OriginalHumanLifetime<'_>> {
        OriginalHumanLifetime::from_original(Some(&self.human), Some(&self.login), end)
    }
}

fn original() -> io::Result<SyntheticOriginalHuman> {
    SyntheticOriginalHuman::new(
        AgentdTextSessionConfig {
            control_socket: "/synthetic/unused-control.sock".into(),
            agent_id: codex_hepta_contracts::AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")
                .map_err(io::Error::other)?,
            spawn_generation: 1,
            thread_id: "synthetic-thread".into(),
            app_server_session_id: "synthetic-session".into(),
            codex_home: "/synthetic/unused-home".into(),
        },
        "synthetic-person".into(),
        /*permission_revision*/ 1,
        /*expires_at_ms*/ u64::MAX,
    )
}

#[test]
fn paired_root_live_human_requires_both_original_descriptors_and_exact_binding() -> io::Result<()> {
    let mut original = original()?;
    let end = Instant::now() + Duration::from_secs(2);
    {
        let held = original.lifetime(end)?;
        held.recheck_original_human_lifetime(&held.binding())?;
        assert!(OriginalHumanLifetime::from_original(None, Some(&original.login), end).is_err());
        assert!(OriginalHumanLifetime::from_original(Some(&original.human), None, end).is_err());
        let mut changed = held.binding();
        changed.permission_revision += 1;
        assert!(held.recheck_original_human_lifetime(&changed).is_err());
    }
    original.login.binding.session_id.push_str("-replacement");
    assert!(original.lifetime(end).is_err());
    Ok(())
}

#[test]
fn paired_root_live_human_keeps_the_original_absolute_deadline() -> io::Result<()> {
    let original = original()?;
    let end = Instant::now() + Duration::from_secs(1);
    let held = original.lifetime(end)?;
    held.recheck_original_human_lifetime(&held.binding())?;
    std::thread::sleep(end.saturating_duration_since(Instant::now()) + Duration::from_millis(1));
    assert!(
        held.recheck_original_human_lifetime(&held.binding())
            .is_err()
    );
    Ok(())
}
