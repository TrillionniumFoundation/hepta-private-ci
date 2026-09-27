use codex_hepta_infer_core::durable_control::native::{
    NativeDispatch, NativeOwnerAuthority, NativeReservationState, NativeRunOutput,
    NativeRunRecord, NativeRunStatus,
};
use ed25519_dalek::{Signer, SigningKey};
use sha2::Digest;

use crate::provider_receipt::{
    provider_receipt_semantic_digest, provider_receipt_signing_bytes,
    ProviderReceiptVerifier, ProviderTerminalReceiptClaims,
    SignedProviderTerminalReceipt,
};

fn dispatch() -> NativeDispatch {
    NativeDispatch {
        thread_id: "thread.1".to_string(),
        model_provider: "provider.1".to_string(),
        context_digest: "1".repeat(64),
        owner_context_digest: Some("2".repeat(64)),
        codex_payload_digest: Some("3".repeat(64)),
        codex_request_digest: Some("4".repeat(64)),
        app_server_version: Some("1.0.0".to_string()),
        protocol_id: Some("codex.app-server.v2".to_string()),
        codex_source_admission_digest: Some("5".repeat(64)),
        codex_home_digest: Some("6".repeat(64)),
        codex_connection_id: Some(7),
        codex_session_id: Some("session.1".to_string()),
        codex_deadline_ms: Some(9_000),
        codex_authority_epoch: Some(3),
        codex_revocation_revision: Some(4),
        codex_revocation_head_sha256: Some("7".repeat(64)),
        codex_authority_witness_sha256: Some("8".repeat(64)),
    }
}

fn record() -> NativeRunRecord {
    NativeRunRecord {
        request: codex_hepta_infer_core::durable_control::native::NativeRequest {
            request_id: "request.1".to_string(),
            principal_id: "principal.1".to_string(),
            worker_generation: 7,
            model: "model.1".to_string(),
            payload_digest: "5".repeat(64),
        },
        revision: 3,
        state: NativeReservationState::Indeterminate,
        dispatch: Some(dispatch()),
        turn_id: Some("turn.1".to_string()),
        cancel_requested: false,
        pre_dispatch_stop: None,
        dispatch_rejection: None,
        observation: Some(NativeRunOutput {
            thread_id: "thread.1".to_string(),
            turn_id: "turn.1".to_string(),
            model: "model.1".to_string(),
            model_provider: "provider.1".to_string(),
            status: NativeRunStatus::Indeterminate,
            boundary_status: Default::default(),
            output: String::new(),
            observed_output_tokens: None,
            terminal_observed: false,
            stop_reason: Some("transport lost".to_string()),
            owner_authority: NativeOwnerAuthority::ObservedReady,
            codex_terminal_correlation_digest: None,
        }),
    }
}

fn signed() -> (ProviderReceiptVerifier, SignedProviderTerminalReceipt) {
    let signing_key = SigningKey::from_bytes(&[42_u8; 32]);
    let mut claims = ProviderTerminalReceiptClaims {
        schema_version: 1,
        issuer: "provider.receipts".to_string(),
        authority_epoch: 9,
        receipt_id: "receipt.1".to_string(),
        request_id: "request.1".to_string(),
        principal_id: "principal.1".to_string(),
        worker_generation: 7,
        model: "model.1".to_string(),
        thread_id: "thread.1".to_string(),
        turn_id: "turn.1".to_string(),
        model_provider: "provider.1".to_string(),
        codex_request_digest: "4".repeat(64),
        codex_payload_digest: "3".repeat(64),
        codex_source_admission_digest: "5".repeat(64),
        terminal_correlation_digest: "9".repeat(64),
        status: NativeRunStatus::Completed,
        output: "provider output".to_string(),
        output_sha256: format!(
            "{:x}",
            sha2::Sha256::digest(b"provider output")
        ),
        observed_output_tokens: Some(0),
        stop_reason: None,
        issued_at_ms: 100,
        expires_at_ms: 1_000,
        semantic_digest: "a".repeat(64),
    };
    claims.semantic_digest = provider_receipt_semantic_digest(&claims).unwrap();
    let signature = signing_key
        .sign(&provider_receipt_signing_bytes(&claims).unwrap())
        .to_bytes()
        .to_vec();
    (
        ProviderReceiptVerifier::new(
            "provider.receipts".to_string(),
            9,
            signing_key.verifying_key().to_bytes(),
            1_000,
        )
        .unwrap(),
        SignedProviderTerminalReceipt { claims, signature },
    )
}

#[test]
fn verified_receipt_preserves_owner_authority_and_zero_usage() {
    let (verifier, signed) = signed();
    let verified = verifier.verify_at(&signed, 200).unwrap();
    let resolution = verified.resolve(&record()).unwrap();
    assert_eq!(resolution.output.status, NativeRunStatus::Completed);
    assert_eq!(resolution.output.observed_output_tokens, Some(0));
    assert_eq!(
        resolution.output.owner_authority,
        NativeOwnerAuthority::ObservedReady
    );
    assert!(!resolution
        .receipt_witness_sha256
        .chars()
        .all(|value| value == '0'));
}

#[test]
fn forged_or_cross_request_receipt_fails_closed() {
    let (verifier, mut signed) = signed();
    signed.claims.request_id = "request.other".to_string();
    assert!(verifier.verify_at(&signed, 200).is_err());

    let (verifier, signed) = signed();
    let verified = verifier.verify_at(&signed, 200).unwrap();
    let mut wrong = record();
    wrong.request.worker_generation += 1;
    assert!(verified.resolve(&wrong).is_err());
}
