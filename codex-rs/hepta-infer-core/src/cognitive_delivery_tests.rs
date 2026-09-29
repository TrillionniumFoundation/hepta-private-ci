use super::*;
use crate::durable_control::native::NativeBoundaryStatus;
use crate::durable_control::native::NativeDispatch;
use crate::durable_control::native::NativeOwnerAuthority;
use crate::durable_control::native::NativeRunOutput;
use crate::durable_control::native::NativeRunStatus;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let nonce = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let sequence = NEXT.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "hepta-cognitive-delivery-{}-{nonce}-{sequence}",
            std::process::id()
        ));
        std::fs::create_dir(&path).unwrap();
        Self(path)
    }

    fn open(&self) -> DurableInferenceControl {
        DurableInferenceControl::open(self.0.join("native.journal"), /*capacity*/ 8).unwrap()
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn request() -> NativeRequest {
    NativeRequest {
        request_id: "request-1".to_string(),
        principal_id: "agent-1".to_string(),
        worker_generation: 4,
        model: "actual-model".to_string(),
        payload_digest: "a".repeat(64),
    }
}

fn context_digest() -> Digest32 {
    "c".repeat(64).parse().unwrap()
}

fn dispatch() -> NativeDispatch {
    NativeDispatch {
        thread_id: "thread-1".to_string(),
        model_provider: "provider".to_string(),
        context_digest: "b".repeat(64),
        owner_context_digest: Some(context_digest().to_string()),
        codex_payload_digest: Some("e".repeat(64)),
        codex_request_digest: Some("d".repeat(64)),
        app_server_version: Some("1.2.3".to_string()),
        protocol_id: Some("codex.app-server.v2".to_string()),
        codex_source_admission_digest: Some(request().payload_digest),
        codex_home_digest: Some("1".repeat(64)),
        codex_connection_id: Some(7),
        codex_session_id: Some("session-1".to_string()),
        codex_deadline_ms: Some(10_000),
        codex_authority_epoch: Some(9),
        codex_revocation_revision: Some(3),
        codex_revocation_head_sha256: Some("3".repeat(64)),
        codex_authority_witness_sha256: Some("2".repeat(64)),
    }
}

fn state(owner: &DurableInferenceControl) -> Option<CognitiveContextDeliveryStateV1> {
    owner
        .cognitive_context_delivery(&request(), context_digest())
        .unwrap()
        .map(|evidence| evidence.state())
}

#[test]
fn dispatch_and_reopen_do_not_prove_cognitive_delivery() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    owner.reserve_native(request(), /*maximum_in_flight*/ 1).unwrap();
    assert_eq!(state(&owner), None);
    owner.dispatch_native("request-1", dispatch()).unwrap();
    assert_eq!(state(&owner), Some(CognitiveContextDeliveryStateV1::AcceptanceUnknown));
    let before = owner.native_record("request-1").unwrap().clone();
    let evidence = owner.cognitive_context_delivery(&request(), context_digest()).unwrap().unwrap();
    assert!(!evidence.accepted_by_app_server());
    let digest = evidence.binding_digest();
    assert_eq!(evidence.authority(), AuthorityPosture::DENY_ALL);
    assert_eq!(owner.native_record("request-1"), Some(&before));
    drop(owner);
    let reopened = fixture.open();
    let evidence = reopened.cognitive_context_delivery(&request(), context_digest()).unwrap().unwrap();
    assert_eq!(evidence.state(), CognitiveContextDeliveryStateV1::AcceptanceUnknown);
    assert_eq!(evidence.binding_digest(), digest);
}

#[test]
fn exact_owner_generation_request_and_context_are_required() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    owner.reserve_native(request(), /*maximum_in_flight*/ 1).unwrap();
    owner.dispatch_native("request-1", dispatch()).unwrap();
    let mut substitutions = Vec::new();
    let mut changed = request();
    changed.principal_id = "agent-2".to_string();
    substitutions.push(changed);
    let mut changed = request();
    changed.worker_generation += 1;
    substitutions.push(changed);
    let mut changed = request();
    changed.model = "other-model".to_string();
    substitutions.push(changed);
    let mut changed = request();
    changed.payload_digest = "f".repeat(64);
    substitutions.push(changed);
    for changed in substitutions {
        assert_eq!(
            owner.cognitive_context_delivery(&changed, context_digest()).unwrap_err(),
            CognitiveContextDeliveryError::RequestMismatch
        );
    }
    assert_eq!(
        owner.cognitive_context_delivery(&request(), Digest32::of_bytes(b"other-context")).unwrap_err(),
        CognitiveContextDeliveryError::ContextMismatch
    );
    assert_eq!(
        owner.cognitive_context_delivery(&request(), Digest32::ZERO).unwrap_err(),
        CognitiveContextDeliveryError::InvalidDigest
    );
}

