//! Synchronization only: a test notification is not a Source completion or an
//! authorization grant. The production observer performs actual owner reads.

use super::*;
use std::sync::{Arc, Barrier};
use std::time::Duration;

#[test]
fn original_source_hint_latches_without_renewing_the_original_deadline() -> anyhow::Result<()> {
    let hint = Arc::new(Hint::new());
    let start = Arc::new(Barrier::new(2));
    let other_hint = Arc::clone(&hint);
    let other_start = Arc::clone(&start);
    let worker = std::thread::spawn(move || {
        other_start.wait();
        other_hint.observed()
    });
    let end = Instant::now() + Duration::from_millis(500);
    start.wait();
    let result = hint.wait_original(end);
    let joined = worker.join().map_err(|_| anyhow::anyhow!("hint notifier panicked"));
    result?;
    joined??;
    // A notification retained before the next wait is not lost, and neither
    // an already latched notification nor an empty latch can renew the end.
    hint.wait_original(end)?;
    let expired = Instant::now();
    let unopened = Hint::new();
    for original in [hint.as_ref(), &unopened] {
        match original.wait_original(expired) {
            Err(AgentdError::Invalid(message)) if message == "the original Source startup expired" => {},
            Err(error) => anyhow::bail!("unrelated readiness error: {error}"),
            Ok(_) => anyhow::bail!("a retained hint renewed an expired startup"),
        }
    }
    Ok(())
}
