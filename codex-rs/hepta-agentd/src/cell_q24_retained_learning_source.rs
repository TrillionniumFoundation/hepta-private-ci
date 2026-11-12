//! Retain one actual completed source across runtime assembly. This read side
//! never dispatches a task, signs, repairs a witness or appends to the Ledger.
//! Its outbox remains in the original AutomationStore; no history is imported.

use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::CircuitCommittedTraceV2;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationRequestV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;

use super::*;
use crate::AgentdError;
use crate::CellQ24PreparedLearningV1;

/// Original source and database capabilities, not a serialized recovery token.
/// A cold host must reacquire the actual owners; absence never opens a retired
/// task writer or changes its original process identity.
pub struct OriginalCellQ24RetainedLearningSourceV1 {
    producer: Arc<OriginalCellQ24TaskLedgerProducerV1>,
    prepared: Arc<CellQ24PreparedLearningV1>,
    captured: Captured,
    decision: LedgerRecord,
    outcome: LedgerRecord,
    store: AutomationStore,
    database: File,
    trace: CircuitCommittedTraceV2,
    fenced: AtomicBool,
}

/// Created only after the real scoped Root bootstrap joins its exact Prepared.
pub(crate) struct RegisteredCellQ24RetainedSourceV1 {
    source: OriginalCellQ24RetainedLearningSourceV1,
    consumer: AgentdIdentity,
}

/// A read observation tied to one actual registered source and witnessed cut.
pub struct OriginalCellQ24RetainedLearningReadyV1 {
    registered: Arc<RegisteredCellQ24RetainedSourceV1>,
    cut: (Digest32, usize),
}

impl OriginalCellQ24TaskLedgerProducerV1 {
    /// Retain the original task's existing database, never the successor's.
    pub async fn retained_learning_source(
        self: &Arc<Self>,
        prepared: Arc<CellQ24PreparedLearningV1>,
        store: AutomationStore,
    ) -> Result<OriginalCellQ24RetainedLearningSourceV1, AgentdError> {
        prepared
            .require_original_task_ledger(&self.ledger)
            .map_err(refused)?;
        if store.owner_agent_id() != &self.identity.agent_id
            || store.path().parent() != Some(self.identity.layout.automation_root())
        {
            return Err(refused(
                "retained source requires its original Automation owner",
            ));
        }
        let (captured, decision, outcome) = {
            let mut state = self.state.lock().map_err(refused)?;
            let captured = self.capture(&mut state).map_err(ledger_error)?;
            let ledger = self.ledger.lock().map_err(refused)?;
            let OriginalCellQ24TaskLedgerStatusV1::Complete { decision, outcome } = self
                .status(&mut state, &ledger, &captured)
                .map_err(ledger_error)?
            else {
                return Err(refused("retained source has no accepted Terminal outcome"));
            };
            (captured, decision, outcome)
        };
        let request = &prepared.initial().request;
        let facts = prepared.read_validated_facts().map_err(refused)?;
        let experience = LearningIterationObservationV1::Experience {
            episode_digest: captured.publication.publication_digest(),
            completed_task_receipt: request.completed_task_receipt,
        };
        if request.source_run_id != captured.publication.original_record().snapshot.run_id
            || request.agent_id.as_str() != self.identity.agent_id.as_str()
            || facts.experience() != &experience
            || !prepared
                .frozen_dataset()
                .snapshot
                .records()
                .contains(&decision)
            || !prepared
                .frozen_dataset()
                .snapshot
                .records()
                .contains(&outcome)
        {
            return Err(refused(
                "retained producer differs from the original Prepared source",
            ));
        }
        let database = std::fs::OpenOptions::new()
            .read(/*read*/ true)
            .custom_flags(libc::O_NOFOLLOW)
            .open(store.path())?;
        let trace = store
            .bounded_circuit_committed_trace(request.source_run_id.as_str())
            .await
            .map_err(refused)?
            .ok_or_else(|| refused("original committed trace is missing"))?;
        if trace.run().run_id() != request.source_run_id.as_str()
            || trace.history_digest() != captured.publication.history_digest()
            || trace.history_digest().as_str() != request.completed_task_receipt.to_string()
            || trace.run().outcome().is_none()
            || trace.run().unresolved() != 0
        {
            return Err(refused(
                "original committed trace differs from the sealed task",
            ));
        }
        // Share the same original journal/witness, Ledger and source reader.
        // Do not retain the retired Cell/GenV2 writer locks in this read side.
        let producer = Arc::new(OriginalCellQ24TaskLedgerProducerV1 {
            state: Arc::clone(&self.state),
            ledger: Arc::clone(&self.ledger),
            source: Arc::clone(&self.source),
            task: OriginalTaskCustodyV1::Retained,
            identity: self.identity.clone(),
            config: self.config.clone(),
            decision_key: self.decision_key.clone(),
            outcome_key: self.outcome_key.clone(),
            ledger_binding: self.ledger_binding,
            trust_digest: self.trust_digest,
        });
        let source = OriginalCellQ24RetainedLearningSourceV1 {
            producer,
            prepared,
            captured,
            decision,
            outcome,
            store,
            database,
            trace,
            fenced: AtomicBool::new(/*value*/ false),
        };
        source.read_original().await?;
        Ok(source)
    }
}

