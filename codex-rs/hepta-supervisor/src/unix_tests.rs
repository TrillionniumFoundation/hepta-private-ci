use std::ffi::OsString;
use std::io::BufRead;
use std::io::BufReader;
use std::io::Write;
use std::os::unix::net::UnixListener;
use std::path::Path;
use std::process::Command;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_agent_protocol::AGENTD_CONTROL_SCHEMA_VERSION;
use codex_hepta_agent_protocol::AgentdPayload;
use codex_hepta_agent_protocol::AgentdRequest;
use codex_hepta_agent_protocol::AgentdResponse;
use codex_hepta_agent_protocol::HealthSnapshot;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_matrix_protocol::MAX_MATRIXD_CONTROL_FRAME_BYTES;
use pretty_assertions::assert_eq;

use super::AgentHealthProbeIdentity;
use super::MatrixHealthProbeIdentity;
use super::UnixProcessDriver;
use super::query_agent_health_once;
use super::query_matrix_health_once;
use crate::AdoptSpec;
use crate::Adoption;
use crate::AgentCommand;
use crate::ManagedProcess;
use crate::MatrixAdoptSpec;
use crate::ProcessDriver;
use crate::ProcessIdentity;
use crate::ProcessState;
use crate::ProcessStream;
use crate::SpawnSpec;

const SQLITE_HOME_POLLUTION_CHILD_ENV: &str = "HEPTA_SUPERVISOR_SQLITE_HOME_POLLUTION_CHILD";
const POLLUTED_SQLITE_HOME: &str = "/tmp/hepta-polluted-shared-sqlite-home";

#[test]
fn unix_wrapper_captures_bounded_stdout_and_stderr() {
    let temp = tempfile::tempdir().expect("temporary directory");
    let command = AgentCommand::new(
        "/bin/sh",
        vec![
            OsString::from("-c"),
            OsString::from("printf stdout; printf stderr >&2"),
        ],
    )
    .expect("valid command");
    let spec = SpawnSpec {
        agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("valid agent id"),
        generation: 1,
        fleet_root: temp.path().join("fleet"),
        workspace: temp.path().to_path_buf(),
        home_root: temp.path().join("home"),
        run_root: temp.path().join("run"),
        control_socket: temp.path().join("run/agentd-control.sock"),
        logs_root: temp.path().join("logs"),
        command,
    };
    let mut process = UnixProcessDriver::new(8)
        .expect("valid driver")
        .spawn(&spec)
        .expect("spawn child")
        .process;
    let deadline = Instant::now() + Duration::from_secs(2);
    let mut logs = Vec::new();
    loop {
        let observation = process.poll(8).expect("poll child");
        logs.extend(observation.logs);
        if matches!(observation.state, ProcessState::Exited(_)) && logs.len() >= 2 {
            break;
        }
        assert!(Instant::now() < deadline, "child did not exit");
        std::thread::yield_now();
    }
    let streams: Vec<_> = logs.iter().map(|log| log.stream).collect();
    assert_eq!(streams.len(), 2);
    assert!(streams.contains(&ProcessStream::Stdout));
    assert!(streams.contains(&ProcessStream::Stderr));
}

