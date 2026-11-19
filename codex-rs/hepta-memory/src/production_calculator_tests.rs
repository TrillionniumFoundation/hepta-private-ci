//! Contract fixtures only. No fixture authority or in-memory channel below
//! qualifies the real Calculator app, original Root deployment or presentation.

use super::*;
use std::collections::VecDeque;
use std::error::Error;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;

fn fixture() -> TestResult<(CalculatorTargetIdentity, String, String)> {
    let identity = CalculatorTargetIdentity {
        session_instance: "1".repeat(32),
        task_id: 2,
        incarnation: "2".repeat(32),
    };
    let payload = serde_json::to_string(&json!({
        "schema_version":1,"action":"evaluate","operation_id":"calculator.test.1",
        "destination_id":identity.destination_id(),"target":identity,"expected_revision":4,
        "left":"12","operator":"add","right":"30"
    }))?;
    let state = CalculatorValueState {
        left: "12".into(),
        operator: Some(CalculatorOperator::Add),
        right: "30".into(),
        result: "42".into(),
    };
    let response = serde_json::to_string_pretty(&json!({
        "schema_version":1,"target":identity,"operation_id":"calculator.test.1",
        "payload_sha256":Sha256Digest::for_bytes(payload.as_bytes()).as_str(),
        "result":{"status":"applied","previous_revision":4,"revision":5,
            "state":state,"state_sha256":state.digest()?.as_str()}
    }))?;
    Ok((identity, payload, response))
}

fn dispatch_request(
    target: &CalculatorTargetIdentity,
    payload: String,
) -> TestResult<ProductionDispatchRequest> {
    let intent = calculator_operation_intent(
        target,
        &payload,
        StableId::new("calculator-test-subject")?,
        Generation::new(1)?,
    )?;
    Ok(ProductionDispatchRequest {
        schema_version: crate::PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION,
        namespace: crate::PRODUCTION_DURABLE_WRITER_NAMESPACE.into(),
        lease_id: "calculator-test-lease".into(),
        occurrence_key: "calculator.test.1".into(),
        topic: CALCULATOR_EVALUATE_TOPIC_V1.into(),
        payload_sha256: Sha256Digest::for_bytes(payload.as_bytes()),
        payload_json: payload,
        idempotency_key: "calculator.test.1".into(),
        operation_scope_sha256: Sha256Digest::parse(intent.scope_digest().to_string())?,
        operation_subject_id: "calculator-test-subject".into(),
        operation_destination_id: target.destination_id(),
        operation_semantic_sha256: Sha256Digest::parse(intent.semantic_digest().to_string())?,
        operation_policy_generation: 1,
        expected_predecessor_sha256: Some(Sha256Digest::parse(
            target.predecessor_digest(4).to_string(),
        )?),
        operation_digest: Sha256Digest::for_bytes(b"explicit unit-test binding"),
    })
}

#[test]
fn calculator_intent_binds_exact_bytes_and_rejects_noncanonical_operands() -> TestResult {
    let (identity, payload, _) = fixture()?;
    let intent = |raw: &str| {
        calculator_operation_intent(
            &identity,
            raw,
            StableId::new("calculator-test-subject").unwrap(),
            Generation::new(1).unwrap(),
        )
    };
    assert_ne!(
        intent(&payload)?.semantic_digest(),
        intent(&(payload.clone() + " "))?.semantic_digest()
    );
    for invalid in ["+12", "012", "-0", " 12", "12 ", "9223372036854775808"] {
        let mut changed: Value = serde_json::from_str(&payload)?;
        changed["left"] = invalid.into();
        assert!(intent(&serde_json::to_string(&changed)?).is_err());
    }
    let mut rebound = identity;
    rebound.incarnation = "3".repeat(32);
    assert!(
        calculator_operation_intent(
            &rebound,
            &payload,
            StableId::new("calculator-test-subject")?,
            Generation::new(1)?,
        )
        .is_err()
    );
    Ok(())
}

