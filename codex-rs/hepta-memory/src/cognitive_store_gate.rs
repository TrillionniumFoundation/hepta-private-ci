//! Process-local whole-pool commit interlock for uncertain checkpoint outcomes.
//!
//! This is not an independently retained recovery witness. Production recovery
//! must still obtain its current cut and publisher-generation fence from the
//! protected host. There is deliberately no method to reopen this generation.

use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use super::CognitiveStoreError;

#[derive(Clone)]
pub(crate) struct CognitiveCommitGate(Arc<GateState>);

struct GateState {
    fenced: AtomicBool,
    managed: AtomicBool,
    dirty_permission: AtomicBool,
}

impl Default for CognitiveCommitGate {
    fn default() -> Self {
        Self(Arc::new(GateState {
            fenced: AtomicBool::new(false),
            managed: AtomicBool::new(false),
            dirty_permission: AtomicBool::new(true),
        }))
    }
}

impl CognitiveCommitGate {
    pub(crate) fn is_fenced(&self) -> bool {
        self.0.fenced.load(Ordering::SeqCst)
    }

    pub(crate) fn is_managed(&self) -> bool {
        self.0.managed.load(Ordering::SeqCst)
    }

    pub(crate) fn manage_commits(&self) {
        self.0.managed.store(true, Ordering::SeqCst);
        self.close_commits();
    }

    pub(crate) fn close_commits(&self) {
        self.0.dirty_permission.store(false, Ordering::SeqCst);
    }

    /// Only the shared coordinator may call this after validating an exact
    /// durable Dirty ACK. The permanent fence always takes precedence.
    pub(crate) fn allow_dirty_commits(&self) {
        self.0.dirty_permission.store(true, Ordering::SeqCst);
    }

    pub(crate) fn commit_allowed(&self) -> bool {
        !self.is_fenced() && self.0.dirty_permission.load(Ordering::SeqCst)
    }

    pub(crate) fn require_open(&self) -> Result<(), CognitiveStoreError> {
        if self.is_fenced() {
            return Err(CognitiveStoreError::Unavailable(
                "cognitive owner generation is fenced after uncertain checkpoint publication"
                    .to_string(),
            ));
        }
        Ok(())
    }

    /// Must be created while the original BEGIN IMMEDIATE transaction is held.
    /// That transaction proves no concurrent commit has already passed its
    /// hook. On drop, the atomic fence is installed before the caller can drop
    /// the transaction; all subsequently admitted commits then roll back.
    pub(crate) fn checkpoint_attempt(&self) -> CheckpointAttempt {
        self.transition_attempt()
    }

    /// Dirty invalidation also fences on uncertain/drop outcomes, even before
    /// a write transaction exists. Unlike publication, it cannot introduce a
    /// Current claim; its late completion only invalidates a recovery witness.
    pub(crate) fn transition_attempt(&self) -> CheckpointAttempt {
        CheckpointAttempt {
            gate: self.clone(),
            acknowledged: false,
        }
    }
}

pub(crate) struct CheckpointAttempt {
    gate: CognitiveCommitGate,
    acknowledged: bool,
}

impl CheckpointAttempt {
    pub(crate) fn acknowledge(mut self) {
        self.acknowledged = true;
    }
}

impl Drop for CheckpointAttempt {
    fn drop(&mut self) {
        if !self.acknowledged {
            self.gate.0.fenced.store(true, Ordering::SeqCst);
            self.gate.close_commits();
        }
    }
}
