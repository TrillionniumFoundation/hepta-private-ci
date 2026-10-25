use super::*;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use std::collections::VecDeque;
use std::sync::Mutex;

type TestResult = Result<(), Box<dyn std::error::Error>>;

fn fixture() -> (AndroidSetTextV1, String, Value) {
    let golden: Value =
        serde_json::from_str(include_str!("../tests/fixtures/android-bound-text-v1.json"))
            .expect("wire fixture");
    let raw = golden["request_utf8"]
        .as_str()
        .expect("fixture request")
        .to_string();
    (
        AndroidSetTextV1::from_json(&raw).expect("valid fixture"),
        raw,
        golden,
    )
}

fn request(raw: String) -> Result<ProductionDispatchRequest, String> {
    let intent = android_text_operation_intent(
        &raw,
        StableId::new("fixture-original-subject").map_err(|e| e.to_string())?,
        Generation::new(1).map_err(|e| e.to_string())?,
    )?;
    Ok(ProductionDispatchRequest {
        schema_version: crate::PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION,
        namespace: crate::PRODUCTION_DURABLE_WRITER_NAMESPACE.to_string(),
        lease_id: "fixture-original-source".to_string(),
        occurrence_key: intent.operation_id().to_string(),
        topic: ANDROID_SET_TEXT_TOPIC_V1.to_string(),
        payload_sha256: Sha256Digest::for_bytes(raw.as_bytes()),
        payload_json: raw,
        idempotency_key: intent.operation_id().to_string(),
        operation_scope_sha256: Sha256Digest::parse(intent.scope_digest().to_string())?,
        operation_subject_id: intent.subject_id().to_string(),
        operation_destination_id: intent.destination_id().to_string(),
        operation_semantic_sha256: Sha256Digest::parse(intent.semantic_digest().to_string())?,
        operation_policy_generation: 1,
        expected_predecessor_sha256: None,
        operation_digest: Sha256Digest::for_bytes(b"fixture-only-final-use"),
    })
}

fn replies(payload: &AndroidSetTextV1, digest: &Sha256Digest) -> (Value, Value) {
    let common = json!({
        "ok":true,"organ_protocol":"pocket4-bound-text-v1","receiver_generation":payload.observation.generation,
        "operation_id":payload.operation_id,"payload_sha256":digest,"causal_receipt_persisted":false,
        "business_success_verified":false,"automatic_retry":false,"accessibility_mode":"none",
        "restored_flags":1,"touch_exploration_after":false,"accessibility_mode_restoration_verified":true
    });
    let mut apply = common.clone();
    for (key, value) in json!({"performed":"set-text","characters":payload.value.chars().count(),"readback_verified":true,
        "password":false,"action_submitted":true,"receiver_preconditions_checked":true,"postcondition_observed":true,
        "independent_readback_required":true,"receiver_action_observed_elapsed_ms":1500}).as_object().expect("apply fields") {
        apply[key] = value.clone();
    }
    let mut observation = serde_json::to_value(&payload.observation).expect("observation fixture");
    observation["observed_elapsed_ms"] = json!(1600);
    observation["target"]["prior_text_sha256"] =
        json!(Sha256Digest::for_bytes(payload.value.as_bytes()));
    let mut node = observation["target"].clone();
    node.as_object_mut().expect("node").remove("node_sha256");
    observation["target"]["node_sha256"] = json!(Sha256Digest::for_bytes(
        &serde_json::to_vec(&node).expect("canonical node")
    ));
    let mut readback = common;
    for (key, value) in json!({"observation":observation,"destination_id":payload.destination_id,"action_submitted":false,
        "independent_readback":true,"state_matches_requested_value":true,"terminal_outcome":"unproven"}).as_object().expect("read fields") {
        readback[key] = value.clone();
    }
    (apply, readback)
}

struct Device {
    replies: Mutex<VecDeque<Result<Vec<u8>, String>>>,
    calls: Mutex<Vec<(String, Vec<u8>)>>,
}

impl Device {
    fn new(replies: Vec<Result<Vec<u8>, String>>) -> Self {
        Self {
            replies: Mutex::new(replies.into()),
            calls: Mutex::new(Vec::new()),
        }
    }

    fn exchange(&self, mode: &str, raw: &[u8]) -> Result<Vec<u8>, String> {
        self.calls
            .lock()
            .expect("calls")
            .push((mode.to_string(), raw.to_vec()));
        self.replies
            .lock()
            .expect("replies")
            .pop_front()
            .unwrap_or_else(|| Err("no fixture reply".to_string()))
    }
}

impl OriginalAndroidTextDevice for Device {
    fn apply(&self, raw: &[u8]) -> Result<Vec<u8>, String> {
        self.exchange("apply", raw)
    }
    fn readback(&self, raw: &[u8]) -> Result<Vec<u8>, String> {
        self.exchange("readback", raw)
    }
    fn invalidate(&self) {
        self.calls
            .lock()
            .expect("calls")
            .push(("invalidate".to_string(), Vec::new()));
    }
}

