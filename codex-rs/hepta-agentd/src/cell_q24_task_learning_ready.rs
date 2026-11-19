//! The actual original task, accepted observations and witnessed Ledger cut.
//! The private constructor creates an observation, never execution authority.

use codex_hepta_automation::CircuitCommittedTraceV2;
use codex_hepta_contracts::Sha256Digest;

use super::*;
use crate::AgentdError;
use crate::CircuitTaskLearningPendingV1;
use crate::CircuitTaskLearningReadinessV1;

pub struct OriginalCellQ24TaskLearningReadyV1 {
    producer: Arc<OriginalCellQ24TaskLedgerProducerV1>,
    record: RunStartRecordV1,
    trace: Sha256Digest,
    publication: Digest32,
    ledger_head: Digest32,
    ledger_records: usize,
    decision: LedgerRecord,
    outcome: LedgerRecord,
}

impl OriginalCellQ24TaskLedgerProducerV1 {
    pub(crate) fn observe_learning(
        self: &Arc<Self>,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
        trace: &CircuitCommittedTraceV2,
    ) -> CircuitTaskLearningReadinessV1 {
        match self.observe_original_learning(identity, record, trace) {
            Ok(Some(ready)) => CircuitTaskLearningReadinessV1::Ready(ready),
            Ok(None) => CircuitTaskLearningReadinessV1::Pending(
                CircuitTaskLearningPendingV1::TerminalOutcome,
            ),
            Err(Error::Owner(
                LearningOriginalOwnerErrorV1::CommitUncertain
                | LearningOriginalOwnerErrorV1::Pending,
            )) => CircuitTaskLearningReadinessV1::Pending(
                CircuitTaskLearningPendingV1::CommitUncertain,
            ),
            Err(Error::Ledger(
                ProductionLedgerError::IndeterminateAfterLedgerCommit { .. }
                | ProductionLedgerError::IndeterminateAfterTopologyChange { .. }
                | ProductionLedgerError::Durable(
                    DurableLedgerError::Indeterminate | DurableLedgerError::Poisoned,
                ),
            )) => CircuitTaskLearningReadinessV1::Pending(
                CircuitTaskLearningPendingV1::CommitUncertain,
            ),
            Err(error) => CircuitTaskLearningReadinessV1::Pending(
                CircuitTaskLearningPendingV1::Refused(error.to_string()),
            ),
        }
    }

    fn observe_original_learning(
        self: &Arc<Self>,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
        trace: &CircuitCommittedTraceV2,
    ) -> Result<Option<OriginalCellQ24TaskLearningReadyV1>, Error> {
        // Exact original source/RunStart/trace checks precede any Generator
        // claim or Ledger append, including startup reconciliation.
        {
            let mut state = self
                .state
                .lock()
                .map_err(|_| Error::Binding("producer lock"))?;
            let captured = self.capture(&mut state)?;
            require_task(self, &captured, identity, record, trace)?;
        }
        let producer: &OriginalCellQ24TaskLedgerProducerV1 = self.as_ref();
        producer.resume_from_original_source()?;
        let mut state = self
            .state
            .lock()
            .map_err(|_| Error::Binding("producer lock"))?;
        let captured = self.capture(&mut state)?;
        require_task(self, &captured, identity, record, trace)?;
        let ledger = self
            .ledger
            .lock()
            .map_err(|_| Error::Binding("ledger lock"))?;
        let (decision, outcome) = match self.status(&mut state, &ledger, &captured)? {
            OriginalCellQ24TaskLedgerStatusV1::AwaitingOutcome { .. } => return Ok(None),
            OriginalCellQ24TaskLedgerStatusV1::Complete { decision, outcome } => {
                (decision, outcome)
            }
        };
        let cut = witnessed_snapshot(&ledger)?;
        self.require_source(&captured)?;
        Ok(Some(OriginalCellQ24TaskLearningReadyV1 {
            producer: Arc::clone(self),
            record: record.clone(),
            trace: trace.history_digest().clone(),
            publication: captured.publication.publication_digest(),
            ledger_head: cut.head_digest,
            ledger_records: cut.records().len(),
            decision,
            outcome,
        }))
    }
}

impl OriginalCellQ24TaskLearningReadyV1 {
    pub(crate) fn require_task(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
        trace: &CircuitCommittedTraceV2,
    ) -> Result<(), AgentdError> {
        self.require_original_task(identity, record, trace)
            .map_err(|error| {
                AgentdError::Protocol(format!(
                    "task committed; original Q24 learning readiness refused: {error}"
                ))
            })
    }

    fn require_original_task(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
        trace: &CircuitCommittedTraceV2,
    ) -> Result<(), Error> {
        if record != &self.record || trace.history_digest() != &self.trace {
            return Err(Error::Binding("original learning RunStart or trace"));
        }
        let mut state = self
            .producer
            .state
            .lock()
            .map_err(|_| Error::Binding("producer lock"))?;
        let captured = self.producer.capture(&mut state)?;
        require_task(&self.producer, &captured, identity, record, trace)?;
        if captured.publication.publication_digest() != self.publication {
            return Err(Error::Binding("original learning publication"));
        }
        let ledger = self
            .producer
            .ledger
            .lock()
            .map_err(|_| Error::Binding("ledger lock"))?;
        match self.producer.status(&mut state, &ledger, &captured)? {
            OriginalCellQ24TaskLedgerStatusV1::Complete { decision, outcome }
                if decision == self.decision && outcome == self.outcome => {}
            _ => return Err(Error::PendingOutcome),
        }
        let cut = witnessed_snapshot(&ledger)?;
        if cut.head_digest != self.ledger_head || cut.records().len() != self.ledger_records {
            return Err(LearningOriginalOwnerErrorV1::CommitUncertain.into());
        }
        self.producer.require_source(&captured)
    }
}

fn require_task(
    producer: &OriginalCellQ24TaskLedgerProducerV1,
    captured: &Captured,
    identity: &AgentdIdentity,
    record: &RunStartRecordV1,
    trace: &CircuitCommittedTraceV2,
) -> Result<(), Error> {
    if identity != &producer.identity
        || record != captured.publication.original_record()
        || trace.run().run_id() != record.snapshot.run_id.as_str()
        || trace.run().outcome().is_none()
        || trace.run().unresolved() != 0
        || trace.history_digest() != captured.publication.history_digest()
    {
        return Err(Error::Binding(
            "complete original RunStart, authentication and task history",
        ));
    }
    producer.require_source(captured)
}
