use super::*;
use pretty_assertions::assert_eq;
use std::collections::VecDeque;
use std::error::Error;
use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

type TestResult = Result<(), Box<dyn Error>>;

#[derive(Deserialize)]
struct Fixture {
    request_utf8: String,
    payload_sha256: String,
    expected_scope_sha256: String,
    expected_predecessor_sha256: String,
    application_response_utf8: String,
}

fn fixture() -> Fixture {
    serde_json::from_str(include_str!("../tests/fixtures/notes-target-v1.json"))
        .expect("shared Notes wire fixture")
}

fn identity() -> NotesTargetIdentity {
    NotesTargetIdentity {
        session_instance: "1".repeat(32),
        task_id: 7,
        incarnation: "2".repeat(32),
    }
}

fn request(payload: String) -> Result<ProductionDispatchRequest, Box<dyn Error>> {
    let intent = notes_operation_intent(
        &identity(),
        &payload,
        StableId::new("notes-test-subject")?,
        Generation::new(1)?,
    )?;
    Ok(ProductionDispatchRequest {
        schema_version: crate::PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION,
        namespace: crate::PRODUCTION_DURABLE_WRITER_NAMESPACE.to_string(),
        lease_id: "notes-test-source".to_string(),
        occurrence_key: intent.operation_id().to_string(),
        topic: NOTES_REPLACE_TOPIC_V1.to_string(),
        payload_sha256: Sha256Digest::for_bytes(payload.as_bytes()),
        payload_json: payload,
        idempotency_key: intent.operation_id().to_string(),
        operation_scope_sha256: Sha256Digest::parse(intent.scope_digest().to_string())?,
        operation_subject_id: intent.subject_id().to_string(),
        operation_destination_id: intent.destination_id().to_string(),
        operation_semantic_sha256: Sha256Digest::parse(intent.semantic_digest().to_string())?,
        operation_policy_generation: intent.policy_generation().get(),
        expected_predecessor_sha256: intent.expected_predecessor()
            .map(|digest| Sha256Digest::parse(digest.to_string())).transpose()?,
        // Only the original dispatcher consumes this authority-bound digest.
        operation_digest: Sha256Digest::for_bytes(b"fixture-final-use-binding"),
    })
}

struct Channel {
    requests: Mutex<Vec<Vec<u8>>>,
    responses: Mutex<VecDeque<Result<Vec<u8>, String>>>,
    invalidations: AtomicUsize,
}

impl Channel {
    fn new(responses: Vec<Result<Vec<u8>, String>>) -> Self {
        Self {
            requests: Mutex::new(Vec::new()),
            responses: Mutex::new(responses.into()),
            invalidations: AtomicUsize::new(0),
        }
    }
}

impl NotesPrivateChannel for Channel {
    fn exchange(&self, request: &[u8]) -> Result<Vec<u8>, String> {
        self.requests.lock().expect("fixture request lock").push(request.to_vec());
        self.responses.lock().expect("fixture response lock").pop_front()
            .unwrap_or_else(|| Err("fixture has no response".to_string()))
    }

    fn invalidate(&self) {
        self.invalidations.fetch_add(1, Ordering::SeqCst);
    }
}

#[tokio::test]
async fn golden_bytes_enter_synchronously_and_bind_scope_predecessor_and_model_receipt() -> TestResult {
    let fixture = fixture();
    let request = request(fixture.request_utf8.clone())?;
    assert_eq!(request.payload_sha256.as_str(), fixture.payload_sha256);
    assert_eq!(identity().scope_digest().to_string(), fixture.expected_scope_sha256);
    assert_eq!(identity().predecessor_digest(0).to_string(), fixture.expected_predecessor_sha256);
    let channel = Arc::new(Channel::new(vec![Ok(fixture.application_response_utf8.as_bytes().to_vec())]));
    let target = ProductionNotesTarget::new(identity(), channel.clone())?;
    let unpolled = target.dispatch(request);
    assert_eq!(*channel.requests.lock().expect("fixture request lock"), vec![fixture.request_utf8.into_bytes()]);
    assert_eq!(unpolled.await, ProductionTargetOutcome::Committed { receipt: fixture.application_response_utf8 });
    assert_eq!(channel.invalidations.load(Ordering::SeqCst), 0);
    Ok(())
}

