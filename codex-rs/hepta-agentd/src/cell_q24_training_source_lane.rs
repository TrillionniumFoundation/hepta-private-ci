//! Private evidence that the original lane has performed this invocation's
//! Source before read. No public callback, constructor, clone, or wire exists.

use std::marker::PhantomData;

#[cfg(target_os = "linux")]
use codex_hepta_neuron::AnchorWitnessStore;

#[cfg(target_os = "linux")]
use super::Error;
#[cfg(target_os = "linux")]
use crate::CellQ24TrainingOwnerErrorV1;
#[cfg(target_os = "linux")]
use crate::CellQ24TrainingOwnerV1;
#[cfg(target_os = "linux")]
use crate::cell_q24_training_source::OriginalCellQ24TrainingSourceOperationV1;

pub(super) struct SourceLaneProof<'a> {
    #[cfg(target_os = "linux")]
    operation: Option<&'a OriginalCellQ24TrainingSourceOperationV1<'a>>,
    _lane: PhantomData<&'a ()>,
}

impl<'a> SourceLaneProof<'a> {
    #[cfg(target_os = "linux")]
    pub(super) fn from_operation(
        operation: Option<&'a OriginalCellQ24TrainingSourceOperationV1<'a>>,
    ) -> Self {
        Self {
            operation,
            _lane: PhantomData,
        }
    }

    #[cfg(not(target_os = "linux"))]
    pub(super) fn legacy() -> Self {
        Self { _lane: PhantomData }
    }

    #[cfg(target_os = "linux")]
    pub(super) fn require_original<W: AnchorWitnessStore>(
        &self,
        training: &mut CellQ24TrainingOwnerV1<W>,
    ) -> Result<(), Error> {
        let operation = self.operation.ok_or(CellQ24TrainingOwnerErrorV1::Binding(
            "ordinary Training requires original source capture",
        ))?;
        training.require_original_source_operation(operation)?;
        Ok(())
    }
}

#[cfg(target_os = "linux")]
mod cancellation {
    use std::sync::Arc;
    use std::sync::atomic::AtomicBool;
    use std::sync::atomic::AtomicU8;
    use std::sync::atomic::Ordering;

    use super::super::Error;

    const SOURCE_BOUND: u8 = 1;
    const CANCELLED: u8 = 2;

    /// The async waiter retains this guard until its actual worker joins.
    /// Cancellation cannot release the worker's original semaphore permit.
    pub(in super::super) struct SourceLaneCancellation {
        state: Arc<AtomicU8>,
        stage_fenced: Arc<AtomicBool>,
        armed: bool,
    }

    pub(in super::super) struct SourceLaneCancellationState {
        state: Arc<AtomicU8>,
        stage_fenced: Arc<AtomicBool>,
    }

    impl SourceLaneCancellation {
        pub(in super::super) fn new(stage_fenced: Arc<AtomicBool>) -> Self {
            Self {
                state: Arc::new(AtomicU8::new(0)),
                stage_fenced,
                armed: true,
            }
        }

        pub(in super::super) fn worker(&self) -> SourceLaneCancellationState {
            SourceLaneCancellationState {
                state: Arc::clone(&self.state),
                stage_fenced: Arc::clone(&self.stage_fenced),
            }
        }

        pub(in super::super) fn joined(&mut self) {
            self.armed = false;
        }
    }

    impl Drop for SourceLaneCancellation {
        fn drop(&mut self) {
            if self.armed {
                let before = self.state.fetch_or(CANCELLED, Ordering::AcqRel);
                if before & SOURCE_BOUND != 0 {
                    self.stage_fenced.store(true, Ordering::Release);
                }
            }
        }
    }

    impl SourceLaneCancellationState {
        /// Called only after the native owner yielded its actual sealed Source.
        /// The shared atomic transition also handles cancellation before bind.
        pub(in super::super) fn bind_source(&self) -> Result<(), Error> {
            let before = self.state.fetch_or(SOURCE_BOUND, Ordering::AcqRel);
            if before & CANCELLED != 0 {
                self.stage_fenced.store(true, Ordering::Release);
                return Err(Error::CommitUncertain);
            }
            self.require_live()
        }

        pub(in super::super) fn require_live(&self) -> Result<(), Error> {
            if self.state.load(Ordering::Acquire) & CANCELLED != 0
                || self.stage_fenced.load(Ordering::Acquire)
            {
                return Err(Error::CommitUncertain);
            }
            Ok(())
        }

        pub(in super::super) fn stage_is_fenced(&self) -> bool {
            self.stage_fenced.load(Ordering::Acquire)
        }
    }
}

#[cfg(target_os = "linux")]
pub(super) use cancellation::SourceLaneCancellation;
