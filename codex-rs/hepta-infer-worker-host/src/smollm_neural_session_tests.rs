//! A supervisor's nonzero exit cannot be replaced by a success-shaped receipt.
//! These are controlled process/receipt fixtures, not model execution evidence.

use std::fs;
use std::process::Command;
use std::process::Stdio;

use super::*;

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
        let mut supervisor = Command::new("/bin/sh")
            .args(["-c", command])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        // Reap this controlled supervisor before composition, without a sleep
        // race. std::process::Child retains its exact status for try_wait.
        assert_eq!(supervisor.wait().unwrap().code(), Some(exit_code));
        let mut session = Session::new(
            File::open(directory.path()).unwrap(),
            supervisor,
            runtime.handle().clone(),
        );
        assert_eq!(session.shutdown(), Err(expected.to_owned()));
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
    let mut supervisor = Command::new("/bin/sh")
        .args(["-c", "read -r value; test \"$value\" = stop"])
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    let pid = supervisor.id();
    let mut input = supervisor.stdin.take().unwrap();
    drop(Session::new(
        File::open(directory.path()).unwrap(),
        supervisor,
        runtime.handle().clone(),
    ));
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
    let mut supervisor = Command::new("/bin/sh")
        .args(["-c", "read -r value; test \"$value\" = stop"])
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    let pid = supervisor.id();
    let mut input = supervisor.stdin.take().unwrap();
    let mut session = Session::new(
        File::open(directory.path()).unwrap(),
        supervisor,
        runtime.handle().clone(),
    );
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