#[test]
fn canonical_utf8_matches_independent_python_golden_and_rejects_duplicates() -> TestResult {
    let (payload, raw, golden) = fixture();
    assert_eq!(payload.to_json()?, raw);
    assert_eq!(
        Sha256Digest::for_bytes(raw.as_bytes()).as_str(),
        golden["payload_sha256"].as_str().ok_or("golden hash")?
    );
    let request = request(raw.clone())?;
    assert_eq!(
        request.operation_scope_sha256.as_str(),
        golden["scope_sha256"].as_str().ok_or("golden scope")?
    );
    assert!(
        AndroidSetTextV1::from_json(&raw.replace(
            "\"schema_version\":1",
            "\"schema_version\":1,\"schema_version\":1"
        ))
        .is_err()
    );
    assert!(AndroidSetTextV1::from_json(&(raw + "\n")).is_err());
    Ok(())
}

#[tokio::test]
async fn effect_and_independent_read_enter_before_poll_and_preserve_original_payload() -> TestResult
{
    let (payload, raw, _) = fixture();
    let request = request(raw.clone())?;
    let (apply, readback) = replies(&payload, &request.payload_sha256);
    let device = Arc::new(Device::new(vec![
        Ok(serde_json::to_vec(&apply)?),
        Ok(serde_json::to_vec(&readback)?),
    ]));
    let target = ProductionAndroidTextTarget::new(&payload.observation, device.clone())?;
    let future = target.dispatch(request);
    let calls = device.calls.lock().expect("calls").clone();
    assert_eq!(
        calls
            .iter()
            .map(|(mode, _)| mode.as_str())
            .collect::<Vec<_>>(),
        vec!["apply", "readback"]
    );
    for ((_, bytes), op) in calls.iter().zip(["organ-set-text", "organ-readback"]) {
        let message: Value = serde_json::from_slice(bytes)?;
        assert_eq!(message["op"], op);
        assert_eq!(
            base64::engine::general_purpose::STANDARD
                .decode(message["payload_base64"].as_str().ok_or("payload")?)?,
            raw.as_bytes()
        );
    }
    assert!(matches!(
        future.await,
        ProductionTargetOutcome::Committed { .. }
    ));
    assert_eq!(device.calls.lock().expect("calls").len(), 2);
    Ok(())
}

#[tokio::test]
async fn lost_ack_never_reads_as_committed_and_recovery_never_replays() -> TestResult {
    let (payload, raw, _) = fixture();
    let request = request(raw)?;
    let (_, readback) = replies(&payload, &request.payload_sha256);
    let device = Arc::new(Device::new(vec![
        Err("lost original response".to_string()),
        Ok(serde_json::to_vec(&readback)?),
    ]));
    let target = ProductionAndroidTextTarget::new(&payload.observation, device.clone())?;
    assert!(matches!(
        target.dispatch(request.clone()).await,
        ProductionTargetOutcome::Indeterminate { .. }
    ));
    assert!(matches!(
        target.observe_terminal(&request).await,
        ProductionTerminalObservation::Indeterminate { .. }
    ));
    assert_eq!(
        device
            .calls
            .lock()
            .expect("calls")
            .iter()
            .map(|(mode, _)| mode.clone())
            .collect::<Vec<_>>(),
        vec!["apply", "invalidate", "readback"]
    );
    Ok(())
}

#[tokio::test]
async fn changed_original_binding_rejects_before_effect_and_observation() -> TestResult {
    let (payload, raw, _) = fixture();
    let original = request(raw)?;
    for change in 0..4 {
        let device = Arc::new(Device::new(Vec::new()));
        let target = ProductionAndroidTextTarget::new(&payload.observation, device.clone())?;
        let mut altered = original.clone();
        match change {
            0 => altered.idempotency_key.push_str("-new"),
            1 => altered.operation_semantic_sha256 = Sha256Digest::for_bytes(b"different"),
            2 => {
                altered.expected_predecessor_sha256 = Some(Sha256Digest::for_bytes(b"unearned-CAS"))
            }
            3 => altered.payload_json = altered.payload_json.replace("mnt:[11]", "mnt:[99]"),
            _ => unreachable!(),
        }
        assert!(matches!(
            target.dispatch(altered.clone()).await,
            ProductionTargetOutcome::Rejected { .. }
        ));
        assert!(matches!(
            target.observe_terminal(&altered).await,
            ProductionTerminalObservation::Unavailable { .. }
        ));
        assert!(device.calls.lock().expect("calls").is_empty());
    }
    Ok(())
}

#[tokio::test]
async fn stale_readback_changed_incarnation_and_wrong_operation_never_commit() -> TestResult {
    let (payload, raw, _) = fixture();
    let request = request(raw)?;
    for change in 0..4 {
        let (mut apply, mut readback) = replies(&payload, &request.payload_sha256);
        match change {
            0 => readback["observation"]["observed_elapsed_ms"] = json!(1400),
            1 => readback["observation"]["application"]["start_ticks"] = json!("445"),
            2 => apply["operation_id"] = json!("another-operation"),
            3 => readback["observation"]["window"]["window_token"] = json!("abc124"),
            _ => unreachable!(),
        }
        let device = Arc::new(Device::new(vec![
            Ok(serde_json::to_vec(&apply)?),
            Ok(serde_json::to_vec(&readback)?),
        ]));
        let target = ProductionAndroidTextTarget::new(&payload.observation, device.clone())?;
        assert!(matches!(
            target.dispatch(request.clone()).await,
            ProductionTargetOutcome::Indeterminate { .. }
        ));
        assert_eq!(
            device
                .calls
                .lock()
                .expect("calls")
                .last()
                .map(|(kind, _)| kind.as_str()),
            Some("invalidate")
        );
    }
    Ok(())
}
