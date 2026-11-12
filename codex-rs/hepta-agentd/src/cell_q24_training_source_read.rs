//! One readonly operation borrows the actual occupied Trainer lane. The two
//! real Material/Observer reads surround native/Generator I/O; no proof can
//! outlive that permit, be cloned, or authorize training and publication.

use std::sync::Arc;
use tokio::sync::OwnedSemaphorePermit;

use super::Error;
use super::OriginalCellQ24DatasetV1;
use super::OriginalCellQ24TrainingSourceV1;
use super::capture_binding;
use super::now;
use super::require_observations;
use super::require_same_material;
use super::verify_original_evidence;

pub(crate) struct OriginalSourceReadV1<'lane> {
    original: Arc<()>,
    before: OriginalCellQ24DatasetV1,
    started_at: u64,
    lane: &'lane OwnedSemaphorePermit,
}

pub(crate) struct OriginalSourceReadTailV1<'lane> {
    original: Arc<()>,
    started_at: u64,
    _lane: &'lane OwnedSemaphorePermit,
}

impl OriginalCellQ24TrainingSourceV1 {
    pub(crate) fn begin_readonly_in_lane<'lane>(
        &self,
        lane: &'lane OwnedSemaphorePermit,
    ) -> Result<OriginalSourceReadV1<'lane>, Error> {
        let started_at = now()?;
        verify_original_evidence(&self.config, started_at)?;
        let before = self.runtime.block_on(async {
            self.live.read_original_evidence(&self.config).await?;
            self.live
                .original
                .read_current_material(&self.config, &self.live.baseline)
                .await
        })?;
        require_observations(&self.config, &before)?;
        require_same_material(&self.material, &before)?;
        if capture_binding(&self.config, &before) != self.binding {
            return Err(Error::Binding("same original readonly source capture"));
        }
        let current = now()?;
        if current < started_at {
            return Err(Error::Binding("readonly source clock moved backwards"));
        }
        verify_original_evidence(&self.config, current)?;
        // The held allocation cannot be reused if the source is dropped.
        // A new actual capture always creates a separate private identity.
        Ok(OriginalSourceReadV1 {
            original: Arc::clone(&self.read_identity),
            before,
            started_at,
            lane,
        })
    }

    pub(crate) fn finish_readonly_in_lane<'lane>(
        &self,
        before: OriginalSourceReadV1<'lane>,
    ) -> Result<OriginalSourceReadTailV1<'lane>, Error> {
        if !Arc::ptr_eq(&self.read_identity, &before.original) {
            return Err(Error::Binding("same original readonly source instance"));
        }
        let after = self.runtime.block_on(async {
            self.live.read_original_evidence(&self.config).await?;
            self.live
                .original
                .read_current_material(&self.config, &self.live.baseline)
                .await
        })?;
        require_observations(&self.config, &after)?;
        require_same_material(&before.before, &after)?;
        require_same_material(&self.material, &after)?;
        if capture_binding(&self.config, &after) != self.binding {
            return Err(Error::Binding("same original readonly source capture"));
        }
        let current = now()?;
        if current < before.started_at {
            return Err(Error::Binding("readonly source clock moved backwards"));
        }
        verify_original_evidence(&self.config, current)?;
        Ok(OriginalSourceReadTailV1 {
            original: before.original,
            started_at: before.started_at,
            _lane: before.lane,
        })
    }

    /// Consume the second read only after the original native and Generator
    /// journals have been checked again. There is no I/O after this fresh check.
    pub(crate) fn authenticate_readonly_tail(
        &self,
        after: OriginalSourceReadTailV1<'_>,
    ) -> Result<(), Error> {
        if !Arc::ptr_eq(&self.read_identity, &after.original) {
            return Err(Error::Binding("same original readonly source instance"));
        }
        let current = now()?;
        if current < after.started_at {
            return Err(Error::Binding("readonly source clock moved backwards"));
        }
        verify_original_evidence(&self.config, current)
    }
}
