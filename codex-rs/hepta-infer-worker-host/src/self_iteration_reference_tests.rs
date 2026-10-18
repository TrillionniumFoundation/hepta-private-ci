use super::*;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;

fn observation() -> Result<NativeReferenceObservationV1, Box<dyn std::error::Error>> {
    let directory = tempfile::tempdir()?;
    let mut control = DurableInferenceControl::open(
        directory.path().join("native.journal"),
        /*capacity*/ 8,
    )?;
    let output = super::super::tests::settle_fixture(&mut control);
    let record = control.native_record_resolved("assessment-1")?;
    Ok(NativeReferenceObservationV1 {
        native_request_id: "assessment-1".into(),
        prompt_digest: Digest32::of_bytes(b"prompt").to_string(),
        original_deadline_ms: 10_000,
        replayed: false,
        fresh_execution_latency_us: Some(400),
        attempt_elapsed_us: 400,
        attempt_started_at_ms: 1_000,
        attempt_finished_at_ms: 1_001,
        native_receipt_digest: record_digest(record.as_ref())?,
        native_record: record,
        native_output: Some(output),
        diagnostic: None,
        succeeded: true,
    })
}
#[test]
fn reference_replay_never_establishes_original_execution_cost()
-> Result<(), Box<dyn std::error::Error>> {
    let mut value = observation()?;
    value.validate()?;
    value.replayed = true;
    assert!(
        value.validate().is_err(),
        "cached attempt cannot retain a fresh-cost claim"
    );
    value.fresh_execution_latency_us = None;
    value.attempt_elapsed_us = 7;
    value.validate()?;
    assert_eq!(value.fresh_execution_latency_us, None);
    Ok(())
}
#[test]
fn reference_terminal_receipt_rejects_changed_output_record_or_success()
-> Result<(), Box<dyn std::error::Error>> {
    let original = observation()?;
    let mut value = original.clone();
    if let Some(output) = &mut value.native_output {
        output.output = "other response".into();
    }
    assert!(value.validate().is_err());
    let mut value = original.clone();
    if let Some(record) = &mut value.native_record {
        record.request.payload_digest = "d".repeat(64);
    }
    assert!(value.validate().is_err());
    let mut value = original;
    value.succeeded = false;
    value.fresh_execution_latency_us = None;
    assert!(value.validate().is_err());
    Ok(())
}
