//! Late binding consumes the initially held channels. Actual original D/T/B
//! and S determine each profile; no new transport or deadline is constructed.

use super::super::super::state::Continuation;
use super::Error;
use super::EvaluatedChannels;
use super::EvaluatedLane;
use super::Origin;
use super::Owners;
use super::Predecessors;
use crate::OriginalCircuitEvaluatedCompletionReadinessClientV1;
use crate::OriginalCircuitEvaluatedNextUseCommandClientV1;
use crate::OriginalCircuitEvaluatedSelectionCommandClientV1;
use crate::OriginalCircuitEvaluatedSelectionReceiptV1;
use crate::OriginalCircuitRetainedVersionClientV1;

impl EvaluatedLane {
    pub(super) fn ensure_version(
        &mut self,
        owners: &Owners,
        current: &Predecessors,
    ) -> Result<(), Error> {
        self.require_predecessors(current)?;
        if self.version.is_some() {
            return Ok(());
        }
        let EvaluatedChannels {
            version,
            selector,
            next_use,
            readiness,
        } = {
            let mut common = owners
                .common
                .continuation
                .try_lock()
                .map_err(|_| Error::QueueFull)?;
            Continuation::take_original_evaluated_channels(
                &mut common,
                &owners.common,
                &current.evaluation,
            )?
        };
        self.version = Some(match owners.common.origin {
            Origin::Fresh => OriginalCircuitRetainedVersionClientV1::bind_original_evaluated_stage_channel(
                version, &owners.common.material, &current.dataset, &current.training, &current.evaluation,
            ),
            Origin::Recovered => OriginalCircuitRetainedVersionClientV1::recover_original_evaluated_stage_channel(
                version, &owners.common.material, &current.dataset, &current.training, &current.evaluation,
            ),
        }.map_err(|_| Error::OwnerUnavailable("original evaluated Version binding"))?);
        self.selector_initial = Some(selector);
        self.next_use_initial = Some(next_use);
        self.readiness_initial = Some(readiness);
        self.predecessors = Some(current.clone());
        Ok(())
    }

    pub(super) fn ensure_selector(
        &mut self,
        owners: &Owners,
        current: &Predecessors,
    ) -> Result<(), Error> {
        self.require_predecessors(current)?;
        if self.selector.is_some() {
            return Ok(());
        }
        let channel = self.selector_initial.take().ok_or(Error::CommitUncertain)?;
        self.selector = Some(match owners.common.origin {
            Origin::Fresh => OriginalCircuitEvaluatedSelectionCommandClientV1::bind_original_stage_channel(
                channel, &owners.common.material, &current.dataset, &current.training, &current.evaluation,
            ),
            Origin::Recovered => OriginalCircuitEvaluatedSelectionCommandClientV1::recover_original_stage_channel(
                channel, &owners.common.material, &current.dataset, &current.training, &current.evaluation,
            ),
        }.map_err(super::selection::selector_failure)?);
        Ok(())
    }

    pub(super) fn ensure_next_use(
        &mut self,
        owners: &Owners,
        current: &Predecessors,
        selection: &OriginalCircuitEvaluatedSelectionReceiptV1,
    ) -> Result<(), Error> {
        self.require_predecessors(current)?;
        if self.next_use.is_some() {
            return Ok(());
        }
        let channel = self.next_use_initial.take().ok_or(Error::CommitUncertain)?;
        self.next_use = Some(
            match owners.common.origin {
                Origin::Fresh => {
                    OriginalCircuitEvaluatedNextUseCommandClientV1::bind_original_stage_channel(
                        channel,
                        &owners.common.material,
                        &current.dataset,
                        selection,
                    )
                }
                Origin::Recovered => {
                    OriginalCircuitEvaluatedNextUseCommandClientV1::recover_original_stage_channel(
                        channel,
                        &owners.common.material,
                        &current.dataset,
                        selection,
                    )
                }
            }
            .map_err(super::next_use::next_use_failure)?,
        );
        Ok(())
    }

    pub(super) fn ensure_readiness(
        &mut self,
        owners: &Owners,
        current: &Predecessors,
        selection: &OriginalCircuitEvaluatedSelectionReceiptV1,
    ) -> Result<(), Error> {
        self.require_predecessors(current)?;
        if self.readiness.is_some() {
            return Ok(());
        }
        let channel = self
            .readiness_initial
            .take()
            .ok_or(Error::CommitUncertain)?;
        self.readiness = Some(
            OriginalCircuitEvaluatedCompletionReadinessClientV1::bind_original_stage_channel(
                channel,
                &owners.common.material,
                &current.dataset,
                selection,
            )
            .map_err(|_| Error::OwnerUnavailable("original evaluated C readiness binding"))?,
        );
        Ok(())
    }
}