#[test]
fn calculator_terminal_preserves_raw_bytes_and_checks_arithmetic_and_predecessor() -> TestResult {
    let (_, payload, response) = fixture()?;
    let checked = CalculatorTerminalReceipt::from_json(&payload, &response)?;
    assert_eq!(
        (checked.outcome(), checked.as_str()),
        (LocalReconcileOutcome::Committed, response.as_str())
    );
    for (path, changed) in [
        ("/result/revision", json!(6)),
        ("/result/state/result", json!("43")),
        ("/target/incarnation", json!("3".repeat(32))),
        ("/payload_sha256", json!("0".repeat(64))),
    ] {
        let mut value: Value = serde_json::from_str(&response)?;
        *value.pointer_mut(path).ok_or("response field")? = changed;
        assert!(
            CalculatorTerminalReceipt::from_json(&payload, &serde_json::to_string(&value)?)
                .is_err()
        );
    }
    let mut unknown: Value = serde_json::from_str(&response)?;
    unknown["result"] = json!({"status":"unknown","current_revision":5});
    assert!(
        CalculatorTerminalReceipt::from_json(&payload, &serde_json::to_string(&unknown)?).is_err()
    );
    Ok(())
}

#[test]
fn calculator_checked_division_does_not_invent_an_applied_result() -> TestResult {
    let (identity, payload, _) = fixture()?;
    for (left, right) in [("1", "0"), ("1", "2"), ("-9223372036854775808", "-1")] {
        let mut value: Value = serde_json::from_str(&payload)?;
        value["left"] = left.into();
        value["right"] = right.into();
        value["operator"] = "divide".into();
        let raw = serde_json::to_string(&value)?;
        assert!(parse_evaluate(&identity, &raw)?.expected_state().is_err());
    }
    Ok(())
}

struct Recovery {
    responses: Mutex<VecDeque<Vec<u8>>>,
    requests: Mutex<Vec<Vec<u8>>>,
}

impl CalculatorRecoveryChannel for Recovery {
    fn exchange(&self, request: &[u8]) -> Result<Vec<u8>, String> {
        self.requests.lock().unwrap().push(request.to_vec());
        self.responses
            .lock()
            .unwrap()
            .pop_front()
            .ok_or_else(|| "no fixture reply".into())
    }
}

struct Channel {
    recovery: Arc<Recovery>,
    effects: AtomicUsize,
    invalidated: AtomicBool,
}

impl CalculatorPrivateChannel for Channel {
    fn exchange(&self, _request: &[u8]) -> Result<Vec<u8>, String> {
        self.effects.fetch_add(1, Ordering::SeqCst);
        Err("fixture applied but lost its reply".into())
    }
    fn invalidate(&self) {
        self.invalidated.store(true, Ordering::SeqCst);
    }
    fn recovery_handle(&self) -> Arc<dyn CalculatorRecoveryChannel> {
        self.recovery.clone()
    }
}

#[tokio::test]
async fn calculator_unknown_entry_is_synchronous_and_recovers_only_by_observation() -> TestResult {
    let (identity, payload, response) = fixture()?;
    let recovery = Arc::new(Recovery {
        responses: Mutex::new([response.as_bytes().to_vec()].into()),
        requests: Mutex::new(Vec::new()),
    });
    let channel = Arc::new(Channel {
        recovery: recovery.clone(),
        effects: AtomicUsize::new(0),
        invalidated: AtomicBool::new(false),
    });
    let target = ProductionCalculatorTarget::new(identity.clone(), channel.clone())?;
    let request = dispatch_request(&identity, payload)?;
    let future = target.dispatch(request.clone());
    assert_eq!(
        channel.effects.load(Ordering::SeqCst),
        1,
        "entry occurs before polling"
    );
    assert!(matches!(
        future.await,
        ProductionTargetOutcome::Indeterminate { .. }
    ));
    assert!(channel.invalidated.load(Ordering::SeqCst));
    assert_eq!(
        target.observe_terminal(&request).await,
        ProductionTerminalObservation::Applied { receipt: response }
    );
    assert_eq!(channel.effects.load(Ordering::SeqCst), 1);
    let request: Value = serde_json::from_slice(&recovery.requests.lock().unwrap()[0])?;
    assert_eq!(request["action"], "observe");
    Ok(())
}

