//! Budget-owning execution handshake for the finite generation experiment.
//!
//! Values are supplied by an external finite Bellman solver. This owner
//! selects an action, charges its fixed cost, and requires fresh model feedback
//! before another decision. It does not execute a neural kernel, authenticate
//! supplied hashes, or grant production/model-dispatch authority.

use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FeedbackActionV1 {
    Emit,
    Refine,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct FeedbackActionValueV1 {
    pub action: FeedbackActionV1,
    /// Full continuation value, including any declared utility cost price.
    pub value: f64,
    pub cost_macs: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FeedbackSnapshotV1 {
    pub session_id: u64,
    pub version: u64,
    pub depth: u16,
    pub portfolio_index: u32,
    pub latent_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FeedbackGenerationConfigV1 {
    pub session_id: u64,
    /// Remaining dense Linear MACs after the separately charged initialization.
    pub budget_macs: u64,
    pub emit_macs: u64,
    pub refine_macs: u64,
    pub max_refinements: u16,
    pub portfolio_index: u32,
    pub latent_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FeedbackPhaseV1 {
    Ready,
    AwaitRefinement,
    AwaitOutputs,
    Sealed,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct FeedbackDecisionV1 {
    pub action: FeedbackActionV1,
    pub value: f64,
    pub version: u64,
    pub depth: u16,
    pub remaining_macs: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FeedbackGenerationError {
    InvalidConfiguration,
    InvalidTable,
    NonFiniteValue,
    CostMismatch,
    SnapshotMismatch,
    PendingExecution,
    Sealed,
    InvalidOutputs,
    InvalidProtocol,
    SessionSequence,
}

impl fmt::Display for FeedbackGenerationError {
    fn fmt(&self, output: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(output, "{self:?}")
    }
}

impl Error for FeedbackGenerationError {}

#[derive(Debug)]
pub struct FeedbackGenerationSessionV1 {
    config: FeedbackGenerationConfigV1,
    snapshot: FeedbackSnapshotV1,
    phase: FeedbackPhaseV1,
    remaining_macs: u64,
    output_digests: Option<[Digest32; 4]>,
}

impl FeedbackGenerationSessionV1 {
    pub fn new(config: FeedbackGenerationConfigV1) -> Result<Self, FeedbackGenerationError> {
        if config.session_id == 0
            || config.emit_macs == 0
            || config.refine_macs == 0
            || config.budget_macs < config.emit_macs
            || config.max_refinements > 64
            || config.portfolio_index > 65_535
            || config.latent_digest.is_zero()
        {
            return Err(FeedbackGenerationError::InvalidConfiguration);
        }
        Ok(Self {
            snapshot: FeedbackSnapshotV1 {
                session_id: config.session_id,
                version: 0,
                depth: 0,
                portfolio_index: config.portfolio_index,
                latent_digest: config.latent_digest,
            },
            remaining_macs: config.budget_macs,
            config,
            phase: FeedbackPhaseV1::Ready,
            output_digests: None,
        })
    }

    pub fn snapshot(&self) -> FeedbackSnapshotV1 {
        self.snapshot
    }

    pub fn phase(&self) -> FeedbackPhaseV1 {
        self.phase
    }

    pub fn remaining_macs(&self) -> u64 {
        self.remaining_macs
    }

    pub fn output_digests(&self) -> Option<[Digest32; 4]> {
        self.output_digests
    }

    pub fn choose(
        &mut self,
        snapshot: FeedbackSnapshotV1,
        actions: &[FeedbackActionValueV1],
    ) -> Result<FeedbackDecisionV1, FeedbackGenerationError> {
        match self.phase {
            FeedbackPhaseV1::Sealed => return Err(FeedbackGenerationError::Sealed),
            FeedbackPhaseV1::AwaitOutputs | FeedbackPhaseV1::AwaitRefinement => {
                return Err(FeedbackGenerationError::PendingExecution);
            }
            FeedbackPhaseV1::Ready => {}
        }
        if snapshot != self.snapshot {
            return Err(FeedbackGenerationError::SnapshotMismatch);
        }
        if actions.is_empty() || actions.len() > 2 {
            return Err(FeedbackGenerationError::InvalidTable);
        }
        let mut emit = None;
        let mut refine = None;
        for candidate in actions {
            if !candidate.value.is_finite() {
                return Err(FeedbackGenerationError::NonFiniteValue);
            }
            let (entry, cost) = match candidate.action {
                FeedbackActionV1::Emit => (&mut emit, self.config.emit_macs),
                FeedbackActionV1::Refine => (&mut refine, self.config.refine_macs),
            };
            if candidate.cost_macs != cost {
                return Err(FeedbackGenerationError::CostMismatch);
            }
            if entry.replace(*candidate).is_some() {
                return Err(FeedbackGenerationError::InvalidTable);
            }
        }
        let mut selected = emit.ok_or(FeedbackGenerationError::InvalidTable)?;
        if let Some(candidate) = refine
            && snapshot.depth < self.config.max_refinements
            && self
                .config
                .refine_macs
                .checked_add(self.config.emit_macs)
                .is_some_and(|cost| cost <= self.remaining_macs)
            && candidate.value > selected.value + 1e-12
        {
            selected = candidate;
        }
        self.remaining_macs -= selected.cost_macs;
        self.snapshot.version += 1;
        self.phase = match selected.action {
            FeedbackActionV1::Emit => FeedbackPhaseV1::AwaitOutputs,
            FeedbackActionV1::Refine => {
                self.snapshot.depth += 1;
                FeedbackPhaseV1::AwaitRefinement
            }
        };
        Ok(FeedbackDecisionV1 {
            action: selected.action,
            value: selected.value,
            version: self.snapshot.version,
            depth: self.snapshot.depth,
            remaining_macs: self.remaining_macs,
        })
    }

    pub fn confirm_refinement(
        &mut self,
        next: FeedbackSnapshotV1,
    ) -> Result<(), FeedbackGenerationError> {
        if self.phase == FeedbackPhaseV1::Sealed {
            return Err(FeedbackGenerationError::Sealed);
        }
        if self.phase != FeedbackPhaseV1::AwaitRefinement {
            return Err(FeedbackGenerationError::PendingExecution);
        }
        if next.latent_digest.is_zero()
            || next.session_id != self.snapshot.session_id
            || next.version != self.snapshot.version
            || next.depth != self.snapshot.depth
            || next.portfolio_index != self.snapshot.portfolio_index
        {
            return Err(FeedbackGenerationError::SnapshotMismatch);
        }
        self.snapshot = next;
        self.phase = FeedbackPhaseV1::Ready;
        Ok(())
    }

    /// Bind all four actual output hashes in text/audio/image/video order.
    /// These are caller-supplied integrity bindings, not signed attestations.
    pub fn confirm_emission(
        &mut self,
        session_id: u64,
        version: u64,
        outputs: [Digest32; 4],
    ) -> Result<(), FeedbackGenerationError> {
        if self.phase == FeedbackPhaseV1::Sealed {
            return Err(FeedbackGenerationError::Sealed);
        }
        if self.phase != FeedbackPhaseV1::AwaitOutputs {
            return Err(FeedbackGenerationError::PendingExecution);
        }
        if session_id != self.snapshot.session_id || version != self.snapshot.version {
            return Err(FeedbackGenerationError::SnapshotMismatch);
        }
        if outputs.into_iter().any(Digest32::is_zero) {
            return Err(FeedbackGenerationError::InvalidOutputs);
        }
        self.output_digests = Some(outputs);
        self.phase = FeedbackPhaseV1::Sealed;
        Ok(())
    }
}

#[cfg(test)]
#[path = "feedback_generation_tests.rs"]
mod tests;
