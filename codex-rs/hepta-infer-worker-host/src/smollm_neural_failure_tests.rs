//! Real controlled socket failures, not model execution or FinalUse evidence.
use super::*;
use std::fs::File;
use std::fs::{self};
use std::io::BufRead;
use std::io::BufReader;
use std::io::Write;
use std::os::unix::net::UnixListener;
use std::process::Command;
use std::time::Duration;

use codex_hepta_agentd::NeuralCognitiveExecutionV1;
use pretty_assertions::assert_eq;
use tokio_util::sync::CancellationToken;

use super::super::session::Session;

fn request() -> WorkerRequest {
    WorkerRequest {
        request_id: "neural-100-9".to_owned(),
        reservation_id: "reservation-neural-100-9".to_owned(),
        model_digest: "wire-only".to_owned(),
        payload_digest: "wire-only".to_owned(),
        maximum_tokens: 1,
        deadline_ms: 2100,
        lease_payload_digest: "wire-only".to_owned(),
        reservation_model_digest: "wire-only".to_owned(),
        reservation_maximum_tokens: 1,
        cancelled: false,
    }
}

#[test]
fn real_socket_timeout_retains_original_errno_and_both_deadlines_before_shutdown() {
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()
        .unwrap();
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("session/worker");
    fs::create_dir_all(&path).unwrap();
    let listener = UnixListener::bind(path.join("model.sock")).unwrap();
    let (release, wait) = std::sync::mpsc::channel();
    let peer = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(2)))
            .unwrap();
        let mut frame = String::new();
        BufReader::new(&mut stream).read_line(&mut frame).unwrap();
        assert_eq!(frame, "original-frame\n");
        wait.recv_timeout(Duration::from_secs(2)).unwrap();
    });
    let mut session = Session::prepare(
        File::open(directory.path()).unwrap(),
        runtime.handle().clone(),
        Instant::now() + Duration::from_secs(120),
        &CancellationToken::new(),
    )
    .unwrap();
    session
        .spawn(Command::new("/bin/sh").args(["-c", "exit 0"]))
        .unwrap();
    let execution = NeuralCognitiveExecutionV1::bounded_read();
    let io_deadline = Instant::now() + Duration::from_millis(40);
    let mut slot = None;
    let request = request();
    let mut recorder = FailureRecorder::new(&mut slot, &request, execution.deadline());
    recorder.io_deadline(io_deadline);
    let error = session
        .exchange(b"original-frame", io_deadline, &execution)
        .unwrap_err();
    let original = error.to_string();
    assert_eq!(recorder.retain(error), original);
    let retained = slot.unwrap();
    let json = serde_json::to_value(retained).unwrap();
    assert_eq!(json["stage"], "read");
    assert!(json["raw_os_error"].as_i64().is_some());
    assert_eq!(json["request_id"], request.request_id);
    assert_eq!(json["reservation_id"], request.reservation_id);
    assert_eq!(
        json["original_error_sha256"],
        Digest32::of_bytes(original.as_bytes()).to_string()
    );
    assert!(
        json["operation_before"]["io_remaining_ns"]
            .as_i64()
            .unwrap()
            > 0
    );
    assert!(json["failure_after"]["io_remaining_ns"].as_i64().unwrap() <= 0);
    assert!(
        json["failure_after"]["execution_remaining_ns"]
            .as_i64()
            .unwrap()
            > 0
    );
    let successor = session
        .exchange(b"successor", execution.deadline(), &execution)
        .unwrap_err();
    assert!(successor.contains("unresolved physical execution"));
    let mut recorder = FailureRecorder::new(&mut slot, &request, execution.deadline());
    recorder.retain(successor);
    release.send(()).unwrap();
    peer.join().unwrap();
    // Actual original unload still fails without a model's original receipt.
    assert!(session.shutdown().is_err());
    assert_eq!(slot, Some(retained));
    assert!(std::mem::size_of_val(&retained) <= 1024);
}

