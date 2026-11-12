//! C waits on the separate actual readiness purpose. Only authenticated Ready
//! is followed by Observer dispatch. Cold recovery begins with original S
//! command readback and never polls the five-cut completed-task read profile.

use std::time::Duration;

use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;

use super::Action;
use super::Error;
use super::EvaluatedLane;
use super::Origin;
use super::Owners;
use super::Predecessors;
use super::auth;
use super::common_auth;
use crate::OriginalCircuitEvaluatedCompletionReadinessClientV1;
use crate::OriginalCircuitEvaluatedNextUseCommandClientV1;
use crate::OriginalCircuitEvaluatedNextUseCommandErrorV1;
use crate::OriginalCircuitEvaluatedNextUseReceiptV1;
use crate::OriginalCircuitEvaluatedSelectionCommandClientV1;
use crate::OriginalCircuitEvaluatedSelectionReceiptV1;
use crate::RootResidentLearningEffectGateV3;

impl Owners {
    pub(super) async fn original_evaluated_next_use(
        &self,
        supplied: &LearningIterationSnapshotV1,
        action: Action,
    ) -> Result<OriginalCircuitEvaluatedNextUseReceiptV1, Error> {
        let started = common_auth::now()?;
        self.require_live_deadline()?;
        let four_cut = self.evaluated_retention_prefix(supplied)?;
        if !(5..=6).contains(&supplied.receipts.len())
            || action == Action::Execute
                && (self.common.origin != Origin::Fresh || supplied.receipts.len() != 5)
        {
            return Err(Error::WrongScope);
        }
        let mut lane = self.retention.try_lock().map_err(|_| Error::QueueFull)?;
        if lane.failed || action == Action::Execute && lane.completion_requested {
            return Err(Error::CommitUncertain);
        }
        lane.failed = true;
        let before = self.evaluated_predecessors(&four_cut).await?;
        lane.ensure_version(self, &before)?;
        self.read_evaluated_version(&mut lane).await?;
        lane.ensure_selector(self, &before)?;
        // The actual S command read installs the host's immutable evidence pin.
        // This precedes C on fresh and cold routes; a supplied S DTO cannot do it.
        let selector = lane.selector.as_ref().ok_or(Error::CommitUncertain)?;
        let selection = OriginalCircuitEvaluatedSelectionCommandClientV1::readback(selector)
            .await
            .map_err(super::selection::selector_failure)?;
        if lane
            .selection
            .as_ref()
            .is_some_and(|saved| !auth::same_selection(saved, &selection))
            || action == Action::Execute && supplied != selection.snapshot()
        {
            return Err(Error::CommitUncertain);
        }
        self.verify_evaluated_selection(supplied, &before, &selection, common_auth::now()?)?;
        lane.ensure_next_use(self, &before, &selection)?;
        let ready = if action == Action::Execute {
            lane.ensure_readiness(self, &before, &selection)?;
            Some(
                self.await_evaluated_c(supplied, &mut lane, &before, &selection)
                    .await?,
            )
        } else {
            None
        };
        let dispatched = if action == Action::Execute {
            let gate = self.common.root.as_ref().ok_or(Error::CommitUncertain)?;
            RootResidentLearningEffectGateV3::require_current(
                gate,
                supplied,
                &self.common.material.scope,
            )
            .await?;
            lane.completion_requested = true;
            let observer = lane.next_use.as_ref().ok_or(Error::CommitUncertain)?;
            let result =
                OriginalCircuitEvaluatedNextUseCommandClientV1::attest_completed_task(observer)
                    .await;
            if RootResidentLearningEffectGateV3::require_current(
                gate,
                supplied,
                &self.common.material.scope,
            )
            .await
            .is_err()
            {
                return Err(Error::CommitUncertain);
            }
            Some(result.map_err(next_use_failure)?)
        } else {
            None
        };
        let after = self.evaluated_predecessors(&four_cut).await?;
        if before != after {
            return Err(Error::CommitUncertain);
        }
        lane.require_predecessors(&after)?;
        // Original Observer readback reads T/B/S and then the actual completed
        // Source/Cell again. It is the final predecessor-dependent I/O here.
        let observer = lane.next_use.as_ref().ok_or(Error::CommitUncertain)?;
        let current = OriginalCircuitEvaluatedNextUseCommandClientV1::readback(observer)
            .await
            .map_err(next_use_failure)?;
        let pin = auth::completion_pin(&current);
        if dispatched
            .as_ref()
            .is_some_and(|original| auth::completion_pin(original) != pin)
            || lane.completion.as_ref().is_some_and(|saved| saved != &pin)
            || ready
                .as_ref()
                .is_some_and(|observation| observation != &current.receipt().observation)
        {
            return Err(Error::CommitUncertain);
        }
        if action == Action::Execute {
            let gate = self.common.root.as_ref().ok_or(Error::CommitUncertain)?;
            if RootResidentLearningEffectGateV3::require_current(
                gate,
                supplied,
                &self.common.material.scope,
            )
            .await
            .is_err()
            {
                return Err(Error::CommitUncertain);
            }
        }
        let fresh =
            common_auth::require_material(&self.common.material, self.common.initial_binding)?;
        common_auth::require_clock(started, fresh)?;
        self.verify_evaluated_next_use(supplied, &after, &selection, &current, fresh)?;
        self.require_live_deadline()?;
        lane.selection = Some(selection);
        lane.completion = Some(pin);
        lane.failed = false;
        Ok(current)
    }

