//! Machine-driven DecisionCell split proposal and lifecycle orchestration.
//!
//! This module closes the source-level gap between a proposal and the existing
//! signed evaluator.  A trigger is converted into a replayable proposal
//! receipt, then the driver advances the lifecycle through evaluation, canary,
//! retention/quarantine and optional parent retirement.  The journal owner is
//! deliberately a trait: production must implement it with the durable
//! TaskFlow/learning-ledger owner, while the in-memory owner below is only a
//! deterministic source qualification fixture.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::str::FromStr;

use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::TaskFlowCommand;
use codex_hepta_automation::TaskFlowDefinition;
use codex_hepta_automation::TaskFlowEdgeSpec;
use codex_hepta_automation::TaskFlowError;
use codex_hepta_automation::TaskFlowEvent;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_automation::TaskFlowNodeKind;
use codex_hepta_automation::TaskFlowNodeSpec;
use codex_hepta_automation::TaskFlowRun;
use codex_hepta_automation::TaskFlowRunState;
use codex_hepta_automation::TaskFlowTransition;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_learning_ledger::CellSplitLearningLedgerV1;
use codex_hepta_learning_ledger::CellSplitLifecycleRecordV1;
use codex_hepta_learning_ledger::DurableLedgerError;
use codex_hepta_types::CellSplitV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::CellRoleQualificationReplayV1;
use crate::CellSplitCanaryReceiptV1;
use crate::CellSplitLifecycleErrorV1;
use crate::CellSplitLifecycleEventV1;
use crate::CellSplitLifecycleJournalV1;
use crate::CellSplitLifecycleStateV1;
use crate::CellSplitLongHorizonEvaluationReceiptV1;
use crate::cell_role_qualification_replay::MAX_CELL_ROLE_QUALIFICATION_REPLAY_BYTES;

pub const CELL_SPLIT_TASKFLOW_ID_V1: &str = "hepta.learning.cell-split.v1";

/// A machine-observed reason for asking the proposal source to emit a split.
/// There is intentionally no manual trigger variant: a human may change the
/// policy, but the proposal event must carry an observed parent signal.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellSplitProposalTriggerV1 {
    UtilityRegression,
    TaskCoverageOpportunity,
    ResourcePressure,
}

impl CellSplitProposalTriggerV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::UtilityRegression => 0,
            Self::TaskCoverageOpportunity => 1,
            Self::ResourcePressure => 2,
        }
    }
}

/// Parent-owned observation from which an autonomous proposal may be emitted.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitProposalSignalV1 {
    pub parent_cell_id: StableId,
    pub parent_generation: Generation,
    pub parent_bundle_digest: Digest32,
    pub trigger: CellSplitProposalTriggerV1,
    pub trigger_evidence_digest: Digest32,
    pub policy_digest: Digest32,
    pub observation_sequence: u64,
    pub observed_at_micros: u64,
    signal_digest: Digest32,
}

impl CellSplitProposalSignalV1 {
    pub fn new(
        parent_cell_id: StableId,
        parent_generation: Generation,
        parent_bundle_digest: Digest32,
        trigger: CellSplitProposalTriggerV1,
        trigger_evidence_digest: Digest32,
        policy_digest: Digest32,
        observation_sequence: u64,
        observed_at_micros: u64,
    ) -> Result<Self, CellSplitAutomationErrorV1> {
        if parent_cell_id.as_str().is_empty()
            || parent_bundle_digest.is_zero()
            || trigger_evidence_digest.is_zero()
            || policy_digest.is_zero()
            || observation_sequence == 0
            || observed_at_micros == 0
        {
            return Err(CellSplitAutomationErrorV1::InvalidProposalSignal);
        }
        let mut signal = Self {
            parent_cell_id,
            parent_generation,
            parent_bundle_digest,
            trigger,
            trigger_evidence_digest,
            policy_digest,
            observation_sequence,
            observed_at_micros,
            signal_digest: Digest32::ZERO,
        };
        signal.signal_digest = signal.digest();
        Ok(signal)
    }

    #[must_use]
    pub fn signal_digest(&self) -> Digest32 {
        self.signal_digest
    }

    pub fn verify_digest(&self) -> Result<(), CellSplitAutomationErrorV1> {
        if self.signal_digest != self.digest() {
            return Err(CellSplitAutomationErrorV1::Digest);
        }
        Ok(())
    }

    fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.learning.cell-split.proposal-signal.v1".to_vec();
        push_id(&mut bytes, &self.parent_cell_id);
        bytes.extend_from_slice(&self.parent_generation.get().to_be_bytes());
        bytes.extend_from_slice(self.parent_bundle_digest.as_array());
        bytes.push(self.trigger.tag());
        bytes.extend_from_slice(self.trigger_evidence_digest.as_array());
        bytes.extend_from_slice(self.policy_digest.as_array());
        bytes.extend_from_slice(&self.observation_sequence.to_be_bytes());
        bytes.extend_from_slice(&self.observed_at_micros.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }
}

/// Receipt emitted by the autonomous proposal source.  It binds the complete
/// split subject to one parent observation and is the first TaskFlow input.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitProposalReceiptV1 {
    pub split_id: StableId,
    pub proposer_id: StableId,
    pub subject_digest: Digest32,
    pub signal_digest: Digest32,
    pub proposal_digest: Digest32,
    pub receipt_digest: Digest32,
}

impl CellSplitProposalReceiptV1 {
    pub fn verify_digest(&self) -> Result<(), CellSplitAutomationErrorV1> {
        if self.receipt_digest != self.digest() {
            return Err(CellSplitAutomationErrorV1::Digest);
        }
        Ok(())
    }

    fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.learning.cell-split.proposal-receipt.v1".to_vec();
        push_id(&mut bytes, &self.split_id);
        push_id(&mut bytes, &self.proposer_id);
        for digest in [
            self.subject_digest,
            self.signal_digest,
            self.proposal_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        Digest32::of_bytes(&bytes)
    }
}

/// Stateless source.  It is intentionally deterministic, so a durable owner
/// can retry a trigger without emitting a second proposal for the same signal.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CellSplitProposalSourceV1;

impl CellSplitProposalSourceV1 {
    pub fn emit(
        &self,
        split: &CellSplitV1,
        signal: &CellSplitProposalSignalV1,
    ) -> Result<CellSplitProposalReceiptV1, CellSplitAutomationErrorV1> {
        split
            .validate_plan()
            .map_err(|_| CellSplitAutomationErrorV1::Binding("split plan"))?;
        signal.verify_digest()?;
        if signal.parent_cell_id != split.parent_cell_id
            || signal.parent_generation != split.predecessor_generation
            || signal.parent_bundle_digest != split.parent_bundle_digest
        {
            return Err(CellSplitAutomationErrorV1::Binding("parent observation"));
        }
        let subject_digest = split
            .evaluation_subject_digest()
            .map_err(|_| CellSplitAutomationErrorV1::Binding("split subject"))?;
        let mut proposal_bytes = b"hepta.learning.cell-split.proposal.v1".to_vec();
        proposal_bytes.extend_from_slice(subject_digest.as_array());
        proposal_bytes.extend_from_slice(signal.signal_digest.as_array());
        let proposal_digest = Digest32::of_bytes(&proposal_bytes);
        let mut receipt = CellSplitProposalReceiptV1 {
            split_id: split.split_id.clone(),
            proposer_id: split.proposer_id.clone(),
            subject_digest,
            signal_digest: signal.signal_digest,
            proposal_digest,
            receipt_digest: Digest32::ZERO,
        };
        receipt.receipt_digest = receipt.digest();
        Ok(receipt)
    }
}

/// Durable owner boundary for the lifecycle journal.  A production adapter
/// should implement this by appending a fenced TaskFlow/ledger event and only
/// returning after its commit witness is durable.
pub trait CellSplitAutomationJournalOwnerV1 {
    fn load(
        &self,
        split_id: &StableId,
    ) -> Result<Option<CellSplitLifecycleJournalV1>, CellSplitAutomationErrorV1>;

    fn commit(
        &mut self,
        journal: &CellSplitLifecycleJournalV1,
    ) -> Result<(), CellSplitAutomationErrorV1>;
}

/// In-memory owner for deterministic source qualification.  It enforces the
/// same append-only and replay checks expected from the durable owner but does
/// not claim fsync, CAS or cross-process fencing.
#[derive(Clone, Debug, Default)]
pub struct CellSplitInMemoryJournalOwnerV1 {
    journals: BTreeMap<StableId, CellSplitLifecycleJournalV1>,
}

impl CellSplitAutomationJournalOwnerV1 for CellSplitInMemoryJournalOwnerV1 {
    fn load(
        &self,
        split_id: &StableId,
    ) -> Result<Option<CellSplitLifecycleJournalV1>, CellSplitAutomationErrorV1> {
        Ok(self.journals.get(split_id).cloned())
    }

    fn commit(
        &mut self,
        journal: &CellSplitLifecycleJournalV1,
    ) -> Result<(), CellSplitAutomationErrorV1> {
        let replayed =
            CellSplitLifecycleJournalV1::replay(journal.split_id.clone(), journal.events.clone())
                .map_err(CellSplitAutomationErrorV1::Lifecycle)?;
        if replayed.current_state != journal.current_state
            || replayed.head_digest != journal.head_digest
        {
            return Err(CellSplitAutomationErrorV1::Store(
                "journal replay does not match commit".to_string(),
            ));
        }
        if let Some(previous) = self.journals.get(&journal.split_id) {
            if previous.events.len() > journal.events.len()
                || previous.events != journal.events[..previous.events.len()]
            {
                return Err(CellSplitAutomationErrorV1::Store(
                    "journal append regressed or rewrote history".to_string(),
                ));
            }
        }
        self.journals
            .insert(journal.split_id.clone(), journal.clone());
        Ok(())
    }
}

