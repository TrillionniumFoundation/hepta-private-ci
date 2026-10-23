//! Embedding-only durable observation after genuine graceful shutdown.

use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;

use codex_protocol::ThreadId;
use codex_queue_extension::QueueHistoricalObserver;
use codex_thread_store::QueueStore;
use codex_thread_store::ThreadStoreError;

use crate::AppServerDrainHandle;

pub(crate) async fn join_thread_background_tasks(tasks: &tokio_util::task::TaskTracker) -> bool {
    tasks.close();
    if tokio::time::timeout(std::time::Duration::from_secs(10), tasks.wait())
        .await
        .is_err()
    {
        tracing::warn!("timed out waiting for background tasks; graceful drain is incomplete");
        return false;
    }
    true
}

pub use codex_queue_extension::QueueHistoricalObservation;
pub use codex_queue_extension::QueueHistoricalOutcome;
pub use codex_queue_extension::QueueHistoricalTerminal;

pub(crate) struct HistoricalObservationOwner {
    codex_home: PathBuf,
    state_db: codex_rollout::StateDbHandle,
    queue: QueueHistoricalObserver,
}

impl AppServerDrainHandle {
    pub(crate) fn bind_historical_owner(
        &self,
        codex_home: PathBuf,
        state_db: codex_rollout::StateDbHandle,
        queue: Arc<dyn QueueStore>,
    ) {
        assert!(
            self.historical_owner
                .set(HistoricalObservationOwner {
                    codex_home,
                    state_db,
                    queue: QueueHistoricalObserver::new(queue),
                })
                .is_ok(),
            "a drain handle belongs to exactly one App Server lifetime"
        );
    }

    /// True only after the original server has closed admission and joined
    /// request/thread-start tasks and thread writers. No transport is reopened.
    pub fn historical_observation_ready(&self) -> bool {
        self.request.is_cancelled() && self.drained() && self.historical_owner.get().is_some()
    }

    /// Read the original owner's exact durable submission and explicit
    /// terminal evidence. This API cannot create, resume, or dispatch work.
    pub async fn observe_exact_submission(
        &self,
        expected_codex_home: &Path,
        thread_id: &str,
        client_user_message_id: &str,
        expected_payload_sha256: &str,
    ) -> Result<QueueHistoricalObservation, ThreadStoreError> {
        if !self.historical_observation_ready() {
            return Err(ThreadStoreError::Unsupported {
                operation: "historical_observation_before_drain",
            });
        }
        let owner = self
            .historical_owner
            .get()
            .ok_or(ThreadStoreError::Unsupported {
                operation: "historical_observation_without_owner",
            })?;
        if owner.codex_home != expected_codex_home {
            return Err(ThreadStoreError::Conflict {
                message: "historical observer home differs from the owning Agent home".to_string(),
            });
        }
        let thread_id =
            ThreadId::from_string(thread_id).map_err(|error| ThreadStoreError::InvalidRequest {
                message: format!("invalid historical thread identity: {error}"),
            })?;
        // Select the original owner's current rollout pointer. General
        // ThreadStore reads can perform metadata repair; historical authority
        // never guesses another rollout when this SELECT has no row.
        let metadata = owner
            .state_db
            .get_thread(thread_id)
            .await
            .map_err(|error| ThreadStoreError::Internal {
                message: format!("read selected historical metadata: {error}"),
            })?;
        let observed = owner
            .queue
            .observe(
                thread_id,
                metadata
                    .as_ref()
                    .map(|metadata| metadata.rollout_path.as_path()),
                client_user_message_id,
                expected_payload_sha256,
            )
            .await
            .map_err(|error| ThreadStoreError::Internal {
                message: format!("exact historical observation failed: {error}"),
            })?;
        let current_metadata = owner
            .state_db
            .get_thread(thread_id)
            .await
            .map_err(|error| ThreadStoreError::Internal {
                message: format!("revalidate selected historical metadata: {error}"),
            })?;
        if metadata
            .as_ref()
            .map(|row| (&row.rollout_path, row.history_mode))
            != current_metadata
                .as_ref()
                .map(|row| (&row.rollout_path, row.history_mode))
        {
            return Err(ThreadStoreError::Conflict {
                message: "selected historical rollout changed during observation".to_string(),
            });
        }
        Ok(observed)
    }
}

#[cfg(test)]
#[path = "historical_observation_tests.rs"]
mod tests;
