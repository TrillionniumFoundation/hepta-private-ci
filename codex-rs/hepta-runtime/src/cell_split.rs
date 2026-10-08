//! Candidate-only, multi-child state migration for an organ-local cell split.
//!
//! This module is deliberately narrower than a model/runtime implementation. It
//! moves already committed owner state through the existing
//! [`OrganStateMigrationV1`](codex_hepta_control_plane::OrganStateMigrationV1)
//! seam. It does not select weights, activate a child, invoke a model, or create
//! a second writer. Every child is prepared in memory first; one failing child
//! fails the complete split. A small logically append-only witness journal makes a
//! prepared-but-uncommitted transition visible after restart.

use std::error::Error as StdError;
use std::fmt;
use std::fs;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_control_plane::OrganMigrationError;
use codex_hepta_control_plane::OrganStateMigrationV1;
use codex_hepta_types::Digest32;

#[path = "cell_split_persistence.rs"]
mod persistence;
use persistence::JOURNAL_VERSION;
use persistence::JournalState;
use persistence::PersistedEnvelope;
use persistence::PersistedSnapshot;
use persistence::decode_phase;
use persistence::decode_state;
use persistence::encode_state;
use persistence::parse_digest;
use persistence::phase_name;
use persistence::validate_envelope;
use persistence::write_atomic;

const MAX_CHILDREN: usize = 32;
const MAX_COMPONENT_BYTES: usize = 64 * 1024;
const MAX_SNAPSHOT_BYTES: usize = 64 * 1024;

/// The committed checkpoint from which a split is allowed to proceed.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitCheckpointV1 {
    pub generation: u64,
    pub digest: Digest32,
    pub committed: bool,
}

/// A message which is still owned by the predecessor writer.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitInFlightMessageV1 {
    pub message_id: String,
    pub source_generation: u64,
    pub payload: Vec<u8>,
}

/// State owned by the parent cell. The selected weights are an immutable
/// reference; this owner never changes or selects them.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitParentStateV1 {
    pub checkpoint: CellSplitCheckpointV1,
    pub selected_weights: Digest32,
    pub recurrent_state: Vec<u8>,
    pub eligibility_state: Vec<u8>,
    pub optimizer_state: Vec<u8>,
    pub cache: Vec<u8>,
    pub cache_generation: u64,
    pub in_flight: Vec<CellSplitInFlightMessageV1>,
}

/// Candidate description supplied by an independently selected topology
/// proposal. A migration owner consumes this description but never selects it.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitChildSpecV1 {
    pub child_id: String,
    pub candidate_weights: Digest32,
    pub transform_digest: Digest32,
}

/// All bindings needed for one split. Generations and writer fences must be
/// exact; a later generation cannot reuse an older handoff.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitPlanV1 {
    pub parent_generation: u64,
    pub candidate_generation: u64,
    pub predecessor_writer_fence: u64,
    pub successor_writer_fence: u64,
    pub selected_weights: Digest32,
    pub migration_digest: Digest32,
    pub rollback_digest: Digest32,
    pub children: Vec<CellSplitChildSpecV1>,
}

/// The input presented to one child transform. Implementations must be
/// deterministic and candidate-only: they may derive state, but may not write
/// the parent or claim selection/activation authority.
pub struct CellSplitChildInputV1<'a> {
    pub spec: &'a CellSplitChildSpecV1,
    pub parent: &'a CellSplitParentStateV1,
    pub predecessor_generation: u64,
    pub candidate_generation: u64,
}

impl fmt::Debug for CellSplitChildInputV1<'_> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("CellSplitChildInputV1")
            .field("spec", self.spec)
            .field("parent", self.parent)
            .field("predecessor_generation", &self.predecessor_generation)
            .field("candidate_generation", &self.candidate_generation)
            .finish()
    }
}

/// A fully prepared child. The parent selected-weight digest is repeated so
/// the owner can prove that a child did not substitute a different model.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitChildStateV1 {
    pub child_id: String,
    pub candidate_weights: Digest32,
    pub selected_weights: Digest32,
    pub recurrent_state: Vec<u8>,
    pub eligibility_state: Vec<u8>,
    pub optimizer_state: Vec<u8>,
    pub cache: Vec<u8>,
    pub cache_generation: u64,
    pub message_fence: Digest32,
}