/// Durable learning-ledger owner for the lifecycle journal.
///
/// This adapter is intentionally separate from [`CellSplitTaskFlowJournalOwnerV1`].
/// The learning ledger supplies the append-only, fsync and independently
/// witnessed lifecycle chain; a production deployment that also uses TaskFlow
/// must bind the two chains at the host boundary.  The deterministic
/// `taskflow_event_digest` field in the ledger record is therefore an owner
/// event binding, not evidence that a TaskFlow run was executed.  Callers must
/// keep the TaskFlow owner in the same transaction/fence protocol before
/// claiming the combined target-host qualification gate.
pub struct CellSplitLearningLedgerJournalOwnerV1 {
    ledger: CellSplitLearningLedgerV1,
}

impl CellSplitLearningLedgerJournalOwnerV1 {
    pub fn create(
        file: std::fs::File,
        witness_file: std::fs::File,
        binding: Digest32,
        max_records: usize,
    ) -> Result<Self, CellSplitAutomationErrorV1> {
        Ok(Self {
            ledger: CellSplitLearningLedgerV1::create(file, witness_file, binding, max_records)
                .map_err(learning_ledger_error)?,
        })
    }

    pub fn recover(
        file: std::fs::File,
        witness_file: std::fs::File,
        binding: Digest32,
        max_records: usize,
    ) -> Result<Self, CellSplitAutomationErrorV1> {
        Ok(Self {
            ledger: CellSplitLearningLedgerV1::recover(file, witness_file, binding, max_records)
                .map_err(learning_ledger_error)?,
        })
    }

    #[must_use]
    pub fn ledger(&self) -> &CellSplitLearningLedgerV1 {
        &self.ledger
    }

    #[must_use]
    pub fn ledger_mut(&mut self) -> &mut CellSplitLearningLedgerV1 {
        &mut self.ledger
    }

    /// Append a lifecycle journal and retain the complete, bounded typed role
    /// qualification/evaluator payload in the same witnessed ledger frame as
    /// the final newly appended transition.  The payload is deliberately
    /// opaque to this owner: the role owner validates its schema, while this
    /// owner guarantees durability, idempotent retry and replay.  An empty
    /// payload is equivalent to [`CellSplitAutomationJournalOwnerV1::commit`].
    pub fn commit_with_role_qualification_payload(
        &mut self,
        journal: &CellSplitLifecycleJournalV1,
        payload: &[u8],
    ) -> Result<(), CellSplitAutomationErrorV1> {
        if payload.len() > 16 * 1024 {
            return Err(CellSplitAutomationErrorV1::Store(
                "role qualification payload exceeds bounded ledger capacity".to_string(),
            ));
        }
        let replayed =
            CellSplitLifecycleJournalV1::replay(journal.split_id.clone(), journal.events.clone())
                .map_err(CellSplitAutomationErrorV1::Lifecycle)?;
        if replayed != *journal {
            return Err(CellSplitAutomationErrorV1::Store(
                "journal replay does not match learning-ledger commit".to_string(),
            ));
        }
        let current = self.load(&journal.split_id)?;
        let current_len = current.as_ref().map_or(0, |value| value.events.len());
        if current_len > journal.events.len()
            || current
                .as_ref()
                .is_some_and(|value| value.events != journal.events[..value.events.len()])
        {
            return Err(CellSplitAutomationErrorV1::Store(
                "learning-ledger append regressed or rewrote history".to_string(),
            ));
        }
        if current_len == journal.events.len() {
            if !payload.is_empty() {
                let records = self.ledger.records().map_err(learning_ledger_error)?;
                let persisted = records
                    .iter()
                    .filter(|record| &record.split_id == &journal.split_id)
                    .filter_map(|record| {
                        (!record.role_qualification_payload.is_empty())
                            .then_some(record.role_qualification_payload.as_slice())
                    })
                    .last();
                if persisted != Some(payload) {
                    return Err(CellSplitAutomationErrorV1::Store(
                        "role qualification payload differs on idempotent retry".to_string(),
                    ));
                }
            }
            return Ok(());
        }
        for (offset, event) in journal.events[current_len..].iter().enumerate() {
            let sequence = event.sequence;
            let prefix_end = usize::try_from(sequence).map_err(|_| {
                CellSplitAutomationErrorV1::Store(
                    "learning-ledger lifecycle sequence exceeds addressable range".to_string(),
                )
            })?;
            if prefix_end >= journal.events.len() {
                return Err(CellSplitAutomationErrorV1::Store(
                    "learning-ledger lifecycle sequence is outside journal".to_string(),
                ));
            }
            let prefix = CellSplitLifecycleJournalV1::replay(
                journal.split_id.clone(),
                journal.events[..=prefix_end].to_vec(),
            )
            .map_err(CellSplitAutomationErrorV1::Lifecycle)?;
            let record = CellSplitLifecycleRecordV1 {
                record_id: lifecycle_record_id(&journal.split_id, sequence)?,
                split_id: journal.split_id.clone(),
                lifecycle_sequence: sequence,
                from_state: ledger_lifecycle_state_tag(event.from),
                to_state: ledger_lifecycle_state_tag(event.to),
                evidence_digest: event.evidence_digest,
                state_digest: event.state_digest,
                taskflow_event_digest: owner_event_digest(&journal.split_id, event),
                support_digest: lifecycle_support_digest(&prefix),
                role_qualification_payload: if offset + 1 == journal.events.len() - current_len {
                    payload.to_vec()
                } else {
                    Vec::new()
                },
            };
            let predecessor = self
                .ledger
                .anchor()
                .map_err(learning_ledger_error)?
                .chain_digest;
            self.ledger
                .append(predecessor, record)
                .map_err(learning_ledger_error)?;
        }
        let persisted = self.load(&journal.split_id)?.ok_or_else(|| {
            CellSplitAutomationErrorV1::Store(
                "learning-ledger journal disappeared after commit".to_string(),
            )
        })?;
        if persisted != *journal {
            return Err(CellSplitAutomationErrorV1::Store(
                "learning-ledger replay differs after commit".to_string(),
            ));
        }
        Ok(())
    }

    /// Return the complete typed payloads retained alongside this split's
    /// lifecycle transitions.  Empty payloads are omitted.  The ledger itself
    /// does not decode them, preserving the external role/target-host evidence
    /// boundary.
    pub fn role_qualification_payloads(
        &self,
        split_id: &StableId,
    ) -> Result<Vec<Vec<u8>>, CellSplitAutomationErrorV1> {
        let records = self.ledger.records().map_err(learning_ledger_error)?;
        if records.iter().any(|record| &record.split_id != split_id) {
            return Err(CellSplitAutomationErrorV1::Store(
                "learning-ledger contains another split".to_string(),
            ));
        }
        Ok(records
            .iter()
            .filter(|record| &record.split_id == split_id)
            .filter(|record| !record.role_qualification_payload.is_empty())
            .map(|record| record.role_qualification_payload.clone())
            .collect())
    }
}

impl CellSplitAutomationJournalOwnerV1 for CellSplitLearningLedgerJournalOwnerV1 {
    fn load(
        &self,
        split_id: &StableId,
    ) -> Result<Option<CellSplitLifecycleJournalV1>, CellSplitAutomationErrorV1> {
        let records = self.ledger.records().map_err(learning_ledger_error)?;
        if records.is_empty() {
            return Ok(None);
        }
        if records.iter().any(|record| &record.split_id != split_id) {
            return Err(CellSplitAutomationErrorV1::Store(
                "learning-ledger contains another split".to_string(),
            ));
        }
        let mut events = Vec::with_capacity(records.len());
        for (index, record) in records.iter().enumerate() {
            let sequence = u64::try_from(index)
                .map_err(|_| CellSplitAutomationErrorV1::Store("sequence overflow".into()))?;
            if record.lifecycle_sequence != sequence
                || record.record_id != lifecycle_record_id(split_id, sequence)?
            {
                return Err(CellSplitAutomationErrorV1::Store(
                    "learning-ledger lifecycle sequence is not replayable".to_string(),
                ));
            }
            let from = ledger_lifecycle_state_from_tag(record.from_state)?;
            let to = ledger_lifecycle_state_from_tag(record.to_state)?;
            let event = CellSplitLifecycleEventV1 {
                sequence,
                from,
                to,
                evidence_digest: record.evidence_digest,
                state_digest: record.state_digest,
            };
            if record.taskflow_event_digest != owner_event_digest(split_id, &event)
                || record.support_digest
                    != lifecycle_support_digest(
                        &CellSplitLifecycleJournalV1::replay(
                            split_id.clone(),
                            events
                                .iter()
                                .cloned()
                                .chain(std::iter::once(event.clone()))
                                .collect(),
                        )
                        .map_err(CellSplitAutomationErrorV1::Lifecycle)?,
                    )
            {
                return Err(CellSplitAutomationErrorV1::Store(
                    "learning-ledger lifecycle evidence binding mismatch".to_string(),
                ));
            }
            events.push(event);
        }
        CellSplitLifecycleJournalV1::replay(split_id.clone(), events)
            .map(Some)
            .map_err(CellSplitAutomationErrorV1::Lifecycle)
    }

