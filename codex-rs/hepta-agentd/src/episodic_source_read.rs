//! Currentness for the explicit CognitiveContext/NativeAppServer path only.
//! Automatic memory attachments and recall tools require separate binding.
//! This is a source-read linearization check, not an external-effect lease.

use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::EpisodicImportReceipt;
use codex_hepta_memory::EpisodicSnapshotAdmission;
use codex_hepta_memory::ProductionWriterError;

use crate::AgentdError;

use super::EpisodicImportIngress;

const MAX_SOURCE_ERROR_CHARACTERS: usize = 512;

#[derive(Default)]
pub(crate) struct EpisodicSourceReads {
    current: Mutex<Option<Arc<CommittedSource>>>,
}

struct CommittedSource {
    snapshot_json: String,
    admission: EpisodicSnapshotAdmission,
    receipt: EpisodicImportReceipt,
}

pub(crate) struct EpisodicSourceRead {
    ingress: Arc<EpisodicImportIngress>,
    observation: Arc<CommittedSource>,
}

impl EpisodicSourceReads {
    pub(super) fn publish(
        &self,
        snapshot_json: String,
        admission: EpisodicSnapshotAdmission,
        receipt: EpisodicImportReceipt,
    ) -> Result<(), AgentdError> {
        // Only the retained owner task calls this after acknowledged commit.
        // No lock is held while verifying a source or awaiting SQLite.
        let next = Arc::new(CommittedSource {
            snapshot_json,
            admission,
            receipt,
        });
        let mut current = self
            .current
            .lock()
            .map_err(|_| unavailable("observation lock poisoned"))?;
        if let Some(previous) = current.as_ref() {
            if previous.receipt.owner_agent_id != next.receipt.owner_agent_id
                || previous.receipt.scope_binding != next.receipt.scope_binding
                || previous.receipt.authority_id != next.receipt.authority_id
                || previous.receipt.namespace != next.receipt.namespace
            {
                return Err(unavailable("committed source identity changed"));
            }
            if next.receipt.generation < previous.receipt.generation {
                // An older acknowledged task may finish after a newer import.
                return Ok(());
            }
            if next.receipt.generation == previous.receipt.generation {
                if next.receipt != previous.receipt || next.admission != previous.admission {
                    return Err(unavailable(
                        "same generation has another committed observation",
                    ));
                }
                if next.snapshot_json == previous.snapshot_json {
                    // An identical reconciliation must not invalidate live readers.
                    return Ok(());
                }
            }
        }
        *current = Some(next);
        Ok(())
    }
}

impl EpisodicImportIngress {
    pub(crate) fn source_read(self: &Arc<Self>) -> Result<EpisodicSourceRead, AgentdError> {
        let observation = self
            .source_reads
            .current
            .lock()
            .map_err(|_| unavailable("observation lock poisoned"))?
            .clone()
            .ok_or_else(|| unavailable("current snapshot must be reconciled after startup"))?;
        let read = EpisodicSourceRead {
            ingress: Arc::clone(self),
            observation,
        };
        read.revalidate()?;
        Ok(read)
    }
}

impl EpisodicSourceRead {
    fn require_current(&self) -> Result<(), AgentdError> {
        let current = self
            .ingress
            .source_reads
            .current
            .lock()
            .map_err(|_| unavailable("observation lock poisoned"))?;
        if current
            .as_ref()
            .is_none_or(|current| !Arc::ptr_eq(current, &self.observation))
        {
            return Err(unavailable(
                "committed observation changed during context read",
            ));
        }
        Ok(())
    }

    pub(crate) async fn revalidate_native(&self) -> Result<(), AgentdError> {
        self.require_current()?;
        let access =
            CognitiveAccess::agent_private(self.ingress.writer.writer().owner_agent_id().clone());
        self.ingress
            .writer
            .revalidate_episodic_receipt(
                &access,
                &CognitiveScope::AgentPrivate,
                &self.observation.receipt,
            )
            .await?;
        self.require_current()
    }

    pub(crate) fn revalidate(&self) -> Result<(), AgentdError> {
        self.require_current()?;
        let admission = self
            .ingress
            .verifier
            .verify_current(&self.observation.snapshot_json)
            .map_err(unavailable)?;
        if admission != self.observation.admission {
            return Err(unavailable(
                "source bytes, metadata or verification changed",
            ));
        }
        self.require_current()
    }
}

fn unavailable(reason: impl AsRef<str>) -> AgentdError {
    let reason: String = reason
        .as_ref()
        .chars()
        .take(MAX_SOURCE_ERROR_CHARACTERS)
        .collect();
    ProductionWriterError::AuthorityRejected(format!("episodic source read unavailable: {reason}"))
        .into()
}

#[cfg(test)]
#[path = "episodic_source_read_tests.rs"]
mod tests;
