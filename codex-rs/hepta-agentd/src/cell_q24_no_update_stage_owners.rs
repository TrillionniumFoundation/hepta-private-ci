//! Concrete ordinary-task composition of the original Material, Trainer,
//! retained-version Selector and completed-C Observer command owners.
//! This value has no key, journal writer, grant issuer or C execution port.

use std::sync::Arc;
use std::time::Instant;

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use tokio::sync::Mutex;

use crate::LearningIterationOwnerFutureV1;
use crate::LearningIterationRuntimeErrorV1;
use crate::LearningIterationStageOwnerPortsV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::PreparedLearningIterationProposalV1;
use crate::RootResidentLearningEffectGateV3;

#[path = "cell_q24_no_update_stage_inputs.rs"]
mod inputs;
#[path = "cell_q24_no_update_stage_state.rs"]
mod state;
#[path = "cell_q24_no_update_stage_execute.rs"]
mod execution;
#[path = "cell_q24_no_update_stage_auth.rs"]
mod auth;

pub use inputs::OriginalCellQ24NoUpdatePeerStreamV1;
pub use inputs::OriginalCellQ24NoUpdateStageStreamsV1;
pub use inputs::OriginalCellQ24NoUpdateTaskStreamV1;
use state::Continuation;

type Error = LearningIterationRuntimeErrorV1;

#[derive(Clone, Copy, Eq, PartialEq)]
pub(super) enum Origin {
    Fresh,
    Recovered,
}

/// Root consumes this value before installing its private fresh-CAS gate.
/// No Clone or owner getter lets a caller retain a dispatch surface afterward.
pub struct OriginalCellQ24NoUpdateStageOwnersV1 {
    material: OriginalCellQ24MaterialReceiptConfigV1,
    initial_binding: Digest32,
    origin: Origin,
    end: Instant,
    continuation: Mutex<Continuation>,
    root: Option<Arc<RootResidentLearningEffectGateV3>>,
}

impl OriginalCellQ24NoUpdateStageOwnersV1 {
    /// Descriptor checks are bounded synchronous I/O on the original host lane.
    /// All six original channels are bound now, before D/T/S or C completion.
    pub fn from_original_streams(
        material: OriginalCellQ24MaterialReceiptConfigV1,
        streams: OriginalCellQ24NoUpdateStageStreamsV1,
    ) -> Result<Self, Error> {
        inputs::bind(material, streams, Origin::Fresh)
    }

    /// Recovered channels may only read the original operation. Actual receipt
    /// and signature bytes are learned through original owner I/O, never upload.
    pub fn recover_original_streams(
        material: OriginalCellQ24MaterialReceiptConfigV1,
        streams: OriginalCellQ24NoUpdateStageStreamsV1,
    ) -> Result<Self, Error> {
        inputs::bind(material, streams, Origin::Recovered)
    }

    /// The Root resident registration compares the complete fixed operation
    /// before taking custody. This check does not grant execution.
    pub(crate) fn require_initial(
        &self,
        initial: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
        verifier: &LearningEvidenceVerifierV1,
    ) -> Result<(), Error> {
        if initial != &self.material.initial
            || scope.binding() != self.material.scope.binding()
            || verifier.trust_digest() != self.material.verifier.trust_digest()
            || verifier.scope_digest() != self.material.verifier.scope_digest()
            || verifier.objective_digest() != self.material.verifier.objective_digest()
        {
            return Err(Error::WrongScope);
        }
        auth::require_material(&self.material, self.initial_binding)?;
        Ok(())
    }

    /// Only the resident fresh-CAS factory calls this while it owns Self by
    /// value. Neither a recovered adapter nor a second install can gain work.
    pub(crate) fn install_fresh_resident_gate(
        &mut self,
        gate: Arc<RootResidentLearningEffectGateV3>,
    ) -> Result<(), Error> {
        if self.origin != Origin::Fresh || self.root.is_some() {
            return Err(Error::WrongScope);
        }
        self.root = Some(gate);
        Ok(())
    }
}

impl LearningIterationStageOwnerPortsV1 for OriginalCellQ24NoUpdateStageOwnersV1 {
    fn validate_recovery<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, ()> {
        Box::pin(async move {
            tokio::time::timeout_at(self.end.into(), async {
                auth::require_snapshot(&self.material, snapshot)?;
                let mut state = self.continuation.try_lock().map_err(|_| Error::QueueFull)?;
                state.read_prefix(self, snapshot).await?;
                auth::verify_prefix(&self.material, snapshot, &state, auth::now()?)
            }).await.map_err(|_| Error::CommitUncertain)?
        })
    }

    fn execute_stage<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
        stage: LearningIterationStageV1,
    ) -> LearningIterationOwnerFutureV1<'a, LearningIterationReceiptV1> {
        // Every fence check lives inside this future, at the actual I/O edge.
        Box::pin(async move {
            tokio::time::timeout_at(self.end.into(), async {
                self.execute_original_stage(snapshot, stage).await
            }).await.map_err(|_| Error::CommitUncertain)?
        })
    }

    fn prepare_proposal<'a>(
        &'a self,
        _snapshot: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, PreparedLearningIterationProposalV1> {
        Box::pin(async { Err(Error::OwnerUnavailable("NoUpdate assembly has no Model or Proposal authority")) })
    }

    fn receipt_attestation<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
        receipt: &'a LearningIterationReceiptV1,
        _now_unix_seconds: u64,
    ) -> LearningIterationOwnerFutureV1<'a, SignedLearningEvidenceV1> {
        Box::pin(async move {
            tokio::time::timeout_at(self.end.into(), async {
                let started_at = auth::now()?;
                auth::require_snapshot(&self.material, snapshot)?;
                let mut state = self.continuation.try_lock().map_err(|_| Error::QueueFull)?;
                let signature = state.read_attestation(self, snapshot, receipt).await?;
                let fresh = auth::now()?;
                auth::require_clock(started_at, fresh)?;
                auth::verify_receipt(&self.material, receipt, &signature, fresh)?;
                Ok(signature)
            }).await.map_err(|_| Error::CommitUncertain)?
        })
    }
}