    fn commit(
        &mut self,
        journal: &CellSplitLifecycleJournalV1,
    ) -> Result<(), CellSplitAutomationErrorV1> {
        self.commit_with_role_qualification_payload(journal, &[])
    }
}

fn learning_ledger_error(error: DurableLedgerError) -> CellSplitAutomationErrorV1 {
    CellSplitAutomationErrorV1::Store(format!("learning-ledger: {error:?}"))
}

fn lifecycle_record_id(
    split_id: &StableId,
    sequence: u64,
) -> Result<StableId, CellSplitAutomationErrorV1> {
    StableId::new(format!(
        "cell-split-lifecycle:{}:{sequence}",
        split_id.as_str()
    ))
    .map_err(|_| CellSplitAutomationErrorV1::Store("invalid lifecycle record id".to_string()))
}

fn ledger_lifecycle_state_tag(state: CellSplitLifecycleStateV1) -> u8 {
    match state {
        CellSplitLifecycleStateV1::Proposed => 0,
        CellSplitLifecycleStateV1::EvaluationPending => 1,
        CellSplitLifecycleStateV1::EvaluationAccepted => 2,
        CellSplitLifecycleStateV1::CanaryRunning => 3,
        CellSplitLifecycleStateV1::Retained => 4,
        CellSplitLifecycleStateV1::Quarantined => 5,
        CellSplitLifecycleStateV1::Retired => 6,
        CellSplitLifecycleStateV1::RolledBack => 7,
    }
}

fn ledger_lifecycle_state_from_tag(
    tag: u8,
) -> Result<CellSplitLifecycleStateV1, CellSplitAutomationErrorV1> {
    match tag {
        0 => Ok(CellSplitLifecycleStateV1::Proposed),
        1 => Ok(CellSplitLifecycleStateV1::EvaluationPending),
        2 => Ok(CellSplitLifecycleStateV1::EvaluationAccepted),
        3 => Ok(CellSplitLifecycleStateV1::CanaryRunning),
        4 => Ok(CellSplitLifecycleStateV1::Retained),
        5 => Ok(CellSplitLifecycleStateV1::Quarantined),
        6 => Ok(CellSplitLifecycleStateV1::Retired),
        7 => Ok(CellSplitLifecycleStateV1::RolledBack),
        _ => Err(CellSplitAutomationErrorV1::Store(
            "learning-ledger lifecycle state tag".to_string(),
        )),
    }
}