#[test]
fn unix_spawn_overrides_polluted_sqlite_home_for_two_agents() {
    if std::env::var_os(SQLITE_HOME_POLLUTION_CHILD_ENV).is_none() {
        let output = Command::new(std::env::current_exe().expect("current test executable"))
            .arg("unix_spawn_overrides_polluted_sqlite_home_for_two_agents")
            .arg("--nocapture")
            .env(SQLITE_HOME_POLLUTION_CHILD_ENV, "1")
            .env("CODEX_SQLITE_HOME", POLLUTED_SQLITE_HOME)
            .output()
            .expect("run isolated polluted-environment child test");
        assert!(
            output.status.success(),
            "polluted-environment child test failed; stdout={}; stderr={}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
        return;
    }

    assert_eq!(
        std::env::var("CODEX_SQLITE_HOME").expect("polluted SQLite environment"),
        POLLUTED_SQLITE_HOME
    );
    let temp = tempfile::tempdir().expect("temporary directory");
    let first_home =
        spawn_sqlite_home_probe(temp.path(), "first", "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12");
    let second_home = spawn_sqlite_home_probe(
        temp.path(),
        "second",
        "019153a4-3088-7e03-a56a-9b1964f75dd3",
    );

    assert_eq!(temp.path().join("first/home"), first_home);
    assert_eq!(temp.path().join("second/home"), second_home);
    assert_ne!(first_home, second_home);
}

fn spawn_sqlite_home_probe(root: &Path, name: &str, agent_id: &str) -> std::path::PathBuf {
    let agent_root = root.join(name);
    let workspace = agent_root.join("workspace");
    let home_root = agent_root.join("home");
    let run_root = agent_root.join("run");
    let logs_root = agent_root.join("logs");
    for directory in [&workspace, &home_root, &run_root, &logs_root] {
        std::fs::create_dir_all(directory).expect("create probe directory");
    }
    let observed_path = workspace.join("observed-sqlite-home");
    let command = AgentCommand::new(
        "/bin/sh",
        vec![
            OsString::from("-c"),
            OsString::from("printf '%s' \"$CODEX_SQLITE_HOME\" > observed-sqlite-home"),
        ],
    )
    .expect("valid probe command");
    let spec = SpawnSpec {
        agent_id: AgentId::parse(agent_id).expect("valid agent id"),
        generation: 1,
        fleet_root: root.join("fleet"),
        workspace,
        home_root,
        run_root: run_root.clone(),
        control_socket: run_root.join("agentd-control.sock"),
        logs_root,
        command,
    };
    let mut process = UnixProcessDriver::new(8)
        .expect("valid driver")
        .spawn(&spec)
        .expect("spawn SQLite home probe")
        .process;
    let deadline = Instant::now() + Duration::from_secs(2);
    loop {
        let observation = process.poll(8).expect("poll SQLite home probe");
        if matches!(observation.state, ProcessState::Exited(_)) {
            break;
        }
        assert!(Instant::now() < deadline, "SQLite home probe did not exit");
        std::thread::yield_now();
    }
    std::path::PathBuf::from(
        std::fs::read_to_string(observed_path).expect("read observed SQLite home"),
    )
}

#[test]
fn failed_exact_adoption_never_signals_an_unrelated_live_pid() {
    let temp = tempfile::tempdir().expect("temporary directory");
    let mut unrelated = Command::new("/bin/sleep")
        .arg("30")
        .spawn()
        .expect("spawn unrelated process");
    let identity = ProcessIdentity::new(
        u64::from(unrelated.id()),
        "deliberately-stale-unrelated-process",
    )
    .expect("process identity");
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("valid agent id");
    let socket = temp.path().join("does-not-exist.sock");
    let mut driver = UnixProcessDriver::new(1).expect("valid driver");

    let agent_adoption = driver
        .adopt(&AdoptSpec {
            agent_id: agent_id.clone(),
            registry_generation: 1,
            spawn_generation: 1,
            workspace: temp.path().join("workspace"),
            home_root: temp.path().join("home"),
            run_root: temp.path().join("run"),
            control_socket: socket.clone(),
            identity: identity.clone(),
        })
        .expect("bounded agentd adoption probe");
    assert!(matches!(agent_adoption, Adoption::Rejected));
    assert!(
        unrelated
            .try_wait()
            .expect("poll unrelated process")
            .is_none(),
        "rejected agentd adoption must not signal the stale PID"
    );

    let matrix_adoption = driver
        .adopt_matrixd(&MatrixAdoptSpec {
            agent_id,
            agent_generation: 1,
            binding_revision: 1,
            binding_digest: Sha256Digest::for_bytes(b"binding"),
            release_id: ReleaseId::parse("matrix-stale-pid-test").expect("release id"),
            process_incarnation: "matrixd-test-incarnation".to_string(),
            plane_epoch: 1,
            control_socket: socket,
            identity,
        })
        .expect("bounded matrixd adoption probe");
    assert!(matches!(matrix_adoption, Adoption::Rejected));
    assert!(
        unrelated
            .try_wait()
            .expect("poll unrelated process")
            .is_none(),
        "rejected matrixd adoption must not signal the stale PID"
    );

    unrelated.kill().expect("terminate test-owned process");
    unrelated.wait().expect("reap test-owned process");
}

#[test]
fn health_probe_requires_exact_agent_generation_pid_and_roots() {
    let temp = tempfile::tempdir().expect("temporary directory");
    let expected_agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent id");
    let other_agent =
        AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dd3").expect("other agent id");
    let identity = AgentHealthProbeIdentity {
        agent_id: expected_agent.clone(),
        spawn_generation: 7,
        process_id: 41,
        workspace: temp.path().join("workspace"),
        home_root: temp.path().join("home"),
        run_root: temp.path().join("run"),
        control_socket: temp.path().join("probe.sock"),
    };

    let exact = health_response(&identity, expected_agent.clone(), 7, 7, 41);
    assert!(serve_and_probe(&identity, 1, exact));

    let wrong_agent = health_response(&identity, other_agent, 7, 7, 41);
    assert!(!serve_and_probe(&identity, 2, wrong_agent));

    let wrong_generation = health_response(&identity, expected_agent.clone(), 7, 8, 41);
    assert!(!serve_and_probe(&identity, 3, wrong_generation));

    let wrong_pid = health_response(&identity, expected_agent, 7, 7, 42);
    assert!(!serve_and_probe(&identity, 4, wrong_pid));

    let running = running_health_response(&identity, 7, 8, 41);
    assert!(serve_and_probe(&identity, 5, running.clone()));
    assert!(serve_and_probe(&identity, 6, running));
}

#[test]
fn matrix_health_transport_rejects_response_larger_than_one_mib() {
    let temp = tempfile::tempdir().expect("temporary directory");
    let socket = temp.path().join("matrix-probe.sock");
    let identity = MatrixHealthProbeIdentity {
        agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("valid agent id"),
        agent_generation: 7,
        binding_revision: 11,
        binding_digest: Sha256Digest::for_bytes(b"binding"),
        release_id: "matrixd-v1".to_string(),
        process_incarnation: "matrixd-incarnation-1".to_string(),
        plane_epoch: 13,
        process_id: 41,
        control_socket: socket.clone(),
    };
    let listener = UnixListener::bind(&socket).expect("bind Matrix probe socket");
    let worker = std::thread::spawn(move || {
        let (stream, _) = listener.accept().expect("accept Matrix probe");
        let mut reader = BufReader::new(stream);
        let mut request = Vec::new();
        reader
            .read_until(b'\n', &mut request)
            .expect("read Matrix health request");
        let mut oversized = vec![
            b'x';
            usize::try_from(MAX_MATRIXD_CONTROL_FRAME_BYTES + 1)
                .expect("frame bound fits usize")
        ];
        *oversized.last_mut().expect("oversized frame") = b'\n';
        let _ = reader.into_inner().write_all(&oversized);
    });

    let observation = query_matrix_health_once(&identity, 1).expect("Matrix health probe");
    assert!(!observation.exact_identity);
    assert!(!observation.ready);
    worker.join().expect("Matrix probe server joins");
    remove_socket(&socket);
}

fn running_health_response(
    identity: &AgentHealthProbeIdentity,
    spawn_generation: u64,
    current_generation: u64,
    process_id: u32,
) -> AgentdResponse {
    let mut response = health_response(
        identity,
        identity.agent_id.clone(),
        spawn_generation,
        current_generation,
        process_id,
    );
    response.payload = AgentdPayload::Health(HealthSnapshot {
        promotion_ready: true,
        ready: true,
        fenced: false,
        lifecycle: codex_hepta_fleet::AgentLifecycle::Running,
        process_id,
        workspace: identity.workspace.clone(),
        home_root: identity.home_root.clone(),
        run_root: identity.run_root.clone(),
    });
    response
}

fn health_response(
    identity: &AgentHealthProbeIdentity,
    agent_id: AgentId,
    spawn_generation: u64,
    current_generation: u64,
    process_id: u32,
) -> AgentdResponse {
    AgentdResponse {
        schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
        request_id: 0,
        agent_id,
        spawn_generation,
        current_generation,
        payload: AgentdPayload::Health(HealthSnapshot {
            promotion_ready: true,
            ready: false,
            fenced: false,
            lifecycle: codex_hepta_fleet::AgentLifecycle::Starting,
            process_id,
            workspace: identity.workspace.clone(),
            home_root: identity.home_root.clone(),
            run_root: identity.run_root.clone(),
        }),
    }
}

fn serve_and_probe(
    identity: &AgentHealthProbeIdentity,
    request_id: u64,
    mut response: AgentdResponse,
) -> bool {
    remove_socket(&identity.control_socket);
    let listener = UnixListener::bind(&identity.control_socket).expect("bind probe socket");
    let worker = std::thread::spawn(move || {
        let (stream, _) = listener.accept().expect("accept probe");
        let mut reader = BufReader::new(stream);
        let mut request_bytes = Vec::new();
        reader
            .read_until(b'\n', &mut request_bytes)
            .expect("read request");
        let request: AgentdRequest =
            serde_json::from_slice(&request_bytes).expect("typed health request");
        response.request_id = request.request_id;
        let mut stream = reader.into_inner();
        serde_json::to_writer(&mut stream, &response).expect("write response");
        stream.write_all(b"\n").expect("terminate response");
    });
    let result = query_agent_health_once(identity, request_id)
        .expect("health probe completes")
        .ready;
    worker.join().expect("probe server joins");
    remove_socket(&identity.control_socket);
    result
}

fn remove_socket(socket: &Path) {
    if let Err(error) = std::fs::remove_file(socket)
        && error.kind() != std::io::ErrorKind::NotFound
    {
        panic!("remove {}: {error}", socket.display());
    }
}
