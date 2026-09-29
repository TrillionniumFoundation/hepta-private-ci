use super::*;

#[test]
fn rejected_and_abandoned_final_use_attempts_are_counted() {
    let before = cognitive_context_metrics::snapshot();
    {
        let _unfinished = OperationObservation::start(Phase::FinalUse);
    }
    let after = cognitive_context_metrics::snapshot();
    assert!(after.revalidation_failures > before.revalidation_failures);
}

#[test]
fn failed_read_attempts_contribute_to_latency_and_request_count() {
    let before = cognitive_context_metrics::snapshot();
    {
        let _unfinished = OperationObservation::start(Phase::Read);
        std::thread::sleep(std::time::Duration::from_millis(1));
    }
    let after = cognitive_context_metrics::snapshot();
    assert!(after.requests > before.requests);
    assert!(after.latency_micros > before.latency_micros);
}

#[tokio::test]
async fn dropping_a_polled_pending_final_use_future_records_failure() {
    let before = cognitive_context_metrics::snapshot();
    let attempt = async {
        let _unfinished = OperationObservation::start(Phase::FinalUse);
        std::future::pending::<()>().await;
    };
    assert!(tokio::time::timeout(std::time::Duration::from_millis(1), attempt).await.is_err());
    assert!(cognitive_context_metrics::snapshot().revalidation_failures > before.revalidation_failures);
}