fn owner_event_digest(split_id: &StableId, event: &CellSplitLifecycleEventV1) -> Digest32 {
    let mut bytes = b"hepta.learning.cell-split.learning-ledger-owner-event.v1".to_vec();
    push_id(&mut bytes, split_id);
    bytes.extend_from_slice(&event.sequence.to_be_bytes());
    bytes.extend_from_slice(event.state_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn lifecycle_support_digest(journal: &CellSplitLifecycleJournalV1) -> Digest32 {
    let mut bytes = b"hepta.learning.cell-split.learning-ledger-support.v1".to_vec();
    bytes.extend_from_slice(&journal.canonical_bytes());
    Digest32::of_bytes(&bytes)
}

/// Production composition boundary for the cell-split lifecycle journal.
///
/// The synchronous in-memory owner above is intentionally retained for pure
/// source qualification.  This owner is the async adapter used by an actual
/// Agent-local TaskFlow store: every lifecycle append becomes a fenced,
/// append-only TaskFlow event, and reopen reconstructs the exact
/// `CellSplitLifecycleJournalV1` from that verified event chain.  The adapter
/// does not execute a provider effect; it only persists and replays owner
/// state.  A deployment must supply a fresh, strictly higher generation when
/// taking over an expired lease after restart.
pub struct CellSplitTaskFlowJournalOwnerV1 {
    store: AutomationStore,
    fence: TaskFlowFence,
    lease_duration_ms: u64,
}

impl CellSplitTaskFlowJournalOwnerV1 {
    pub const DEFAULT_LEASE_DURATION_MS: u64 = 300_000;

    pub fn new(
        store: AutomationStore,
        fence: TaskFlowFence,
        lease_duration_ms: u64,
    ) -> Result<Self, CellSplitAutomationErrorV1> {
        if lease_duration_ms == 0 {
            return Err(CellSplitAutomationErrorV1::TaskFlow(
                "TaskFlow lease duration must be non-zero".to_string(),
            ));
        }
        Ok(Self {
            store,
            fence,
            lease_duration_ms,
        })
    }

    #[must_use]
    pub fn store(&self) -> &AutomationStore {
        &self.store
    }

    #[must_use]
    pub fn fence(&self) -> &TaskFlowFence {
        &self.fence
    }

    /// Reopens a cell-split journal from the verified TaskFlow event chain.
    pub async fn load_async(
        &self,
        split_id: &StableId,
    ) -> Result<Option<CellSplitLifecycleJournalV1>, CellSplitAutomationErrorV1> {
        let run_id = cell_split_run_id(split_id);
        let Some(_run) = self
            .store
            .taskflow_run(&run_id)
            .await
            .map_err(taskflow_error)?
        else {
            return Ok(None);
        };
        let events = self
            .store
            .taskflow_events(&run_id)
            .await
            .map_err(taskflow_error)?;
        replay_taskflow_journal(split_id, &events)
    }

    /// Replays the complete typed role-qualification payloads attached to a
    /// TaskFlow lifecycle stream.  Payloads are returned as canonical bytes so
    /// the role/evaluator owner can decode and validate its own schema; this
    /// adapter never turns repository evidence into target-host admission.
    pub async fn role_qualification_payloads_async(
        &self,
        split_id: &StableId,
    ) -> Result<Vec<Vec<u8>>, CellSplitAutomationErrorV1> {
        let run_id = cell_split_run_id(split_id);
        let Some(_run) = self
            .store
            .taskflow_run(&run_id)
            .await
            .map_err(taskflow_error)?
        else {
            return Ok(Vec::new());
        };
        let events = self
            .store
            .taskflow_events(&run_id)
            .await
            .map_err(taskflow_error)?;
        let mut payloads = Vec::new();
        for event in events {
            if event.transition != "waiting" {
                continue;
            }
            let transition: TaskFlowTransition = serde_json::from_str(&event.payload_json)
                .map_err(|_| {
                    CellSplitAutomationErrorV1::TaskFlow(
                        "TaskFlow transition payload is corrupt".to_string(),
                    )
                })?;
            let TaskFlowTransition::Wait { token, .. } = transition else {
                continue;
            };
            let (_, payload) = decode_lifecycle_event_with_payload(&token)?;
            if !payload.is_empty() {
                payloads.push(payload);
            }
        }
        Ok(payloads)
    }

    /// Append a journal at an explicit host timestamp.  The timestamp is part
    /// of the TaskFlow run/event evidence and should come from the host's
    /// monotonic durable clock rather than a model-produced value.
    pub async fn commit_async(
        &self,
        journal: &CellSplitLifecycleJournalV1,
        now_ms: u64,
    ) -> Result<(), CellSplitAutomationErrorV1> {
        self.commit_async_with_role_qualification_payload(journal, &[], now_ms)
            .await
    }

    /// Commit a lifecycle journal while carrying the complete typed role
    /// qualification/evaluator receipt in the same durable TaskFlow event as
    /// the final newly appended transition.  TaskFlow persists the canonical
    /// payload; it is not reduced to the lifecycle evidence digest.  This
    /// method does not grant target-host admission or execute any effect.
    pub async fn commit_async_with_role_qualification(
        &self,
        journal: &CellSplitLifecycleJournalV1,
        evidence: &CellRoleQualificationReplayV1,
        now_ms: u64,
    ) -> Result<(), CellSplitAutomationErrorV1> {
        let payload = evidence
            .encode_bounded()
            .map_err(|message| CellSplitAutomationErrorV1::Binding(message))?;
        self.commit_async_with_role_qualification_payload(journal, &payload, now_ms)
            .await
    }

    async fn commit_async_with_role_qualification_payload(
        &self,
        journal: &CellSplitLifecycleJournalV1,
        role_qualification_payload: &[u8],
        now_ms: u64,
    ) -> Result<(), CellSplitAutomationErrorV1> {
        if role_qualification_payload.len() > MAX_CELL_ROLE_QUALIFICATION_REPLAY_BYTES {
            return Err(CellSplitAutomationErrorV1::Store(
                "role qualification payload exceeds bounded TaskFlow capacity".to_string(),
            ));
        }
        if now_ms == 0 {
            return Err(CellSplitAutomationErrorV1::TaskFlow(
                "TaskFlow timestamp must be non-zero".to_string(),
            ));
        }
        let definition = cell_split_taskflow_definition().map_err(taskflow_error)?;
        self.store
            .register_taskflow_definition(&definition, &self.fence, now_ms)
            .await
            .map_err(taskflow_error)?;

        let run_id = cell_split_run_id(&journal.split_id);
        let mut run = match self
            .store
            .taskflow_run(&run_id)
            .await
            .map_err(taskflow_error)?
        {
            Some(run) => run,
            None => self
                .store
                .create_taskflow_run(
                    run_id.clone(),
                    CELL_SPLIT_TASKFLOW_ID_V1,
                    CELL_SPLIT_TASKFLOW_VERSION_V1,
                    definition.definition_digest(),
                    format!("cell-split:thread:{}", journal.split_id.as_str()),
                    now_ms,
                )
                .await
                .map_err(taskflow_error)?,
        };

        let events = self
            .store
            .taskflow_events(&run_id)
            .await
            .map_err(taskflow_error)?;
        let current = replay_taskflow_journal(&journal.split_id, &events)?.unwrap_or(
            CellSplitLifecycleJournalV1::replay(journal.split_id.clone(), Vec::new())
                .map_err(CellSplitAutomationErrorV1::Lifecycle)?,
        );
        if current.split_id != journal.split_id {
            return Err(CellSplitAutomationErrorV1::Binding("journal"));
        }
        if current.events.len() > journal.events.len()
            || current.events != journal.events[..current.events.len()]
        {
            return Err(CellSplitAutomationErrorV1::Store(
                "TaskFlow journal append regressed or rewrote history".to_string(),
            ));
        }

        // A retry after a crash may find the exact target already durable but
        // the TaskFlow run still waiting between its lifecycle Wait and
        // Resume commands.  Finish that fenced command before returning so a
        // replay is observationally complete.
        run = self.ensure_run_ready(run, now_ms).await?;
        if current.events.len() == journal.events.len() {
            validate_taskflow_state_for_journal(&run, &current)?;
            if !role_qualification_payload.is_empty() {
                let persisted = self
                    .role_qualification_payloads_async(&journal.split_id)
                    .await?;
                if persisted.last().map(Vec::as_slice) != Some(role_qualification_payload) {
                    return Err(CellSplitAutomationErrorV1::Store(
                        "role qualification payload differs on idempotent TaskFlow retry"
                            .to_string(),
                    ));
                }
            }
            return Ok(());
        }

        let current_len = current.events.len();
        let mut predecessor_state = current.current_state;
        for (offset, event) in journal.events[current_len..].iter().enumerate() {
            let expected_sequence = u64::try_from(current_len + offset).map_err(|_| {
                CellSplitAutomationErrorV1::Store(
                    "TaskFlow journal sequence exceeds addressable range".to_string(),
                )
            })?;
            if event.sequence != expected_sequence {
                return Err(CellSplitAutomationErrorV1::Store(
                    "TaskFlow journal sequence is not append-only".to_string(),
                ));
            }
            if event.from != predecessor_state {
                return Err(CellSplitAutomationErrorV1::Binding("journal predecessor"));
            }
            let payload = (offset + 1 == journal.events.len() - current_len)
                .then_some(role_qualification_payload)
                .filter(|payload| !payload.is_empty());
            run = self
                .apply_lifecycle_event(run, event, now_ms, payload)
                .await?;
            predecessor_state = event.to;
        }

        let persisted = self.load_async(&journal.split_id).await?.ok_or_else(|| {
            CellSplitAutomationErrorV1::TaskFlow("TaskFlow journal vanished".to_string())
        })?;
        if &persisted != journal {
            return Err(CellSplitAutomationErrorV1::Store(
                "TaskFlow replay does not match committed lifecycle journal".to_string(),
            ));
        }
        let _ = run;
        Ok(())
    }

    async fn ensure_run_ready(
        &self,
        mut run: TaskFlowRun,
        now_ms: u64,
    ) -> Result<TaskFlowRun, CellSplitAutomationErrorV1> {
        if matches!(
            run.state,
            TaskFlowRunState::Succeeded | TaskFlowRunState::Failed | TaskFlowRunState::Cancelled
        ) {
            return Ok(run);
        }
        run = self
            .store
            .claim_taskflow_run(&run.run_id, &self.fence, now_ms, self.lease_duration_ms)
            .await
            .map_err(taskflow_error)?;
        if run.state == TaskFlowRunState::Queued {
            let command = TaskFlowCommand::new(
                run.run_id.clone(),
                format!("{}:start", run.run_id),
                self.fence.clone(),
                run.revision,
                TaskFlowTransition::Start,
                now_ms,
            )
            .map_err(taskflow_error)?;
            self.store
                .apply_taskflow_command(&command)
                .await
                .map_err(taskflow_error)?;
            run = self
                .store
                .taskflow_run(&run.run_id)
                .await
                .map_err(taskflow_error)?
                .ok_or_else(|| {
                    CellSplitAutomationErrorV1::TaskFlow("TaskFlow run disappeared".to_string())
                })?;
        }
        if run.state == TaskFlowRunState::Waiting {
            let token = run.wait_token.clone().ok_or_else(|| {
                CellSplitAutomationErrorV1::TaskFlow("waiting run has no token".to_string())
            })?;
            let command = TaskFlowCommand::new(
                run.run_id.clone(),
                format!("{}:resume:{}", run.run_id, run.revision),
                self.fence.clone(),
                run.revision,
                TaskFlowTransition::Resume { token },
                now_ms,
            )
            .map_err(taskflow_error)?;
            self.store
                .apply_taskflow_command(&command)
                .await
                .map_err(taskflow_error)?;
            run = self
                .store
                .taskflow_run(&run.run_id)
                .await
                .map_err(taskflow_error)?
                .ok_or_else(|| {
                    CellSplitAutomationErrorV1::TaskFlow("TaskFlow run disappeared".to_string())
                })?;
        }
        if run.state != TaskFlowRunState::Running {
            return Err(CellSplitAutomationErrorV1::TaskFlow(format!(
                "TaskFlow run is not writable: {:?}",
                run.state
            )));
        }
        Ok(run)
    }

    async fn apply_lifecycle_event(
        &self,
        mut run: TaskFlowRun,
        event: &CellSplitLifecycleEventV1,
        now_ms: u64,
        role_qualification_payload: Option<&[u8]>,
    ) -> Result<TaskFlowRun, CellSplitAutomationErrorV1> {
        if run.current_node != lifecycle_node(event.from) {
            return Err(CellSplitAutomationErrorV1::Binding(
                "TaskFlow lifecycle predecessor",
            ));
        }
        let token = encode_lifecycle_event(event, role_qualification_payload);
        let resume_node = (event.from != event.to).then(|| lifecycle_node(event.to).to_string());
        let wait = TaskFlowCommand::new(
            run.run_id.clone(),
            format!("{}:event:{}:wait", run.run_id, event.sequence),
            self.fence.clone(),
            run.revision,
            TaskFlowTransition::Wait {
                token: token.clone(),
                resume_node,
            },
            now_ms,
        )
        .map_err(taskflow_error)?;
        self.store
            .apply_taskflow_command(&wait)
            .await
            .map_err(taskflow_error)?;
        run = self
            .store
            .taskflow_run(&run.run_id)
            .await
            .map_err(taskflow_error)?
            .ok_or_else(|| {
                CellSplitAutomationErrorV1::TaskFlow("TaskFlow run disappeared".to_string())
            })?;

        let resume = TaskFlowCommand::new(
            run.run_id.clone(),
            format!("{}:event:{}:resume", run.run_id, event.sequence),
            self.fence.clone(),
            run.revision,
            TaskFlowTransition::Resume {
                token: token.clone(),
            },
            now_ms,
        )
        .map_err(taskflow_error)?;
        self.store
            .apply_taskflow_command(&resume)
            .await
            .map_err(taskflow_error)?;
        run = self
            .store
            .taskflow_run(&run.run_id)
            .await
            .map_err(taskflow_error)?
            .ok_or_else(|| {
                CellSplitAutomationErrorV1::TaskFlow("TaskFlow run disappeared".to_string())
            })?;

        if matches!(
            event.to,
            CellSplitLifecycleStateV1::Retired
                | CellSplitLifecycleStateV1::Quarantined
                | CellSplitLifecycleStateV1::RolledBack
        ) {
            let transition = if event.to == CellSplitLifecycleStateV1::Retired {
                TaskFlowTransition::Succeed {
                    output_digest: digest_to_sha(event.state_digest)?,
                }
            } else {
                TaskFlowTransition::Fail {
                    reason: format!("cell-split-terminal:{token}"),
                }
            };
            let terminal = TaskFlowCommand::new(
                run.run_id.clone(),
                format!("{}:event:{}:terminal", run.run_id, event.sequence),
                self.fence.clone(),
                run.revision,
                transition,
                now_ms,
            )
            .map_err(taskflow_error)?;
            self.store
                .apply_taskflow_command(&terminal)
                .await
                .map_err(taskflow_error)?;
            run = self
                .store
                .taskflow_run(&run.run_id)
                .await
                .map_err(taskflow_error)?
                .ok_or_else(|| {
                    CellSplitAutomationErrorV1::TaskFlow("TaskFlow run disappeared".to_string())
                })?;
        }
        Ok(run)
    }
}

const CELL_SPLIT_TASKFLOW_VERSION_V1: u32 = 1;

fn taskflow_error(error: TaskFlowError) -> CellSplitAutomationErrorV1 {
    if matches!(&error, TaskFlowError::StaleFence) {
        CellSplitAutomationErrorV1::TaskFlow("stale TaskFlow fence".to_string())
    } else {
        CellSplitAutomationErrorV1::TaskFlow(error.to_string())
    }
}

fn digest_to_sha(value: Digest32) -> Result<Sha256Digest, CellSplitAutomationErrorV1> {
    Sha256Digest::parse(value.to_string()).map_err(CellSplitAutomationErrorV1::TaskFlow)
}

fn cell_split_run_id(split_id: &StableId) -> String {
    format!("cell-split:run:{}", split_id.as_str())
}

fn lifecycle_node(state: CellSplitLifecycleStateV1) -> &'static str {
    match state {
        CellSplitLifecycleStateV1::Proposed => "proposed",
        CellSplitLifecycleStateV1::EvaluationPending => "evaluation_pending",
        CellSplitLifecycleStateV1::EvaluationAccepted => "evaluation_accepted",
        CellSplitLifecycleStateV1::CanaryRunning => "canary_running",
        CellSplitLifecycleStateV1::Retained => "retained",
        CellSplitLifecycleStateV1::Quarantined => "quarantined",
        CellSplitLifecycleStateV1::Retired => "retired",
        CellSplitLifecycleStateV1::RolledBack => "rolled_back",
    }
}

fn lifecycle_state_tag(state: CellSplitLifecycleStateV1) -> u8 {
    match state {
        CellSplitLifecycleStateV1::Proposed => 0,
        CellSplitLifecycleStateV1::EvaluationPending => 1,
        CellSplitLifecycleStateV1::EvaluationAccepted => 2,
        CellSplitLifecycleStateV1::CanaryRunning => 3,
        CellSplitLifecycleStateV1::Retained => 4,
        CellSplitLifecycleStateV1::Quarantined => 5,
        CellSplitLifecycleStateV1::Retired => 6,
        CellSplitLifecycleStateV1::RolledBack => 7,
    }
}

fn lifecycle_state_from_tag(tag: u8) -> Option<CellSplitLifecycleStateV1> {
    Some(match tag {
        0 => CellSplitLifecycleStateV1::Proposed,
        1 => CellSplitLifecycleStateV1::EvaluationPending,
        2 => CellSplitLifecycleStateV1::EvaluationAccepted,
        3 => CellSplitLifecycleStateV1::CanaryRunning,
        4 => CellSplitLifecycleStateV1::Retained,
        5 => CellSplitLifecycleStateV1::Quarantined,
        6 => CellSplitLifecycleStateV1::Retired,
        7 => CellSplitLifecycleStateV1::RolledBack,
        _ => return None,
    })
}

fn encode_lifecycle_event(event: &CellSplitLifecycleEventV1, payload: Option<&[u8]>) -> String {
    let mut token = format!(
        "csl1:{}:{}:{}:{}:{}",
        event.sequence,
        lifecycle_state_tag(event.from),
        lifecycle_state_tag(event.to),
        event.evidence_digest,
        event.state_digest
    );
    if let Some(payload) = payload {
        token.push(':');
        token.push_str(&hex_encode(payload));
    }
    token
}

fn decode_lifecycle_event(
    token: &str,
) -> Result<CellSplitLifecycleEventV1, CellSplitAutomationErrorV1> {
    decode_lifecycle_event_with_payload(token).map(|(event, _)| event)
}

fn decode_lifecycle_event_with_payload(
    token: &str,
) -> Result<(CellSplitLifecycleEventV1, Vec<u8>), CellSplitAutomationErrorV1> {
    let mut fields = token.split(':');
    if fields.next() != Some("csl1") {
        return Err(CellSplitAutomationErrorV1::TaskFlow(
            "TaskFlow event is not a cell-split lifecycle token".to_string(),
        ));
    }
    let sequence = fields
        .next()
        .ok_or_else(|| {
            CellSplitAutomationErrorV1::TaskFlow("lifecycle token sequence".to_string())
        })?
        .parse::<u64>()
        .map_err(|_| {
            CellSplitAutomationErrorV1::TaskFlow("lifecycle token sequence".to_string())
        })?;
    let from = lifecycle_state_from_tag(
        fields
            .next()
            .ok_or_else(|| {
                CellSplitAutomationErrorV1::TaskFlow("lifecycle token from".to_string())
            })?
            .parse::<u8>()
            .map_err(|_| {
                CellSplitAutomationErrorV1::TaskFlow("lifecycle token from".to_string())
            })?,
    )
    .ok_or_else(|| CellSplitAutomationErrorV1::TaskFlow("lifecycle token from".to_string()))?;
    let to = lifecycle_state_from_tag(
        fields
            .next()
            .ok_or_else(|| CellSplitAutomationErrorV1::TaskFlow("lifecycle token to".to_string()))?
            .parse::<u8>()
            .map_err(|_| CellSplitAutomationErrorV1::TaskFlow("lifecycle token to".to_string()))?,
    )
    .ok_or_else(|| CellSplitAutomationErrorV1::TaskFlow("lifecycle token to".to_string()))?;
    let evidence_digest = Digest32::from_str(fields.next().ok_or_else(|| {
        CellSplitAutomationErrorV1::TaskFlow("lifecycle token evidence".to_string())
    })?)
    .map_err(|_| CellSplitAutomationErrorV1::TaskFlow("lifecycle token evidence".to_string()))?;
    let state_digest = Digest32::from_str(fields.next().ok_or_else(|| {
        CellSplitAutomationErrorV1::TaskFlow("lifecycle token state".to_string())
    })?)
    .map_err(|_| CellSplitAutomationErrorV1::TaskFlow("lifecycle token state".to_string()))?;
    let payload = match fields.next() {
        None => Vec::new(),
        Some(value) if fields.next().is_none() => hex_decode(value)?,
        Some(_) => {
            return Err(CellSplitAutomationErrorV1::TaskFlow(
                "lifecycle token has trailing fields".to_string(),
            ));
        }
    };
    if payload.len() > MAX_CELL_ROLE_QUALIFICATION_REPLAY_BYTES {
        return Err(CellSplitAutomationErrorV1::TaskFlow(
            "role qualification payload exceeds TaskFlow capacity".to_string(),
        ));
    }
    Ok((
        CellSplitLifecycleEventV1 {
            sequence,
            from,
            to,
            evidence_digest,
            state_digest,
        },
        payload,
    ))
}

fn replay_taskflow_journal(
    split_id: &StableId,
    events: &[TaskFlowEvent],
) -> Result<Option<CellSplitLifecycleJournalV1>, CellSplitAutomationErrorV1> {
    let mut lifecycle_events = Vec::new();
    for event in events {
        if event.transition != "waiting" {
            continue;
        }
        let transition: TaskFlowTransition =
            serde_json::from_str(&event.payload_json).map_err(|_| {
                CellSplitAutomationErrorV1::TaskFlow(
                    "TaskFlow transition payload is corrupt".to_string(),
                )
            })?;
        let TaskFlowTransition::Wait { token, .. } = transition else {
            continue;
        };
        lifecycle_events.push(decode_lifecycle_event(&token)?);
    }
    if lifecycle_events.is_empty() {
        return Ok(None);
    }
    let journal = CellSplitLifecycleJournalV1::replay(split_id.clone(), lifecycle_events)
        .map_err(CellSplitAutomationErrorV1::Lifecycle)?;
    Ok(Some(journal))
}

fn hex_encode(bytes: &[u8]) -> String {
    let mut encoded = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        use std::fmt::Write as _;
        let _ = write!(encoded, "{byte:02x}");
    }
    encoded
}