impl OriginalCellQ24RetainedLearningSourceV1 {
    /// Read the same private Prepared/source pair at the live phase join.
    /// This performs only the existing original trace/Ledger/file readback.
    pub(crate) async fn require_same_actor_phase_prepared(
        &self,
        prepared: &Arc<CellQ24PreparedLearningV1>,
        identity: &AgentdIdentity,
    ) -> Result<(), AgentdError> {
        if !Arc::ptr_eq(&self.prepared, prepared) || &self.producer.identity != identity {
            return Err(refused(
                "same-actor phase differs from its actual retained source",
            ));
        }
        self.read_original().await?;
        Ok(())
    }

    pub(crate) fn register_original_scope(
        self,
        consumer: AgentdIdentity,
        initial: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
    ) -> Result<Arc<RegisteredCellQ24RetainedSourceV1>, AgentdError> {
        self.prepared
            .require_initial(initial, scope)
            .map_err(refused)?;
        if consumer.agent_id != self.producer.identity.agent_id || consumer.spawn_generation == 0 {
            return Err(refused(
                "retained source consumer differs from its Root scope",
            ));
        }
        Ok(Arc::new(RegisteredCellQ24RetainedSourceV1 {
            source: self,
            consumer,
        }))
    }

    fn read_accepted(&self) -> Result<(Digest32, usize), AgentdError> {
        self.prepared
            .require_original_task_ledger(&self.producer.ledger)
            .map_err(refused)?;
        self.require_database()?;
        let cut = {
            let mut state = self.producer.state.lock().map_err(refused)?;
            let ledger = self.producer.ledger.lock().map_err(refused)?;
            match self
                .producer
                .status(&mut state, &ledger, &self.captured)
                .map_err(ledger_error)?
            {
                OriginalCellQ24TaskLedgerStatusV1::Complete { decision, outcome }
                    if decision == self.decision && outcome == self.outcome => {}
                _ => return Err(refused("original accepted source changed")),
            }
            let snapshot = witnessed_snapshot(&ledger).map_err(ledger_error)?;
            (snapshot.head_digest, snapshot.records().len())
        };
        CellQ24PreparedLearningV1::revalidate_source(self.prepared.as_ref()).map_err(refused)?;
        self.require_database()?;
        Ok(cut)
    }

