//! A supervisor's nonzero exit cannot be replaced by a success-shaped receipt.
//! These are controlled process/receipt fixtures, not model execution evidence.

use std::fs;
use std::process::Command;
use std::process::Stdio;

use super::*;

fn prepared(directory: &Path, runtime: &tokio::runtime::Runtime) -> Session {
    Session::prepare(
        File::open(directory).unwrap(),
        runtime.handle().clone(),
        Instant::now() + Duration::from_secs(120),
        &tokio_util::sync::CancellationToken::new(),
    )
    .unwrap()
}

#[test]
fn terminal_unload_requires_successful_supervisor_and_original_child_receipt() {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();
    for (command, exit_code, outcome, expected) in [
        (
            "exit 7",
            7,
            "success",
            "neural supervisor did not exit successfully",
        ),
        (
            "exit 0",
            0,
            "budget-exceeded",
            "neural unload lacks a successful original owned-child receipt",
        ),
    ] {
        let directory = tempfile::tempdir().unwrap();
        let worker = directory.path().join("session/worker");
        fs::create_dir_all(&worker).unwrap();
        let receipt = serde_json::json!({
            "outcome":outcome, "exit_code":0, "stop_reason":null,
            "waited_child_reaped":true, "owned_child_reap_resolved":true,
            "waited_child_observation_error":null, "observed_wall_ns":1,
            "waited_child_peak_rss_bytes":4096,
            "budget":{"wall_seconds":600, "rss_bytes":8589934592_u64},
        });
        fs::write(
            worker.join("supervisor.json"),
            serde_json::to_vec(&receipt).unwrap(),
        )
        .unwrap();
        let mut session = prepared(directory.path(), &runtime);
        session
            .spawn(
                Command::new("/bin/sh")
                    .args(["-c", command])
                    .stdin(Stdio::null())
                    .stdout(Stdio::null())
                    .stderr(Stdio::null()),
            )
            .unwrap();
        let supervisor = &session.supervisor;
        // Reap this controlled supervisor before composition, without a sleep
        // race. std::process::Child retains its exact status for try_wait.
        assert_eq!(supervisor.wait().unwrap().code(), Some(exit_code));
        assert_eq!(session.shutdown(), Err(expected.to_owned()));
        let original_cutoff = session.shutdown_deadline.unwrap();
        assert_eq!(session.shutdown(), Err(expected.to_owned()));
        assert_eq!(session.shutdown_deadline, Some(original_cutoff));
        // Shorten only this negative fixture; a late receipt cannot renew it.
        session.shutdown_deadline = Some(Instant::now());
        assert!(
            session
                .shutdown()
                .unwrap_err()
                .contains("terminal observation unavailable")
        );
        assert!(session.supervisor.is_some());
    }
}

#[test]
fn dropped_cold_session_retries_stop_when_socket_appears_and_retains_reaper() {
    use std::os::unix::net::UnixListener;

    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();
    let directory = tempfile::tempdir().unwrap();
    let worker = directory.path().join("session/worker");
    fs::create_dir_all(&worker).unwrap();
    // A controlled supervisor remains alive until this test observes the exact
    // STOP frame. No model, issuer or successful supervisor receipt is faked.
    let session = prepared(directory.path(), &runtime);
    session
        .spawn(
            Command::new("/bin/sh")
                .args(["-c", "read -r value; test \"$value\" = stop"])
                .stdin(Stdio::piped())
                .stdout(Stdio::null())
                .stderr(Stdio::null()),
        )
        .unwrap();
    let supervisor = &session.supervisor;
    let pid = supervisor.id();
    let mut input = supervisor.take_stdin().unwrap();
    drop(session);
    // Publish after the drop path's initial attempt, as in a cancelled cold
    // load. The original one-shot cleanup would forget this absent socket.
    std::thread::sleep(Duration::from_millis(100));
    let listener = UnixListener::bind(worker.join("model.sock")).unwrap();
    listener.set_nonblocking(true).unwrap();
    let deadline = Instant::now() + Duration::from_secs(5);
    let mut connection = loop {
        match listener.accept() {
            Ok((connection, _)) => break connection,
            Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                assert!(
                    Instant::now() < deadline,
                    "cold session lost its pending STOP"
                );
                std::thread::sleep(Duration::from_millis(10));
            }
            Err(error) => panic!("accept STOP: {error}"),
        }
    };
    connection
        .set_read_timeout(Some(Duration::from_secs(1)))
        .unwrap();
    let mut frame = vec![0; STOP.len()];
    connection.read_exact(&mut frame).unwrap();
    assert_eq!(frame, STOP);
    input.write_all(b"stop\n").unwrap();
    drop(input);
    // Only the Session's retained owner may wait/reap this child.
    let process = std::path::PathBuf::from(format!("/proc/{pid}"));
    while process.exists() {
        assert!(
            Instant::now() < deadline,
            "original supervisor was not reaped"
        );
        std::thread::sleep(Duration::from_millis(10));
    }
}

