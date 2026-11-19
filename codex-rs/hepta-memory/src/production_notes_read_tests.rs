use super::*;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

struct StateChannel {
    reply: Vec<u8>,
    queries: AtomicUsize,
}

impl NotesPrivateChannel for StateChannel {
    fn exchange(&self, _: &[u8]) -> Result<Vec<u8>, String> {
        panic!("read-only observer must never enter the effect channel")
    }
    fn invalidate(&self) {
        panic!("read-only observation must not invalidate the effect channel")
    }
    fn recovery_exchange(&self, request: &[u8]) -> Result<Vec<u8>, String> {
        let request: Value = serde_json::from_slice(request).unwrap();
        assert_eq!(request["action"], "read_document_state");
        assert!(request.get("operation_id").is_none());
        assert!(request.get("text").is_none());
        self.queries.fetch_add(1, Ordering::SeqCst);
        Ok(self.reply.clone())
    }
}

#[test]
fn notes_objective_document_observer_validates_state_and_never_enters_effect() {
    let identity = NotesTargetIdentity {
        session_instance: "1".repeat(32),
        task_id: 7,
        incarnation: "2".repeat(32),
    };
    let nonce = "3".repeat(32);
    let valid = json!({"schema_version":1,"action":"document_state","target":identity,
        "request_id":nonce,"revision":19,"text_sha256":"4".repeat(64),"receipt_pending":true});
    for change in 0..10 {
        let mut response = valid.clone();
        match change {
            0 => {}
            1 => response["target"]["task_id"] = json!(8),
            2 => response["request_id"] = json!("5".repeat(32)),
            3 => response["schema_version"] = json!(2),
            4 => response["text_sha256"] = json!("F".repeat(64)),
            5 => response["action"] = json!("applied"),
            6 => response["revision"] = json!(-1),
            7 => response["extra_authority"] = json!(true),
            8 => response["receipt_pending"] = Value::Null,
            9 => response["text_sha256"] = json!("x".repeat(NOTES_RESPONSE_MAX_BYTES)),
            _ => unreachable!(),
        }
        let channel = Arc::new(StateChannel {
            reply: serde_json::to_vec(&response).unwrap(),
            queries: AtomicUsize::new(0),
        });
        let target = ProductionNotesTarget::new(identity.clone(), channel.clone()).unwrap();
        let observer = target.document_observer();
        assert!(observer.observe_document("bad nonce").is_err());
        assert_eq!(channel.queries.load(Ordering::SeqCst), 0);
        let observed = observer.observe_document(&nonce);
        if change == 0 {
            assert_eq!(
                observed.unwrap(),
                NotesDocumentState {
                    target: identity.clone(),
                    revision: 19,
                    text_sha256: Sha256Digest::parse("4".repeat(64)).unwrap(),
                    receipt_pending: true,
                }
            );
        } else {
            assert!(observed.is_err(), "invalid response case {change}");
        }
        assert_eq!(channel.queries.load(Ordering::SeqCst), 1);
    }
}

#[test]
fn notes_objective_document_observer_reads_shared_os_golden() {
    let fixture: Value = serde_json::from_str(include_str!(
        "../tests/fixtures/notes-document-state-v1.json"
    ))
    .unwrap();
    let request: Value = serde_json::from_str(fixture["request_utf8"].as_str().unwrap()).unwrap();
    let response: Value = serde_json::from_str(fixture["response_utf8"].as_str().unwrap()).unwrap();
    let identity: NotesTargetIdentity = serde_json::from_value(request["target"].clone()).unwrap();
    let channel = Arc::new(StateChannel {
        reply: fixture["response_utf8"]
            .as_str()
            .unwrap()
            .as_bytes()
            .to_vec(),
        queries: AtomicUsize::new(0),
    });
    let target = ProductionNotesTarget::new(identity.clone(), channel).unwrap();
    assert_eq!(
        target
            .document_observer()
            .observe_document(request["request_id"].as_str().unwrap())
            .unwrap(),
        NotesDocumentState {
            target: identity,
            revision: response["revision"].as_u64().unwrap(),
            text_sha256: Sha256Digest::parse(response["text_sha256"].as_str().unwrap()).unwrap(),
            receipt_pending: response["receipt_pending"].as_bool().unwrap(),
        }
    );
}