    async fn read_original(&self) -> Result<(Digest32, usize), AgentdError> {
        if self.fenced.load(Ordering::Acquire) {
            return Err(refused("retained source is fenced"));
        }
        let result = async {
            let before = self.read_accepted()?;
            let trace = self
                .store
                .bounded_circuit_committed_trace(self.trace.run().run_id())
                .await
                .map_err(refused)?
                .ok_or_else(|| refused("original committed trace disappeared"))?;
            if trace != self.trace || self.read_accepted()? != before {
                return Err(refused("retained source changed across original readback"));
            }
            Ok(before)
        }
        .await;
        match result {
            Err(error) => {
                self.fenced.store(/*value*/ true, Ordering::Release);
                Err(error)
            }
            Ok(cut) if !self.fenced.load(Ordering::Acquire) => Ok(cut),
            Ok(_) => Err(refused("retained source is fenced")),
        }
    }

    fn require_database(&self) -> Result<(), AgentdError> {
        let checked = (|| {
            let retained = self.database.metadata()?;
            let current = std::fs::symlink_metadata(self.store.path())?;
            if !retained.is_file()
                || !current.is_file()
                || retained.nlink() != 1
                || current.nlink() != 1
                || retained.dev() != current.dev()
                || retained.ino() != current.ino()
            {
                return Err(refused("original Automation database was replaced"));
            }
            Ok(())
        })();
        match checked {
            Err(error) => {
                self.fenced.store(true, Ordering::Release);
                Err(error)
            }
            Ok(()) if !self.fenced.load(Ordering::Acquire) => Ok(()),
            Ok(()) => Err(refused("retained source is fenced")),
        }
    }
}

impl RegisteredCellQ24RetainedSourceV1 {
    pub(crate) fn request(&self) -> &LearningIterationRequestV1 {
        &self.source.prepared.initial().request
    }

    pub(crate) fn source_run_id(&self) -> &StableId {
        &self.source.prepared.initial().request.source_run_id
    }

    pub(crate) fn original_identity(&self) -> &AgentdIdentity {
        &self.source.producer.identity
    }

    pub(crate) fn original_record(&self) -> &RunStartRecordV1 {
        self.source.captured.publication.original_record()
    }

    pub(crate) fn original_trace(&self) -> &CircuitCommittedTraceV2 {
        &self.source.trace
    }

    pub(crate) fn original_outbox(
        &self,
        consumer: &AgentdIdentity,
        request: &LearningIterationRequestV1,
    ) -> Result<AutomationStore, AgentdError> {
        if consumer != &self.consumer || request != &self.source.prepared.initial().request {
            return Err(refused(
                "retained source request or current consumer differs",
            ));
        }
        self.source.require_database()?;
        Ok(self.source.store.clone())
    }

    pub(crate) async fn observe_retained_learning(
        self: &Arc<Self>,
        consumer: &AgentdIdentity,
    ) -> Result<OriginalCellQ24RetainedLearningReadyV1, AgentdError> {
        if consumer != &self.consumer {
            return Err(refused("retained source consumer changed"));
        }
        let cut = self.source.read_original().await?;
        Ok(OriginalCellQ24RetainedLearningReadyV1 {
            registered: Arc::clone(self),
            cut,
        })
    }
}

impl OriginalCellQ24RetainedLearningReadyV1 {
    pub(crate) async fn require_retained_task(
        &self,
        registered: &Arc<RegisteredCellQ24RetainedSourceV1>,
        consumer: &AgentdIdentity,
        record: &RunStartRecordV1,
        trace: &CircuitCommittedTraceV2,
    ) -> Result<(), AgentdError> {
        if !Arc::ptr_eq(&self.registered, registered)
            || consumer != &registered.consumer
            || record != registered.original_record()
            || trace != registered.original_trace()
            || self.registered.source.read_original().await? != self.cut
        {
            return Err(refused(
                "retained Ready differs from its registered original source",
            ));
        }
        Ok(())
    }
}

fn ledger_error(error: Error) -> AgentdError {
    AgentdError::Io(std::io::Error::other(error))
}
fn refused(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::GenerationFenced(format!("original retained learning source: {error}"))
}
