//! Channel failure is not permission to replay an unknown Browser operation.

use std::collections::BTreeSet;
use std::collections::VecDeque;
use std::sync::Arc;

use codex_hepta_contracts::FinalUseRevocations;
use ed25519_dalek::SigningKey;

use super::*;

#[derive(Default)]
struct Script {
    writes: Vec<Vec<u8>>,
    reads: VecDeque<Result<Vec<u8>, BrowserServoError>>,
    write_fails: bool,
}

struct ScriptTransport(Arc<Mutex<Script>>);

impl BrowserServoTransport for ScriptTransport {
    fn write_frame(&mut self, bytes: &[u8]) -> Result<(), BrowserServoError> {
        let mut script = self.0.lock().expect("script lock");
        script.writes.push(bytes.to_vec());
        if script.write_fails {
            Err(BrowserServoError::Indeterminate("partial write".into()))
        } else {
            Ok(())
        }
    }

    fn read_frame(&mut self) -> Result<Vec<u8>, BrowserServoError> {
        self.0
            .lock()
            .expect("script lock")
            .reads
            .pop_front()
            .unwrap_or_else(|| Err(BrowserServoError::Indeterminate("read deadline".into())))
    }
}

struct Fixture {
    port: BrowserServoPort<ScriptTransport>,
    script: Arc<Mutex<Script>>,
    _directory: tempfile::TempDir,
}

