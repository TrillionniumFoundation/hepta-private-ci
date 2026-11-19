//! Refusals before any Root connection. These tests create no authority.

use super::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use std::io::Write;
use std::os::fd::FromRawFd;

fn identity(root: &Path) -> AgentdIdentity {
    let agent_id = AgentId::parse("019a2a19-0000-7000-8000-000000000005").unwrap();
    let fleet_root = root.join("fleet");
    let layout = HeptaFleetRoot::parse(fleet_root.clone())
        .unwrap()
        .layout()
        .agent(&agent_id);
    AgentdIdentity {
        agent_id,
        spawn_generation: 1,
        fleet_root,
        workspace: root.join("workspace"),
        resources: ResourceBudget::local_default(),
        home_root: layout.home_root().to_owned(),
        run_root: layout.run_root().to_owned(),
        control_socket: layout.agentd_control_socket().to_owned(),
        app_server_socket: layout.app_server_socket().to_owned(),
        layout,
    }
}

#[test]
fn ordinary_json_file_is_not_a_root_production_handoff() {
    let directory = tempfile::tempdir().unwrap();
    let mut file = tempfile::tempfile().unwrap();
    file.write_all(b"{}").unwrap();
    let error = read_bootstrap(file, &identity(directory.path())).unwrap_err();
    assert!(
        matches!(error, AgentdError::Io(_)),
        "the file must fail custody before JSON parsing"
    );
}

#[test]
fn unsealed_memfd_is_refused_before_parsing_or_connecting() {
    let directory = tempfile::tempdir().unwrap();
    // SAFETY: a static NUL-terminated name creates one new owned descriptor.
    let raw = unsafe {
        libc::memfd_create(
            c"unsealed-root-input-test".as_ptr(),
            libc::MFD_CLOEXEC | libc::MFD_ALLOW_SEALING,
        )
    };
    assert!(raw >= 0);
    // SAFETY: memfd_create above returned the sole owned descriptor.
    let mut file = unsafe { File::from_raw_fd(raw) };
    file.write_all(b"{}").unwrap();
    // SAFETY: the descriptor is retained by file; this changes only fixture mode.
    assert_eq!(unsafe { libc::fchmod(raw, 0o400) }, 0);
    let error = read_bootstrap(file, &identity(directory.path())).unwrap_err();
    assert!(
        matches!(error, AgentdError::Io(error) if error.kind() == std::io::ErrorKind::InvalidData)
    );
}

#[test]
fn empty_or_oversized_handoff_is_refused_before_custody_or_parsing() {
    let directory = tempfile::tempdir().unwrap();
    for length in [0, HOST_AUTHORITY_BOOTSTRAP_BOUND as u64 + 1] {
        let file = tempfile::tempfile().unwrap();
        file.set_len(length).unwrap();
        let error = read_bootstrap(file, &identity(directory.path())).unwrap_err();
        assert!(
            matches!(error, AgentdError::GenerationFenced(message) if message.contains("original bound"))
        );
    }
}

#[tokio::test]
async fn invalid_timing_refuses_before_any_descriptor_or_connection_use() {
    let directory = tempfile::tempdir().unwrap();
    let identity = identity(directory.path());
    for (timeout, lifetime) in [
        (Duration::ZERO, Duration::from_secs(1)),
        (Duration::from_millis(501), Duration::from_secs(1)),
        (Duration::from_millis(1), Duration::ZERO),
        (Duration::from_millis(1), Duration::from_secs(301)),
    ] {
        let error = receive_root_production_inputs(
            File::open("/dev/null").unwrap(),
            File::open("/dev/null").unwrap().into(),
            &identity,
            timeout,
            lifetime,
        )
        .await
        .err()
        .unwrap();
        assert!(
            matches!(error, AgentdError::GenerationFenced(message) if message.contains("timing"))
        );
    }
}
