use std::io::BufRead;
use std::io::BufReader;
use std::io::Read;
use std::io::Write;
use std::os::unix::net::UnixListener;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_matrix_protocol::MATRIXD_CONTROL_SCHEMA_VERSION;
use codex_hepta_matrix_protocol::MatrixdHealth;
use codex_hepta_matrix_protocol::MatrixdLifecycle;
use codex_hepta_matrix_protocol::MatrixdPayload;
use codex_hepta_matrix_protocol::MatrixdRequest;
use codex_hepta_matrix_protocol::MatrixdResponse;
use pretty_assertions::assert_eq;

use super::HealthProbeObservation;
use super::MatrixHealthProbeIdentity;
use super::query_matrix_health_once;

type TestResult = Result<(), Box<dyn std::error::Error>>;

fn identity(
    socket: std::path::PathBuf,
    process_id: u32,
) -> Result<MatrixHealthProbeIdentity, Box<dyn std::error::Error>> {
    Ok(MatrixHealthProbeIdentity {
        agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?,
        agent_generation: 7,
        binding_revision: 11,
        binding_digest: Sha256Digest::for_bytes(b"binding"),
        release_id: "matrixd-v1".to_string(),
        process_incarnation: "matrixd-incarnation-1".to_string(),
        plane_epoch: 13,
        process_id,
        control_socket: socket,
    })
}

#[test]
fn matrix_health_accepts_kernel_authenticated_peer_and_exact_envelope() -> TestResult {
    let temp = tempfile::Builder::new()
        .prefix("hpeer-")
        .tempdir_in("/tmp")?;
    let identity = identity(temp.path().join("matrix.sock"), std::process::id())?;
    let listener = UnixListener::bind(&identity.control_socket)?;
    let response = MatrixdResponse {
        schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
        request_id: 17,
        agent_id: identity.agent_id.clone(),
        release_id: identity.release_id.clone(),
        binding_revision: identity.binding_revision,
        binding_digest: identity.binding_digest.clone(),
        attached_agent_generation: identity.agent_generation,
        process_incarnation: identity.process_incarnation.clone(),
        plane_epoch: identity.plane_epoch,
        payload: MatrixdPayload::Health(MatrixdHealth {
            lifecycle: MatrixdLifecycle::Ready,
            process_id: identity.process_id,
            agentd_connected: true,
            matrix_sync_connected: true,
            fenced: false,
        }),
    };
    let worker = std::thread::spawn(move || -> std::io::Result<()> {
        let (stream, _) = listener.accept()?;
        let mut reader = BufReader::new(stream);
        let mut request = Vec::new();
        reader.read_until(b'\n', &mut request)?;
        let request: MatrixdRequest = serde_json::from_slice(&request)?;
        assert_eq!(request.request_id, response.request_id);
        let mut stream = reader.into_inner();
        serde_json::to_writer(&mut stream, &response)?;
        stream.write_all(b"\n")
    });
    let observation = query_matrix_health_once(&identity, /*request_id*/ 17);
    worker.join().expect("peer fixture thread")?;
    assert_eq!(
        observation?,
        HealthProbeObservation {
            exact_identity: true,
            ready: true
        }
    );
    Ok(())
}

#[test]
fn matrix_health_rejects_same_owner_wrong_process_before_sending_request() -> TestResult {
    let temp = tempfile::Builder::new()
        .prefix("hpeer-")
        .tempdir_in("/tmp")?;
    // This live process's PID is deliberately different from the socket owner.
    // Echoing its PID in JSON must never suffice to adopt or later signal it.
    let socket = temp.path().join("matrix.sock");
    let listener = UnixListener::bind(&socket)?;
    let mut unrelated = std::process::Command::new("/bin/sleep").arg("30").spawn()?;
    let identity = identity(socket, unrelated.id())?;
    let worker = std::thread::spawn(move || -> std::io::Result<Vec<u8>> {
        let (mut stream, _) = listener.accept()?;
        stream.set_read_timeout(Some(super::HEALTH_PROBE_IO_TIMEOUT))?;
        let mut request = Vec::new();
        stream.read_to_end(&mut request)?;
        Ok(request)
    });
    let result = query_matrix_health_once(&identity, /*request_id*/ 19);
    let still_running = unrelated.try_wait()?.is_none();
    unrelated.kill()?;
    unrelated.wait()?;
    let request = worker.join().expect("peer fixture thread")?;
    assert!(
        result.is_err(),
        "a different live PID cannot authenticate by response fields"
    );
    assert_eq!(request, Vec::<u8>::new());
    assert!(
        still_running,
        "identity rejection must not signal the claimed PID"
    );
    Ok(())
}

#[test]
fn matrix_peer_credentials_bind_real_socket_pair_to_owner_and_process() -> TestResult {
    let (stream, _other) = std::os::unix::net::UnixStream::pair()?;
    super::peer::ensure_process_owner(&stream, std::process::id())?;
    let mut unrelated = std::process::Command::new("/bin/sleep").arg("30").spawn()?;
    let result = super::peer::ensure_process_owner(&stream, unrelated.id());
    unrelated.kill()?;
    unrelated.wait()?;
    assert_eq!(
        result.expect_err("different live process").kind(),
        std::io::ErrorKind::PermissionDenied
    );
    Ok(())
}
