//! Process-local exclusion between an operation's live execution and recovery.
//! The registry's OS owner lock supplies cross-process exclusion; this guard
//! never holds a mutex during provider I/O, callbacks, or an await point.
use super::*;
use std::collections::BTreeSet;
use std::sync::Mutex;

#[derive(Default)]
pub(super) struct ExecutionSet(Arc<Mutex<BTreeSet<String>>>);

pub(crate) struct ConsumptionExecutionGuard {
    active: Arc<Mutex<BTreeSet<String>>>,
    operation_id: String,
    _owner_lock: Arc<File>,
}

impl Drop for ConsumptionExecutionGuard {
    fn drop(&mut self) {
        // A poisoned set stays fail-closed; recovering it must not permit entry.
        if let Ok(mut active) = self.active.lock() {
            active.remove(&self.operation_id);
        }
    }
}

impl DurableLeaseRegistryV1 {
    pub(crate) fn consumption_execution(
        &self,
        operation_id: &str,
    ) -> Result<ConsumptionExecutionGuard, LeaseRegistryErrorV1> {
        self.ensure_writable()?;
        if !identifier(operation_id) {
            return Err(LeaseRegistryErrorV1::InvalidInput);
        }
        let mut active = self.executions.0.lock().map_err(|_| LeaseRegistryErrorV1::Fenced)?;
        if active.contains(operation_id) {
            return Err(LeaseRegistryErrorV1::WriterBusy);
        }
        if active.len() >= MAX_RECORDS {
            return Err(LeaseRegistryErrorV1::CapacityExceeded);
        }
        active.insert(operation_id.to_owned());
        Ok(ConsumptionExecutionGuard {
            active: Arc::clone(&self.executions.0),
            operation_id: operation_id.to_owned(),
            _owner_lock: Arc::clone(&self.lock),
        })
    }
}

#[cfg(all(test, unix))]
#[path = "consumption_execution_tests.rs"]
mod tests;
