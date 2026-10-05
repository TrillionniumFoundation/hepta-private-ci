//! Actual pathname sockets: a queue or trickled frame cannot renew a probe deadline.

use std::io::BufRead;
use std::io::BufReader;
use std::io::Write;
use std::os::unix::net::UnixListener;
#[cfg(target_os = "linux")]
use std::os::unix::net::UnixStream;
use std::path::PathBuf;
use std::sync::mpsc;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use pretty_assertions::assert_eq;

use super::AgentHealthProbeIdentity;
use super::MatrixHealthProbeIdentity;
use super::ProcessDriverError;

type TestResult = Result<(), Box<dyn std::error::Error>>;

#[derive(Clone, Copy)]
enum Probe {
    AgentHealth,
    MatrixHealth,
    AgentDrain,
}

fn run_probe(probe: Probe, socket: PathBuf) -> Result<bool, ProcessDriverError> {
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")
        .map_err(|error| ProcessDriverError::new(error.to_string()))?;
    match probe {
        Probe::MatrixHealth => super::query_matrix_health_once(
            &MatrixHealthProbeIdentity {
                agent_id,
                agent_generation: 7,
                binding_revision: 11,
                binding_digest: Sha256Digest::for_bytes(b"binding"),
                release_id: "matrixd-v1".to_string(),
                process_incarnation: "matrixd-incarnation-1".to_string(),
                plane_epoch: 13,
                process_id: std::process::id(),
                control_socket: socket,
            },
            /*request_id*/ 17,
        )
        .map(|observation| observation.ready),
        Probe::AgentHealth | Probe::AgentDrain => {
            let identity = AgentHealthProbeIdentity {
                agent_id,
                spawn_generation: 7,
                process_id: std::process::id(),
                workspace: PathBuf::from("/tmp/workspace"),
                home_root: PathBuf::from("/tmp/home"),
                run_root: PathBuf::from("/tmp/run"),
                control_socket: socket,
            };
            match probe {
                Probe::AgentHealth => {
                    super::query_agent_health_once(&identity, /*request_id*/ 17)
                        .map(|observation| observation.ready)
                }
                Probe::AgentDrain => {
                    super::query_agent_drain_once(&identity, /*request_id*/ 17)
                }
                Probe::MatrixHealth => unreachable!("handled above"),
            }
        }
    }
}

#[cfg(target_os = "linux")]
fn saturated_queue(probe: Probe) -> TestResult {
    let temp = tempfile::Builder::new()
        .prefix("hdeadline-")
        .tempdir_in("/tmp")?;
    let socket = temp.path().join("probe.sock");
    let listener = UnixListener::bind(&socket)?;
    // Linux permits one queued connection with backlog zero. No server accept
    // happens until after the observation; the test owns every descriptor.
    rustix::net::listen(&listener, /*backlog*/ 0)?;
    let queued = UnixStream::connect(&socket)?;
    let (tx, rx) = mpsc::channel();
    let worker = std::thread::spawn(move || {
        let result = run_probe(probe, socket);
        let _ = tx.send(result);
    });
    let observation = rx.recv_timeout(Duration::from_millis(700));
    // Closing the listener also releases the deliberately blocked old code,
    // so a red regression never abandons its probe thread or listener.
    drop(listener);
    drop(queued);
    worker
        .join()
        .map_err(|_| std::io::Error::other("probe worker panicked"))?;
    let result = observation
        .map_err(|_| std::io::Error::other("full accept queue escaped the probe budget"))?;
    assert!(
        !matches!(result, Ok(true)),
        "unaccepted connection is not a healthy or drained process"
    );
    Ok(())
}

fn trickled_response(probe: Probe) -> TestResult {
    let temp = tempfile::Builder::new()
        .prefix("hdeadline-")
        .tempdir_in("/tmp")?;
    let socket = temp.path().join("probe.sock");
    let listener = UnixListener::bind(&socket)?;
    let worker = std::thread::spawn(move || -> std::io::Result<()> {
        let (mut stream, _) = listener.accept()?;
        stream.set_read_timeout(Some(Duration::from_secs(2)))?;
        let mut request = String::new();
        BufReader::new(&mut stream).read_line(&mut request)?;
        // Every fragment arrives well inside the old 200ms per-read timeout.
        // An incomplete frame must still consume only one operation budget.
        for _ in 0..40 {
            if stream.write_all(b" ").is_err() {
                return Ok(());
            }
            std::thread::sleep(Duration::from_millis(20));
        }
        let _ = stream.write_all(b"\n");
        Ok(())
    });
    let started = Instant::now();
    let result = run_probe(probe, socket);
    let elapsed = started.elapsed();
    worker
        .join()
        .map_err(|_| std::io::Error::other("frame worker panicked"))??;
    assert!(
        elapsed < Duration::from_millis(650),
        "partial reads renewed the operation budget: {elapsed:?}"
    );
    assert!(
        !matches!(result, Ok(true)),
        "partial frame cannot acknowledge readiness or drain"
    );
    Ok(())
}

