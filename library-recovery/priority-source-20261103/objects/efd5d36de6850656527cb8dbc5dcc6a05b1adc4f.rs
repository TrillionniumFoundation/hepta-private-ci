use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use super::*;

struct ObservationGuard(Arc<AtomicBool>);

impl Drop for ObservationGuard {
    fn drop(&mut self) {
        self.0.store(true, Ordering::Release);
    }
}

#[tokio::test]
async fn stalled_observation_times_out_and_releases_inflight_future()
-> Result<(), Box<dyn std::error::Error>> {
    let released = Arc::new(AtomicBool::new(false));
    let guard = ObservationGuard(Arc::clone(&released));
    let result = tokio::time::timeout(
        RECOVERY_OBSERVATION_TIMEOUT + Duration::from_secs(1),
        bounded_observation(async move {
            let _guard = guard;
            std::future::pending::<Result<(), AgentdError>>().await
        }),
    )
    .await?;
    assert!(result?.is_none());
    assert!(released.load(Ordering::Acquire));
    assert_eq!(bounded_observation(async { Ok(42) }).await?, Some(42));
    Ok(())
}

#[tokio::test]
async fn observation_protocol_and_generation_failures_are_not_timeouts() {
    let malformed = bounded_observation::<()>(async {
        Err(AgentdError::Protocol("mismatched durable identity".to_string()))
    })
    .await;
    assert!(matches!(malformed, Err(AgentdError::Protocol(_))));
    let fenced = bounded_observation::<()>(async {
        Err(AgentdError::GenerationFenced("retired owner".to_string()))
    })
    .await;
    assert!(matches!(fenced, Err(AgentdError::GenerationFenced(_))));
}
