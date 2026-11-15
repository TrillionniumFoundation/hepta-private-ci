use super::*;
use crate::AgentdNotesChannel;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::ProductionNotesTarget;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use std::error::Error;
use std::io;
use std::os::unix::net::UnixDatagram;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::time::Duration;

#[test]
fn notes_document_observer_clones_fence_revision_and_content_without_writing_effects()
-> Result<(), Box<dyn Error>> {
    let (effect, mut application_effect) = UnixStream::pair()?;
    let (recovery, application) = UnixDatagram::pair()?;
    application.set_read_timeout(Some(Duration::from_secs(5)))?;
    application_effect.set_nonblocking(true)?;
    let identity = NotesTargetIdentity {
        session_instance: "1".repeat(32),
        task_id: 1,
        incarnation: "2".repeat(32),
    };
    let target = ProductionNotesTarget::new(
        identity.clone(),
        Arc::new(AgentdNotesChannel::from_private_channels(effect, recovery)?),
    )?;
    let observer = AgentdNotesDocumentObserver::new(target.document_observer());
    let other = observer.clone();
    // New nonces cannot renew old document state. Receipt retirement changes
    // independently and does not require a document revision increment.
    let cases = [
        (8, "original", true, true),
        (8, "original", false, true),
        (9, "later", false, true),
        (8, "original", false, false),
        (9, "original", false, false),
        (9, "later", true, true),
        (10, "latest", false, true),
    ];
    let observed_target = identity.clone();
    let peer = std::thread::spawn(move || -> Result<(), String> {
        let mut nonces = std::collections::BTreeSet::new();
        for (revision, text, receipt_pending, _) in cases {
            let mut bytes = [0_u8; 8192];
            let size = application
                .recv(&mut bytes)
                .map_err(|error| error.to_string())?;
            let request: Value =
                serde_json::from_slice(&bytes[..size]).map_err(|error| error.to_string())?;
            assert_eq!(request["action"], "read_document_state");
            assert_eq!(request["target"], json!(observed_target));
            assert!(nonces.insert(request["request_id"].as_str().unwrap().to_owned()));
            let response = json!({"schema_version":1,"action":"document_state",
                "target":observed_target,"request_id":request["request_id"],
                "revision":revision,"text_sha256":Sha256Digest::for_bytes(text.as_bytes()).as_str(),
                "receipt_pending":receipt_pending});
            application
                .send(&serde_json::to_vec(&response).unwrap())
                .map_err(|error| error.to_string())?;
        }
        Ok(())
    });
    for (index, (revision, text, receipt_pending, accepted)) in cases.into_iter().enumerate() {
        let reader = if index % 2 == 0 { &observer } else { &other };
        let result = reader.observe_document();
        if accepted {
            assert_eq!(
                result?,
                NotesDocumentState {
                    target: identity.clone(),
                    revision,
                    text_sha256: Sha256Digest::for_bytes(text.as_bytes()),
                    receipt_pending,
                }
            );
        } else {
            assert!(
                result.is_err(),
                "fresh reply must not renew revision {revision}"
            );
        }
    }
    assert_eq!(
        application_effect.read(&mut [0_u8; 1]).unwrap_err().kind(),
        io::ErrorKind::WouldBlock
    );
    peer.join().expect("document fence peer")?;
    Ok(())
}

#[test]
fn notes_document_observer_clones_do_not_queue_behind_an_inflight_exchange()
-> Result<(), Box<dyn Error>> {
    let (effect, mut application_effect) = UnixStream::pair()?;
    let (recovery, application) = UnixDatagram::pair()?;
    application.set_read_timeout(Some(Duration::from_secs(5)))?;
    application_effect.set_nonblocking(true)?;
    let identity = NotesTargetIdentity {
        session_instance: "1".repeat(32),
        task_id: 1,
        incarnation: "2".repeat(32),
    };
    let target = ProductionNotesTarget::new(
        identity.clone(),
        Arc::new(AgentdNotesChannel::from_private_channels(effect, recovery)?),
    )?;
    let observer = AgentdNotesDocumentObserver::new(target.document_observer());
    let other = observer.clone();
    let read = std::thread::spawn(move || other.observe_document());
    let mut bytes = [0_u8; 8192];
    let size = application.recv(&mut bytes)?;
    let request: Value = serde_json::from_slice(&bytes[..size])?;
    // The first read is blocked on this exact application's response.
    assert!(observer.observe_document().is_err());
    let expected = NotesDocumentState {
        target: identity.clone(),
        revision: 1,
        text_sha256: Sha256Digest::for_bytes(b"current"),
        receipt_pending: false,
    };
    let response = json!({"schema_version":1,"action":"document_state",
        "target":identity,"request_id":request["request_id"],
        "revision":expected.revision,"text_sha256":expected.text_sha256.as_str(),
        "receipt_pending":expected.receipt_pending});
    application.send(&serde_json::to_vec(&response)?)?;
    assert_eq!(read.join().expect("original in-flight read")?, expected);
    application.set_nonblocking(true)?;
    assert_eq!(
        application.recv(&mut bytes).unwrap_err().kind(),
        io::ErrorKind::WouldBlock
    );
    assert_eq!(
        application_effect.read(&mut [0_u8; 1]).unwrap_err().kind(),
        io::ErrorKind::WouldBlock
    );
    Ok(())
}

