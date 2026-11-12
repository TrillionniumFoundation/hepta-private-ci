//! One borrowed Source read interval inside the original occupied native lane.
//! The proof is neither cloneable nor serializable. It owns no writer, journal,
//! key, callback, or new connection. Every invocation performs its own reads.

use std::sync::atomic::Ordering;

use super::*;

const IDLE: u8 = 0;
const ACTIVE: u8 = 1;
const FENCED: u8 = 2;

enum Phase {
    BeforeRead,
    NativeWork,
    ReadingAfter,
    AfterRead,
    Finished,
}

/// Only begin_source_operation creates this value, after fresh original I/O.
/// Its lifetime borrows the same Source Arc held by the occupied native owner.
pub(crate) struct OriginalCellQ24TrainingSourceOperationV1<'a> {
    source: &'a Arc<OriginalCellQ24TrainingSourceV1>,
    config: Arc<OriginalCellQ24TrainingSourceConfigV1>,
    baseline: Arc<LoadedCellQ24ModelV1>,
    before: Option<OriginalCellQ24DatasetV1>,
    started_at: u64,
    phase: Phase,
}

impl OriginalCellQ24TrainingSourceV1 {
    /// Retain the same original clients and read each one once before native
    /// work. Independent require_current_in_lane still performs its full pair.
    pub(crate) fn begin_source_operation(
        source: &Arc<Self>,
    ) -> Result<OriginalCellQ24TrainingSourceOperationV1<'_>, Error> {
        source
            .operation_state
            .compare_exchange(IDLE, ACTIVE, Ordering::AcqRel, Ordering::Acquire)
            .map_err(|state| {
                if state == FENCED {
                    Error::CaptureUncertain
                } else {
                    Error::Busy
                }
            })?;
        let mut operation = OriginalCellQ24TrainingSourceOperationV1 {
            source,
            config: Arc::clone(&source.config),
            baseline: Arc::clone(&source.live.baseline),
            before: None,
            started_at: 0,
            phase: Phase::BeforeRead,
        };
        operation.started_at = now()?;
        let before = source
            .runtime
            .block_on(source.live.material_once_for_operation(&operation.config))?;
        require_same_material(&source.material, &before)?;
        if capture_binding(&operation.config, &before) != source.binding {
            return Err(Error::Binding("same original capture identity"));
        }
        operation.before = Some(before);
        operation.phase = Phase::NativeWork;
        operation.require_original_source(source)?;
        Ok(operation)
    }

    pub(crate) fn source_operation_fenced(&self) -> bool {
        self.operation_state.load(Ordering::Acquire) == FENCED
    }
}

impl OriginalCellQ24TrainingSourceOperationV1<'_> {
    /// This private proof is only useful during the same native invocation.
    /// It cannot authorize a second operation or a different owner/config Arc.
    pub(crate) fn require_original_source(
        &self,
        source: &Arc<OriginalCellQ24TrainingSourceV1>,
    ) -> Result<(), Error> {
        if !matches!(self.phase, Phase::NativeWork) {
            return Err(Error::Binding("source operation already consumed"));
        }
        self.require_same_identity(source)?;
        self.require_fresh()
    }

    fn require_same_identity(
        &self,
        source: &Arc<OriginalCellQ24TrainingSourceV1>,
    ) -> Result<(), Error> {
        if !Arc::ptr_eq(self.source, source)
            || !Arc::ptr_eq(&self.config, &source.config)
            || !Arc::ptr_eq(&self.baseline, &source.live.baseline)
            || source.operation_state.load(Ordering::Acquire) != ACTIVE
        {
            return Err(Error::Binding("same original source operation custody"));
        }
        let before = self
            .before
            .as_ref()
            .ok_or(Error::Binding("completed original source before read"))?;
        require_same_material(&source.material, before)?;
        if capture_binding(&self.config, before) != source.binding {
            return Err(Error::Binding("complete original source operation binding"));
        }
        Ok(())
    }

    /// Called once after the actual native work, even when work returned Err.
    /// A failure leaves the operation armed; Drop permanently fences its Source.
    pub(crate) fn read_after_native(
        &mut self,
        source: &Arc<OriginalCellQ24TrainingSourceV1>,
    ) -> Result<(), Error> {
        self.require_original_source(source)?;
        self.phase = Phase::ReadingAfter;
        let after = source
            .runtime
            .block_on(source.live.material_once_for_operation(&self.config))?;
        let before = self
            .before
            .as_ref()
            .ok_or(Error::Binding("completed original source before read"))?;
        require_same_material(before, &after)?;
        require_same_material(&source.material, &after)?;
        if capture_binding(&self.config, &after) != source.binding {
            return Err(Error::Binding("same original capture identity after native work"));
        }
        self.phase = Phase::AfterRead;
        self.require_same_identity(source)?;
        self.require_fresh()
    }

    /// Consume only after the native and Generator physical tail rereads.
    /// Fresh authentication follows that last I/O; no RPC result is a lease.
    pub(crate) fn finish(
        mut self,
        source: &Arc<OriginalCellQ24TrainingSourceV1>,
    ) -> Result<(), Error> {
        if !matches!(self.phase, Phase::AfterRead) {
            return Err(Error::Binding("source operation requires its after read"));
        }
        self.require_same_identity(source)?;
        self.require_fresh()?;
        source.operation_state.store(IDLE, Ordering::Release);
        self.phase = Phase::Finished;
        Ok(())
    }

    fn require_fresh(&self) -> Result<(), Error> {
        let fresh_now = now()?;
        if fresh_now < self.started_at {
            return Err(Error::Binding("source operation clock moved backwards"));
        }
        verify_original_evidence(&self.config, fresh_now)?;
        OriginalCellQ24DatasetV1::require_original_freeze_current(
            &self.source.material,
            &self.config,
            fresh_now,
        )
        .map_err(|_| Error::Binding("fresh original source freeze"))?;
        Ok(())
    }
}

impl Drop for OriginalCellQ24TrainingSourceOperationV1<'_> {
    fn drop(&mut self) {
        if !matches!(self.phase, Phase::Finished) {
            self.source
                .operation_state
                .store(FENCED, Ordering::Release);
        }
    }
}

impl LiveOwners {
    /// One physical read per original channel, used only by this sealed
    /// before/after operation. Standalone current_material remains unchanged.
    async fn material_once_for_operation(
        &self,
        config: &OriginalCellQ24TrainingSourceConfigV1,
    ) -> Result<OriginalCellQ24DatasetV1, Error> {
        let started_at = now()?;
        verify_original_evidence(config, started_at)?;
        self.read_original_evidence(config).await?;
        let material = self
            .original
            .read_current_material(config, &self.baseline)
            .await?;
        require_observations(config, &material)?;
        let fresh_now = now()?;
        if fresh_now < started_at {
            return Err(Error::Binding("source operation read clock moved backwards"));
        }
        verify_original_evidence(config, fresh_now)?;
        OriginalCellQ24DatasetV1::require_original_freeze_current(&material, config, fresh_now)
            .map_err(|_| Error::Binding("fresh original source freeze"))?;
        Ok(material)
    }
}