#[test]
fn real_socket_success_eof_multiple_frames_and_json_decode_keep_distinct_causes() {
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()
        .unwrap();
    for (response, expected) in [
        (b"valid\n".as_slice(), None),
        (b"".as_slice(), Some("read")),
        (b"a\nb\n".as_slice(), Some("response_frame_terminator")),
        (b"not-json\n".as_slice(), Some("response_decode")),
    ] {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("session/worker");
        fs::create_dir_all(&path).unwrap();
        let listener = UnixListener::bind(path.join("model.sock")).unwrap();
        let peer = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut frame = String::new();
            BufReader::new(&mut stream).read_line(&mut frame).unwrap();
            assert_eq!(frame, "original-frame\n");
            stream.write_all(response).unwrap();
        });
        let session = Session::prepare(
            File::open(directory.path()).unwrap(),
            runtime.handle().clone(),
            Instant::now() + Duration::from_secs(120),
            &CancellationToken::new(),
        )
        .unwrap();
        let execution = NeuralCognitiveExecutionV1::bounded_read();
        let mut slot = None;
        let request = request();
        let mut recorder = FailureRecorder::new(&mut slot, &request, execution.deadline());
        recorder.io_deadline(execution.deadline());
        let result = session
            .exchange(b"original-frame", execution.deadline(), &execution)
            .map_err(|error| recorder.retain(error));
        if expected == Some("response_decode") {
            let raw = result.unwrap();
            let attempt = Attempt::new("response_decode");
            let error = serde_json::from_slice::<super::super::Response>(&raw)
                .err()
                .expect("actual malformed JSON");
            let original = error.to_string();
            assert_eq!(recorder.retain(attempt.message(original.clone())), original);
        } else if expected.is_none() {
            assert_eq!(result.unwrap(), b"valid");
        } else {
            assert!(result.is_err());
        }
        peer.join().unwrap();
        assert_eq!(slot.map(|value| value.stage), expected);
    }
}

#[test]
fn original_cancellation_sends_no_frame_and_is_recorded_without_io_error() {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();
    let directory = tempfile::tempdir().unwrap();
    fs::create_dir_all(directory.path().join("session/worker")).unwrap();
    let listener = UnixListener::bind(directory.path().join("session/worker/model.sock")).unwrap();
    listener.set_nonblocking(true).unwrap();
    let session = Session::prepare(
        File::open(directory.path()).unwrap(),
        runtime.handle().clone(),
        Instant::now() + Duration::from_secs(120),
        &CancellationToken::new(),
    )
    .unwrap();
    let cancel = CancellationToken::new();
    cancel.cancel();
    let execution =
        NeuralCognitiveExecutionV1::with_deadline(Instant::now() + Duration::from_secs(2), cancel);
    let mut slot = None;
    let request = request();
    let mut recorder = FailureRecorder::new(&mut slot, &request, execution.deadline());
    assert_eq!(
        recorder.retain(
            session
                .exchange(b"original-frame", execution.deadline(), &execution)
                .unwrap_err()
        ),
        "neural read execution cancelled"
    );
    assert_eq!(
        listener.accept().unwrap_err().kind(),
        io::ErrorKind::WouldBlock
    );
    let failure = slot.unwrap();
    assert_eq!(failure.stage, "execution_check");
    assert_eq!(failure.raw_os_error, None);
}

#[test]
fn bounded_utf8_error_and_unavailable_oversized_ids_cannot_alias_or_replace_first_failure() {
    let mut request = request();
    request.request_id = "x".repeat(65);
    request.reservation_id = "界".repeat(64);
    let mut mailbox = super::super::measurement::MailboxState::default();
    let deadline = Instant::now() + Duration::from_secs(2);
    let original = "界".repeat(200);
    let mut recorder = FailureRecorder::new(&mut mailbox.first_failure, &request, deadline);
    assert_eq!(
        recorder.retain(Attempt::new("response_decode").message(original.clone())),
        original
    );
    let retained = mailbox.first_failure.unwrap();
    let json = serde_json::to_value(retained).unwrap();
    assert!(json["request_id"].is_null());
    assert!(json["reservation_id"].is_null());
    assert_eq!(json["request_id_bytes"], 65);
    assert_eq!(json["reservation_id_bytes"], 192);
    assert_eq!(
        json["original_error_prefix"].as_str().unwrap(),
        "界".repeat(85)
    );
    assert_eq!(json["original_error_truncated"], true);
    mailbox.measurements.clear_forward();
    mailbox.measurements.suspend();
    mailbox.measurements.clear();
    let mut recorder = FailureRecorder::new(&mut mailbox.first_failure, &request, deadline);
    assert_eq!(
        recorder.retain(Attempt::new("write").io(io::Error::from_raw_os_error(libc::EPIPE))),
        io::Error::from_raw_os_error(libc::EPIPE).to_string()
    );
    assert_eq!(mailbox.first_failure, Some(retained));
}