#[tokio::test]
async fn mismatched_original_intent_is_rejected_before_private_channel_entry() -> TestResult {
    let original = request(fixture().request_utf8)?;
    let changes: [fn(&mut ProductionDispatchRequest); 13] = [
        |request| request.expected_predecessor_sha256 = None,
        |request| request.expected_predecessor_sha256 = Some(Sha256Digest::for_bytes(b"other predecessor")),
        |request| request.operation_scope_sha256 = Sha256Digest::for_bytes(b"other scope"),
        |request| request.operation_semantic_sha256 = Sha256Digest::for_bytes(b"other intent"),
        |request| request.operation_subject_id = "another-subject".to_string(),
        |request| request.operation_policy_generation += 1,
        |request| request.operation_destination_id.push('x'),
        |request| request.occurrence_key.push('x'),
        |request| request.idempotency_key.push('x'),
        |request| request.payload_json.push(' '),
        |request| request.topic = "another-topic".to_string(),
        |request| request.namespace = "another-namespace".to_string(),
        |request| request.schema_version += 1,
    ];
    let channel = Arc::new(Channel::new(Vec::new()));
    let target = ProductionNotesTarget::new(identity(), channel.clone())?;
    for change in changes {
        let mut changed = original.clone();
        change(&mut changed);
        assert!(matches!(target.dispatch(changed).await, ProductionTargetOutcome::Rejected { .. }));
    }
    assert!(channel.requests.lock().expect("fixture request lock").is_empty());
    Ok(())
}

#[test]
fn duplicate_unknown_and_oversized_request_fields_are_not_accepted() -> TestResult {
    let fixture = fixture();
    let duplicate = fixture.request_utf8.replacen("{", "{\"schema_version\":1,", 1);
    let unknown = fixture.request_utf8.replacen("{", "{\"extra\":true,", 1);
    let mut oversized: serde_json::Value = serde_json::from_str(&fixture.request_utf8)?;
    oversized["text"] = serde_json::json!("x".repeat(4097));
    for raw in [duplicate, unknown, serde_json::to_string(&oversized)?, " ".repeat(NOTES_REQUEST_MAX_BYTES + 1)] {
        assert!(notes_operation_intent(&identity(), &raw, StableId::new("subject")?, Generation::new(1)?).is_err());
    }
    let mut other_incarnation = identity();
    other_incarnation.incarnation = "3".repeat(32);
    assert!(notes_operation_intent(&other_incarnation, &fixture.request_utf8, StableId::new("subject")?, Generation::new(1)?).is_err());
    Ok(())
}

#[tokio::test]
async fn exact_json_whitespace_is_preserved_in_payload_and_receipt_identity() -> TestResult {
    let fixture = fixture();
    let payload = format!(" {}\n", fixture.request_utf8);
    let request = request(payload.clone())?;
    let mut response: serde_json::Value = serde_json::from_str(&fixture.application_response_utf8)?;
    response["payload_sha256"] = serde_json::json!(request.payload_sha256.as_str());
    let channel = Arc::new(Channel::new(vec![Ok(serde_json::to_vec(&response)?)]));
    let target = ProductionNotesTarget::new(identity(), channel.clone())?;
    assert!(matches!(target.dispatch(request).await, ProductionTargetOutcome::Committed { .. }));
    assert_eq!(*channel.requests.lock().expect("fixture request lock"), vec![payload.into_bytes()]);
    Ok(())
}