#[test]
fn notes_objective_private_document_observer_correlates_fresh_nonce_and_never_writes_effect()
-> Result<(), Box<dyn Error>> {
    let (effect, mut application_effect) = UnixStream::pair()?;
    let (recovery, application) = UnixDatagram::pair()?;
    application.set_read_timeout(Some(Duration::from_secs(5)))?;
    application_effect.set_nonblocking(true)?;
    let identity = NotesTargetIdentity {
        session_instance: "1".repeat(32),
        task_id: 1,
        incarnation: "2".repeat(32),
    };
    let target = ProductionNotesTarget::new(
        identity.clone(),
        Arc::new(AgentdNotesChannel::from_private_channels(effect, recovery)?),
    )?;
    let observer = AgentdNotesDocumentObserver::new(target.document_observer());
    let observed_target = identity.clone();
    let peer = std::thread::spawn(move || -> Result<(), String> {
        let mut prior_nonce = Value::Null;
        for revision in 1..=2 {
            let mut bytes = [0_u8; 8192];
            let size = application
                .recv(&mut bytes)
                .map_err(|error| error.to_string())?;
            let request: Value =
                serde_json::from_slice(&bytes[..size]).map_err(|error| error.to_string())?;
            assert_eq!(request["action"], "read_document_state");
            assert_eq!(
                request["target"],
                serde_json::to_value(&observed_target).unwrap()
            );
            assert_ne!(request["request_id"], prior_nonce);
            let mut response = json!({"schema_version":1,"action":"document_state",
                "target":observed_target,"request_id":prior_nonce,"revision":revision,
                "text_sha256":Sha256Digest::for_bytes(b"current document").as_str(),
                "receipt_pending":revision == 2});
            application
                .send(&serde_json::to_vec(&response).unwrap())
                .map_err(|error| error.to_string())?;
            response["request_id"] = request["request_id"].clone();
            application
                .send(&serde_json::to_vec(&response).unwrap())
                .map_err(|error| error.to_string())?;
            prior_nonce = request["request_id"].clone();
        }
        Ok(())
    });
    for revision in 1..=2 {
        assert_eq!(
            observer.observe_document()?,
            NotesDocumentState {
                target: identity.clone(),
                revision,
                text_sha256: Sha256Digest::for_bytes(b"current document"),
                receipt_pending: revision == 2,
            }
        );
    }
    assert_eq!(
        application_effect.read(&mut [0_u8; 1]).unwrap_err().kind(),
        io::ErrorKind::WouldBlock
    );
    peer.join().expect("document state peer")?;
    Ok(())
}

#[test]
fn notes_objective_recovery_handle_retains_no_effect_descriptor_and_correlates_discovery()
-> Result<(), Box<dyn Error>> {
    use codex_hepta_memory::NotesPrivateChannel;
    let (effect, mut application_effect) = UnixStream::pair()?;
    let (recovery, application) = UnixDatagram::pair()?;
    let channel = AgentdNotesChannel::from_private_channels(effect, recovery)?;
    let recovery_only = channel.recovery_handle()?;
    drop(channel);
    application_effect.set_read_timeout(Some(Duration::from_secs(1)))?;
    assert_eq!(
        application_effect.read(&mut [0_u8; 1])?,
        0,
        "narrow capability must not retain the effect descriptor"
    );
    let request = json!({"schema_version":1,"action":"read_previous_receipt",
        "target":{"session_instance":"1".repeat(32),"task_id":1,"incarnation":"2".repeat(32)},
        "request_id":"3".repeat(32)});
    let expected = request.clone();
    let peer = std::thread::spawn(move || -> Result<(), String> {
        application
            .set_read_timeout(Some(Duration::from_secs(2)))
            .map_err(|error| error.to_string())?;
        let mut bytes = [0_u8; 8192];
        let size = application
            .recv(&mut bytes)
            .map_err(|error| error.to_string())?;
        assert_eq!(
            serde_json::from_slice::<Value>(&bytes[..size]).unwrap(),
            expected
        );
        let mut response = json!({"schema_version":1,"action":"previous_receipt",
            "target":expected["target"],"request_id":"4".repeat(32),"pending_receipt":null});
        application
            .send(&serde_json::to_vec(&response).unwrap())
            .map_err(|error| error.to_string())?;
        response["request_id"] = expected["request_id"].clone();
        application
            .send(&serde_json::to_vec(&response).unwrap())
            .map_err(|error| error.to_string())?;
        Ok(())
    });
    let observed: Value =
        serde_json::from_slice(&recovery_only.exchange(&serde_json::to_vec(&request)?)?)?;
    assert_eq!(observed["request_id"], request["request_id"]);
    assert!(
        recovery_only
            .exchange(br#"{"schema_version":1,"action":"replace_note"}"#)
            .is_err()
    );
    peer.join().expect("previous receipt discovery peer")?;
    Ok(())
}
