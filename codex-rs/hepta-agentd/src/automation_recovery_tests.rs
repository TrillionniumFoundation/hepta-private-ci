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
async fn stalled_observation_times_out_and_releases_inflight_future() {
    let released = Arc::new(AtomicBool::new(false));
    let guard = ObservationGuard(Arc::clone(&released));
    let result = tokio::time::timeout(
        RECOVERY_OBSERVATION_TIMEOUT + Duration::from_secs(1),
        bounded_observation(async move {
            let _guard = guard;
            std::future::pending::<Result<(), AgentdError>>().await
        }),
    )
    .await
    .expect("recovery must have its own finite deadline");
    assert!(matches!(result, Err(AgentdError::Protocol(_))));
    assert!(released.load(Ordering::Acquire));
    assert_eq!(bounded_observation(async { Ok(42) }).await.unwrap(), 42);
}
