//! Read-only pins for the actual evaluated-retention four/five-stage cuts.
//! Only existing opaque T/B or S results construct this profile. It does not
//! deserialize a capability, publish a task, or promote recovered work.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::time::Duration;

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_types::Digest32;

use super::Error;
use super::OriginalCircuitLearningReadClientV1;
use super::OriginalCircuitLearningReadOwnerV1;
use super::now;
use super::profile::ReadProfile;
use super::wire;
use crate::AgentdIdentity;
use crate::AgentdRootAuthorityPeer;
use crate::CircuitTaskSourceReadbackV1;
use crate::OriginalCircuitEvaluatedRetentionContextV1;
use crate::OriginalCircuitEvaluatedSelectionReceiptV1;
use crate::PublishedCircuitCellOwnerV1;
use crate::learning_iteration_checkpoint::encode_original_owner_snapshot_v1;

enum OriginalCut {
    Selection(OriginalCircuitEvaluatedRetentionContextV1),
    NextUse(OriginalCircuitEvaluatedSelectionReceiptV1),
}

/// Fixed-purpose metadata from actual opaque original receipts. Cloning this
/// read-only profile neither clones a stream nor transfers signing custody.
pub struct OriginalCircuitEvaluatedLearningReadContextV1 {
    original: OriginalCut,
    scope: FrozenLearningScopeV2,
}

impl Clone for OriginalCircuitEvaluatedLearningReadContextV1 {
    fn clone(&self) -> Self {
        Self {
            original: match &self.original {
                OriginalCut::Selection(context) => {
                    OriginalCut::Selection(context.clone_for_original_receipt())
                }
                OriginalCut::NextUse(selection) => OriginalCut::NextUse(selection.clone()),
            },
            scope: self.scope.clone(),
        }
    }
}

impl OriginalCircuitEvaluatedLearningReadContextV1 {
    pub fn for_original_selection(
        context: OriginalCircuitEvaluatedRetentionContextV1,
    ) -> Result<Self, Error> {
        let context = context.into_original_receipt_readback();
        let (scope, _, _) = context.receipt_configuration();
        let profile = Self {
            original: OriginalCut::Selection(context),
            scope,
        };
        profile.binding(now()?)?;
        Ok(profile)
    }

    pub fn for_original_next_use(
        selection: OriginalCircuitEvaluatedSelectionReceiptV1,
    ) -> Result<Self, Error> {
        let selection = selection.into_original_receipt_readback();
        let (scope, _, _) = selection.original_context().receipt_configuration();
        let profile = Self {
            original: OriginalCut::NextUse(selection),
            scope,
        };
        profile.binding(now()?)?;
        Ok(profile)
    }

    pub(super) fn prefix(&self) -> &LearningIterationSnapshotV1 {
        match &self.original {
            OriginalCut::Selection(context) => context.snapshot(),
            OriginalCut::NextUse(selection) => selection.snapshot(),
        }
    }

    pub(super) fn scope(&self) -> &FrozenLearningScopeV2 {
        &self.scope
    }

    pub(super) fn mode(&self) -> wire::Mode {
        match &self.original {
            OriginalCut::Selection(_) => wire::Mode::Selection,
            OriginalCut::NextUse(_) => wire::Mode::NextUse,
        }
    }

    pub(super) fn binding(&self, at: u64) -> Result<Digest32, Error> {
        let (length, stage, domain, original) = match &self.original {
            OriginalCut::Selection(context) => {
                context
                    .original_receipt_predecessors(at)
                    .map_err(|_| Error::Binding("original evaluated read T/B signatures"))?;
                (
                    4,
                    LearningIterationStageV1::Selection,
                    b"selection".as_slice(),
                    context.receipt_context_binding(),
                )
            }
            OriginalCut::NextUse(selection) => {
                selection
                    .original_receipt_predecessors(at)
                    .map_err(|_| Error::Binding("original evaluated read T/B/S signatures"))?;
                (
                    5,
                    LearningIterationStageV1::NextUse,
                    b"next_use".as_slice(),
                    selection.original_receipt_binding(),
                )
            }
        };
        let prefix = self.prefix();
        let coordinator = LearningIterationCoordinatorV1::from_snapshot(prefix.clone())?;
        self.scope.validate_snapshot(prefix)?;
        if prefix.receipts.len() != length
            || coordinator.next_stage() != Some(stage)
            || prefix.training_no_update_v2().is_some()
            || coordinator.candidate().is_none()
            || coordinator.next_task_bundle() != Some(&prefix.request.selected_bundle)
        {
            return Err(Error::Binding("exact original evaluated read profile"));
        }
        Ok(Digest32::of_parts(&[
            b"hepta.agentd.original-circuit-evaluated-current-read.v1\0",
            domain,
            &encode_original_owner_snapshot_v1(prefix)?,
            self.scope.binding().as_array(),
            original.as_array(),
        ]))
    }