#[test]
fn calculator_readback_is_correlated_and_has_no_effect_descriptor() -> TestResult {
    let (identity, payload, receipt) = fixture()?;
    let applied: Value = serde_json::from_str(&receipt)?;
    let observation_id = "4".repeat(32);
    let response = json!({"schema_version":1,"action":"calculator_state","target":identity,
        "observation_id":observation_id,"revision":5,"state":applied["result"]["state"],
        "state_sha256":applied["result"]["state_sha256"],"receipt_pending":true});
    let mut stale = response.clone();
    stale["observation_id"] = "5".repeat(32).into();
    let recovery = Arc::new(Recovery {
        responses: Mutex::new([serde_json::to_vec(&response)?, serde_json::to_vec(&stale)?].into()),
        requests: Mutex::new(Vec::new()),
    });
    let channel = Arc::new(Channel {
        recovery,
        effects: AtomicUsize::new(0),
        invalidated: AtomicBool::new(false),
    });
    let target = ProductionCalculatorTarget::new(identity, channel.clone())?;
    let observer = target.state_observer();
    drop(target);
    assert_eq!(observer.observe_state(&observation_id)?.state.result, "42");
    assert!(observer.observe_state(&observation_id).is_err());
    assert_eq!(channel.effects.load(Ordering::SeqCst), 0);
    assert!(
        CalculatorTerminalReceipt::from_json(&payload, &serde_json::to_string(&response)?).is_err()
    );
    Ok(())
}

#[tokio::test]
async fn later_manual_state_does_not_erase_an_earlier_causal_applied_receipt() -> TestResult {
    let (identity, payload, original_receipt) = fixture()?;
    let manual = CalculatorValueState {
        left: "77".into(),
        operator: Some(CalculatorOperator::Add),
        right: "22".into(),
        result: "99".into(),
    };
    let observation_id = "6".repeat(32);
    let current = json!({"schema_version":1,"action":"calculator_state","target":identity,
        "observation_id":observation_id,"revision":9,"state":manual,
        "state_sha256":manual.digest()?.as_str(),"receipt_pending":true});
    let recovery = Arc::new(Recovery {
        responses: Mutex::new(
            [
                serde_json::to_vec(&current)?,
                original_receipt.as_bytes().to_vec(),
            ]
            .into(),
        ),
        requests: Mutex::new(Vec::new()),
    });
    let channel = Arc::new(Channel {
        recovery: recovery.clone(),
        effects: AtomicUsize::new(0),
        invalidated: AtomicBool::new(false),
    });
    let target = ProductionCalculatorTarget::new(identity.clone(), channel.clone())?;
    let current = target.state_observer().observe_state(&observation_id)?;
    assert_eq!((current.revision, current.state.result.as_str()), (9, "99"));
    let request = dispatch_request(&identity, payload)?;
    assert_eq!(
        target.observe_terminal(&request).await,
        ProductionTerminalObservation::Applied {
            receipt: original_receipt
        }
    );
    assert_eq!(channel.effects.load(Ordering::SeqCst), 0);
    let requests = recovery.requests.lock().unwrap();
    let actions = requests
        .iter()
        .map(|bytes| serde_json::from_slice::<Value>(bytes).unwrap()["action"].clone())
        .collect::<Vec<_>>();
    assert_eq!(actions, vec![json!("read_calculator"), json!("observe")]);
    Ok(())
}