fn hex_decode(value: &str) -> Result<Vec<u8>, CellSplitAutomationErrorV1> {
    if value.len() % 2 != 0 {
        return Err(CellSplitAutomationErrorV1::TaskFlow(
            "role qualification payload is not even-length hex".to_string(),
        ));
    }
    let mut bytes = Vec::with_capacity(value.len() / 2);
    for pair in value.as_bytes().chunks_exact(2) {
        let text = std::str::from_utf8(pair).map_err(|_| {
            CellSplitAutomationErrorV1::TaskFlow(
                "role qualification payload is not UTF-8 hex".to_string(),
            )
        })?;
        let byte = u8::from_str_radix(text, 16).map_err(|_| {
            CellSplitAutomationErrorV1::TaskFlow(
                "role qualification payload is not hex".to_string(),
            )
        })?;
        bytes.push(byte);
    }
    Ok(bytes)
}

fn validate_taskflow_state_for_journal(
    run: &TaskFlowRun,
    journal: &CellSplitLifecycleJournalV1,
) -> Result<(), CellSplitAutomationErrorV1> {
    if run.current_node != lifecycle_node(journal.current_state) {
        return Err(CellSplitAutomationErrorV1::Binding(
            "TaskFlow lifecycle state",
        ));
    }
    if journal.current_state == CellSplitLifecycleStateV1::Retired
        && run.state != TaskFlowRunState::Succeeded
    {
        return Err(CellSplitAutomationErrorV1::TaskFlow(
            "retired cell split is not terminally succeeded".to_string(),
        ));
    }
    if matches!(
        journal.current_state,
        CellSplitLifecycleStateV1::Quarantined | CellSplitLifecycleStateV1::RolledBack
    ) && run.state != TaskFlowRunState::Failed
    {
        return Err(CellSplitAutomationErrorV1::TaskFlow(
            "quarantined/rolled-back cell split is not terminally failed".to_string(),
        ));
    }
    Ok(())
}