#[test]
fn only_durable_pre_effect_proof_establishes_not_sent() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    owner.reserve_native(request(), /*maximum_in_flight*/ 1).unwrap();
    let (_, proof) = owner.dispatch_native_with_pre_effect_abort("request-1", dispatch()).unwrap();
    owner.abort_native_before_effect(proof, "stale owner cut".to_string()).unwrap();
    assert_eq!(state(&owner), Some(CognitiveContextDeliveryStateV1::NotSent));
    drop(owner);
    assert_eq!(state(&fixture.open()), Some(CognitiveContextDeliveryStateV1::NotSent));
}

#[test]
fn cancellation_does_not_erase_observed_acceptance() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    owner.reserve_native(request(), /*maximum_in_flight*/ 1).unwrap();
    owner.dispatch_native("request-1", dispatch()).unwrap();
    owner.cancel_native("request-1").unwrap();
    assert_eq!(state(&owner), Some(CognitiveContextDeliveryStateV1::AcceptanceUnknown));
    // A separate fixture represents cancellation after actual turn acceptance.
    let accepted_fixture = Fixture::new();
    let mut accepted = accepted_fixture.open();
    accepted.reserve_native(request(), /*maximum_in_flight*/ 1).unwrap();
    accepted.dispatch_native("request-1", dispatch()).unwrap();
    accepted.native_started("request-1", "turn-1".to_string()).unwrap();
    accepted.cancel_native("request-1").unwrap();
    assert_eq!(state(&accepted), Some(CognitiveContextDeliveryStateV1::TurnAccepted));
}

#[test]
fn terminal_delivery_and_authorized_success_are_not_conflated() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    owner.reserve_native(request(), /*maximum_in_flight*/ 1).unwrap();
    owner.dispatch_native("request-1", dispatch()).unwrap();
    owner.native_started("request-1", "turn-1".to_string()).unwrap();
    let output = NativeRunOutput {
        thread_id: "thread-1".to_string(),
        turn_id: "turn-1".to_string(),
        model: "actual-model".to_string(),
        model_provider: "provider".to_string(),
        status: NativeRunStatus::Failed,
        boundary_status: NativeBoundaryStatus::Failed,
        output: "PRIVATE-OUTPUT-MUST-NOT-APPEAR-IN-DEBUG".to_string(),
        observed_output_tokens: None,
        terminal_observed: true,
        stop_reason: Some("failed".to_string()),
        owner_authority: NativeOwnerAuthority::Unverified,
        codex_terminal_correlation_digest: Some("d".repeat(64)),
    };
    assert!(!output.succeeded());
    owner.settle_native("request-1", output).unwrap();
    let evidence = owner.cognitive_context_delivery(&request(), context_digest()).unwrap().unwrap();
    assert_eq!(evidence.state(), CognitiveContextDeliveryStateV1::TerminalObserved);
    assert!(evidence.accepted_by_app_server());
    assert!(!format!("{evidence:?}").contains("PRIVATE-OUTPUT"));
    let digest = evidence.binding_digest();
    drop(owner);
    let reopened = fixture.open();
    assert_eq!(
        reopened.cognitive_context_delivery(&request(), context_digest()).unwrap().unwrap().binding_digest(),
        digest
    );
}

#[test]
fn substituted_source_admission_cannot_join_a_preparation() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    owner.reserve_native(request(), /*maximum_in_flight*/ 1).unwrap();
    let mut changed = dispatch();
    changed.codex_source_admission_digest = Some("f".repeat(64));
    owner.dispatch_native("request-1", changed).unwrap();
    assert_eq!(
        owner.cognitive_context_delivery(&request(), context_digest()).unwrap_err(),
        CognitiveContextDeliveryError::RequestMismatch
    );
}

#[test]
fn observed_server_rejection_does_not_claim_the_payload_was_not_sent() {
    use crate::durable_control::native::NativeDispatchRejection;
    use crate::durable_control::native::NativeDispatchRejectionStatus;

    let fixture = Fixture::new();
    let mut owner = fixture.open();
    owner.reserve_native(request(), /*maximum_in_flight*/ 1).unwrap();
    owner.dispatch_native("request-1", dispatch()).unwrap();
    owner.reject_native_before_start("request-1", NativeDispatchRejection {
        status: NativeDispatchRejectionStatus::Rejected,
        reason: "observed refusal".to_string(),
        response_digest: "4".repeat(64),
        retry_safe_before_admission: false,
    }).unwrap();
    assert_eq!(state(&owner), Some(CognitiveContextDeliveryStateV1::RejectedBeforeTurn));
    drop(owner);
    assert_eq!(state(&fixture.open()), Some(CognitiveContextDeliveryStateV1::RejectedBeforeTurn));
}
