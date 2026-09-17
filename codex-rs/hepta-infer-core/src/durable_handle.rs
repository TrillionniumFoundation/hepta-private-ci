//! Reopen-per-transaction handle for the inference control journal.
//!
//! The journal remains the single durable owner. Each mutation acquires the
//! exclusive file lock, replays the current cut, commits one bounded state
//! transition, fsyncs it and releases the lock before model/network work.

use std::path::Path;
use std::path::PathBuf;

use crate::durable_control::DurableInferenceControl;
use crate::durable_control::Error;
use crate::durable_control::native::NativeDispatch;
use crate::durable_control::native::NativeRequest;
use crate::durable_control::native::NativeRunOutput;
use crate::durable_control::native::NativeRunRecord;

#[derive(Clone, Debug)]
pub struct DurableInferenceControlHandle {
    path: PathBuf,
    capacity: usize,
}

impl DurableInferenceControlHandle {
    pub fn new(path: impl AsRef<Path>, capacity: usize) -> Result<Self, Error> {
        let path = path.as_ref().to_path_buf();
        // Validate configuration and on-disk state now, but do not retain the
        // writer lock after construction.
        drop(DurableInferenceControl::open(&path, capacity)?);
        Ok(Self { path, capacity })
    }

    pub fn journal_path(&self) -> &Path {
        &self.path
    }

    fn transaction<T>(
        &self,
        operation: impl FnOnce(&mut DurableInferenceControl) -> Result<T, Error>,
    ) -> Result<T, Error> {
        let mut control = DurableInferenceControl::open(&self.path, self.capacity)?;
        operation(&mut control)
    }

    pub fn reserve_native(
        &self,
        request: NativeRequest,
        maximum_in_flight: usize,
    ) -> Result<NativeRunRecord, Error> {
        self.transaction(|control| control.reserve_native(request, maximum_in_flight))
    }

    pub fn dispatch_native(
        &self,
        request_id: &str,
        dispatch: NativeDispatch,
    ) -> Result<NativeRunRecord, Error> {
        self.transaction(|control| control.dispatch_native(request_id, dispatch))
    }

    pub fn native_started(
        &self,
        request_id: &str,
        turn_id: String,
    ) -> Result<NativeRunRecord, Error> {
        self.transaction(|control| control.native_started(request_id, turn_id))
    }

    pub fn cancel_native(&self, request_id: &str) -> Result<NativeRunRecord, Error> {
        self.transaction(|control| control.cancel_native(request_id))
    }

    pub fn stop_native_before_dispatch(
        &self,
        request_id: &str,
        reason: String,
    ) -> Result<NativeRunRecord, Error> {
        self.transaction(|control| control.stop_native_before_dispatch(request_id, reason))
    }

    pub fn settle_native(
        &self,
        request_id: &str,
        output: NativeRunOutput,
    ) -> Result<NativeRunRecord, Error> {
        self.transaction(|control| control.settle_native(request_id, output))
    }

    pub fn native_record(&self, request_id: &str) -> Result<Option<NativeRunRecord>, Error> {
        self.transaction(|control| Ok(control.native_record(request_id).cloned()))
    }
}
