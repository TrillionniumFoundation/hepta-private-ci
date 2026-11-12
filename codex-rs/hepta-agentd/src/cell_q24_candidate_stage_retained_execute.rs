//! Fresh evaluated retention effects stay behind the same actual Root gate.
//! Waiting only reads the original Version or C; it never renews a deadline,
//! resends a consumed Prepare, creates a grant, or starts C from a receipt.

use std::time::Duration;

use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use crate::OriginalCellQ24CandidateStageOwnersV1;
use crate::OriginalCircuitRetainedVersionErrorV1;
use crate::RootResidentLearningEffectGateV3;

use super::*;

impl Owners {
    pub(in super::super) async fn execute_evaluated_retained_stage(
        &self, snapshot: &LearningIterationSnapshotV1, stage: Stage,
    ) -> Result<LearningIterationReceiptV1, Error> {
        OriginalCellQ24CandidateStageOwnersV1::require_evaluated_retained_stage(snapshot, stage)?;
        if self.common.origin != Origin::Fresh { return Err(Error::WrongScope); }
        let started = auth::now()?;
        let gate = self.common.root.as_ref()
            .ok_or(Error::OwnerUnavailable("fresh resident evaluated retention continuation"))?;
        RootResidentLearningEffectGateV3::require_current(gate, snapshot, &self.common.material.scope).await?;
        let mut lane = self.retained.try_lock().map_err(|_| Error::QueueFull)?;
        if lane.failed { return Err(Error::CommitUncertain); }
        lane.failed = true;
        lane.refresh(self, snapshot).await?;
        lane.pins.as_ref().ok_or(Error::CommitUncertain)?.context.require_new_original_receipt(auth::now()?)
            .map_err(|_| Error::OwnerUnavailable("fresh original evaluated retention context"))?;
        let ready = match stage {
            Stage::Selection => {
                lane.prepare_retained_version(self, snapshot, gate).await?;
                lane.bind_selector(self)?;
                None
            },
            Stage::NextUse => {
                lane.read_selection(self, snapshot).await?;
                lane.bind_next_use(self)?;
                Some(lane.await_completed_c(self, snapshot, gate).await?)
            },
            _ => return Err(Error::WrongScope),
        };
        RootResidentLearningEffectGateV3::require_current(gate, snapshot, &self.common.material.scope).await?;
        lane.refresh(self, snapshot).await?;
        let fresh = auth::require_material(&self.common.material, self.common.initial_binding)?;
        auth::require_clock(started, fresh)?;
        let result = match stage {
            Stage::Selection => OriginalCircuitSelectionCommandClientV1::execute_selection(
                lane.selector.as_ref().ok_or(Error::CommitUncertain)?,
            ).await.map_err(auth::selector_failure).and_then(|original| {
                lane.pin_selection(self, snapshot, &original)?;
                Ok((original.receipt().clone(), original.attestation().clone()))
            }),
            Stage::NextUse => OriginalCircuitNextUseCommandClientV1::attest_completed_task(
                lane.next_use.as_ref().ok_or(Error::CommitUncertain)?,
            ).await.map_err(auth::next_use_failure).and_then(|original| {
                if ready.as_ref() != Some(&original.receipt().observation) { return Err(Error::CommitUncertain); }
                lane.pin_completion(self, snapshot, &original)?;
                Ok((original.receipt().clone(), original.attestation().clone()))
            }),
            _ => return Err(Error::WrongScope),
        };
        if RootResidentLearningEffectGateV3::require_current(gate, snapshot, &self.common.material.scope).await.is_err() {
            return Err(Error::CommitUncertain);
        }
        lane.require_published().await?;
        if stage == Stage::NextUse { lane.read_selection(self, snapshot).await?; }
        lane.refresh(self, snapshot).await?;
        let (receipt, signature) = result?;
        let fresh = auth::require_material(&self.common.material, self.common.initial_binding)?;
        auth::require_clock(started, fresh)?;
        auth::verify_receipt(&self.common.material, &receipt, &signature, fresh)?;
        self.require_live_deadline()?;
        lane.failed = false;
        Ok(receipt)
    }
}

impl EvaluatedContinuation {
    async fn prepare_retained_version(&mut self, owners: &Owners, snapshot: &LearningIterationSnapshotV1,
        gate: &RootResidentLearningEffectGateV3) -> Result<(), Error> {
        RootResidentLearningEffectGateV3::require_current(gate, snapshot, &owners.common.material.scope).await?;
        let client = self.version.as_ref().ok_or(Error::CommitUncertain)?;
        let cancellation = RootResidentLearningEffectGateV3::training_cancellation(gate);
        let dispatched = OriginalCircuitRetainedVersionClientV1::prepare_original_version(client, cancellation).await;
        if RootResidentLearningEffectGateV3::require_current(gate, snapshot, &owners.common.material.scope).await.is_err() {
            return Err(Error::CommitUncertain);
        }
        let mut actual = match dispatched {
            Ok(observed) => Some(observed),
            Err(OriginalCircuitRetainedVersionErrorV1::Busy
                | OriginalCircuitRetainedVersionErrorV1::ReadbackRequired
                | OriginalCircuitRetainedVersionErrorV1::CommitUncertain) => None,
            Err(_) => return Err(Error::CommitUncertain),
        };
        for _ in 0..128 {
            if actual.as_ref().is_some_and(|read| read.publication().is_some()) {
                self.refresh(owners, snapshot).await?;
                RootResidentLearningEffectGateV3::require_current(gate, snapshot, &owners.common.material.scope).await?;
                return Ok(());
            }
            tokio::time::sleep(Duration::from_secs(2)).await;
            RootResidentLearningEffectGateV3::require_current(gate, snapshot, &owners.common.material.scope).await?;
            actual = Some(OriginalCircuitRetainedVersionClientV1::readback(
                self.version.as_ref().ok_or(Error::CommitUncertain)?,
            ).await.map_err(|_| Error::CommitUncertain)?);
        }
        Err(Error::OwnerUnavailable("original evaluated Version readback frame budget"))
    }

    async fn await_completed_c(&mut self, owners: &Owners, snapshot: &LearningIterationSnapshotV1,
        gate: &RootResidentLearningEffectGateV3) -> Result<LearningIterationObservationV1, Error> {
        for _ in 0..128 {
            RootResidentLearningEffectGateV3::require_current(gate, snapshot, &owners.common.material.scope).await?;
            let current = OriginalCircuitCompletionReadinessClientV1::read_current(
                self.readiness.as_ref().ok_or(Error::CommitUncertain)?,
            ).await.map_err(|_| Error::OwnerUnavailable("actual original evaluated C readiness"))?;
            if let Some(ready) = current {
                self.read_selection(owners, snapshot).await?;
                self.refresh(owners, snapshot).await?;
                return Ok(ready.observation().clone());
            }
            tokio::time::sleep(Duration::from_secs(2)).await;
        }
        Err(Error::OwnerUnavailable("original evaluated C readiness frame budget"))
    }
}
