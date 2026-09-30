//! The lifecycle owner remains serialized in its existing blocking worker.

use std::future::Future;

use tokio::runtime::Handle;
use tokio::runtime::RuntimeFlavor;

use super::LocalFleetHost;
use crate::ProcessDriverError;

impl LocalFleetHost {
    pub(super) fn run<T>(&self, work: impl Future<Output = T>) -> Result<T, ProcessDriverError> {
        match Handle::try_current() {
            Ok(current) if current.runtime_flavor() == RuntimeFlavor::MultiThread => {
                // handle_request itself is polled by Handle::block_on on the
                // owner worker. Exit that runtime context before synchronously
                // polling SQL; the same owner permit stays held throughout.
                Ok(tokio::task::block_in_place(|| self.runtime.block_on(work)))
            }
            Ok(_) => Err(ProcessDriverError::new(
                "local resource callbacks require a multi-thread Tokio runtime",
            )),
            Err(_) => Ok(self.runtime.block_on(work)),
        }
    }
}

#[cfg(test)]
#[path = "local_fleet_runtime_tests.rs"]
mod tests;