fn cell_split_taskflow_definition() -> Result<TaskFlowDefinition, TaskFlowError> {
    let mut nodes = vec![
        TaskFlowNodeSpec::new("proposed", TaskFlowNodeKind::Activity),
        TaskFlowNodeSpec::new("evaluation_pending", TaskFlowNodeKind::Activity),
        TaskFlowNodeSpec::new("evaluation_accepted", TaskFlowNodeKind::Activity),
        TaskFlowNodeSpec::new("canary_running", TaskFlowNodeKind::Activity),
        TaskFlowNodeSpec::new("retained", TaskFlowNodeKind::Activity),
        TaskFlowNodeSpec::new("quarantined", TaskFlowNodeKind::Activity),
        TaskFlowNodeSpec::new("retired", TaskFlowNodeKind::Activity),
        TaskFlowNodeSpec::new("rolled_back", TaskFlowNodeKind::Activity),
        TaskFlowNodeSpec::new("task_success", TaskFlowNodeKind::TerminalSuccess),
        TaskFlowNodeSpec::new("task_failure", TaskFlowNodeKind::TerminalFailure),
    ];
    // The graph captures the lifecycle transition ABI.  Self-transitions are
    // represented by a Wait without a resume node because TaskFlow forbids
    // graph self-loops while lifecycle evaluation may remain pending.
    let mut edges = vec![
        TaskFlowEdgeSpec::new("proposed", "evaluation_pending"),
        TaskFlowEdgeSpec::new("proposed", "evaluation_accepted"),
        TaskFlowEdgeSpec::new("proposed", "quarantined"),
        TaskFlowEdgeSpec::new("evaluation_pending", "evaluation_accepted"),
        TaskFlowEdgeSpec::new("evaluation_pending", "quarantined"),
        TaskFlowEdgeSpec::new("evaluation_accepted", "canary_running"),
        TaskFlowEdgeSpec::new("canary_running", "retained"),
        TaskFlowEdgeSpec::new("canary_running", "quarantined"),
        TaskFlowEdgeSpec::new("canary_running", "rolled_back"),
        TaskFlowEdgeSpec::new("retained", "retired"),
        TaskFlowEdgeSpec::new("retained", "rolled_back"),
    ];
    for state in [
        "proposed",
        "evaluation_pending",
        "evaluation_accepted",
        "canary_running",
        "retained",
        "quarantined",
        "retired",
        "rolled_back",
    ] {
        edges.push(TaskFlowEdgeSpec::new(state, "task_success"));
        edges.push(TaskFlowEdgeSpec::new(state, "task_failure"));
    }
    let policy_digest = Sha256Digest::for_bytes(b"hepta.learning.cell-split.taskflow.policy.v1");
    TaskFlowDefinition::new(
        CELL_SPLIT_TASKFLOW_ID_V1,
        CELL_SPLIT_TASKFLOW_VERSION_V1,
        "proposed",
        std::mem::take(&mut nodes),
        edges,
        Vec::new(),
        policy_digest,
    )
}

/// Adapter implemented by real owners.  The evaluator must return the opaque
/// signed receipt; the driver never accepts a disposition or digest supplied by
/// the caller as a substitute for `CellSplitLongHorizonEvaluationReceiptV1`.
pub trait CellSplitAutomationExecutorV1 {
    type Error: fmt::Display;

    fn evaluate(
        &mut self,
        split: &CellSplitV1,
    ) -> Result<CellSplitLongHorizonEvaluationReceiptV1, Self::Error>;

    fn canary(&mut self, split: &CellSplitV1) -> Result<CellSplitCanaryReceiptV1, Self::Error>;

