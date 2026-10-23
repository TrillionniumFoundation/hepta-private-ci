//! Process-local whole-pool commit interlock for uncertain checkpoint outcomes.
//!
//! This is not an independently retained recovery witness. Production recovery
//! must still obtain its current cut and publisher-generation fence from the
//! protected host. There is deliberately no method to reopen this generation.

use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use super::CognitiveStoreError;

#[derive(Clone, Default)]
pub(crate) struct CognitiveCommitGate(Arc<AtomicBool>);

impl CognitiveCommitGate {
    pub(crate) fn is_fenced(&self) -> bool {
        self.0.load(Ordering::SeqCst)
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
            self.gate.0.store(true, Ordering::SeqCst);
        }
    }
}
