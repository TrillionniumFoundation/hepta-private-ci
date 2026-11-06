//! Unix fault-injection executables test transport failure classification only.
//! The qualification acceptance suite runs the real pinned Python supervisor.

#![cfg(unix)]
#![allow(clippy::expect_used, reason = "HCSN transport fault fixtures")]

use std::os::unix::fs::PermissionsExt;

use super::*;
use crate::hcsn_job::HCSN_SUPERVISOR_SCHEMA_VERSION;
use crate::hcsn_job::HcsnJobIdentityV1;
use crate::hcsn_job::HcsnJobStateV1;

struct Fixture {
    _directory: tempfile::TempDir,
    config: HcsnProcessSupervisorConfig,
    command: HcsnSupervisorCommandV1,
}

impl Fixture {
    fn new(executable_body: &str) -> Self {
        let directory = tempfile::tempdir().expect("transport fixture");
        let root = directory.path().canonicalize().expect("canonical root");
        let source = root.join("qualification/hcsn_training");
        std::fs::create_dir_all(&source).expect("source");
        let script = source.join("supervisor.py");
        std::fs::write(&script, b"# pinned fault-injection source\n").expect("script");
        let executable = root.join("transport-fault-executable");
        std::fs::write(&executable, format!("#!/bin/sh\n{executable_body}\n")).expect("executable");
        std::fs::set_permissions(&executable, std::fs::Permissions::from_mode(0o700))
            .expect("executable mode");
        let durable_root = root.join("store");
        std::fs::create_dir(&durable_root).expect("store");
        let payload = "{\"operation_id\":\"transport-test\"}".to_string();
        let identity = HcsnJobIdentityV1::for_taskflow(
            "provider:hcsn",
            "run",
            "training",
            Sha256Digest::for_bytes(payload.as_bytes()),
        )
        .expect("identity");
        Self {
            command: HcsnSupervisorCommandV1::start(identity, payload).expect("command"),
            config: HcsnProcessSupervisorConfig {
                python_sha256: file_digest(&executable).expect("pin executable"),
                python_executable: executable,
                repository_root: root,
                supervisor_sha256: file_digest(&script).expect("pin source"),
                durable_root,
                deadline: Duration::from_secs(2),
            },
            _directory: directory,
        }
    }

    fn assert_no_transport_files(&self) {
        let leftovers: Vec<_> = std::fs::read_dir(&self.config.durable_root)
            .expect("store")
            .map(|entry| entry.expect("entry").file_name())
            .filter(|name| name.to_string_lossy().starts_with(".hcsn-rpc-"))
            .collect();
        assert!(
            leftovers.is_empty(),
            "transport files remain: {leftovers:?}"
        );
    }
}

#[test]
fn exact_response_is_validated_and_transport_files_are_removed() {
    let fixture = Fixture::new("exec cat \"$5/reply.json\"");
    let observation = HcsnJobObservationV1 {
        schema_version: HCSN_SUPERVISOR_SCHEMA_VERSION,
        dispatch: fixture.command.dispatch.clone(),
        target: fixture.command.target.clone(),
        state: HcsnJobStateV1::Reserved,
        process: None,
        evidence: None,
    };
    std::fs::write(
        fixture.config.durable_root.join("reply.json"),
        serde_json::to_vec(&observation).expect("response"),
    )
    .expect("reply");
    let mut supervisor = HcsnProcessSupervisor::new(fixture.config.clone()).expect("supervisor");
    assert_eq!(supervisor.exchange(&fixture.command), Ok(observation));
    fixture.assert_no_transport_files();
}

#[test]
fn source_change_is_rejected_before_contact() {
    let fixture = Fixture::new("touch \"$5/contacted\"");
    let mut supervisor = HcsnProcessSupervisor::new(fixture.config.clone()).expect("supervisor");
    std::fs::write(
        fixture
            .config
            .repository_root
            .join("qualification/hcsn_training/supervisor.py"),
        b"changed",
    )
    .expect("source drift");
    assert_eq!(
        supervisor.exchange(&fixture.command),
        Err(HcsnSupervisorError::BeforeContact)
    );
    assert!(!fixture.config.durable_root.join("contacted").exists());
    fixture.assert_no_transport_files();
}

#[test]
fn malformed_oversized_and_nonzero_responses_are_unknown_after_contact() {
    for response in [
        b"not-json".to_vec(),
        vec![b'x'; MAX_RESPONSE_BYTES as usize + 1],
    ] {
        let fixture = Fixture::new("exec cat \"$5/reply.json\"");
        std::fs::write(fixture.config.durable_root.join("reply.json"), response).expect("reply");
        let mut supervisor =
            HcsnProcessSupervisor::new(fixture.config.clone()).expect("supervisor");
        assert_eq!(
            supervisor.exchange(&fixture.command),
            Err(HcsnSupervisorError::Unknown)
        );
        fixture.assert_no_transport_files();
    }
    let fixture = Fixture::new("exit 7");
    let mut supervisor = HcsnProcessSupervisor::new(fixture.config.clone()).expect("supervisor");
    assert_eq!(
        supervisor.exchange(&fixture.command),
        Err(HcsnSupervisorError::Unknown)
    );
    fixture.assert_no_transport_files();
}

#[test]
fn timeout_kills_and_reaps_only_the_owned_rpc_child() {
    let mut fixture = Fixture::new("echo $$ > \"$5/rpc.pid\"\nexec sleep 10");
    fixture.config.deadline = Duration::from_millis(200);
    let mut supervisor = HcsnProcessSupervisor::new(fixture.config.clone()).expect("supervisor");
    let started = Instant::now();
    assert_eq!(
        supervisor.exchange(&fixture.command),
        Err(HcsnSupervisorError::Unknown)
    );
    assert!(started.elapsed() < Duration::from_secs(2));
    #[cfg(target_os = "linux")]
    {
        let pid =
            std::fs::read_to_string(fixture.config.durable_root.join("rpc.pid")).expect("RPC pid");
        assert!(
            !Path::new("/proc").join(pid.trim()).exists(),
            "owned child must be reaped"
        );
    }
    fixture.assert_no_transport_files();
}

#[test]
fn a_spawn_failure_is_proven_before_contact() {
    let fixture = Fixture::new("exit 0");
    std::fs::set_permissions(
        &fixture.config.python_executable,
        std::fs::Permissions::from_mode(0o600),
    )
    .expect("remove execute bit");
    let mut supervisor = HcsnProcessSupervisor::new(fixture.config.clone()).expect("supervisor");
    assert_eq!(
        supervisor.exchange(&fixture.command),
        Err(HcsnSupervisorError::BeforeContact)
    );
    fixture.assert_no_transport_files();
}