    pub(super) fn decision(&self) -> Result<LearningIterationCoordinatorV1, Error> {
        let context = match &self.original {
            OriginalCut::Selection(context) => context,
            OriginalCut::NextUse(selection) => selection.original_context(),
        };
        Ok(LearningIterationCoordinatorV1::from_snapshot(
            context.snapshot().clone(),
        )?)
    }

    pub(super) fn require_original_selection(
        &self,
        expected: &OriginalCircuitEvaluatedRetentionContextV1,
    ) -> Result<(), Error> {
        let OriginalCut::Selection(original) = &self.original else {
            return Err(Error::Binding("evaluated Selection-only read purpose"));
        };
        if original.snapshot() != expected.snapshot()
            || original.receipt_context_binding() != expected.receipt_context_binding()
        {
            return Err(Error::Binding("same original evaluated read T/B context"));
        }
        Ok(())
    }
    pub(super) fn require_original_next_use(
        &self,
        expected: &OriginalCircuitEvaluatedSelectionReceiptV1,
    ) -> Result<(), Error> {
        let OriginalCut::NextUse(original) = &self.original else {
            return Err(Error::Binding("evaluated NextUse-only read purpose"));
        };
        if original.snapshot() != expected.snapshot()
            || original.original_receipt_binding() != expected.original_receipt_binding()
        {
            return Err(Error::Binding("same original evaluated read T/B/S context"));
        }
        Ok(())
    }
}

impl OriginalCircuitLearningReadClientV1 {
    /// The original task's existing stream and held pidfd are consumed once.
    /// The evaluated profile cannot enter the legacy TNU readiness protocol.
    pub fn from_original_evaluated_stream(
        stream: UnixStream,
        original_task_process: AgentdRootAuthorityPeer,
        original_task_uid: u32,
        original_task_pidfd: OwnedFd,
        context: OriginalCircuitEvaluatedLearningReadContextV1,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        Self::from_original_profile(
            stream,
            original_task_process,
            original_task_uid,
            original_task_pidfd,
            ReadProfile::Evaluated(context),
            timeout,
            lifetime,
        )
    }

    pub(crate) fn require_original_evaluated_selection(
        &self,
        expected: &OriginalCircuitEvaluatedRetentionContextV1,
    ) -> Result<(), Error> {
        let ReadProfile::Evaluated(original) = &self.context else {
            return Err(Error::Binding("original evaluated read capability"));
        };
        original.require_original_selection(expected)
    }
    pub(crate) fn require_original_evaluated_next_use(
        &self,
        expected: &OriginalCircuitEvaluatedSelectionReceiptV1,
    ) -> Result<(), Error> {
        let ReadProfile::Evaluated(original) = &self.context else {
            return Err(Error::Binding("original evaluated read capability"));
        };
        original.require_original_next_use(expected)
    }
}

impl<C: AnchorWitnessStore, S: AnchorWitnessStore> OriginalCircuitLearningReadOwnerV1<C, S> {
    /// These are the existing original read-only owners, including any Clone
    /// views sharing their original journals. No file or writer is reopened.
    pub fn from_original_evaluated_owners(
        cell: PublishedCircuitCellOwnerV1<C>,
        source: CircuitTaskSourceReadbackV1<S>,
        identity: AgentdIdentity,
        context: OriginalCircuitEvaluatedLearningReadContextV1,
    ) -> Result<Self, Error> {
        Self::from_original_profile(cell, source, identity, ReadProfile::Evaluated(context))
    }
}
