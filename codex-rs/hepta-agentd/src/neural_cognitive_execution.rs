//! A caller-owned execution window, never an authorization or receipt.

use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;
use tokio_util::sync::CancellationToken;

/// The original caller's monotonic deadline and cancellation survive executor
/// queueing. Cloning this value never starts another window or creates a grant.
#[derive(Clone)]
pub struct NeuralCognitiveExecutionV1 {
    deadline: Instant,
    cancellation: CancellationToken,
    pub(crate) observations: Arc<Mutex<Option<crate::cognitive_execution::ReadObservationV1>>>,
}

impl NeuralCognitiveExecutionV1 {
    pub fn with_deadline(deadline: Instant, cancellation: CancellationToken) -> Self {
        Self {
            deadline,
            cancellation,
            observations: Arc::new(Mutex::new(None)),
        }
    }

    /// Explicit window for a direct controlled/evaluation read, outside the
    /// control connection. Product connections always pass their original one.
    pub fn bounded_read() -> Self {
        Self::with_deadline(
            Instant::now() + Duration::from_secs(2),
            CancellationToken::new(),
        )
    }

    pub fn deadline(&self) -> Instant {
        self.deadline
    }

    pub fn remaining(&self) -> Result<Duration, String> {
        if self.cancellation.is_cancelled() {
            return Err("neural read execution cancelled".to_owned());
        }
        self.deadline
            .checked_duration_since(Instant::now())
            .filter(|remaining| !remaining.is_zero())
            .ok_or_else(|| "neural read execution deadline".to_owned())
    }

    pub fn check(&self) -> Result<(), String> {
        self.remaining().map(|_| ())
    }

    pub async fn cancelled(&self) {
        self.cancellation.cancelled().await
    }
}
