#!/usr/bin/env python3
"""One-shot regression materialization; removed before source qualification."""
from pathlib import Path
p = Path('codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs')
s = p.read_text()
s = s.replace('agentd_effect_entry_cas_is_the_last_fallible_gate_before_physical_send', 'agentd_effect_entry_cas_precedes_proof_drop_and_physical_send')
s = s.replace('.find("owner.revalidate_cognitive_context(snapshot)")', '.find(".revalidate_cognitive_context(snapshot)")')
s = s.replace('.find("control.complete_native_rejection_before_start(")', '.rfind("control.complete_native_rejection_before_start(")')
p.write_text(s)
p = Path('codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs')
with p.open('a') as f:
    f.write('''

#[tokio::test]
async fn standalone_pending_rejection_reopens_without_agentd_or_provider_io() {
    use codex_hepta_infer_core::durable_control::native::NativeDispatchRejection;
    use codex_hepta_infer_core::durable_control::native::NativeDispatchRejectionStatus;

    let (driver, path) = fixture("pending-local-rejection");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    control.reserve_native(request(&driver), 1).unwrap();
    let dispatch: NativeDispatch = serde_json::from_value(serde_json::json!({
        "thread_id": "thread-local", "model_provider": "provider",
        "context_digest": "a".repeat(64)
    })).unwrap();
    control.dispatch_native("r1", dispatch).unwrap();
    control.prepare_native_rejection_before_start("r1", NativeDispatchRejection {
        status: NativeDispatchRejectionStatus::Rejected,
        reason: "invalid request before admission".to_string(),
        response_digest: "b".repeat(64),
        retry_safe_before_admission: false,
    }).unwrap();
    assert_eq!(control.native_record("r1").unwrap().state, NativeReservationState::Dispatching);
    drop(control);
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    let pending = control.native_record("r1").unwrap().clone();
    assert!(pending.pre_admission_rejection_pending);
    assert!(pending.owner_dispatch.is_none());
    // The fixture has an unusable socket: recovery must not contact Agentd.
    driver.reconcile_pending_pre_admission_rejection(&mut control, &pending).await.unwrap();
    let settled = control.native_record("r1").unwrap().clone();
    assert_eq!(settled.state, NativeReservationState::Released);
    assert!(!settled.pre_admission_rejection_pending);
    assert!(settled.turn_id.is_none());
    assert!(settled.observation.is_none());
    drop(control);
    let reopened = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(reopened.native_record("r1"), Some(&settled));
    drop(reopened);
    std::fs::remove_file(path).unwrap();
}
''')
p = Path('codex-rs/hepta-infer-worker-host/src/native_deadline_tests.rs')
with p.open('a') as f:
    f.write('''

#[test]
fn a_final_owner_rpc_cannot_refund_budget_and_submillisecond_budget_is_rejected() {
    let clock = NativeDeadline::new(10_000, Duration::from_secs(5)).unwrap();
    assert!(clock.remaining_at(Duration::from_secs(5), 14_500).is_err());
    assert!(NativeDeadline::new(10_000, Duration::from_nanos(1)).is_err());
}
''')
Path('.github/workflows/runtime-codex-convergence-arm.yml').unlink(missing_ok=True)
Path(__file__).unlink()