fn fixture() -> Fixture {
    let directory = tempfile::tempdir().expect("authority directory");
    let key = SigningKey::from_bytes(&[8; 32]);
    let authority = FinalUseAuthority::open_state_dir(
        &directory.path().join("authority"),
        "browser-recovery-tests".into(),
        key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("authority");
    let script = Arc::new(Mutex::new(Script::default()));
    Fixture {
        port: BrowserServoPort::new(authority, ScriptTransport(Arc::clone(&script))),
        script,
        _directory: directory,
    }
}

fn read_call(input: Value) -> BrowserServoCall {
    BrowserServoCall::read(BrowserServoMethod::ObservePage, input).expect("read call")
}

fn frame(sequence: u64, request_id: &str, payload: Value) -> Vec<u8> {
    let digest = sha256_bytes(canonical_json(&payload).expect("payload").as_bytes());
    let body = canonical_json(&json!({
        "schema": PROTOCOL_SCHEMA,
        "protocolVersion": PROTOCOL_VERSION,
        "sequence": sequence,
        "kind": "response",
        "requestId": request_id,
        "payloadDigest": hex_lower(&digest),
        "payload": payload,
    }))
    .expect("frame")
    .into_bytes();
    let mut bytes = Vec::with_capacity(body.len() + 4);
    bytes.extend_from_slice(&(body.len() as u32).to_be_bytes());
    bytes.extend_from_slice(&body);
    bytes
}

fn response(sequence: u64, request: u64) -> Vec<u8> {
    frame(
        sequence,
        &format!("browser.agentd.{request}"),
        json!({"ok": true, "result": {"terminalObserved": false}}),
    )
}

#[test]
fn complete_responses_settle_transport_without_claiming_external_terminality() {
    let fixture = fixture();
    fixture
        .script
        .lock()
        .expect("script")
        .reads
        .extend([Ok(response(1, 1)), Ok(response(2, 2))]);
    for _ in 0..2 {
        assert_eq!(
            fixture.port.call(read_call(json!({}))).expect("response"),
            json!({"terminalObserved": false})
        );
    }
    assert_eq!(fixture.script.lock().expect("script").writes.len(), 2);
}

#[test]
fn complete_service_rejection_does_not_corrupt_next_exchange() {
    let fixture = fixture();
    fixture.script.lock().expect("script").reads.extend([
        Ok(frame(
            1,
            "browser.agentd.1",
            json!({"ok": false, "error": "closed profile"}),
        )),
        Ok(response(2, 2)),
    ]);
    assert!(matches!(
        fixture.port.call(read_call(json!({}))),
        Err(BrowserServoError::Rejected(_))
    ));
    assert!(fixture.port.call(read_call(json!({}))).is_ok());
}

#[test]
fn local_encoding_rejection_does_not_spend_output_sequence() {
    let fixture = fixture();
    // The payload fits, but the full envelope does not. This exercises the
    // old sequence-before-envelope-validation bug, not payload prevalidation.
    let oversized = json!({"query": "x".repeat(MAX_FRAME_BYTES - 128)});
    assert!(
        canonical_json(&json!({
            "method": "observe_page",
            "input": oversized.clone(),
        }))
        .is_ok()
    );
    assert!(fixture.port.call(read_call(oversized)).is_err());
    assert!(fixture.script.lock().expect("script").writes.is_empty());
    fixture
        .script
        .lock()
        .expect("script")
        .reads
        .push_back(Ok(response(1, 2)));
    assert!(fixture.port.call(read_call(json!({}))).is_ok());
    let script = fixture.script.lock().expect("script");
    let sent: Value = serde_json::from_slice(&script.writes[0][4..]).expect("sent frame");
    assert_eq!(sent["sequence"], 1);
}

#[test]
fn partial_write_permanently_fences_following_calls_without_more_io() {
    let fixture = fixture();
    fixture.script.lock().expect("script").write_fails = true;
    assert!(fixture.port.call(read_call(json!({}))).is_err());
    fixture.script.lock().expect("script").write_fails = false;
    fixture
        .script
        .lock()
        .expect("script")
        .reads
        .push_back(Ok(response(1, 1)));
    assert!(matches!(
        fixture.port.call(read_call(json!({}))),
        Err(BrowserServoError::Indeterminate(_))
    ));
    let script = fixture.script.lock().expect("script");
    assert_eq!((script.writes.len(), script.reads.len()), (1, 1));
}

#[test]
fn timeout_does_not_assign_a_late_reply_to_a_new_request() {
    let fixture = fixture();
    assert!(fixture.port.call(read_call(json!({}))).is_err());
    fixture
        .script
        .lock()
        .expect("script")
        .reads
        .push_back(Ok(response(1, 1)));
    assert!(matches!(
        fixture.port.call(read_call(json!({}))),
        Err(BrowserServoError::Indeterminate(_))
    ));
    let script = fixture.script.lock().expect("script");
    assert_eq!((script.writes.len(), script.reads.len()), (1, 1));
}

#[test]
fn invalid_reply_keeps_the_channel_fenced() {
    for bad in [
        vec![0, 0, 0, 1, b'{'],
        response(2, 1),
        response(1, 2),
        frame(1, "browser.agentd.1", json!({"ok": true})),
        frame(1, "browser.agentd.1", json!({"ok": "yes", "result": {}})),
    ] {
        let fixture = fixture();
        fixture
            .script
            .lock()
            .expect("script")
            .reads
            .push_back(Ok(bad));
        assert!(fixture.port.call(read_call(json!({}))).is_err());
        assert!(matches!(
            fixture.port.call(read_call(json!({}))),
            Err(BrowserServoError::Indeterminate(_))
        ));
        assert_eq!(fixture.script.lock().expect("script").writes.len(), 1);
    }
}

#[test]
fn output_sequence_exhaustion_does_not_touch_transport() {
    let fixture = fixture();
    fixture
        .port
        .state
        .lock()
        .expect("state")
        .next_outgoing_sequence = JS_SAFE_INTEGER + 1;
    assert!(fixture.port.call(read_call(json!({}))).is_err());
    assert!(fixture.script.lock().expect("script").writes.is_empty());
}

#[cfg(unix)]
#[test]
fn child_cleanup_disconnects_a_full_reader_queue_before_joining() {
    let mut child = Command::new("/bin/sh")
        .args(["-c", "read unused"])
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .spawn()
        .expect("real child");
    let stdin = child.stdin.take().expect("child stdin");
    let (sender, frames) = mpsc::sync_channel(1);
    let (ready_tx, ready_rx) = mpsc::channel();
    let reader = thread::spawn(move || {
        sender.send(Ok(vec![1])).expect("fill queue");
        ready_tx.send(()).expect("ready");
        // This blocks until the receiver is drained or disconnected.
        let _ = sender.send(Ok(vec![2]));
    });
    ready_rx
        .recv_timeout(Duration::from_secs(2))
        .expect("full queue");
    let transport = ChildBrowserTransport {
        child,
        stdin,
        frames: Some(frames),
        reader: Some(reader),
    };
    let (done_tx, done_rx) = mpsc::channel();
    let cleanup = thread::spawn(move || {
        drop(transport);
        done_tx.send(()).expect("cleanup result");
    });
    done_rx
        .recv_timeout(Duration::from_secs(2))
        .expect("bounded cleanup");
    cleanup.join().expect("cleanup thread");
}
