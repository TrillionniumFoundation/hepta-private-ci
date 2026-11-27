use super::DurableInferenceControl;
use super::Error;
use super::InferenceRequest;
use super::PhaseMetricEventV1;
use super::PhaseMetricSinkV1;
use super::RequestRecord;
use super::RequestState;
use codex_hepta_types::PhaseMetricSinkErrorV1;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

#[derive(Debug)]
struct PanicOnceMetrics {
    armed: AtomicBool,
}

impl PhaseMetricSinkV1 for PanicOnceMetrics {
    fn record(&self, _event: PhaseMetricEventV1) -> Result<(), PhaseMetricSinkErrorV1> {
        if self.armed.swap(/*val*/ false, Ordering::AcqRel) {
            panic!("injected metrics callback panic after durable append");
        }
        Ok(())
    }

    fn healthy(&self) -> bool {
        true
    }

    fn flush(&self) -> Result<(), PhaseMetricSinkErrorV1> {
        Ok(())
    }
}

#[test]
fn metrics_panic_fences_the_original_writer_until_cold_replay()
-> Result<(), Box<dyn std::error::Error>> {
    let nonce = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)?
        .as_nanos();
    let path = std::env::temp_dir().join(format!(
        "hepta-control-metric-panic-{}-{nonce}",
        std::process::id()
    ));
    let request = InferenceRequest {
        request_id: "metric-panic-request".to_owned(),
        principal_id: "metric-panic-principal".to_owned(),
        model_digest: "1".repeat(64),
        payload_digest: "2".repeat(64),
        semantic_digest: "3".repeat(64),
        maximum_tokens: 16,
        deadline_ms: 1000,
    };
    let expected = RequestRecord {
        request: request.clone(),
        revision: 1,
        state: RequestState::Pending,
        reservation: None,
        assignment: None,
        terminal_observation_digest: None,
        consumed_tokens: 0,
        usage_units: 0,
    };
    let mut owner = DurableInferenceControl::open(&path, /*capacity*/ 8)?.with_metrics_sink(
        Arc::new(PanicOnceMetrics {
            armed: AtomicBool::new(/*v*/ true),
        }),
    );
    let observed = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        owner.submit(/*now_ms*/ 100, request.clone())
    }));
    assert!(observed.is_err());
    assert!(owner.get(&request.request_id).is_none());
    let committed_length = owner.file.metadata()?.len();
    assert!(committed_length > 0);

    // The sink now returns success. Only the retained writer fence can keep
    // this same request from appending a duplicate durable submission.
    assert!(matches!(
        owner.submit(/*now_ms*/ 100, request.clone()),
        Err(Error::WriterUnavailable)
    ));
    assert!(owner.file.metadata()?.len() == committed_length);
    assert!(!owner.production_metrics_ready());
    assert!(!owner.flush_production_metrics());
    drop(owner);

    let committed_bytes = std::fs::read(&path)?;
    let recovered = DurableInferenceControl::open(&path, /*capacity*/ 8)?;
    assert!(recovered.get(&request.request_id) == Some(&expected));
    drop(recovered);
    assert!(std::fs::read(&path)? == committed_bytes);
    std::fs::remove_file(path)?;
    Ok(())
}
