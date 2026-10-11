//! Contract-only compact persistence seam for local development.
//!
//! This is a replayable append-only model of the Agent-local SQLite/WAL
//! transaction. It performs no file I/O, KG write, scheduler operation, or
//! external effect. A future authoritative writer may persist this exact
//! event shape after its own migration and caller review.

use std::collections::BTreeMap;

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use thiserror::Error;

use crate::CompactCheckpoint;
use crate::CompactCommitDecision;
use crate::CompactFence;
use crate::CompactParentSnapshot;
use crate::framing::frame_part;

// Version 2 binds every persisted event to the complete compact fence.  The
// previous v1 event shape only carried generation/token, which allowed a
// journal to be reopened under a different authority or owner epoch.  v1
// journals are intentionally not upgraded as trusted history; the SQLite
// migration leaves their epoch columns NULL and the loader rejects them.
pub const COMPACT_PERSISTENCE_SCHEMA_VERSION: u32 = 2;
pub const COMPACT_PERSISTENCE_NAMESPACE: &str = "local_development_only";
pub const COMPACT_PERSISTENCE_EXTERNAL_EFFECTS: bool = false;
pub const COMPACT_PERSISTENCE_KG_WRITE_AUTHORITY: bool = false;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CompactPersistenceState {
    Pending,
    Indeterminate,
    Committed,
    Rejected,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CompactReconcileOutcome {
    Committed,
    Rejected,
    StillIndeterminate,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum CompactPersistenceEventKind {
    Intent {
        checkpoint_id: String,
        checkpoint_revision: u64,
        checkpoint_sha256: Sha256Digest,
        parent_sha256: Sha256Digest,
    },
    CheckpointCommitted {
        checkpoint_sha256: Sha256Digest,
    },
    Indeterminate {
        reason_code: String,
    },
    Reconciled {
        outcome: CompactReconcileOutcome,
    },
    /// Durable local acknowledgement that the committed checkpoint's
    /// rehydration plan was replayed.  This is metadata only: it does not
    /// reconstruct KG state or claim an external effect.
    Rehydrated {
        checkpoint_sha256: Sha256Digest,
        expected_revision: u64,
    },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CompactPersistenceEvent {
    pub schema_version: u32,
    pub namespace: String,
    pub sequence: u64,
    pub operation_id: String,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub generation: u64,
    pub fencing_token: String,
    pub kind: CompactPersistenceEventKind,
    pub previous_sha256: Sha256Digest,
    pub event_sha256: Sha256Digest,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CompactPersistenceSnapshot {
    pub schema_version: u32,
    pub namespace: String,
    pub fence: CompactFence,
    pub entries: Vec<CompactPersistenceEvent>,
    pub head_sha256: Sha256Digest,
}

/// The append-only witness retained for a completed local rehydration replay.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CompactRehydrationRecord {
    pub sequence: u64,
    pub checkpoint_sha256: Sha256Digest,
    pub expected_revision: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CompactPersistenceAppend {
    Appended { sequence: u64 },
    Replay { sequence: u64 },
}

#[derive(Clone, Debug, Eq, PartialEq, Error)]
pub enum CompactPersistenceError {
    #[error("invalid compact persistence contract: {0}")]
    Invalid(String),
    #[error("compact persistence CAS conflict: {0}")]
    CasConflict(String),
    #[error("compact persistence stale generation or fence")]
    StaleFence,
    #[error("compact persistence illegal transition for {operation_id}: {message}")]
    IllegalTransition {
        operation_id: String,
        message: String,
    },
    #[error("compact persistence journal is corrupt: {0}")]
    Corrupt(String),
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct Binding {
    sequence: u64,
    checkpoint_id: String,
    checkpoint_revision: u64,
    checkpoint_sha256: Sha256Digest,
    parent_sha256: Sha256Digest,
}

#[derive(Clone, Debug)]
pub struct CompactPersistenceJournal {
    fence: CompactFence,
    entries: Vec<CompactPersistenceEvent>,
    head_sha256: Sha256Digest,
    bindings: BTreeMap<String, Binding>,
    states: BTreeMap<String, CompactPersistenceState>,
    rehydrations: BTreeMap<String, CompactRehydrationRecord>,
}

impl CompactPersistenceJournal {
    pub fn new(fence: CompactFence) -> Result<Self, CompactPersistenceError> {
        if fence.generation == 0 || fence.authority_epoch == 0 || fence.owner_epoch == 0 {
            return Err(invalid("fence epochs must be non-zero"));
        }
        validate_text(
            &fence.fencing_token,
            "fencing token",
            /*max_bytes*/ 256,
        )?;
        Ok(Self {
            fence,
            entries: Vec::new(),
            head_sha256: empty_digest(),
            bindings: BTreeMap::new(),
            states: BTreeMap::new(),
            rehydrations: BTreeMap::new(),
        })
    }

    pub fn fence(&self) -> &CompactFence {
        &self.fence
    }

    pub fn entries(&self) -> &[CompactPersistenceEvent] {
        &self.entries
    }

    pub fn state(&self, operation_id: &str) -> Option<CompactPersistenceState> {
        self.states.get(operation_id).copied()
    }

    pub fn rehydration(&self, operation_id: &str) -> Option<&CompactRehydrationRecord> {
        self.rehydrations.get(operation_id)
    }

    pub fn snapshot(&self) -> CompactPersistenceSnapshot {
        CompactPersistenceSnapshot {
            schema_version: COMPACT_PERSISTENCE_SCHEMA_VERSION,
            namespace: COMPACT_PERSISTENCE_NAMESPACE.to_string(),
            fence: self.fence.clone(),
            entries: self.entries.clone(),
            head_sha256: self.head_sha256.clone(),
        }
    }

    pub fn reopen(snapshot: CompactPersistenceSnapshot) -> Result<Self, CompactPersistenceError> {
        if snapshot.schema_version != COMPACT_PERSISTENCE_SCHEMA_VERSION
            || snapshot.namespace != COMPACT_PERSISTENCE_NAMESPACE
        {
            return Err(corrupt("snapshot schema or namespace mismatch"));
        }
        let mut journal = Self::new(snapshot.fence)?;
        for entry in snapshot.entries {
            journal.replay(entry)?;
        }
        if journal.head_sha256 != snapshot.head_sha256 {
            return Err(corrupt("snapshot head digest mismatch"));
        }
        Ok(journal)
    }

    pub fn append_intent(
        &mut self,
        operation_id: impl Into<String>,
        checkpoint: &CompactCheckpoint,
        current: &CompactParentSnapshot,
    ) -> Result<CompactPersistenceAppend, CompactPersistenceError> {
        let operation_id = operation_id.into();
        validate_text(&operation_id, "operation id", /*max_bytes*/ 512)?;
        if current.fence != self.fence {
            return Err(CompactPersistenceError::StaleFence);
        }
        match checkpoint.validate_against(current) {
            CompactCommitDecision::Accepted { .. } => {}
            CompactCommitDecision::Conflict { .. } => {
                return Err(CompactPersistenceError::CasConflict(
                    "parent snapshot changed".to_string(),
                ));
            }
            CompactCommitDecision::StaleGeneration => {
                return Err(CompactPersistenceError::StaleFence);
            }
            CompactCommitDecision::Rejected { .. } => {
                return Err(invalid("checkpoint payload rejected"));
            }
        }
        let checkpoint_sha256 = checkpoint_digest(checkpoint)?;
        let parent_sha256 = parent_digest(current);
        if let Some(binding) = self.bindings.get(&operation_id) {
            if binding.checkpoint_id == checkpoint.checkpoint_id
                && binding.checkpoint_revision == checkpoint.checkpoint_revision
                && binding.checkpoint_sha256 == checkpoint_sha256
                && binding.parent_sha256 == parent_sha256
            {
                return Ok(CompactPersistenceAppend::Replay {
                    sequence: binding.sequence,
                });
            }
            return Err(CompactPersistenceError::CasConflict(
                "operation replay changed its payload".to_string(),
            ));
        }
        let entry = self.make_entry(
            &operation_id,
            CompactPersistenceEventKind::Intent {
                checkpoint_id: checkpoint.checkpoint_id.clone(),
                checkpoint_revision: checkpoint.checkpoint_revision,
                checkpoint_sha256: checkpoint_sha256.clone(),
                parent_sha256: parent_sha256.clone(),
            },
        );
        let sequence = entry.sequence;
        self.head_sha256 = entry.event_sha256.clone();
        self.entries.push(entry);
        self.bindings.insert(
            operation_id.clone(),
            Binding {
                sequence,
                checkpoint_id: checkpoint.checkpoint_id.clone(),
                checkpoint_revision: checkpoint.checkpoint_revision,
                checkpoint_sha256,
                parent_sha256,
            },
        );
        self.states
            .insert(operation_id, CompactPersistenceState::Pending);
        Ok(CompactPersistenceAppend::Appended { sequence })
    }

    pub fn commit_checkpoint(
        &mut self,
        operation_id: &str,
        checkpoint_sha256: &Sha256Digest,
    ) -> Result<CompactPersistenceAppend, CompactPersistenceError> {
        let binding = self.binding(operation_id)?.clone();
        if binding.checkpoint_sha256 != *checkpoint_sha256 {
            return Err(CompactPersistenceError::CasConflict(
                "checkpoint digest differs from intent".to_string(),
            ));
        }
        match self.states.get(operation_id).copied() {
            Some(CompactPersistenceState::Pending) => {}
            Some(CompactPersistenceState::Committed) => {
                return Ok(CompactPersistenceAppend::Replay {
                    sequence: self.latest_sequence(operation_id),
                });
            }
            Some(state) => {
                return Err(illegal(
                    operation_id,
                    format!("cannot commit from {state:?}"),
                ));
            }
            None => return Err(corrupt("intent has no state")),
        }
        let entry = self.make_entry(
            operation_id,
            CompactPersistenceEventKind::CheckpointCommitted {
                checkpoint_sha256: checkpoint_sha256.clone(),
            },
        );
        let sequence = entry.sequence;
        self.head_sha256 = entry.event_sha256.clone();
        self.entries.push(entry);
        self.states
            .insert(operation_id.to_string(), CompactPersistenceState::Committed);
        Ok(CompactPersistenceAppend::Appended { sequence })
    }

    pub fn mark_indeterminate(
        &mut self,
        operation_id: &str,
        reason_code: impl Into<String>,
    ) -> Result<CompactPersistenceAppend, CompactPersistenceError> {
        let _ = self.binding(operation_id)?;
        let reason_code = reason_code.into();
        validate_text(&reason_code, "reason code", /*max_bytes*/ 256)?;
        match self.states.get(operation_id).copied() {
            Some(CompactPersistenceState::Pending)
            | Some(CompactPersistenceState::Indeterminate) => {}
            Some(state) => {
                return Err(illegal(
                    operation_id,
                    format!("cannot mark {state:?} indeterminate"),
                ));
            }
            None => return Err(corrupt("intent has no state")),
        }
        let entry = self.make_entry(
            operation_id,
            CompactPersistenceEventKind::Indeterminate { reason_code },
        );
        let sequence = entry.sequence;
        self.head_sha256 = entry.event_sha256.clone();
        self.entries.push(entry);
        self.states.insert(
            operation_id.to_string(),
            CompactPersistenceState::Indeterminate,
        );
        Ok(CompactPersistenceAppend::Appended { sequence })
    }

    pub fn reconcile(
        &mut self,
        operation_id: &str,
        outcome: CompactReconcileOutcome,
    ) -> Result<CompactPersistenceAppend, CompactPersistenceError> {
        let _ = self.binding(operation_id)?;
        if self.states.get(operation_id) != Some(&CompactPersistenceState::Indeterminate) {
            return Err(illegal(
                operation_id,
                "reconcile requires indeterminate state".to_string(),
            ));
        }
        let entry = self.make_entry(
            operation_id,
            CompactPersistenceEventKind::Reconciled { outcome },
        );
        let sequence = entry.sequence;
        self.head_sha256 = entry.event_sha256.clone();
        self.entries.push(entry);
        let state = match outcome {
            CompactReconcileOutcome::Committed => CompactPersistenceState::Committed,
            CompactReconcileOutcome::Rejected => CompactPersistenceState::Rejected,
            CompactReconcileOutcome::StillIndeterminate => CompactPersistenceState::Indeterminate,
        };
        self.states.insert(operation_id.to_string(), state);
        Ok(CompactPersistenceAppend::Appended { sequence })
    }

    /// Append an idempotent local rehydration witness for a committed
    /// checkpoint.  The witness is deliberately bounded to the exact intent
    /// digest and revision, so a restarted executor cannot acknowledge a
    /// different checkpoint under the same operation id.
    pub fn record_rehydration(
        &mut self,
        operation_id: &str,
        checkpoint_sha256: &Sha256Digest,
        expected_revision: u64,
    ) -> Result<CompactPersistenceAppend, CompactPersistenceError> {
        let binding = self.binding(operation_id)?.clone();
        if binding.checkpoint_sha256 != *checkpoint_sha256 {
            return Err(CompactPersistenceError::CasConflict(
                "rehydration digest differs from intent".to_string(),
            ));
        }
        if binding.checkpoint_revision != expected_revision {
            return Err(CompactPersistenceError::CasConflict(
                "rehydration revision differs from intent".to_string(),
            ));
        }
        if self.states.get(operation_id) != Some(&CompactPersistenceState::Committed) {
            return Err(illegal(
                operation_id,
                "rehydration requires committed state".to_string(),
            ));
        }
        if let Some(existing) = self.rehydrations.get(operation_id) {
            if existing.checkpoint_sha256 == *checkpoint_sha256
                && existing.expected_revision == expected_revision
            {
                return Ok(CompactPersistenceAppend::Replay {
                    sequence: existing.sequence,
                });
            }
            return Err(CompactPersistenceError::CasConflict(
                "operation rehydration replay changed its payload".to_string(),
            ));
        }
        let entry = self.make_entry(
            operation_id,
            CompactPersistenceEventKind::Rehydrated {
                checkpoint_sha256: checkpoint_sha256.clone(),
                expected_revision,
            },
        );
        let sequence = entry.sequence;
        self.head_sha256 = entry.event_sha256.clone();
        self.entries.push(entry);
        self.rehydrations.insert(
            operation_id.to_string(),
            CompactRehydrationRecord {
                sequence,
                checkpoint_sha256: checkpoint_sha256.clone(),
                expected_revision,
            },
        );
        Ok(CompactPersistenceAppend::Appended { sequence })
    }

    fn make_entry(
        &self,
        operation_id: &str,
        kind: CompactPersistenceEventKind,
    ) -> CompactPersistenceEvent {
        let sequence = self.entries.len() as u64 + 1;
        let mut entry = CompactPersistenceEvent {
            schema_version: COMPACT_PERSISTENCE_SCHEMA_VERSION,
            namespace: COMPACT_PERSISTENCE_NAMESPACE.to_string(),
            sequence,
            operation_id: operation_id.to_string(),
            authority_epoch: self.fence.authority_epoch,
            owner_epoch: self.fence.owner_epoch,
            generation: self.fence.generation,
            fencing_token: self.fence.fencing_token.clone(),
            kind,
            previous_sha256: self.head_sha256.clone(),
            event_sha256: empty_digest(),
        };
        entry.event_sha256 = event_digest(&entry);
        entry
    }

    fn replay(&mut self, entry: CompactPersistenceEvent) -> Result<(), CompactPersistenceError> {
        let expected = self.entries.len() as u64 + 1;
        if entry.sequence != expected {
            return Err(corrupt("journal sequence is not contiguous"));
        }
        if entry.schema_version != COMPACT_PERSISTENCE_SCHEMA_VERSION
            || entry.namespace != COMPACT_PERSISTENCE_NAMESPACE
            || entry.authority_epoch != self.fence.authority_epoch
            || entry.owner_epoch != self.fence.owner_epoch
            || entry.generation != self.fence.generation
            || entry.fencing_token != self.fence.fencing_token
            || entry.previous_sha256 != self.head_sha256
            || entry.event_sha256 != event_digest(&entry)
        {
            return Err(corrupt("event binding or digest mismatch"));
        }
        match &entry.kind {
            CompactPersistenceEventKind::Intent {
                checkpoint_id,
                checkpoint_revision,
                checkpoint_sha256,
                parent_sha256,
            } => {
                if self.bindings.contains_key(&entry.operation_id) {
                    return Err(corrupt("duplicate intent"));
                }
                validate_text(checkpoint_id, "checkpoint id", /*max_bytes*/ 512)
                    .map_err(|e| corrupt(e.to_string()))?;
                self.bindings.insert(
                    entry.operation_id.clone(),
                    Binding {
                        sequence: entry.sequence,
                        checkpoint_id: checkpoint_id.clone(),
                        checkpoint_revision: *checkpoint_revision,
                        checkpoint_sha256: checkpoint_sha256.clone(),
                        parent_sha256: parent_sha256.clone(),
                    },
                );
                self.states
                    .insert(entry.operation_id.clone(), CompactPersistenceState::Pending);
            }
            CompactPersistenceEventKind::CheckpointCommitted { checkpoint_sha256 } => {
                let binding = self.binding(&entry.operation_id)?;
                if binding.checkpoint_sha256 != *checkpoint_sha256
                    || self.states.get(&entry.operation_id)
                        != Some(&CompactPersistenceState::Pending)
                {
                    return Err(corrupt("commit transition is invalid"));
                }
                self.states.insert(
                    entry.operation_id.clone(),
                    CompactPersistenceState::Committed,
                );
            }
            CompactPersistenceEventKind::Indeterminate { reason_code } => {
                let _ = self.binding(&entry.operation_id)?;
                validate_text(reason_code, "reason code", /*max_bytes*/ 256)
                    .map_err(|e| corrupt(e.to_string()))?;
                if !matches!(
                    self.states.get(&entry.operation_id),
                    Some(CompactPersistenceState::Pending)
                        | Some(CompactPersistenceState::Indeterminate)
                ) {
                    return Err(corrupt("indeterminate transition is invalid"));
                }
                self.states.insert(
                    entry.operation_id.clone(),
                    CompactPersistenceState::Indeterminate,
                );
            }
            CompactPersistenceEventKind::Reconciled { outcome } => {
                let _ = self.binding(&entry.operation_id)?;
                if self.states.get(&entry.operation_id)
                    != Some(&CompactPersistenceState::Indeterminate)
                {
                    return Err(corrupt("reconcile transition is invalid"));
                }
                let state = match outcome {
                    CompactReconcileOutcome::Committed => CompactPersistenceState::Committed,
                    CompactReconcileOutcome::Rejected => CompactPersistenceState::Rejected,
                    CompactReconcileOutcome::StillIndeterminate => {
                        CompactPersistenceState::Indeterminate
                    }
                };
                self.states.insert(entry.operation_id.clone(), state);
            }
            CompactPersistenceEventKind::Rehydrated {
                checkpoint_sha256,
                expected_revision,
            } => {
                let binding = self.binding(&entry.operation_id)?;
                if binding.checkpoint_sha256 != *checkpoint_sha256
                    || binding.checkpoint_revision != *expected_revision
                    || self.states.get(&entry.operation_id)
                        != Some(&CompactPersistenceState::Committed)
                {
                    return Err(corrupt("rehydration transition is invalid"));
                }
                if self.rehydrations.contains_key(&entry.operation_id) {
                    return Err(corrupt("duplicate rehydration witness"));
                }
                self.rehydrations.insert(
                    entry.operation_id.clone(),
                    CompactRehydrationRecord {
                        sequence: entry.sequence,
                        checkpoint_sha256: checkpoint_sha256.clone(),
                        expected_revision: *expected_revision,
                    },
                );
            }
        }
        self.head_sha256 = entry.event_sha256.clone();
        self.entries.push(entry);
        Ok(())
    }

    fn binding(&self, operation_id: &str) -> Result<&Binding, CompactPersistenceError> {
        self.bindings
            .get(operation_id)
            .ok_or_else(|| illegal(operation_id, "intent does not exist".to_string()))
    }

    fn latest_sequence(&self, operation_id: &str) -> u64 {
        self.entries
            .iter()
            .rev()
            .find(|entry| entry.operation_id == operation_id)
            .map(|entry| entry.sequence)
            .unwrap_or(0)
    }
}

pub fn checkpoint_digest(
    checkpoint: &CompactCheckpoint,
) -> Result<Sha256Digest, CompactPersistenceError> {
    checkpoint
        .rehydration_plan(checkpoint.checkpoint_revision)
        .map_err(|e| invalid(e.to_string()))?;
    let mut hasher = Sha256::new();
    frame_part(
        &mut hasher,
        b"hepta-memory:compact-persistence:checkpoint:v1",
    );
    frame_part(&mut hasher, &checkpoint.schema_version.to_be_bytes());
    frame_part(&mut hasher, checkpoint.namespace.as_bytes());
    frame_part(&mut hasher, checkpoint.checkpoint_id.as_bytes());
    frame_part(
        &mut hasher,
        checkpoint.lease.lease_sha256.as_str().as_bytes(),
    );
    frame_part(&mut hasher, checkpoint.lease.snapshot.context_id.as_bytes());
    frame_part(
        &mut hasher,
        &checkpoint.lease.snapshot.parent_event_start.to_be_bytes(),
    );
    frame_part(
        &mut hasher,
        &checkpoint.lease.snapshot.parent_event_end.to_be_bytes(),
    );
    frame_part(
        &mut hasher,
        &checkpoint
            .lease
            .snapshot
            .expected_parent_revision
            .to_be_bytes(),
    );
    frame_part(
        &mut hasher,
        checkpoint
            .lease
            .snapshot
            .expected_state_sha256
            .as_str()
            .as_bytes(),
    );
    frame_part(
        &mut hasher,
        &checkpoint
            .lease
            .snapshot
            .fence
            .authority_epoch
            .to_be_bytes(),
    );
    frame_part(
        &mut hasher,
        &checkpoint.lease.snapshot.fence.owner_epoch.to_be_bytes(),
    );
    frame_part(
        &mut hasher,
        &checkpoint.lease.snapshot.fence.generation.to_be_bytes(),
    );
    frame_part(
        &mut hasher,
        checkpoint.lease.snapshot.fence.fencing_token.as_bytes(),
    );
    frame_part(
        &mut hasher,
        checkpoint.summary.summary_sha256.as_str().as_bytes(),
    );
    frame_part(
        &mut hasher,
        checkpoint.loss_report.report_sha256.as_str().as_bytes(),
    );
    frame_part(&mut hasher, &checkpoint.checkpoint_revision.to_be_bytes());
    let mut protected = checkpoint.protected_refs.iter().collect::<Vec<_>>();
    protected.sort_by(|left, right| left.ref_id.cmp(&right.ref_id));
    frame_part(
        &mut hasher,
        &u64::try_from(protected.len())
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    );
    for protected_ref in protected {
        frame_part(&mut hasher, protected_ref.ref_id.as_bytes());
        frame_part(&mut hasher, protected_ref.kind.as_bytes());
        frame_part(&mut hasher, &[u8::from(protected_ref.required)]);
    }
    Ok(Sha256Digest::from_sha256_output(hasher.finalize()))
}

fn parent_digest(snapshot: &CompactParentSnapshot) -> Sha256Digest {
    let mut hasher = Sha256::new();
    frame_part(&mut hasher, b"hepta-memory:compact-persistence:parent:v1");
    frame_part(&mut hasher, snapshot.context_id.as_bytes());
    frame_part(&mut hasher, &snapshot.parent_event_start.to_be_bytes());
    frame_part(&mut hasher, &snapshot.parent_event_end.to_be_bytes());
    frame_part(
        &mut hasher,
        &snapshot.expected_parent_revision.to_be_bytes(),
    );
    frame_part(
        &mut hasher,
        snapshot.expected_state_sha256.as_str().as_bytes(),
    );
    frame_part(&mut hasher, &snapshot.fence.authority_epoch.to_be_bytes());
    frame_part(&mut hasher, &snapshot.fence.owner_epoch.to_be_bytes());
    frame_part(&mut hasher, &snapshot.fence.generation.to_be_bytes());
    frame_part(&mut hasher, snapshot.fence.fencing_token.as_bytes());
    Sha256Digest::from_sha256_output(hasher.finalize())
}

fn event_digest(entry: &CompactPersistenceEvent) -> Sha256Digest {
    let mut hasher = Sha256::new();
    frame_part(&mut hasher, b"hepta-memory:compact-persistence:event:v1");
    frame_part(&mut hasher, &entry.sequence.to_be_bytes());
    frame_part(&mut hasher, entry.operation_id.as_bytes());
    frame_part(&mut hasher, &entry.authority_epoch.to_be_bytes());
    frame_part(&mut hasher, &entry.owner_epoch.to_be_bytes());
    frame_part(&mut hasher, &entry.generation.to_be_bytes());
    frame_part(&mut hasher, entry.fencing_token.as_bytes());
    frame_part(&mut hasher, entry.previous_sha256.as_str().as_bytes());
    match &entry.kind {
        CompactPersistenceEventKind::Intent {
            checkpoint_id,
            checkpoint_revision,
            checkpoint_sha256,
            parent_sha256,
        } => {
            frame_part(&mut hasher, b"intent");
            frame_part(&mut hasher, checkpoint_id.as_bytes());
            frame_part(&mut hasher, &checkpoint_revision.to_be_bytes());
            frame_part(&mut hasher, checkpoint_sha256.as_str().as_bytes());
            frame_part(&mut hasher, parent_sha256.as_str().as_bytes());
        }
        CompactPersistenceEventKind::CheckpointCommitted { checkpoint_sha256 } => {
            frame_part(&mut hasher, b"checkpoint-committed");
            frame_part(&mut hasher, checkpoint_sha256.as_str().as_bytes());
        }
        CompactPersistenceEventKind::Indeterminate { reason_code } => {
            frame_part(&mut hasher, b"indeterminate");
            frame_part(&mut hasher, reason_code.as_bytes());
        }
        CompactPersistenceEventKind::Reconciled { outcome } => {
            frame_part(&mut hasher, b"reconciled");
            frame_part(
                &mut hasher,
                match outcome {
                    CompactReconcileOutcome::Committed => b"committed",
                    CompactReconcileOutcome::Rejected => b"rejected",
                    CompactReconcileOutcome::StillIndeterminate => b"still-indeterminate",
                },
            );
        }
        CompactPersistenceEventKind::Rehydrated {
            checkpoint_sha256,
            expected_revision,
        } => {
            frame_part(&mut hasher, b"rehydrated");
            frame_part(&mut hasher, checkpoint_sha256.as_str().as_bytes());
            frame_part(&mut hasher, &expected_revision.to_be_bytes());
        }
    }
    Sha256Digest::from_sha256_output(hasher.finalize())
}

fn empty_digest() -> Sha256Digest {
    Sha256Digest::for_bytes(b"hepta-memory:compact-persistence:empty:v1")
}

fn validate_text(
    value: &str,
    label: &str,
    max_bytes: usize,
) -> Result<(), CompactPersistenceError> {
    if value.trim().is_empty() || value.len() > max_bytes || value.as_bytes().contains(&0) {
        return Err(invalid(format!(
            "{label} must contain 1..={max_bytes} non-NUL bytes"
        )));
    }
    Ok(())
}

fn invalid(message: impl Into<String>) -> CompactPersistenceError {
    CompactPersistenceError::Invalid(message.into())
}

fn corrupt(message: impl Into<String>) -> CompactPersistenceError {
    CompactPersistenceError::Corrupt(message.into())
}

fn illegal(operation_id: &str, message: String) -> CompactPersistenceError {
    CompactPersistenceError::IllegalTransition {
        operation_id: operation_id.to_string(),
        message,
    }
}