/// The state visible after a committed split. It contains candidate children,
/// but no selected-child or activation bit.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitCommittedStateV1 {
    pub parent: CellSplitParentStateV1,
    pub children: Vec<CellSplitChildStateV1>,
}

/// Child migration callbacks are state transforms only. They are deliberately
/// separate from topology selection and from the runtime's live host.
pub trait CellSplitChildMigrationV1: fmt::Debug + Send {
    fn child_id(&self) -> &str;

    fn migrate(
        &mut self,
        input: &CellSplitChildInputV1<'_>,
    ) -> Result<CellSplitChildStateV1, CellSplitMigrationError>;
}

/// Journal phase. Prepared, migrating and failed phases are unsafe to resume
/// blindly and therefore reopen as quarantined.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellSplitPhaseV1 {
    Empty,
    Prepared,
    Migrating,
    Committed,
    RolledBack,
    Quarantined,
}

/// Deterministic failure injection used by crash/restart tests and by host
/// qualification. It does not grant any production capability.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellSplitFailPointV1 {
    CrashAfterPrepare,
    Child(String),
    CompareAndSwap,
    Rollback,
}

/// Errors are intentionally typed around safety outcomes rather than exposing
/// filesystem or callback internals to the topology owner.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellSplitMigrationError {
    InvalidPlan(&'static str),
    InvalidState(&'static str),
    GenerationFence,
    WriterFence,
    InFlightNotFenced,
    SnapshotMismatch,
    SnapshotTooLarge { actual: usize },
    ChildFailed { child_id: String },
    PartialChild { child_id: String },
    ImmutableWeightsChanged { child_id: String },
    CacheGenerationMismatch { child_id: String },
    CompareAndSwap,
    JournalCorrupt,
    JournalIo,
    Quarantined,
    RollbackFailed,
    InjectedCrash,
}

impl fmt::Display for CellSplitMigrationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CellSplitMigrationError {}

#[derive(Debug)]
pub struct CellSplitMigrationOwnerV1 {
    plan: CellSplitPlanV1,
    handoff_plan_digest: Digest32,
    state: CellSplitCommittedStateV1,
    children: Vec<Box<dyn CellSplitChildMigrationV1>>,
    journal_path: Option<PathBuf>,
    journal: JournalState,
    phase: CellSplitPhaseV1,
    before_state: Option<CellSplitCommittedStateV1>,
    snapshot: Option<Vec<u8>>,
    failpoint: Option<CellSplitFailPointV1>,
}

impl CellSplitMigrationOwnerV1 {
    /// Construct a candidate-only owner over an already committed parent.
    pub fn new_in_memory(
        plan: CellSplitPlanV1,
        handoff_plan_digest: Digest32,
        parent: CellSplitParentStateV1,
        children: Vec<Box<dyn CellSplitChildMigrationV1>>,
    ) -> Result<Self, CellSplitMigrationError> {
        validate_plan(&plan, &parent, &children)?;
        Ok(Self {
            plan,
            handoff_plan_digest,
            state: CellSplitCommittedStateV1 {
                parent,
                children: Vec::new(),
            },
            children,
            journal_path: None,
            journal: JournalState {
                sequence: 0,
                head: Digest32::ZERO,
                witness: Digest32::ZERO,
            },
            phase: CellSplitPhaseV1::Empty,
            before_state: None,
            snapshot: None,
            failpoint: None,
        })
    }

    /// Create a durable owner. The journal is written with temp-file + fsync +
    /// rename, so a restart sees either the old envelope or the complete new
    /// envelope.
    pub fn create_persistent(
        path: impl AsRef<Path>,
        plan: CellSplitPlanV1,
        handoff_plan_digest: Digest32,
        parent: CellSplitParentStateV1,
        children: Vec<Box<dyn CellSplitChildMigrationV1>>,
    ) -> Result<Self, CellSplitMigrationError> {
        let mut owner = Self::new_in_memory(plan, handoff_plan_digest, parent, children)?;
        owner.journal_path = Some(path.as_ref().to_owned());
        owner.persist(CellSplitPhaseV1::Empty)?;
        Ok(owner)
    }

    /// Reopen a durable owner. An unfinished transition is never guessed to be
    /// successful: it is quarantined and must be reconciled by a fresh,
    /// independently authorized generation.
    pub fn reopen_persistent(
        path: impl AsRef<Path>,
        plan: CellSplitPlanV1,
        handoff_plan_digest: Digest32,
        children: Vec<Box<dyn CellSplitChildMigrationV1>>,
    ) -> Result<Self, CellSplitMigrationError> {
        let path = path.as_ref();
        let bytes = fs::read(path).map_err(|_| CellSplitMigrationError::JournalIo)?;
        let envelope: PersistedEnvelope =
            serde_json::from_slice(&bytes).map_err(|_| CellSplitMigrationError::JournalCorrupt)?;
        validate_envelope(&envelope)?;
        let state = decode_state(&envelope.state)?;
        validate_plan(&plan, &state.parent, &children)?;
        if envelope.writer_fence != plan.predecessor_writer_fence
            && envelope.writer_fence != plan.successor_writer_fence
        {
            return Err(CellSplitMigrationError::WriterFence);
        }
        let phase = decode_phase(&envelope.phase)?;
        let quarantined = matches!(
            phase,
            CellSplitPhaseV1::Prepared
                | CellSplitPhaseV1::Migrating
                | CellSplitPhaseV1::Quarantined
        );
        Ok(Self {
            plan,
            handoff_plan_digest,
            state,
            children,
            journal_path: Some(path.to_owned()),
            journal: JournalState {
                sequence: envelope.sequence,
                head: parse_digest(&envelope.head)?,
                witness: parse_digest(&envelope.witness)?,
            },
            phase: if quarantined {
                CellSplitPhaseV1::Quarantined
            } else {
                phase
            },
            before_state: None,
            snapshot: None,
            failpoint: None,
        })
    }

    pub fn state(&self) -> &CellSplitCommittedStateV1 {
        &self.state
    }

    pub fn phase(&self) -> CellSplitPhaseV1 {
        self.phase
    }

    pub fn is_quarantined(&self) -> bool {
        self.phase == CellSplitPhaseV1::Quarantined
    }

    pub fn journal_head(&self) -> Digest32 {
        self.journal.head
    }

    pub fn writer_fence(&self) -> u64 {
        match self.phase {
            CellSplitPhaseV1::Committed => self.plan.successor_writer_fence,
            _ => self.plan.predecessor_writer_fence,
        }
    }

    pub fn message_fence(&self) -> Digest32 {
        message_fence(&self.state.parent)
    }

    pub fn set_failpoint(&mut self, failpoint: CellSplitFailPointV1) {
        self.failpoint = Some(failpoint);
    }

    fn reject_if_quarantined(&self) -> Result<(), CellSplitMigrationError> {
        if self.is_quarantined() {
            Err(CellSplitMigrationError::Quarantined)
        } else {
            Ok(())
        }
    }

    fn persist(&mut self, phase: CellSplitPhaseV1) -> Result<(), CellSplitMigrationError> {
        let persisted = encode_state(&self.state)?;
        let next_sequence = self
            .journal
            .sequence
            .checked_add(1)
            .ok_or(CellSplitMigrationError::CompareAndSwap)?;
        let record = serde_json::to_vec(&(&next_sequence, phase_name(phase), &persisted))
            .map_err(|_| CellSplitMigrationError::JournalCorrupt)?;
        let next_head = Digest32::of_parts(&[self.journal.head.as_array(), &record]);
        let mut envelope = PersistedEnvelope {
            version: JOURNAL_VERSION,
            sequence: next_sequence,
            phase: phase_name(phase).to_owned(),
            writer_fence: match phase {
                CellSplitPhaseV1::Committed => self.plan.successor_writer_fence,
                _ => self.plan.predecessor_writer_fence,
            },
            head: next_head.to_string(),
            state: persisted,
            witness: String::new(),
        };
        let witness_bytes =
            serde_json::to_vec(&envelope).map_err(|_| CellSplitMigrationError::JournalCorrupt)?;
        let witness = Digest32::of_bytes(&witness_bytes);
        envelope.witness = witness.to_string();
        if let Some(path) = &self.journal_path {
            if path.exists() {
                let current = fs::read(path).map_err(|_| CellSplitMigrationError::JournalIo)?;
                let current: PersistedEnvelope = serde_json::from_slice(&current)
                    .map_err(|_| CellSplitMigrationError::JournalCorrupt)?;
                validate_envelope(&current)?;
                if parse_digest(&current.head)? != self.journal.head {
                    return Err(CellSplitMigrationError::CompareAndSwap);
                }
            }
            write_atomic(path, &envelope)?;
        }
        self.journal.sequence = next_sequence;
        self.journal.head = next_head;
        self.journal.witness = witness;
        Ok(())
    }

    fn quarantine(&mut self) {
        self.phase = CellSplitPhaseV1::Quarantined;
        let _ = self.persist(CellSplitPhaseV1::Quarantined);
    }
}

impl CellSplitParentStateV1 {
    /// Digest of the predecessor message queue. An empty queue is still bound
    /// to its checkpoint generation, so a child cannot claim a fence from a
    /// different predecessor.
    pub fn message_fence(&self) -> Digest32 {
        message_fence(self)
    }
}

impl OrganStateMigrationV1 for CellSplitMigrationOwnerV1 {
    fn snapshot(
        &mut self,
        predecessor: codex_hepta_types::Generation,
    ) -> Result<Vec<u8>, OrganMigrationError> {
        let predecessor = predecessor.get();
        self.reject_if_quarantined()
            .and_then(|_| {
                if self.phase != CellSplitPhaseV1::Empty {
                    return Err(CellSplitMigrationError::InvalidState("snapshot phase"));
                }
                if predecessor != self.plan.parent_generation
                    || self.state.parent.checkpoint.generation != predecessor
                {
                    return Err(CellSplitMigrationError::GenerationFence);
                }
                if self.plan.predecessor_writer_fence != predecessor
                    || !self.state.parent.checkpoint.committed
                {
                    return Err(CellSplitMigrationError::WriterFence);
                }
                if !self.state.parent.in_flight.is_empty() {
                    return Err(CellSplitMigrationError::InFlightNotFenced);
                }
                if self.state.parent.selected_weights != self.plan.selected_weights {
                    return Err(CellSplitMigrationError::ImmutableWeightsChanged {
                        child_id: "parent".to_owned(),
                    });
                }
                let persisted = encode_state(&self.state)?;
                let snapshot = PersistedSnapshot {
                    version: JOURNAL_VERSION,
                    plan_digest: plan_digest(&self.plan).to_string(),
                    predecessor_generation: predecessor,
                    candidate_generation: self.plan.candidate_generation,
                    state: persisted,
                };
                let bytes = serde_json::to_vec(&snapshot)
                    .map_err(|_| CellSplitMigrationError::JournalCorrupt)?;
                if bytes.len() > MAX_SNAPSHOT_BYTES {
                    return Err(CellSplitMigrationError::SnapshotTooLarge {
                        actual: bytes.len(),
                    });
                }
                self.before_state = Some(self.state.clone());
                self.snapshot = Some(bytes.clone());
                self.phase = CellSplitPhaseV1::Prepared;
                self.persist(CellSplitPhaseV1::Prepared)?;
                Ok(bytes)
            })
            .map_err(to_organ_error)
    }

    fn migrate(
        &mut self,
        snapshot: &[u8],
        predecessor: codex_hepta_types::Generation,
        candidate: codex_hepta_types::Generation,
    ) -> Result<(), OrganMigrationError> {
        let predecessor = predecessor.get();
        let candidate = candidate.get();
        let result =
            (|| {
                self.reject_if_quarantined()?;
                if self.phase != CellSplitPhaseV1::Prepared
                    || predecessor != self.plan.parent_generation
                    || candidate != self.plan.candidate_generation
                    || self.snapshot.as_deref() != Some(snapshot)
                {
                    return Err(CellSplitMigrationError::SnapshotMismatch);
                }
                if self.failpoint.as_ref().is_some_and(|failpoint| {
                    matches!(failpoint, CellSplitFailPointV1::CrashAfterPrepare)
                }) {
                    self.failpoint = None;
                    return Err(CellSplitMigrationError::InjectedCrash);
                }
                self.phase = CellSplitPhaseV1::Migrating;
                self.persist(CellSplitPhaseV1::Migrating)?;
                let parent = &self.state.parent;
                let mut prepared = Vec::with_capacity(self.plan.children.len());
                for spec in &self.plan.children {
                    if self.failpoint.as_ref().is_some_and(|failpoint| {
                    matches!(failpoint, CellSplitFailPointV1::Child(id) if id == &spec.child_id)
                }) {
                    self.failpoint = None;
                    return Err(CellSplitMigrationError::ChildFailed {
                        child_id: spec.child_id.clone(),
                    });
                }
                    let child = self
                        .children
                        .iter_mut()
                        .find(|child| child.child_id() == spec.child_id)
                        .ok_or_else(|| CellSplitMigrationError::PartialChild {
                            child_id: spec.child_id.clone(),
                        })?;
                    let input = CellSplitChildInputV1 {
                        spec,
                        parent,
                        predecessor_generation: predecessor,
                        candidate_generation: candidate,
                    };
                    let state = child.migrate(&input).map_err(|_| {
                        CellSplitMigrationError::ChildFailed {
                            child_id: spec.child_id.clone(),
                        }
                    })?;
                    validate_child(spec, &state, parent, candidate)?;
                    prepared.push(state);
                }
                if self.failpoint.as_ref().is_some_and(|failpoint| {
                    matches!(failpoint, CellSplitFailPointV1::CompareAndSwap)
                }) {
                    self.failpoint = None;
                    return Err(CellSplitMigrationError::CompareAndSwap);
                }
                self.state.children = prepared;
                self.persist(CellSplitPhaseV1::Committed)?;
                self.phase = CellSplitPhaseV1::Committed;
                Ok(())
            })();
        result.map_err(|error| {
            // Keep the in-memory predecessor available for the seam's
            // rollback callback. The journal remains in a non-terminal phase;
            // a restart will quarantine it rather than guessing success.
            if !matches!(&error, CellSplitMigrationError::InjectedCrash) {
                let _ = self.persist(CellSplitPhaseV1::Migrating);
            }
            to_organ_error(error)
        })
    }

    fn rollback(
        &mut self,
        snapshot: &[u8],
        predecessor: codex_hepta_types::Generation,
        candidate: codex_hepta_types::Generation,
    ) -> Result<(), OrganMigrationError> {
        let result = (|| {
            if self
                .failpoint
                .as_ref()
                .is_some_and(|failpoint| matches!(failpoint, CellSplitFailPointV1::Rollback))
            {
                self.failpoint = None;
                self.quarantine();
                return Err(CellSplitMigrationError::RollbackFailed);
            }
            if self.is_quarantined() {
                return Err(CellSplitMigrationError::Quarantined);
            }
            if self.snapshot.as_deref() != Some(snapshot)
                || predecessor.get() != self.plan.parent_generation
                || candidate.get() != self.plan.candidate_generation
            {
                return Err(CellSplitMigrationError::SnapshotMismatch);
            }
            let previous = self
                .before_state
                .take()
                .ok_or(CellSplitMigrationError::RollbackFailed)?;
            self.state = previous;
            self.snapshot = None;
            self.phase = CellSplitPhaseV1::RolledBack;
            if let Err(error) = self.persist(CellSplitPhaseV1::RolledBack) {
                self.quarantine();
                return Err(error);
            }
            Ok(())
        })();
        result.map_err(to_organ_error)
    }
}

impl crate::RuntimeTopologyMigrationOwnerV1 for CellSplitMigrationOwnerV1 {
    fn handoff_plan_digest(&self) -> Digest32 {
        self.handoff_plan_digest
    }
}

fn validate_plan(
    plan: &CellSplitPlanV1,
    parent: &CellSplitParentStateV1,
    children: &[Box<dyn CellSplitChildMigrationV1>],
) -> Result<(), CellSplitMigrationError> {
    if plan.parent_generation == 0
        || plan.candidate_generation != plan.parent_generation.saturating_add(1)
        || plan.predecessor_writer_fence != plan.parent_generation
        || plan.successor_writer_fence != plan.candidate_generation
    {
        return Err(CellSplitMigrationError::InvalidPlan("generation/fence"));
    }
    if !parent.checkpoint.committed
        || parent.checkpoint.generation != plan.parent_generation
        || parent.selected_weights != plan.selected_weights
    {
        return Err(CellSplitMigrationError::InvalidState("parent checkpoint"));
    }
    if plan.children.is_empty() || plan.children.len() > MAX_CHILDREN {
        return Err(CellSplitMigrationError::InvalidPlan("child count"));
    }
    let mut ids = std::collections::BTreeSet::new();
    for spec in &plan.children {
        if spec.child_id.is_empty() || !ids.insert(spec.child_id.clone()) {
            return Err(CellSplitMigrationError::InvalidPlan("child identity"));
        }
        if !children
            .iter()
            .any(|child| child.child_id() == spec.child_id)
        {
            return Err(CellSplitMigrationError::PartialChild {
                child_id: spec.child_id.clone(),
            });
        }
    }
    let mut callback_ids = std::collections::BTreeSet::new();
    for child in children {
        if !callback_ids.insert(child.child_id().to_owned()) {
            return Err(CellSplitMigrationError::InvalidPlan(
                "duplicate child callback",
            ));
        }
    }
    validate_bytes(parent)?;
    Ok(())
}

fn validate_bytes(parent: &CellSplitParentStateV1) -> Result<(), CellSplitMigrationError> {
    for bytes in [
        &parent.recurrent_state,
        &parent.eligibility_state,
        &parent.optimizer_state,
        &parent.cache,
    ] {
        if bytes.len() > MAX_COMPONENT_BYTES {
            return Err(CellSplitMigrationError::InvalidState("component bound"));
        }
    }
    for message in &parent.in_flight {
        if message.message_id.is_empty() || message.payload.len() > MAX_COMPONENT_BYTES {
            return Err(CellSplitMigrationError::InvalidState("message bound"));
        }
    }
    Ok(())
}

fn validate_child(
    spec: &CellSplitChildSpecV1,
    child: &CellSplitChildStateV1,
    parent: &CellSplitParentStateV1,
    candidate_generation: u64,
) -> Result<(), CellSplitMigrationError> {
    if child.child_id != spec.child_id {
        return Err(CellSplitMigrationError::PartialChild {
            child_id: spec.child_id.clone(),
        });
    }
    if child.candidate_weights != spec.candidate_weights {
        return Err(CellSplitMigrationError::PartialChild {
            child_id: spec.child_id.clone(),
        });
    }
    if child.selected_weights != parent.selected_weights {
        return Err(CellSplitMigrationError::ImmutableWeightsChanged {
            child_id: spec.child_id.clone(),
        });
    }
    if child.cache_generation != candidate_generation {
        return Err(CellSplitMigrationError::CacheGenerationMismatch {
            child_id: spec.child_id.clone(),
        });
    }
    if child.message_fence != parent.message_fence() {
        return Err(CellSplitMigrationError::PartialChild {
            child_id: spec.child_id.clone(),
        });
    }
    for bytes in [
        &child.recurrent_state,
        &child.eligibility_state,
        &child.optimizer_state,
        &child.cache,
    ] {
        if bytes.len() > MAX_COMPONENT_BYTES {
            return Err(CellSplitMigrationError::PartialChild {
                child_id: spec.child_id.clone(),
            });
        }
    }
    Ok(())
}

fn plan_digest(plan: &CellSplitPlanV1) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.runtime.cell-split-plan.v1\0");
    for value in [
        plan.parent_generation,
        plan.candidate_generation,
        plan.predecessor_writer_fence,
        plan.successor_writer_fence,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    for digest in [
        plan.selected_weights,
        plan.migration_digest,
        plan.rollback_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    for child in &plan.children {
        bytes.extend_from_slice(&(child.child_id.len() as u64).to_be_bytes());
        bytes.extend_from_slice(child.child_id.as_bytes());
        bytes.extend_from_slice(child.candidate_weights.as_array());
        bytes.extend_from_slice(child.transform_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn message_fence(parent: &CellSplitParentStateV1) -> Digest32 {
    let mut bytes = b"hepta.runtime.cell-split-message-fence.v1\0".to_vec();
    bytes.extend_from_slice(&parent.checkpoint.generation.to_be_bytes());
    for message in &parent.in_flight {
        bytes.extend_from_slice(&(message.message_id.len() as u64).to_be_bytes());
        bytes.extend_from_slice(message.message_id.as_bytes());
        bytes.extend_from_slice(&message.source_generation.to_be_bytes());
        bytes.extend_from_slice(Digest32::of_bytes(&message.payload).as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn to_organ_error(error: CellSplitMigrationError) -> OrganMigrationError {
    let suffix = match error {
        CellSplitMigrationError::ChildFailed { .. } => "child-failed",
        CellSplitMigrationError::RollbackFailed => "rollback-failed",
        CellSplitMigrationError::Quarantined => "quarantined",
        _ => "cell-split-rejected",
    };
    let Ok(id) = codex_hepta_types::StableId::new(format!("runtime.cell-split.{suffix}")) else {
        return OrganMigrationError::Rejected;
    };
    OrganMigrationError::Callback(id)
}

#[cfg(test)]
#[path = "cell_split_tests.rs"]
mod tests;