#[test]
fn dropped_session_does_not_extend_its_expired_stop_window() {
    use std::os::unix::net::UnixListener;

    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();
    let directory = tempfile::tempdir().unwrap();
    let worker = directory.path().join("session/worker");
    fs::create_dir_all(&worker).unwrap();
    let mut session = prepared(directory.path(), &runtime);
    session
        .spawn(
            Command::new("/bin/sh")
                .args(["-c", "read -r value; test \"$value\" = stop"])
                .stdin(Stdio::piped())
                .stdout(Stdio::null())
                .stderr(Stdio::null()),
        )
        .unwrap();
    let supervisor = &session.supervisor;
    let pid = supervisor.id();
    let mut input = supervisor.take_stdin().unwrap();
    // Shorten the controlled owner's deadline; no production deadline is
    // overridden or renewed by a late socket becoming available.
    session.cleanup_deadline = Instant::now();
    drop(session);
    let listener = UnixListener::bind(worker.join("model.sock")).unwrap();
    listener.set_nonblocking(true).unwrap();
    std::thread::sleep(Duration::from_millis(100));
    assert_eq!(
        listener.accept().unwrap_err().kind(),
        std::io::ErrorKind::WouldBlock
    );
    input.write_all(b"stop\n").unwrap();
    drop(input);
    let deadline = Instant::now() + Duration::from_secs(5);
    let process = std::path::PathBuf::from(format!("/proc/{pid}"));
    while process.exists() {
        assert!(
            Instant::now() < deadline,
            "expired owner did not retain its reaper"
        );
        std::thread::sleep(Duration::from_millis(10));
    }
}

#[test]
fn cancelled_read_sends_no_frame_and_uncertain_exchange_blocks_successor() {
    use std::os::unix::net::UnixListener;
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()
        .unwrap();
    let directory = tempfile::tempdir().unwrap();
    let worker = directory.path().join("session/worker");
    fs::create_dir_all(&worker).unwrap();
    let listener = UnixListener::bind(worker.join("model.sock")).unwrap();
    listener.set_nonblocking(true).unwrap();
    let session = prepared(directory.path(), &runtime);
    session
        .spawn(Command::new("/bin/sh").args(["-c", "exit 0"]))
        .unwrap();
    let supervisor = &session.supervisor;
    assert!(supervisor.wait().unwrap().success());
    let cancellation = tokio_util::sync::CancellationToken::new();
    cancellation.cancel();
    let cancelled = codex_hepta_agentd::NeuralCognitiveExecutionV1::with_deadline(
        Instant::now() + Duration::from_secs(2),
        cancellation,
    );
    assert!(
        session
            .exchange(b"bounded-frame", cancelled.deadline(), &cancelled)
            .is_err()
    );
    assert_eq!(
        listener.accept().unwrap_err().kind(),
        std::io::ErrorKind::WouldBlock
    );
    listener.set_nonblocking(false).unwrap();
    let (observed_tx, observed_rx) = std::sync::mpsc::channel();
    let (release_tx, release_rx) = std::sync::mpsc::channel();
    let peer = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(1)))
            .unwrap();
        let mut frame = Vec::new();
        loop {
            let mut byte = [0_u8; 1];
            stream.read_exact(&mut byte).unwrap();
            frame.push(byte[0]);
            if byte[0] == b'\n' {
                break;
            }
        }
        observed_tx.send(frame).unwrap();
        release_rx.recv_timeout(Duration::from_secs(2)).unwrap();
        listener.set_nonblocking(true).unwrap();
        assert_eq!(
            listener.accept().unwrap_err().kind(),
            std::io::ErrorKind::WouldBlock
        );
    });
    let execution = codex_hepta_agentd::NeuralCognitiveExecutionV1::with_deadline(
        Instant::now() + Duration::from_millis(50),
        tokio_util::sync::CancellationToken::new(),
    );
    assert!(
        session
            .exchange(b"bounded-frame", execution.deadline(), &execution)
            .is_err()
    );
    assert_eq!(
        observed_rx.recv_timeout(Duration::from_secs(1)).unwrap(),
        b"bounded-frame\n"
    );
    let successor = codex_hepta_agentd::NeuralCognitiveExecutionV1::bounded_read();
    assert!(
        session
            .exchange(b"must-not-send", successor.deadline(), &successor)
            .unwrap_err()
            .contains("unresolved physical execution")
    );
    release_tx.send(()).unwrap();
    peer.join().unwrap();
    assert!(session.in_flight_or_unknown.load(Ordering::SeqCst));
}