#[tokio::test]
async fn lost_ack_bad_revision_bad_digest_and_unknown_never_infer_success() -> TestResult {
    let fixture = fixture();
    let response: serde_json::Value = serde_json::from_str(&fixture.application_response_utf8)?;
    let mut bad_revision = response.clone();
    bad_revision["result"]["revision"] = serde_json::json!(2);
    let mut bad_digest = response.clone();
    bad_digest["payload_sha256"] = serde_json::json!("0".repeat(64));
    let mut bad_text = response.clone();
    bad_text["result"]["text_sha256"] = serde_json::json!("0".repeat(64));
    let mut unknown = response.clone();
    unknown["result"] = serde_json::json!({"status":"unknown","current_revision":1});
    let duplicate = fixture.application_response_utf8.replacen("{", "{\"schema_version\":1,", 1);
    for response in [Err("lost reply".to_string()), Ok(serde_json::to_vec(&bad_revision)?), Ok(serde_json::to_vec(&bad_digest)?), Ok(serde_json::to_vec(&bad_text)?), Ok(serde_json::to_vec(&unknown)?), Ok(duplicate.into_bytes())] {
        let channel = Arc::new(Channel::new(vec![response]));
        let target = ProductionNotesTarget::new(identity(), channel.clone())?;
        assert!(matches!(target.dispatch(request(fixture.request_utf8.clone())?).await, ProductionTargetOutcome::Indeterminate { .. }));
        assert_eq!(channel.invalidations.load(Ordering::SeqCst), 1);
        assert_eq!(channel.requests.lock().expect("fixture request lock").len(), 1);
    }
    Ok(())
}

#[tokio::test]
async fn explicit_cas_refusal_is_not_applied_but_missing_observed_receipt_stays_unknown() -> TestResult {
    let fixture = fixture();
    let mut response: serde_json::Value = serde_json::from_str(&fixture.application_response_utf8)?;
    response["result"] = serde_json::json!({"status":"not_applied","reason":"revision_conflict","current_revision":9});
    let refusal = serde_json::to_string(&response)?;
    response["result"] = serde_json::json!({"status":"unknown","current_revision":9});
    let channel = Arc::new(Channel::new(vec![Ok(refusal.as_bytes().to_vec()), Ok(serde_json::to_vec(&response)?)]));
    let target = ProductionNotesTarget::new(identity(), channel.clone())?;
    let request = request(fixture.request_utf8)?;
    assert_eq!(target.dispatch(request.clone()).await, ProductionTargetOutcome::NotApplied { reason: refusal });
    assert!(matches!(target.observe_terminal(&request).await, ProductionTerminalObservation::Indeterminate { .. }));
    let queries = channel.requests.lock().expect("fixture request lock");
    let observed: serde_json::Value = serde_json::from_slice(&queries[1])?;
    assert_eq!(observed, serde_json::json!({"schema_version":1,"action":"observe","target":identity(),"operation_id":"fixture-notes-v1","payload_sha256":request.payload_sha256.as_str()}));
    assert_eq!(channel.invalidations.load(Ordering::SeqCst), 0);
    Ok(())
}

#[tokio::test]
async fn terminal_observation_reads_only_the_original_operation_receipt() -> TestResult {
    let fixture = fixture();
    let channel = Arc::new(Channel::new(vec![Ok(fixture.application_response_utf8.as_bytes().to_vec())]));
    let target = ProductionNotesTarget::new(identity(), channel.clone())?;
    assert_eq!(target.observe_terminal(&request(fixture.request_utf8)?).await, ProductionTerminalObservation::Applied { receipt: fixture.application_response_utf8 });
    let queries = channel.requests.lock().expect("fixture request lock");
    assert_eq!(queries.len(), 1);
    let observed: serde_json::Value = serde_json::from_slice(&queries[0])?;
    assert_eq!(observed["action"], "observe");
    assert!(observed.get("text").is_none());
    Ok(())
}