    async fn await_evaluated_c(
        &self,
        five_cut: &LearningIterationSnapshotV1,
        lane: &mut EvaluatedLane,
        before: &Predecessors,
        selection: &OriginalCircuitEvaluatedSelectionReceiptV1,
    ) -> Result<LearningIterationObservationV1, Error> {
        let gate = self.common.root.as_ref().ok_or(Error::CommitUncertain)?;
        for _ in 0..128 {
            RootResidentLearningEffectGateV3::require_current(
                gate,
                five_cut,
                &self.common.material.scope,
            )
            .await?;
            let readiness = lane.readiness.as_ref().ok_or(Error::CommitUncertain)?;
            let current =
                OriginalCircuitEvaluatedCompletionReadinessClientV1::read_current(readiness)
                    .await
                    .map_err(|_| {
                        Error::OwnerUnavailable("original evaluated C readiness CURRENT")
                    })?;
            if let Some(ready) = current {
                let after = self
                    .evaluated_predecessors(before.evaluation.snapshot())
                    .await?;
                if &after != before {
                    return Err(Error::CommitUncertain);
                }
                lane.require_predecessors(&after)?;
                let selector = lane.selector.as_ref().ok_or(Error::CommitUncertain)?;
                let current_selection =
                    OriginalCircuitEvaluatedSelectionCommandClientV1::readback(selector)
                        .await
                        .map_err(super::selection::selector_failure)?;
                if !auth::same_selection(selection, &current_selection) {
                    return Err(Error::CommitUncertain);
                }
                self.verify_evaluated_selection(
                    five_cut,
                    &after,
                    &current_selection,
                    common_auth::now()?,
                )?;
                RootResidentLearningEffectGateV3::require_current(
                    gate,
                    five_cut,
                    &self.common.material.scope,
                )
                .await?;
                return Ok(ready.observation().clone());
            }
            // Authenticated NotReady retains this same bounded connection.
            // Cancellation drops the future; no replacement transport exists.
            tokio::time::sleep(Duration::from_secs(2)).await;
        }
        Err(Error::OwnerUnavailable(
            "original evaluated C readiness frame budget",
        ))
    }
}

pub(super) fn next_use_failure(error: OriginalCircuitEvaluatedNextUseCommandErrorV1) -> Error {
    use OriginalCircuitEvaluatedNextUseCommandErrorV1 as Source;
    match error {
        Source::Missing | Source::Pending | Source::ReadbackRequired | Source::CommitUncertain => {
            Error::CommitUncertain
        }
        Source::DeadlineExceeded => Error::DeadlineExceeded,
        Source::Busy => Error::QueueFull,
        Source::Evidence(error) => Error::Evidence(error),
        Source::Binding(_) | Source::Iteration(_) | Source::Checkpoint(_) | Source::Encoding(_) => {
            Error::WrongScope
        }
        Source::Unavailable | Source::Transport(_) | Source::Owner(_) | Source::Retention(_) => {
            Error::OwnerUnavailable("original evaluated C Observer")
        }
    }
}
