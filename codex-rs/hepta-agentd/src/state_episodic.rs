//! Generation-fenced dispatch for the configured episodic owner.
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_agent_protocol::EpisodicSnapshotImportResult;
use codex_hepta_agent_protocol::MAX_EPISODIC_SNAPSHOT_IMPORT_BYTES;
use codex_hepta_memory::ProductionCognitiveMutationError;

use crate::AgentdError;
use crate::AgentdPayload;

use super::AgentdState;
use super::control::require_cognitive_control_ready;
use super::poisoned_state;

// A timed-out control connection must not leave an unbounded detached queue.
const MAX_PENDING_IMPORTS: usize = 32;

struct AdmittedImport {
    pending: Arc<AtomicUsize>,
    unresolved: Arc<AtomicBool>,
    settled: bool,
}

impl Drop for AdmittedImport {
    fn drop(&mut self) {
        if !self.settled {
            // Publish uncertainty before releasing the final pending reference.
            // This also covers a panic or a task cancelled by runtime shutdown.
            self.unresolved.store(true, Ordering::Release);
        }
        self.pending.fetch_sub(1, Ordering::AcqRel);
    }
}

fn settlement_unknown(result: &Result<EpisodicSnapshotImportResult, AgentdError>) -> bool {
    matches!(
        result,
        Err(AgentdError::ProductionCognitiveMutation(
            ProductionCognitiveMutationError::TransactionSettlementUnknown { .. }
        ))
    )
}

impl AgentdState {
    pub(crate) fn episodic_import_pending_count(&self) -> usize {
        self.episodic_imports.load(Ordering::Acquire)
    }

    pub(super) fn episodic_import_drain_clear(&self) -> bool {
        // Acquire the decrement before inspecting its preceding unresolved flag.
        self.episodic_import_pending_count() == 0
            && !self.episodic_import_unresolved.load(Ordering::Acquire)
    }

    pub(crate) async fn import_episodic_snapshot(
        &self,
        snapshot_json: &str,
    ) -> Result<AgentdPayload, AgentdError> {
        if snapshot_json.len() > MAX_EPISODIC_SNAPSHOT_IMPORT_BYTES {
            return Err(AgentdError::Invalid(
                "episodic control input exceeds 20 KiB".into(),
            ));
        }
        let ingress = Arc::clone(
            self.episodic_snapshot_import
                .get()
                .ok_or(AgentdError::CognitiveWriteRuntimeUnavailable)?,
        );
        let snapshot_json = snapshot_json.to_owned();
        self.refresh_generation()?;
        let admitted = {
            let runtime = self.runtime.lock().map_err(poisoned_state)?;
            require_cognitive_control_ready(
                runtime.lifecycle,
                runtime.app_server_ready,
                runtime.critical_stores_ready,
                runtime.revocation_ready,
                runtime.required_ports_ready,
                runtime.admission_open,
                runtime.fenced,
            )?;
            if self.episodic_import_unresolved.load(Ordering::Acquire) {
                return Err(AgentdError::GenerationFenced(
                    "episodic owner requires original transaction recovery".into(),
                ));
            }
            self.episodic_imports
                .fetch_update(Ordering::AcqRel, Ordering::Acquire, |count| {
                    if count < MAX_PENDING_IMPORTS {
                        Some(count + 1)
                    } else {
                        None
                    }
                })
                .map_err(|_| AgentdError::Overloaded { retry_after_ms: 50 })?;
            AdmittedImport {
                pending: Arc::clone(&self.episodic_imports),
                unresolved: Arc::clone(&self.episodic_import_unresolved),
                settled: false,
            }
        };
        // A control timeout drops only this JoinHandle. The original owner and
        // guard remain alive through an acknowledged commit or rollback.
        let owner = tokio::spawn(async move {
            let mut admitted = admitted;
            let result = ingress.import(&snapshot_json, &admitted.unresolved).await;
            admitted.settled = !settlement_unknown(&result);
            result
        });
        let result = match owner.await {
            Ok(result) => result,
            Err(error) => {
                self.mark_fenced();
                return Err(AgentdError::GenerationFenced(format!(
                    "episodic owner task did not settle: {error}"
                )));
            }
        };
        if settlement_unknown(&result) {
            self.mark_fenced();
            return result.map(AgentdPayload::EpisodicSnapshotImported);
        }
        // A commit may have succeeded before this fence changed. The caller
        // reconciles through identical input; never invent a second source event.
        self.refresh_generation()?;
        {
            let runtime = self.runtime.lock().map_err(poisoned_state)?;
            require_cognitive_control_ready(
                runtime.lifecycle,
                runtime.app_server_ready,
                runtime.critical_stores_ready,
                runtime.revocation_ready,
                runtime.required_ports_ready,
                runtime.admission_open,
                runtime.fenced,
            )?;
        }
        result.map(AgentdPayload::EpisodicSnapshotImported)
    }
}
