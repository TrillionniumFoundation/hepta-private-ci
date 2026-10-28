use super::*;
use pretty_assertions::assert_eq;
use std::error::Error;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
type TestResult = Result<(), Box<dyn Error>>;
fn fixture() -> serde_json::Value {
    serde_json::from_str(include_str!("../tests/fixtures/desktop-x11-v1.json")).unwrap()
}
fn raw(name: &str) -> String {
    fixture()[name].as_str().unwrap().to_string()
}
fn identity() -> DesktopTargetIdentity {
    serde_json::from_str::<DesktopInput>(&raw("input_raw"))
        .unwrap()
        .target
}
fn request(payload: String) -> Result<ProductionDispatchRequest, Box<dyn Error>> {
    let intent = desktop_operation_intent(
        &identity(),
        &payload,
        StableId::new("desktop-test-subject")?,
        Generation::new(1)?,
    )?;
    Ok(ProductionDispatchRequest {
        schema_version: crate::PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION,
        namespace: crate::PRODUCTION_DURABLE_WRITER_NAMESPACE.to_string(),
        lease_id: "desktop-test-source".to_string(),
        occurrence_key: intent.operation_id().to_string(),
        topic: DESKTOP_INPUT_TOPIC_V1.to_string(),
        payload_sha256: Sha256Digest::for_bytes(payload.as_bytes()),
        payload_json: payload,
        idempotency_key: intent.operation_id().to_string(),
        operation_scope_sha256: Sha256Digest::parse(intent.scope_digest().to_string())?,
        operation_subject_id: intent.subject_id().to_string(),
        operation_destination_id: intent.destination_id().to_string(),
        operation_semantic_sha256: Sha256Digest::parse(intent.semantic_digest().to_string())?,
        operation_policy_generation: intent.policy_generation().get(),
        expected_predecessor_sha256: intent
            .expected_predecessor()
            .map(|digest| Sha256Digest::parse(digest.to_string()))
            .transpose()?,
        // Only the original dispatcher consumes this authority-bound digest.
        operation_digest: Sha256Digest::for_bytes(b"fixture-final-use-binding"),
    })
}

struct Channel {
    response: Mutex<Result<Vec<u8>, String>>,
    calls: AtomicUsize,
    disabled: AtomicBool,
}
impl Channel {
    fn new(response: Result<Vec<u8>, String>) -> Self {
        Self {
            response: Mutex::new(response),
            calls: AtomicUsize::new(0),
            disabled: AtomicBool::new(false),
        }
    }
}
impl DesktopPrivateChannel for Channel {
    fn exchange(&self, request: &[u8]) -> Result<Vec<u8>, String> {
        assert_eq!(request, raw("input_raw").as_bytes());
        self.calls.fetch_add(1, Ordering::SeqCst);
        self.response.lock().unwrap().clone()
    }
    fn invalidate(&self) {
        self.disabled.store(true, Ordering::SeqCst);
    }
}
impl DesktopObservationChannel for Channel {
    fn exchange(&self, request: &[u8]) -> Result<Vec<u8>, String> {
        let q: serde_json::Value = serde_json::from_slice(request).unwrap();
        assert_eq!(
            q,
            serde_json::from_str::<serde_json::Value>(&raw("observe_raw")).unwrap()
        );
        self.calls.fetch_add(1, Ordering::SeqCst);
        self.response.lock().unwrap().clone()
    }
}
#[tokio::test]
async fn desktop_golden_enters_synchronously_and_preserves_exact_injection_receipt() -> TestResult {
    let channel = Arc::new(Channel::new(Ok(raw("receipt_raw").into_bytes())));
    let target = ProductionDesktopTarget::new(identity(), channel.clone(), channel.clone())?;
    let req = request(raw("input_raw"))?;
    assert_eq!(
        req.operation_scope_sha256.as_str(),
        fixture()["scope_sha256"].as_str().unwrap()
    );
    assert_eq!(
        req.expected_predecessor_sha256.as_ref().unwrap().as_str(),
        fixture()["predecessor_sha256"].as_str().unwrap()
    );
    let future = target.dispatch(req.clone());
    assert_eq!(channel.calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        future.await,
        ProductionTargetOutcome::Committed {
            receipt: raw("receipt_raw")
        }
    );
    assert_eq!(
        target.observe_terminal(&req).await,
        ProductionTerminalObservation::Applied {
            receipt: raw("receipt_raw")
        }
    );
    assert_eq!(channel.calls.load(Ordering::SeqCst), 2);
    let terminal = DesktopTerminalReceipt::from_json(&raw("input_raw"), &raw("receipt_raw"))?;
    assert_eq!(terminal.as_str(), raw("receipt_raw"));
    assert_eq!(terminal.outcome(), crate::LocalReconcileOutcome::Committed);
    Ok(())
}
#[tokio::test]
async fn desktop_ambiguous_effect_fences_effect_but_unknown_observation_never_commits() -> TestResult
{
    let effect = Arc::new(Channel::new(Err("lost reply".into())));
    let mut unknown: serde_json::Value = serde_json::from_str(&raw("receipt_raw"))?;
    unknown["result"] = serde_json::json!({"status":"unknown","current_sequence":0});
    let bytes = serde_json::to_vec(&unknown)?;
    let observe = Arc::new(Channel::new(Ok(bytes.clone())));
    let target = ProductionDesktopTarget::new(identity(), effect.clone(), observe.clone())?;
    let req = request(raw("input_raw"))?;
    assert!(matches!(
        target.dispatch(req.clone()).await,
        ProductionTargetOutcome::Indeterminate { .. }
    ));
    assert!(effect.disabled.load(Ordering::SeqCst));
    assert!(matches!(
        target.observe_terminal(&req).await,
        ProductionTerminalObservation::Indeterminate { .. }
    ));
    assert!(
        DesktopTerminalReceipt::from_json(&raw("input_raw"), std::str::from_utf8(&bytes)?).is_err()
    );
    assert_eq!(effect.calls.load(Ordering::SeqCst), 1);
    Ok(())
}
#[tokio::test]
async fn desktop_exact_binding_and_balanced_events_refuse_before_channel_entry() -> TestResult {
    let channel = Arc::new(Channel::new(Ok(raw("receipt_raw").into_bytes())));
    let target = ProductionDesktopTarget::new(identity(), channel.clone(), channel.clone())?;
    let mut request = request(raw("input_raw"))?;
    request.expected_predecessor_sha256 = Some(Sha256Digest::for_bytes(b"wrong"));
    assert!(matches!(
        target.dispatch(request).await,
        ProductionTargetOutcome::Rejected { .. }
    ));
    let mut unbalanced: serde_json::Value = serde_json::from_str(&raw("input_raw"))?;
    unbalanced["events"].as_array_mut().unwrap().pop();
    assert!(
        desktop_operation_intent(
            &identity(),
            &serde_json::to_string(&unbalanced)?,
            StableId::new("fixture")?,
            Generation::new(1)?
        )
        .is_err()
    );
    let mut forged: serde_json::Value = serde_json::from_str(&raw("receipt_raw"))?;
    forged["result"]["effect_semantics"] = serde_json::json!("application_completed");
    assert!(
        DesktopTerminalReceipt::from_json(&raw("input_raw"), &serde_json::to_string(&forged)?)
            .is_err()
    );
    assert_eq!(channel.calls.load(Ordering::SeqCst), 0);
    Ok(())
}