#[cfg(target_os = "linux")]
#[test]
fn agent_health_full_accept_queue_returns_without_blocking() -> TestResult {
    saturated_queue(Probe::AgentHealth)
}
#[cfg(target_os = "linux")]
#[test]
fn matrix_health_full_accept_queue_returns_without_blocking() -> TestResult {
    saturated_queue(Probe::MatrixHealth)
}
#[cfg(target_os = "linux")]
#[test]
fn agent_drain_full_accept_queue_returns_without_blocking() -> TestResult {
    saturated_queue(Probe::AgentDrain)
}
#[test]
fn agent_health_trickled_frame_cannot_extend_total_deadline() -> TestResult {
    trickled_response(Probe::AgentHealth)
}
#[test]
fn matrix_health_trickled_frame_cannot_extend_total_deadline() -> TestResult {
    trickled_response(Probe::MatrixHealth)
}
#[test]
fn agent_drain_trickled_frame_cannot_extend_total_deadline() -> TestResult {
    trickled_response(Probe::AgentDrain)
}

#[test]
fn fragmented_complete_frame_preserves_bytes_and_stops_at_first_newline() -> TestResult {
    let temp = tempfile::Builder::new()
        .prefix("hdeadline-")
        .tempdir_in("/tmp")?;
    let socket = temp.path().join("probe.sock");
    let listener = UnixListener::bind(&socket)?;
    let worker = std::thread::spawn(move || -> std::io::Result<()> {
        let (mut stream, _) = listener.accept()?;
        stream.set_read_timeout(Some(Duration::from_secs(2)))?;
        let mut request = String::new();
        BufReader::new(&mut stream).read_line(&mut request)?;
        assert_eq!(request, "request\n");
        for part in [
            b"first ".as_slice(),
            b"bounded ",
            b"frame\nignored second frame\n",
        ] {
            stream.write_all(part)?;
            std::thread::sleep(Duration::from_millis(10));
        }
        Ok(())
    });
    let result = super::transport::exchange(
        &socket,
        std::process::id(),
        b"request\n",
        /*frame_limit*/ 64,
        super::HEALTH_PROBE_IO_TIMEOUT,
    );
    worker
        .join()
        .map_err(|_| std::io::Error::other("frame worker panicked"))??;
    assert_eq!(result?, b"first bounded frame\n");
    Ok(())
}

#[test]
fn expired_deadline_never_connects_or_sends_a_request() -> TestResult {
    let temp = tempfile::Builder::new()
        .prefix("hdeadline-")
        .tempdir_in("/tmp")?;
    let socket = temp.path().join("probe.sock");
    let listener = UnixListener::bind(&socket)?;
    listener.set_nonblocking(true)?;
    let result = super::transport::exchange(
        &socket,
        std::process::id(),
        b"request\n",
        /*frame_limit*/ 64,
        Duration::ZERO,
    );
    assert_eq!(
        result.expect_err("expired probe").kind(),
        std::io::ErrorKind::TimedOut
    );
    assert_eq!(
        listener
            .accept()
            .expect_err("no dispatched connection")
            .kind(),
        std::io::ErrorKind::WouldBlock
    );
    Ok(())
}

#[test]
fn blocked_request_write_consumes_the_same_operation_budget() -> TestResult {
    let temp = tempfile::Builder::new()
        .prefix("hdeadline-")
        .tempdir_in("/tmp")?;
    let socket = temp.path().join("probe.sock");
    let listener = UnixListener::bind(&socket)?;
    let (release, wait) = mpsc::channel::<()>();
    let worker = std::thread::spawn(move || -> std::io::Result<()> {
        let (_stream, _) = listener.accept()?;
        let _ = wait.recv_timeout(Duration::from_secs(2));
        Ok(())
    });
    let request = vec![b'x'; 1024 * 1024];
    let started = Instant::now();
    let result = super::transport::exchange(
        &socket,
        std::process::id(),
        &request,
        /*frame_limit*/ 1024 * 1024,
        super::HEALTH_PROBE_IO_TIMEOUT,
    );
    let elapsed = started.elapsed();
    let _ = release.send(());
    worker
        .join()
        .map_err(|_| std::io::Error::other("write worker panicked"))??;
    assert_eq!(
        result.expect_err("peer never consumed the request").kind(),
        std::io::ErrorKind::TimedOut
    );
    assert!(
        elapsed < Duration::from_millis(650),
        "write escaped its deadline: {elapsed:?}"
    );
    Ok(())
}