    fn retire(&mut self, split: &CellSplitV1) -> Result<Digest32, Self::Error>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CellSplitAutomationOutcomeV1 {
    pub state: CellSplitLifecycleStateV1,
    pub journal_head_digest: Digest32,
    pub proposal_digest: Digest32,
}

/// Execute one deterministic proposal run.  Every state transition is
/// committed before the next owner callback is entered, so a restart resumes
/// from the last durable state and never re-enters a retired/rolled-back run.
pub fn run_cell_split_automation_v1<Owner, Executor>(
    split: &CellSplitV1,
    proposal: &CellSplitProposalReceiptV1,
    owner: &mut Owner,
    executor: &mut Executor,
) -> Result<CellSplitAutomationOutcomeV1, CellSplitAutomationErrorV1>
where
    Owner: CellSplitAutomationJournalOwnerV1,
    Executor: CellSplitAutomationExecutorV1,
{
    proposal.verify_digest()?;
    if proposal.split_id != split.split_id
        || proposal.proposer_id != split.proposer_id
        || proposal.subject_digest
            != split
                .evaluation_subject_digest()
                .map_err(|_| CellSplitAutomationErrorV1::Binding("split subject"))?
    {
        return Err(CellSplitAutomationErrorV1::Binding("proposal"));
    }
    split
        .validate_plan()
        .map_err(|_| CellSplitAutomationErrorV1::Binding("split plan"))?;
    let mut journal = owner
        .load(&split.split_id)?
        .unwrap_or(CellSplitLifecycleJournalV1::proposed(split)?);
    if journal.split_id != split.split_id {
        return Err(CellSplitAutomationErrorV1::Binding("journal"));
    }
    if journal.current_state == CellSplitLifecycleStateV1::Proposed {
        journal.record_proposal(proposal.proposal_digest)?;
        owner.commit(&journal)?;
    }
    if matches!(
        journal.current_state,
        CellSplitLifecycleStateV1::Retained
            | CellSplitLifecycleStateV1::Quarantined
            | CellSplitLifecycleStateV1::Retired
            | CellSplitLifecycleStateV1::RolledBack
    ) {
        return Ok(outcome(&journal, proposal));
    }

    let evaluation = match executor.evaluate(split) {
        Ok(receipt) => receipt,
        Err(error) => {
            journal.quarantine(error_digest("evaluation", &error))?;
            owner.commit(&journal)?;
            return Ok(outcome(&journal, proposal));
        }
    };
    journal.apply_evaluation(split, &evaluation)?;
    owner.commit(&journal)?;
    if !crate::cell_split_evaluation::disposition_allows_canary(&evaluation) {
        return Ok(outcome(&journal, proposal));
    }

    journal.begin_canary(evaluation.binding().evaluation_receipt_digest)?;
    owner.commit(&journal)?;
    let canary = match executor.canary(split) {
        Ok(receipt) => receipt,
        Err(error) => {
            journal.quarantine(error_digest("canary", &error))?;
            owner.commit(&journal)?;
            return Ok(outcome(&journal, proposal));
        }
    };
    journal.finish_canary(&canary)?;
    owner.commit(&journal)?;
    if journal.current_state != CellSplitLifecycleStateV1::Retained {
        return Ok(outcome(&journal, proposal));
    }

    if split.retirement.disposition == codex_hepta_types::CellParentDispositionV1::Retire {
        match executor.retire(split) {
            Ok(retirement_digest) if retirement_digest == split.retirement.tombstone_digest => {
                // A successful callback alone cannot prove the committed
                // tombstone matches the frozen retirement plan. Fail closed
                // rather than recording Retired under an unrelated digest.
                journal.retire(split)?;
                owner.commit(&journal)?;
            }
            Ok(_) => {
                // A mismatched receipt does not prove that rollback ran.
                // Leave the last witnessed state Retained and require
                // external reconciliation; never invent a RolledBack receipt.
                return Err(CellSplitAutomationErrorV1::Binding(
                    "retirement tombstone receipt",
                ));
            }
            Err(error) => {
                journal.rollback(split, error_digest("retire", &error))?;
                owner.commit(&journal)?;
            }
        }
    }
    Ok(outcome(&journal, proposal))
}

fn outcome(
    journal: &CellSplitLifecycleJournalV1,
    proposal: &CellSplitProposalReceiptV1,
) -> CellSplitAutomationOutcomeV1 {
    CellSplitAutomationOutcomeV1 {
        state: journal.current_state,
        journal_head_digest: journal.head_digest,
        proposal_digest: proposal.proposal_digest,
    }
}

fn error_digest<E: fmt::Display>(stage: &str, error: &E) -> Digest32 {
    Digest32::of_bytes(format!("hepta.cell-split.{stage}.error.v1:{error}").as_bytes())
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    let value = id.as_str().as_bytes();
    bytes.extend_from_slice(&(value.len() as u32).to_be_bytes());
    bytes.extend_from_slice(value);
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellSplitAutomationErrorV1 {
    InvalidProposalSignal,
    Binding(&'static str),
    Lifecycle(CellSplitLifecycleErrorV1),
    Store(String),
    Executor(String),
    TaskFlow(String),
    Digest,
}

impl fmt::Display for CellSplitAutomationErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CellSplitAutomationErrorV1 {}

impl From<CellSplitLifecycleErrorV1> for CellSplitAutomationErrorV1 {
    fn from(value: CellSplitLifecycleErrorV1) -> Self {
        Self::Lifecycle(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::CellSplitEvaluationDispositionV1;
    use codex_hepta_contracts::AgentId;
    use codex_hepta_fleet::AgentManifest;
    use codex_hepta_fleet::FleetRegistry;
    use codex_hepta_fleet::ResourceBudget;
    use codex_hepta_fleet::WorkspaceBinding;
    use codex_hepta_paths::HeptaFleetRoot;
    use codex_hepta_types::CellBundleBindingV1;
    use codex_hepta_types::CellBundleInheritanceV1;
    use codex_hepta_types::CellBundleModeV1;
    use codex_hepta_types::CellCachePolicyV1;
    use codex_hepta_types::CellChildPortBindingV1;
    use codex_hepta_types::CellChildV1;
    use codex_hepta_types::CellParentDispositionV1;
    use codex_hepta_types::CellParentRetirementPlanV1;
    use codex_hepta_types::CellPortCompatibilityV1;
    use codex_hepta_types::CellResourceDeltaV1;
    use codex_hepta_types::CellRouteModeV1;
    use codex_hepta_types::CellSplitEvaluationBindingV1;
    use codex_hepta_types::CellStateSplitPlanV1;
    use codex_hepta_types::CellStateTransformKindV1;
    use codex_hepta_types::CellStateTransformV1;
    use codex_hepta_types::Generation;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("test id")
    }

    fn digest(seed: u8) -> Digest32 {
        Digest32::from_array([seed; 32])
    }

    fn transform(seed: u8, kind: CellStateTransformKindV1) -> CellStateTransformV1 {
        CellStateTransformV1 {
            kind,
            source_schema_digest: digest(seed),
            target_schema_digest: digest(seed + 1),
            mapping_digest: match kind {
                CellStateTransformKindV1::Partition | CellStateTransformKindV1::Custom => {
                    digest(seed + 2)
                }
                CellStateTransformKindV1::Copy | CellStateTransformKindV1::Reset => Digest32::ZERO,
            },
        }
    }

    fn split() -> CellSplitV1 {
        let children = vec![
            CellChildV1 {
                child_cell_id: id("cell.a"),
                child_generation: Generation::new(8).expect("generation"),
                child_scope_digest: digest(10),
                lineage_digest: digest(17),
                child_definition_digest: digest(11),
                child_bundle_digest: digest(12),
                dataset_partition_digest: digest(13),
                task_objective_digest: digest(14),
                route_predicate_digest: digest(15),
                fallback_route_digest: digest(16),
                route_mode: CellRouteModeV1::Exclusive,
            },
            CellChildV1 {
                child_cell_id: id("cell.b"),
                child_generation: Generation::new(8).expect("generation"),
                child_scope_digest: digest(20),
                lineage_digest: digest(27),
                child_definition_digest: digest(21),
                child_bundle_digest: digest(22),
                dataset_partition_digest: digest(23),
                task_objective_digest: digest(24),
                route_predicate_digest: digest(25),
                fallback_route_digest: digest(26),
                route_mode: CellRouteModeV1::Exclusive,
            },
        ];
        let bundles = children
            .iter()
            .enumerate()
            .map(|(index, child)| CellBundleBindingV1 {
                child_cell_id: child.child_cell_id.clone(),
                base_digest: digest(30),
                organ_adapter_digest: digest(40),
                cell_adapter_digest: digest(50 + index as u8),
                head_digest: digest(60 + index as u8),
                compatibility_digest: digest(70 + index as u8),
            })
            .collect();
        let ports = children
            .iter()
            .enumerate()
            .map(|(index, child)| CellChildPortBindingV1 {
                child_cell_id: child.child_cell_id.clone(),
                input_port_digest: digest(80 + index as u8),
                output_port_digest: digest(90 + index as u8),
                termination_port_digest: digest(100 + index as u8),
                compatibility_digest: digest(110 + index as u8),
            })
            .collect();
        CellSplitV1 {
            split_id: id("split.automation"),
            proposer_id: id("proposer"),
            evaluator_id: id("evaluator"),
            parent_cell_id: id("cell.parent"),
            organ_id: id("organ.retrieval"),
            parent_scope_digest: digest(1),
            predecessor_generation: Generation::new(7).expect("generation"),
            successor_generation: Generation::new(8).expect("generation"),
            parent_definition_digest: digest(2),
            parent_bundle_digest: digest(3),
            children,
            inheritance: CellBundleInheritanceV1 {
                base_mode: CellBundleModeV1::SharedImmutable,
                organ_adapter_mode: CellBundleModeV1::SharedImmutable,
                cell_adapter_mode: CellBundleModeV1::CloneMutable,
                head_mode: CellBundleModeV1::CloneMutable,
                compatibility_digest: digest(4),
                children: bundles,
            },
            state: CellStateSplitPlanV1 {
                recurrent: transform(120, CellStateTransformKindV1::Partition),
                eligibility: transform(123, CellStateTransformKindV1::Partition),
                optimizer: transform(126, CellStateTransformKindV1::Reset),
                cache_policy: CellCachePolicyV1::Revalidate,
                in_flight_policy: codex_hepta_types::CellInFlightPolicyV1::Drain,
                state_evidence_digest: digest(129),
            },
            ports: CellPortCompatibilityV1 {
                parent_input_port_digest: digest(130),
                parent_output_port_digest: digest(131),
                circuit_route_digest: digest(132),
                abi_digest: digest(133),
                children: ports,
            },
            resources: CellResourceDeltaV1 {
                inference_latency_micros: 100,
                training_steps: 200,
                communication_bytes: 300,
                migration_bytes: 400,
                evaluation_steps: 500,
                resident_bytes: 600,
                checkpoint_bytes: 700,
            },
            retirement: CellParentRetirementPlanV1 {
                disposition: CellParentDispositionV1::Retire,
                drain_watermark_digest: digest(134),
                tombstone_digest: digest(135),
                deletion_lineage_digest: digest(136),
                rollback_digest: digest(137),
            },
            evaluation: CellSplitEvaluationBindingV1 {
                no_change_baseline_id: id("baseline.no-change"),
                evaluation_id: id("evaluation.automation"),
                evaluator_id: id("evaluator"),
                evaluation_receipt_digest: digest(138),
                retention_receipt_digest: digest(139),
                negative_transfer_receipt_digest: digest(140),
                cost_receipt_digest: digest(141),
            },
            rollback_predecessor_digest: digest(142),
            evidence_digest: digest(143),
        }
    }

    struct Executor {
        evaluate_disposition: CellSplitEvaluationDispositionV1,
        canary_failures: u64,
        retired: bool,
    }

    impl Default for Executor {
        fn default() -> Self {
            Self {
                evaluate_disposition: CellSplitEvaluationDispositionV1::InsufficientEvidence,
                canary_failures: 0,
                retired: false,
            }
        }
    }

    impl CellSplitAutomationExecutorV1 for Executor {
        type Error = &'static str;

        fn evaluate(
            &mut self,
            split: &CellSplitV1,
        ) -> Result<CellSplitLongHorizonEvaluationReceiptV1, Self::Error> {
            Ok(crate::cell_split_evaluation::test_receipt_for_lifecycle(
                split,
                self.evaluate_disposition,
            ))
        }

        fn canary(&mut self, split: &CellSplitV1) -> Result<CellSplitCanaryReceiptV1, Self::Error> {
            Ok(CellSplitCanaryReceiptV1::new(
                split.split_id.clone(),
                split.successor_generation,
                digest(31),
                digest(32),
                digest(33),
                10,
                self.canary_failures,
                true,
            )
            .expect("canary"))
        }

        fn retire(&mut self, split: &CellSplitV1) -> Result<Digest32, Self::Error> {
            self.retired = true;
            Ok(split.retirement.tombstone_digest)
        }
    }

    fn proposal(split: &CellSplitV1) -> CellSplitProposalReceiptV1 {
        let signal = CellSplitProposalSignalV1::new(
            split.parent_cell_id.clone(),
            split.predecessor_generation,
            split.parent_bundle_digest,
            CellSplitProposalTriggerV1::TaskCoverageOpportunity,
            digest(41),
            digest(42),
            1,
            10,
        )
        .expect("signal");
        CellSplitProposalSourceV1
            .emit(split, &signal)
            .expect("proposal")
    }

    struct TaskFlowFixture {
        _temp: tempfile::TempDir,
        layout: codex_hepta_paths::HeptaAgentLayout,
    }

    impl TaskFlowFixture {
        fn new() -> Self {
            let temp = tempfile::tempdir().expect("temp root");
            let root = temp.path().canonicalize().expect("canonical temp root");
            let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
            let registry = FleetRegistry::initialize(fleet_root.clone()).expect("fleet registry");
            let workspace = root.join("workspace");
            std::fs::create_dir(&workspace).expect("workspace");
            let workspace = workspace.canonicalize().expect("canonical workspace");
            let agent_id =
                AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent id");
            let manifest = AgentManifest::new(
                agent_id,
                WorkspaceBinding::new(workspace, &fleet_root).expect("binding"),
                ResourceBudget::local_default(),
            )
            .expect("manifest");
            Self {
                _temp: temp,
                layout: registry.register(manifest).expect("register").layout,
            }
        }
    }

    fn taskflow_fence(generation: u64) -> TaskFlowFence {
        TaskFlowFence::new(
            AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent id"),
            "cell-split-owner",
            1,
            generation,
            format!("cell-split-fence-{generation}"),
        )
        .expect("fence")
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn taskflow_owner_reopens_idempotently_and_rejects_stale_generation() {
        let fixture = TaskFlowFixture::new();
        let store = AutomationStore::open(&fixture.layout).await.expect("store");
        let split = split();
        let mut journal = CellSplitLifecycleJournalV1::proposed(&split).expect("journal");
        journal
            .record_proposal(digest(150))
            .expect("proposal event");

        let owner = CellSplitTaskFlowJournalOwnerV1::new(store.clone(), taskflow_fence(1), 1)
            .expect("owner");
        owner.commit_async(&journal, 10).await.expect("commit");
        assert_eq!(
            owner.load_async(&split.split_id).await.expect("load"),
            Some(journal.clone())
        );
        owner
            .commit_async(&journal, 10)
            .await
            .expect("idempotent replay");

        let stale =
            CellSplitTaskFlowJournalOwnerV1::new(store, taskflow_fence(1), 1).expect("stale owner");
        let mut next = journal.clone();
        next.quarantine(digest(151)).expect("next event");
        assert!(matches!(
            stale.commit_async(&next, 20).await,
            Err(CellSplitAutomationErrorV1::TaskFlow(_))
        ));
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn taskflow_owner_replays_complete_retire_chain_in_one_fenced_commit() {
        let fixture = TaskFlowFixture::new();
        let store = AutomationStore::open(&fixture.layout).await.expect("store");
        let split = split();
        let owner = CellSplitTaskFlowJournalOwnerV1::new(store.clone(), taskflow_fence(1), 1)
            .expect("owner");
        let mut journal = CellSplitLifecycleJournalV1::proposed(&split).expect("journal");
        journal.record_proposal(digest(150)).expect("proposal");
        let evaluation = crate::cell_split_evaluation::test_receipt_for_lifecycle(
            &split,
            CellSplitEvaluationDispositionV1::EligibleForCanary,
        );
        journal
            .apply_evaluation(&split, &evaluation)
            .expect("evaluation");
        journal
            .begin_canary(evaluation.binding().evaluation_receipt_digest)
            .expect("canary start");
        let canary = CellSplitCanaryReceiptV1::new(
            split.split_id.clone(),
            split.successor_generation,
            digest(151),
            digest(152),
            digest(153),
            10,
            0,
            true,
        )
        .expect("canary receipt");
        journal.finish_canary(&canary).expect("canary finish");
        journal.retire(&split).expect("retire");

        // A single commit must advance each predecessor state in order. This
        // is the crash boundary used by a producer that batches its journal
        // before the first TaskFlow command is acknowledged.
        owner
            .commit_async(&journal, 10)
            .await
            .expect("commit chain");
        assert_eq!(
            owner.load_async(&split.split_id).await.expect("load"),
            Some(journal.clone())
        );

        // A fresh owner can replay the terminal state without re-entering any
        // provider callback. A higher generation models lease takeover after
        // process restart; the external host still has to supply the lease.
        let reopened = CellSplitTaskFlowJournalOwnerV1::new(store, taskflow_fence(2), 1)
            .expect("reopened owner");
        assert_eq!(
            reopened.load_async(&split.split_id).await.expect("replay"),
            Some(journal)
        );
    }

    #[test]
    fn proposal_source_is_deterministic_and_binds_parent_observation() {
        let split = split();
        let first = proposal(&split);
        let second = proposal(&split);
        assert_eq!(first, second);

        let bad_signal = CellSplitProposalSignalV1::new(
            id("other-parent"),
            split.predecessor_generation,
            split.parent_bundle_digest,
            CellSplitProposalTriggerV1::ResourcePressure,
            digest(41),
            digest(42),
            1,
            10,
        )
        .expect("signal");
        assert_eq!(
            CellSplitProposalSourceV1.emit(&split, &bad_signal),
            Err(CellSplitAutomationErrorV1::Binding("parent observation"))
        );
    }

    #[test]
    fn automation_rejects_wrong_retirement_tombstone_receipt() {
        let split = split();
        let receipt = proposal(&split);
        let mut owner = CellSplitInMemoryJournalOwnerV1::default();
        struct WrongRetirement;
        impl CellSplitAutomationExecutorV1 for WrongRetirement {
            type Error = &'static str;
            fn evaluate(&mut self, split: &CellSplitV1) -> Result<CellSplitLongHorizonEvaluationReceiptV1, Self::Error> {
                Executor { evaluate_disposition: CellSplitEvaluationDispositionV1::EligibleForCanary, ..Executor::default() }.evaluate(split)
            }
            fn canary(&mut self, split: &CellSplitV1) -> Result<CellSplitCanaryReceiptV1, Self::Error> {
                Executor::default().canary(split)
            }
            fn retire(&mut self, _split: &CellSplitV1) -> Result<Digest32, Self::Error> {
                Ok(digest(34))
            }
        }
        assert!(matches!(
            run_cell_split_automation_v1(&split, &receipt, &mut owner, &mut WrongRetirement),
            Err(CellSplitAutomationErrorV1::Binding("retirement tombstone receipt"))
        ));
        let journal = owner.load(&split.split_id).expect("load").expect("journal");
        assert_eq!(journal.current_state, CellSplitLifecycleStateV1::Retained);
    }

    #[test]
    fn automation_runs_proposal_evaluation_canary_retain_and_retire() {
        let split = split();
        let receipt = proposal(&split);
        let mut owner = CellSplitInMemoryJournalOwnerV1::default();
        let mut executor = Executor {
            evaluate_disposition: CellSplitEvaluationDispositionV1::EligibleForCanary,
            ..Executor::default()
        };
        let outcome = run_cell_split_automation_v1(&split, &receipt, &mut owner, &mut executor)
            .expect("automation");
        assert_eq!(outcome.state, CellSplitLifecycleStateV1::Retired);
        assert!(executor.retired);
        let journal = owner.load(&split.split_id).expect("load").expect("journal");
        assert_eq!(journal.events.len(), 5);
        assert_eq!(journal.current_state, CellSplitLifecycleStateV1::Retired);

        let replayed = run_cell_split_automation_v1(&split, &receipt, &mut owner, &mut executor)
            .expect("terminal replay");
        assert_eq!(replayed.state, CellSplitLifecycleStateV1::Retired);
    }

    #[test]
    fn automation_quarantines_failed_canary_and_never_retires() {
        let split = split();
        let receipt = proposal(&split);
        let mut owner = CellSplitInMemoryJournalOwnerV1::default();
        let mut executor = Executor {
            evaluate_disposition: CellSplitEvaluationDispositionV1::EligibleForCanary,
            canary_failures: 10,
            ..Executor::default()
        };
        let outcome = run_cell_split_automation_v1(&split, &receipt, &mut owner, &mut executor)
            .expect("automation");
        assert_eq!(outcome.state, CellSplitLifecycleStateV1::Quarantined);
        assert!(!executor.retired);
    }

    #[test]
    fn learning_ledger_replays_complete_retire_chain_after_restart() {
        let directory = tempfile::tempdir().expect("temporary directory");
        let ledger_path = directory.path().join("ledger");
        let witness_path = directory.path().join("witness");
        let split = split();
        let binding = digest(170);
        let mut owner = CellSplitLearningLedgerJournalOwnerV1::create(
            std::fs::File::create(&ledger_path).expect("ledger"),
            std::fs::File::create(&witness_path).expect("witness"),
            binding,
            32,
        )
        .expect("owner");
        let proposal = proposal(&split);
        let mut executor = Executor {
            evaluate_disposition: CellSplitEvaluationDispositionV1::EligibleForCanary,
            ..Executor::default()
        };
        let outcome = run_cell_split_automation_v1(&split, &proposal, &mut owner, &mut executor)
            .expect("durable automation");
        assert_eq!(outcome.state, CellSplitLifecycleStateV1::Retired);
        let committed = owner.load(&split.split_id).expect("load").expect("journal");
        assert_eq!(committed.events.len(), 5);
        drop(owner);

        let reopened = CellSplitLearningLedgerJournalOwnerV1::recover(
            std::fs::OpenOptions::new()
                .read(true)
                .write(true)
                .open(&ledger_path)
                .expect("reopen ledger"),
            std::fs::OpenOptions::new()
                .read(true)
                .write(true)
                .open(&witness_path)
                .expect("reopen witness"),
            binding,
            32,
        )
        .expect("reopen owner");
        assert_eq!(
            reopened.load(&split.split_id).expect("replay"),
            Some(committed)
        );
    }

    #[test]
    fn learning_ledger_replays_retained_to_rollback_chain() {
        let directory = tempfile::tempdir().expect("temporary directory");
        let ledger_path = directory.path().join("ledger");
        let witness_path = directory.path().join("witness");
        let split = split();
        let binding = digest(171);
        let mut owner = CellSplitLearningLedgerJournalOwnerV1::create(
            std::fs::File::create(&ledger_path).expect("ledger"),
            std::fs::File::create(&witness_path).expect("witness"),
            binding,
            32,
        )
        .expect("owner");
        let proposal = proposal(&split);
        let mut journal = CellSplitLifecycleJournalV1::proposed(&split).expect("journal");
        journal
            .record_proposal(proposal.proposal_digest)
            .expect("proposal");
        let evaluation = crate::cell_split_evaluation::test_receipt_for_lifecycle(
            &split,
            CellSplitEvaluationDispositionV1::EligibleForCanary,
        );
        journal
            .apply_evaluation(&split, &evaluation)
            .expect("evaluation");
        journal
            .begin_canary(evaluation.binding().evaluation_receipt_digest)
            .expect("canary start");
        let canary = CellSplitCanaryReceiptV1::new(
            split.split_id.clone(),
            split.successor_generation,
            digest(172),
            digest(173),
            digest(174),
            10,
            0,
            true,
        )
        .expect("canary");
        journal.finish_canary(&canary).expect("retained");
        journal.rollback(&split, digest(175)).expect("rollback");
        owner.commit(&journal).expect("durable rollback");
        drop(owner);

        let reopened = CellSplitLearningLedgerJournalOwnerV1::recover(
            std::fs::OpenOptions::new()
                .read(true)
                .write(true)
                .open(&ledger_path)
                .expect("reopen ledger"),
            std::fs::OpenOptions::new()
                .read(true)
                .write(true)
                .open(&witness_path)
                .expect("reopen witness"),
            binding,
            32,
        )
        .expect("reopen owner");
        let replayed = reopened
            .load(&split.split_id)
            .expect("replay")
            .expect("journal");
        assert_eq!(
            replayed.current_state,
            CellSplitLifecycleStateV1::RolledBack
        );
        assert_eq!(replayed.events.len(), 5);
    }
}
