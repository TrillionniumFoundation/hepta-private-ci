//! Budgeted cache integrity maintenance; federation grants and results remain
//! freshly resolved by their original owners on every actual read.
use super::*;
const BUDGET: Duration = Duration::from_secs(5);
const INTERVAL: Duration = Duration::from_secs(60);

pub(super) async fn maintain_once(
    state: &AgentdState,
    runtime: &CognitiveRuntime,
) -> Result<(), AgentdError> {
    state.refresh_generation()?;
    if let Err(error) = runtime.maintain_federation_integrity(BUDGET).await {
        // Integrity failures quarantine the affected reader. Contention may
        // defer maintenance; stale sources expire at the memory read boundary.
        tracing::warn!(error = %error, "cognitive federation integrity maintenance deferred or isolated a peer");
    }
    state.refresh_generation()?;
    Ok(())
}

pub(super) async fn run(
    state: Arc<AgentdState>,
    runtime: CognitiveRuntime,
    cancellation: CancellationToken,
) -> Result<(), AgentdError> {
    let mut interval = tokio::time::interval_at(Instant::now() + INTERVAL, INTERVAL);
    interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    loop {
        tokio::select! {
            _ = cancellation.cancelled() => return Ok(()),
            _ = interval.tick() => {}
        }
        // Do not abandon an in-progress physical owner future on cancellation.
        // Its own five-second budget and RuntimeTasks retirement bound apply.
        maintain_once(&state, &runtime).await?;
        if cancellation.is_cancelled() {
            return Ok(());
        }
    }
}
