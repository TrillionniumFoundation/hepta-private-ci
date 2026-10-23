use super::*;
use pretty_assertions::assert_eq;
use std::error::Error;
use std::os::unix::net::UnixListener;

type TestResult = Result<(), Box<dyn Error>>;

#[test]
fn independent_recovery_survives_effect_loss_and_filters_late_datagrams() -> TestResult {
    let (owner, mut app) = UnixStream::pair()?;
    let (recovery, recovery_app) = UnixDatagram::pair()?;
    let channel = AgentdNotesChannel::from_private_channels(owner, recovery)?;
    let query = serde_json::json!({"schema_version":1,"action":"observe",
        "target":{"session_instance":"11111111111111111111111111111111","task_id":1,"incarnation":"22222222222222222222222222222222"},
        "operation_id":"exact-operation","payload_sha256":"a".repeat(64)});
    let raw = serde_json::to_vec(&query)?;
    let mut reply = query;
    reply
        .as_object_mut()
        .ok_or("reply object")?
        .remove("action");
    reply["result"] = serde_json::json!({"status":"unknown","current_revision":1});
    let expected = serde_json::to_vec(&reply)?;
    let response = expected.clone();
    let peer = std::thread::spawn(move || -> io::Result<()> {
        let mut effect = [0_u8; 10];
        app.read_exact(&mut effect)?;
        drop(app); // application model survives the effect stream loss
        recovery_app.set_read_timeout(Some(Duration::from_secs(5)))?;
        let mut bytes = [0_u8; 8192];
        recovery_app.recv(&mut bytes)?;
        let mut stale: serde_json::Value = serde_json::from_slice(&response)?;
        stale["operation_id"] = serde_json::json!("unrelated-operation");
        recovery_app.send(&serde_json::to_vec(&stale)?)?;
        recovery_app.send(&response)?;
        Ok(())
    });
    assert!(channel.exchange(b"effect").is_err());
    assert!(channel.exchange(b"effect").is_err());
    assert_eq!(channel.recovery_exchange(&raw)?, expected);
    peer.join().expect("recovery peer")?;
    Ok(())
}

#[test]
fn lost_retirement_ack_can_retry_the_exact_datagram_and_cannot_send_effects() -> TestResult {
    let (owner, _app) = UnixStream::pair()?;
    let (recovery, recovery_app) = UnixDatagram::pair()?;
    let channel = AgentdNotesChannel::from_private_channels(owner, recovery)?;
    assert!(
        channel
            .recovery_exchange(br#"{"action":"replace_note"}"#)
            .is_err()
    );
    recovery_app.set_nonblocking(true)?;
    assert_eq!(
        recovery_app
            .recv(&mut [0_u8; 1])
            .expect_err("no effect sent")
            .kind(),
        io::ErrorKind::WouldBlock
    );
    recovery_app.set_nonblocking(false)?;
    let request = serde_json::to_vec(
        &serde_json::json!({"schema_version":1,"action":"acknowledge_terminal",
        "target":{"session_instance":"11111111111111111111111111111111","task_id":1,"incarnation":"22222222222222222222222222222222"},
        "operation_id":"exact-operation","payload_sha256":"a".repeat(64),"receipt_sha256":"b".repeat(64)}),
    )?;
    let expected = request.clone();
    let peer = std::thread::spawn(move || -> io::Result<()> {
        recovery_app.set_read_timeout(Some(Duration::from_secs(5)))?;
        let mut bytes = [0_u8; 8192];
        for attempt in 0..2 {
            let length = recovery_app.recv(&mut bytes)?;
            assert_eq!(&bytes[..length], expected);
            if attempt == 0 {
                continue;
            }
            let mut response: serde_json::Value = serde_json::from_slice(&bytes[..length])?;
            response.as_object_mut().expect("object").remove("action");
            response["status"] = serde_json::json!("already_released");
            recovery_app.send(&serde_json::to_vec(&response)?)?;
        }
        Ok(())
    });
    assert!(channel.recovery_exchange(&request).is_err());
    let response: serde_json::Value =
        serde_json::from_slice(&channel.recovery_exchange(&request)?)?;
    assert_eq!(response["status"], "already_released");
    peer.join().expect("retirement peer")?;
    Ok(())
}

#[test]
fn inherited_socketpair_preserves_exact_frame_bytes() -> TestResult {
    let (owner, mut application) = UnixStream::pair()?;
    let channel = AgentdNotesChannel::from_private_channel(owner)?;
    let peer = std::thread::spawn(move || -> io::Result<Vec<u8>> {
        let mut prefix = [0; 4];
        application.read_exact(&mut prefix)?;
        let mut request = vec![0; u32::from_be_bytes(prefix) as usize];
        application.read_exact(&mut request)?;
        application.write_all(&3_u32.to_be_bytes())?;
        application.write_all(b"ack")?;
        Ok(request)
    });
    assert_eq!(channel.exchange(b" exact\nbytes ")?, b"ack");
    assert_eq!(peer.join().expect("application thread")?, b" exact\nbytes ");
    Ok(())
}

#[test]
fn named_socket_is_not_a_bootstrap_channel() -> TestResult {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("not-private.sock");
    let listener = UnixListener::bind(&path)?;
    let client = UnixStream::connect(&path)?;
    let (server, _) = listener.accept()?;
    assert!(AgentdNotesChannel::from_private_channel(client).is_err());
    assert!(AgentdNotesChannel::from_private_channel(server).is_err());
    Ok(())
}

#[test]
fn lost_reply_permanently_disables_further_effect_entry() -> TestResult {
    let (owner, mut application) = UnixStream::pair()?;
    let channel = AgentdNotesChannel::from_private_channel(owner)?;
    let peer = std::thread::spawn(move || -> io::Result<Vec<u8>> {
        let mut request = [0; 10];
        application.read_exact(&mut request)?;
        Ok(request.to_vec())
    });
    assert!(channel.exchange(b"effect").is_err());
    assert!(channel.exchange(b"effect").is_err());
    assert_eq!(
        peer.join().expect("application thread")?,
        [0, 0, 0, 6, b'e', b'f', b'f', b'e', b'c', b't']
    );
    assert!(channel.disabled.load(Ordering::Acquire));
    Ok(())
}

#[test]
fn malformed_reply_prefix_closes_stream_without_accepting_a_later_reply() -> TestResult {
    let (owner, mut application) = UnixStream::pair()?;
    let channel = AgentdNotesChannel::from_private_channel(owner)?;
    let peer = std::thread::spawn(move || -> io::Result<()> {
        let mut request = [0; 5];
        application.read_exact(&mut request)?;
        application.write_all(&2049_u32.to_be_bytes())?;
        let mut byte = [0; 1];
        assert_eq!(application.read(&mut byte)?, 0);
        Ok(())
    });
    assert!(channel.exchange(b"x").is_err());
    assert!(channel.exchange(b"x").is_err());
    peer.join().expect("application thread")?;
    Ok(())
}

#[test]
fn invalid_bound_does_not_write_and_explicit_invalidation_is_permanent() -> TestResult {
    let (owner, mut application) = UnixStream::pair()?;
    let channel = AgentdNotesChannel::from_private_channel(owner)?;
    assert!(channel.exchange(&[]).is_err());
    assert!(
        channel
            .exchange(&vec![0; NOTES_REQUEST_MAX_BYTES + 1])
            .is_err()
    );
    channel.invalidate();
    assert!(channel.exchange(b"effect").is_err());
    let mut byte = [0; 1];
    assert_eq!(application.read(&mut byte)?, 0);
    Ok(())
}
