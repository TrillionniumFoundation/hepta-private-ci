//! Golden bytes produced by actual Desktop core Rust serialization at
//! 5a8684cc4591a4163c162f198b4121ca4cfc6ebc. Fixture SHA256:
//! 3fe384300463b8692cba32e720df5ac5f61403c4dfa6223e0ffdd1e6dbb303c7.
//! This checks the original owner decoder, not GUI or production acceptance.
use super::*;
use serde_json::Value;
const REQUEST: &str = r#"{"schema_version":1,"action":"evaluate","operation_id":"original-1","destination_id":"trill.calculator:11111111111111111111111111111111:2:22222222222222222222222222222222","target":{"session_instance":"11111111111111111111111111111111","task_id":2,"incarnation":"22222222222222222222222222222222"},"expected_revision":0,"left":"12","operator":"add","right":"30"}"#;
const APPLIED: &str = r#"{"schema_version":1,"target":{"session_instance":"11111111111111111111111111111111","task_id":2,"incarnation":"22222222222222222222222222222222"},"operation_id":"original-1","payload_sha256":"f2604897d0641366919a36284d53dfa621f994206a3d30301d1cc13c6332bbc0","result":{"status":"applied","previous_revision":0,"revision":1,"state":{"left":"12","operator":"add","right":"30","result":"42"},"state_sha256":"1ce69e4a380ebbccdc1ff31a3671359cf5418a5fb34ba59968387d6de253172f"}}"#;
const READBACK: &str = r#"{"schema_version":1,"action":"calculator_state","target":{"session_instance":"11111111111111111111111111111111","task_id":2,"incarnation":"22222222222222222222222222222222"},"observation_id":"33333333333333333333333333333333","revision":1,"state":{"left":"12","operator":"add","right":"30","result":"42"},"state_sha256":"1ce69e4a380ebbccdc1ff31a3671359cf5418a5fb34ba59968387d6de253172f","receipt_pending":true}"#;

struct ReadOnly;
impl CalculatorRecoveryChannel for ReadOnly {
    fn exchange(&self, request: &[u8]) -> Result<Vec<u8>, String> {
        let value: Value = serde_json::from_slice(request).map_err(|error| error.to_string())?;
        if value["action"] != "read_calculator" || value["observation_id"] != "3".repeat(32) {
            return Err("unexpected golden read request".into());
        }
        Ok(READBACK.as_bytes().to_vec())
    }
}
struct NeverEffect;
impl CalculatorPrivateChannel for NeverEffect {
    fn exchange(&self, _request: &[u8]) -> Result<Vec<u8>, String> {
        panic!("golden observer must have no effect path")
    }
    fn invalidate(&self) {}
    fn recovery_handle(&self) -> Arc<dyn CalculatorRecoveryChannel> {
        Arc::new(ReadOnly)
    }
}

#[test]
fn original_owner_accepts_exact_desktop_rust_payload_receipt_and_independent_readback() {
    let payload: Value = serde_json::from_str(REQUEST).unwrap();
    let target: CalculatorTargetIdentity =
        serde_json::from_value(payload["target"].clone()).unwrap();
    assert_eq!(
        Sha256Digest::for_bytes(REQUEST.as_bytes()).as_str(),
        "f2604897d0641366919a36284d53dfa621f994206a3d30301d1cc13c6332bbc0"
    );
    assert_eq!(
        Sha256Digest::for_bytes(APPLIED.as_bytes()).as_str(),
        "6ccbc1b07aa43ac2f1ad7a7f0b67474a659ebc31868fc36adabeae54b275bd4c"
    );
    assert_eq!(
        target.scope_digest().to_string(),
        "26f0b23d411fc006bb1af3f6fe3a89d8a3f208a42618d0de5626d94ef9a218f2"
    );
    assert_eq!(
        target.predecessor_digest(0).to_string(),
        "381600e70b8bfee64ff978d99cc06e2042c8c7030ac8c670dff2fe5503033197"
    );
    let terminal = CalculatorTerminalReceipt::from_json(REQUEST, APPLIED).unwrap();
    assert_eq!(terminal.outcome(), LocalReconcileOutcome::Committed);
    assert_eq!(terminal.as_str(), APPLIED);
    let owner = ProductionCalculatorTarget::new(target.clone(), Arc::new(NeverEffect)).unwrap();
    let state = owner
        .state_observer()
        .observe_state(&"3".repeat(32))
        .unwrap();
    assert_eq!(state.target, target);
    assert_eq!(state.revision, 1);
    assert_eq!(state.state.result, "42");
    assert!(state.receipt_pending);
    assert_eq!(
        state.state_sha256.as_str(),
        "1ce69e4a380ebbccdc1ff31a3671359cf5418a5fb34ba59968387d6de253172f"
    );
}
