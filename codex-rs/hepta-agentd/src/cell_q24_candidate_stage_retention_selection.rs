//! Retained Version publication and evaluated Selection use the same admitted
//! Root intent. Post-effect authority loss is uncertain and fences this lane.

use std::time::Duration;

use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;

use super::Action;
use super::Error;
use super::EvaluatedLane;
use super::Origin;
use super::Owners;
use super::auth;
use super::common_auth;
use crate::OriginalCircuitEvaluatedSelectionCommandClientV1;
use crate::OriginalCircuitEvaluatedSelectionCommandErrorV1;
use crate::OriginalCircuitEvaluatedSelectionReceiptV1;
use crate::OriginalCircuitEvaluatedVersionProgressV1;
use crate::OriginalCircuitRetainedVersionClientV1;
use crate::OriginalCircuitRetainedVersionErrorV1;
use crate::RootResidentLearningEffectGateV3;

// Prepare, progress, and complete reads share the original 128-frame channel.
// Reserve the later S/C CURRENT reads after the mandatory complete readback.
// Progress itself cannot attest CURRENT or authorize Selection.
const VERSION_READBACK_RESERVE: usize = 8;

impl Owners {
    pub(super) async fn original_evaluated_selection(
        &self,
        supplied: &LearningIterationSnapshotV1,
        action: Action,
    ) -> Result<OriginalCircuitEvaluatedSelectionReceiptV1, Error> {
        let started = common_auth::now()?;
        self.require_live_deadline()?;
        let four_cut = self.evaluated_retention_prefix(supplied)?;
        if action == Action::Execute
            && (self.common.origin != Origin::Fresh || supplied != &four_cut)
        {
            return Err(Error::WrongScope);
        }
        let mut lane_lease = self.retention.try_take()?;
        let lane = lane_lease.state_mut()?;
        if lane.failed || action == Action::Execute && lane.selection_requested {
            return Err(Error::CommitUncertain);
        }
        // Every awaited path below leaves this bit set on cancellation or an
        // unknown result. Only complete original readback clears it.
        lane.failed = true;
        let before = self.evaluated_predecessors(&four_cut).await?;
        lane.ensure_version(self, &before)?;
        if action == Action::Execute {
            lane.selection_requested = true;
            self.prepare_evaluated_version(&four_cut, lane).await?;
        } else {
            self.read_evaluated_version(lane).await?;
        }
        // An actual Version publication is required before S can be bound.
        lane.ensure_selector(self, &before)?;
        let dispatched = if action == Action::Execute {
            let gate = self.common.root.as_ref().ok_or(Error::CommitUncertain)?;
            RootResidentLearningEffectGateV3::require_current(
                gate,
                &four_cut,
                &self.common.material.scope,
            )
            .await?;
            let selector = lane.selector.as_ref().ok_or(Error::CommitUncertain)?;
            let result =
                OriginalCircuitEvaluatedSelectionCommandClientV1::execute_selection(selector).await;
            if RootResidentLearningEffectGateV3::require_current(
                gate,
                &four_cut,
                &self.common.material.scope,
            )
            .await
            .is_err()
            {
                return Err(Error::CommitUncertain);
            }
            Some(result.map_err(selector_failure)?)
        } else {
            None
        };
        let after = self.evaluated_predecessors(&four_cut).await?;
        if before != after {
            return Err(Error::CommitUncertain);
        }
        lane.require_predecessors(&after)?;
        // The original S read itself re-reads T/B and then actual Source/Cell.
        // It follows the last predecessor await here, including on cold paths.
        let selector = lane.selector.as_ref().ok_or(Error::CommitUncertain)?;
        let current = OriginalCircuitEvaluatedSelectionCommandClientV1::readback(selector)
            .await
            .map_err(selector_failure)?;
        if dispatched
            .as_ref()
            .is_some_and(|original| !auth::same_selection(original, &current))
            || lane
                .selection
                .as_ref()
                .is_some_and(|saved| !auth::same_selection(saved, &current))
        {
            return Err(Error::CommitUncertain);
        }
        if action == Action::Execute {
            let gate = self.common.root.as_ref().ok_or(Error::CommitUncertain)?;
            if RootResidentLearningEffectGateV3::require_current(
                gate,
                &four_cut,
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
        self.verify_evaluated_selection(supplied, &after, &current, fresh)?;
        self.require_live_deadline()?;
        lane.selection = Some(current.clone());
        lane.failed = false;
        Ok(current)
    }

    async fn prepare_evaluated_version(
        &self,
        four_cut: &LearningIterationSnapshotV1,
        lane: &mut EvaluatedLane,
    ) -> Result<(), Error> {
        let gate = self.common.root.as_ref().ok_or(Error::CommitUncertain)?;
        RootResidentLearningEffectGateV3::require_current(
            gate,
            four_cut,
            &self.common.material.scope,
        )
        .await?;
        lane.take_version_request()?;
        let client = lane.version.as_ref().ok_or(Error::CommitUncertain)?;
        let result = OriginalCircuitRetainedVersionClientV1::prepare_original_version(
            client,
            RootResidentLearningEffectGateV3::training_cancellation(gate),
        )
        .await;
        if RootResidentLearningEffectGateV3::require_current(
            gate,
            four_cut,
            &self.common.material.scope,
        )
        .await
        .is_err()
        {
            return Err(Error::CommitUncertain);
        }
        let actual = match result {
            Ok(original) => Some(original),
            Err(
                OriginalCircuitRetainedVersionErrorV1::Busy
                | OriginalCircuitRetainedVersionErrorV1::ReadbackRequired
                | OriginalCircuitRetainedVersionErrorV1::CommitUncertain,
            ) => None,
            Err(_) => return Err(Error::CommitUncertain),
        };
        loop {
            if actual
                .as_ref()
                .is_some_and(|read| read.publication().is_some())
            {
                // The actual four-cut Root intent remains pending until S is
                // verified and checkpointed. Never ask it to accept future S.
                RootResidentLearningEffectGateV3::require_current(
                    gate,
                    four_cut,
                    &self.common.material.scope,
                )
                .await?;
                return Ok(());
            }
            if lane.version_requests >= 128 - VERSION_READBACK_RESERVE - 1 {
                return Err(Error::OwnerUnavailable(
                    "original evaluated Version wait frame budget",
                ));
            }
            // Only bounded progress follows Prepare while publication is pending.
            // The original host owns FinalUse; this lane cannot resend, obtain
            // a grant, or treat this scheduling hint as an original readback.
            tokio::time::sleep(Duration::from_secs(2)).await;
            RootResidentLearningEffectGateV3::require_current(
                gate,
                four_cut,
                &self.common.material.scope,
            )
            .await?;
            lane.take_version_request()?;
            let client = lane.version.as_ref().ok_or(Error::CommitUncertain)?;
            let progress =
                OriginalCircuitRetainedVersionClientV1::publication_progress(client).await;
            if RootResidentLearningEffectGateV3::require_current(
                gate,
                four_cut,
                &self.common.material.scope,
            )
            .await
            .is_err()
            {
                return Err(Error::CommitUncertain);
            }
            match progress {
                Ok(OriginalCircuitEvaluatedVersionProgressV1::Pending)
                | Err(OriginalCircuitRetainedVersionErrorV1::Busy) => {}
                Ok(OriginalCircuitEvaluatedVersionProgressV1::ReadbackAvailable) => {
                    // A scheduling hint grants nothing. The same original
                    // channel must return a complete, actual publication.
                    self.read_evaluated_version(lane).await?;
                    if RootResidentLearningEffectGateV3::require_current(
                        gate,
                        four_cut,
                        &self.common.material.scope,
                    )
                    .await
                    .is_err()
                    {
                        return Err(Error::CommitUncertain);
                    }
                    return Ok(());
                }
                Err(_) => return Err(Error::CommitUncertain),
            }
        }
    }

    pub(super) async fn read_evaluated_version(
        &self,
        lane: &mut EvaluatedLane,
    ) -> Result<(), Error> {
        lane.take_version_request()?;
        let client = lane.version.as_ref().ok_or(Error::CommitUncertain)?;
        let actual = OriginalCircuitRetainedVersionClientV1::readback(client)
            .await
            .map_err(|_| Error::CommitUncertain)?;
        if actual.publication().is_none() {
            return Err(Error::OwnerUnavailable(
                "original evaluated Version awaits FinalUse",
            ));
        }
        Ok(())
    }
}

pub(super) fn selector_failure(error: OriginalCircuitEvaluatedSelectionCommandErrorV1) -> Error {
    use OriginalCircuitEvaluatedSelectionCommandErrorV1 as Source;
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
        Source::Unavailable
        | Source::Transport(_)
        | Source::Owner(_)
        | Source::Retention(_)
        | Source::Readback(_) => Error::OwnerUnavailable("original evaluated Selector"),
    }
}