#[test]
fn ready_published_after_original_startup_window_cannot_be_adopted() {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();
    let directory = tempfile::tempdir().unwrap();
    let worker = directory.path().join("session/worker");
    fs::create_dir_all(&worker).unwrap();
    let mut session = prepared(directory.path(), &runtime);
    session
        .spawn(
            Command::new("/bin/sh")
                .args(["-c", "read -r value; test \"$value\" = stop"])
                .stdin(Stdio::piped())
                .stdout(Stdio::null())
                .stderr(Stdio::null()),
        )
        .unwrap();
    let execution = codex_hepta_agentd::NeuralCognitiveExecutionV1::with_deadline(
        Instant::now() + Duration::from_millis(20),
        tokio_util::sync::CancellationToken::new(),
    );
    let publisher = std::thread::spawn(move || {
        std::thread::sleep(Duration::from_millis(30));
        fs::write(worker.join("ready.json"), b"{}").unwrap();
    });
    publisher.join().unwrap();
    assert!(
        session
            .wait_ready(&execution)
            .unwrap_err()
            .contains("deadline")
    );
    assert!(!session.has_exited().unwrap());
    session
        .supervisor
        .take_stdin()
        .unwrap()
        .write_all(b"stop\n")
        .unwrap();
    assert!(session.supervisor.wait().unwrap().success());
}

#[test]
fn cancelled_original_startup_cannot_adopt_an_already_published_ready() {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();
    let directory = tempfile::tempdir().unwrap();
    let worker = directory.path().join("session/worker");
    fs::create_dir_all(&worker).unwrap();
    let mut session = prepared(directory.path(), &runtime);
    session
        .spawn(
            Command::new("/bin/sh")
                .args(["-c", "read -r value; test \"$value\" = stop"])
                .stdin(Stdio::piped())
                .stdout(Stdio::null())
                .stderr(Stdio::null()),
        )
        .unwrap();
    let cancellation = tokio_util::sync::CancellationToken::new();
    let execution = codex_hepta_agentd::NeuralCognitiveExecutionV1::with_deadline(
        Instant::now() + Duration::from_secs(2),
        cancellation.clone(),
    );
    fs::write(worker.join("ready.json"), b"{}").unwrap();
    assert_eq!(session.wait_ready(&execution).unwrap(), b"{}");
    cancellation.cancel();
    assert!(
        session
            .wait_ready(&execution)
            .unwrap_err()
            .contains("cancelled")
    );
    assert!(!session.has_exited().unwrap());
    session
        .supervisor
        .take_stdin()
        .unwrap()
        .write_all(b"stop\n")
        .unwrap();
    assert!(session.supervisor.wait().unwrap().success());
}
