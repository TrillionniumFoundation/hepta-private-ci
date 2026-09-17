//! Reopen-per-transaction handle for the inference control journal.
//!
//! The journal remains the single durable owner. Each mutation acquires the
//! exclusive file lock, replays the current cut, commits one bounded state
//! transition, fsyncs it and releases the lock before model/network work.

use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;

use crate::durable_control::DurableInferenceControl;
use crate::durable_control::Error;
use crate::durable_control::native::NativeDispatch;
use crate::durable_control::native::NativeRequest;
use crate::durable_control::native::NativeRunOutput;
use crate::durable_control::native::NativeRunRecord;

const WRITER_RETRY_ATTEMPTS: usize = 200;
const WRITER_RETRY_DELAY: Duration = Duration::from_millis(10);

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
        let mut operation = Some(operation);
        for attempt in 0..=WRITER_RETRY_ATTEMPTS {
            match DurableInferenceControl::open(&self.path, self.capacity) {
                Ok(mut control) => {
                    return operation
                        .take()
                        .expect("durable transaction operation is consumed once")(
                        &mut control,
                    );
                }
                Err(Error::WriterUnavailable) if attempt < WRITER_RETRY_ATTEMPTS => {
                    std::thread::sleep(WRITER_RETRY_DELAY);
                }
                Err(error) => return Err(error),
            }
        }
        Err(Error::WriterUnavailable)
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

#[cfg(test)]
mod tests {
    use std::sync::Arc;
    use std::sync::Barrier;

    use super::*;

    fn request(id: &str) -> NativeRequest {
        NativeRequest {
            request_id: id.to_string(),
            principal_id: "agent-one".to_string(),
            worker_generation: 1,
            model: "model-one".to_string(),
            payload_digest: "1".repeat(64),
        }
    }

    #[test]
    fn handle_does_not_retain_writer_lock_between_transactions() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("inference.journal");
        let handle = DurableInferenceControlHandle::new(&path, 16).unwrap();

        let second_writer = DurableInferenceControl::open(&path, 16)
            .expect("handle lifetime must not retain the journal writer lock");
        drop(second_writer);

        handle.reserve_native(request("r1"), 2).unwrap();
        assert!(handle.native_record("r1").unwrap().is_some());
    }

    #[test]
    fn concurrent_handles_share_one_budget_without_holding_model_length_lock() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("inference.journal");
        let handle = DurableInferenceControlHandle::new(&path, 16).unwrap();
        let barrier = Arc::new(Barrier::new(3));

        let mut threads = Vec::new();
        for id in ["r1", "r2"] {
            let handle = handle.clone();
            let barrier = Arc::clone(&barrier);
            threads.push(std::thread::spawn(move || {
                barrier.wait();
                handle.reserve_native(request(id), 2)
            }));
        }
        barrier.wait();
        for thread in threads {
            thread.join().unwrap().unwrap();
        }

        assert!(handle.native_record("r1").unwrap().is_some());
        assert!(handle.native_record("r2").unwrap().is_some());
        let third = handle.reserve_native(request("r3"), 2);
        assert_eq!(third.unwrap_err(), Error::CapacityExceeded);
    }
}
