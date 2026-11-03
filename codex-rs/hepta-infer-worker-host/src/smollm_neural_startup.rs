//! Preserve the caller's original startup execution across Cell and model loading.

use std::time::Duration;
use tokio_util::sync::CancellationToken;

/// One original startup window, including Cell verification when selected.
/// Keeping the token and execution together prevents a loader from restarting
/// the clock or using a different cancellation owner after material scanning.
pub(crate) struct SmolLmStartupExecutionV1 {
    pub(super) execution: codex_hepta_agentd::NeuralCognitiveExecutionV1,
    pub(super) cancellation: CancellationToken,
}

impl SmolLmStartupExecutionV1 {
    pub(crate) fn new(cancellation: CancellationToken) -> Self {
        Self {
            execution: codex_hepta_agentd::NeuralCognitiveExecutionV1::with_deadline(
                std::time::Instant::now() + Duration::from_secs(120),
                cancellation.clone(),
            ),
            cancellation,
        }
    }

    pub(crate) fn execution(&self) -> &codex_hepta_agentd::NeuralCognitiveExecutionV1 {
        &self.execution
    }
}
