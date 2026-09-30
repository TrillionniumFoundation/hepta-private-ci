use std::collections::BTreeMap;
use std::time::Duration;

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeDispatch;
use codex_hepta_infer_core::durable_control::native::NativeRequest;
use codex_hepta_infer_core::durable_control::native::NativeRunStatus;
use tempfile::tempdir;

use super::*;

struct PassVerifier;

impl TrustedProviderTerminalReceiptVerifier for PassVerifier {
    fn verify<'a>(
        &'a self,
        _record: &'a NativeRunRecord,
        proposed: ProviderTerminalReceipt,
    ) -> ProviderReceiptVerificationFuture<'a> {
        Box::pin(async move { Ok(proposed) })
    }
}

fn digest(label: &str) -> String {
    use sha2::Digest;
    format!("{:x}", sha2::Sha256::digest(label.as_bytes()))
}

fn open_dispatched_control() -> (tempfile::TempDir, DurableInferenceControl) {
    let directory = tempdir().expect("temporary journal directory");
    let path = directory.path().join("native-recovery.journal");
    let mut control = DurableInferenceControl::open(path, 32).expect("open control");
    control
        .reserve_native(
            NativeRequest {
                request_id: "request.recovery.1".to_string(),
                principal_id: "agent.recovery.1".to_string(),
                worker_generation: 1,
                model: "model.recovery.1".to_string(),
                payload_digest: digest("payload"),
            },
            2,
        )
        .expect("reserve");
    control
        .dispatch_native(
            "request.recovery.1",
            NativeDispatch {
                thread_id: "thread.recovery.1".to_string(),
                model_provider: "provider.recovery.1".to_string(),
                context_digest: digest("context"),
                owner_context_digest: None,
                codex_payload_digest: None,
                codex_request_digest: None,
                app_server_version: None,
                protocol_id: None,
                codex_source_admission_digest: None,
                codex_home_digest: None,
                codex_connection_id: None,
                codex_session_id: None,
                codex_deadline_ms: None,
                codex_authority_epoch: None,
                codex_revocation_revision: None,
                codex_revocation_head_sha256: None,
                codex_authority_witness_sha256: None,
            },
        )
        .expect("dispatch");
    control
        .native_started(
            "request.recovery.1",
            "turn.provisional.1".to_string(),
        )
        .expect("started");
    (directory, control)
}

#[test]
fn policy_rejects_unbounded_reconcile_windows() {
    assert!(NativeRecoveryPolicy::new(Duration::from_millis(9)).is_err());
    assert!(NativeRecoveryPolicy::new(Duration::from_secs(31)).is_err());
    assert_eq!(
        NativeRecoveryPolicy::new(Duration::from_millis(250))
            .expect("policy")
            .turn_start_reconcile_grace(),
        Duration::from_millis(250)
    );
}

#[test]
fn operational_counters_preserve_denial_and_interrupt_latency() {
    let counters = NativeRecoveryCounters::default();
    counters.record_authority_denial();
    counters.record_authority_denial();
    counters.record_cancellation_to_interrupt_latency(Duration::from_micros(17));
    counters.record_cancellation_to_interrupt_latency(Duration::from_micros(29));

    let snapshot = counters.snapshot();
    assert_eq!(snapshot.authority_denials, 2);
    assert_eq!(snapshot.interrupt_latency_samples, 2);
    assert_eq!(snapshot.interrupt_latency_micros, 46);
    assert_eq!(snapshot.maximum_interrupt_latency_micros, 29);
}

#[tokio::test]
async fn missing_history_stays_quarantined_until_trusted_terminal_receipt() {
    let (_directory, mut control) = open_dispatched_control();
    let counters = NativeRecoveryCounters::default();
    let unknown = quarantine_missing_history(
        &mut control,
        "request.recovery.1",
        "App Server history unavailable; do not replay",
    )
    .expect("quarantine");
    let output = unknown.observation.expect("indeterminate observation");
    assert_eq!(output.status, NativeRunStatus::Indeterminate);
    assert!(!output.terminal_observed);
    assert_eq!(output.observed_output_tokens, None);

    let settled = reconcile_provider_terminal(
        &mut control,
        "request.recovery.1",
        ProviderTerminalReceipt {
            request_id: "request.recovery.1".to_string(),
            thread_id: "thread.recovery.1".to_string(),
            turn_id: "turn.final.1".to_string(),
            model: "model.recovery.1".to_string(),
            model_provider: "provider.recovery.1".to_string(),
            status: NativeRunStatus::Completed,
            output: "provider output".to_string(),
            observed_output_tokens: None,
            stop_reason: None,
            verifier_witness_digest: digest("trusted-provider-receipt"),
        },
        &PassVerifier,
        &counters,
    )
    .await
    .expect("trusted terminal reconciliation");
    let terminal = settled.observation.expect("terminal observation");
    assert!(terminal.terminal_observed);
    assert_eq!(terminal.status, NativeRunStatus::Completed);
    assert_eq!(terminal.observed_output_tokens, None);
    assert!(!terminal.succeeded());
    assert!(terminal.stop_reason.is_some());

    let snapshot = NativeRecoverySnapshot::observe(
        &control,
        10_000,
        &BTreeMap::new(),
        &counters,
    );
    assert_eq!(snapshot.total_records, 1);
    assert_eq!(snapshot.held_reservations, 0);
    assert_eq!(snapshot.indeterminate_count, 0);
    assert_eq!(snapshot.terminal_without_usage_count, 1);
    assert_eq!(snapshot.counters.provider_receipt_successes, 1);
}

#[tokio::test]
async fn provider_receipt_must_match_exact_durable_dispatch() {
    let (_directory, mut control) = open_dispatched_control();
    let counters = NativeRecoveryCounters::default();
    let error = reconcile_provider_terminal(
        &mut control,
        "request.recovery.1",
        ProviderTerminalReceipt {
            request_id: "request.recovery.1".to_string(),
            thread_id: "thread.other".to_string(),
            turn_id: "turn.final.1".to_string(),
            model: "model.recovery.1".to_string(),
            model_provider: "provider.recovery.1".to_string(),
            status: NativeRunStatus::Failed,
            output: String::new(),
            observed_output_tokens: Some(0),
            stop_reason: Some("provider failure".to_string()),
            verifier_witness_digest: digest("trusted-provider-receipt"),
        },
        &PassVerifier,
        &counters,
    )
    .await
    .expect_err("thread drift must fail");
    assert_eq!(error, NativeRecoveryError::BindingMismatch);
    assert_eq!(counters.snapshot().provider_receipt_successes, 0);
}
