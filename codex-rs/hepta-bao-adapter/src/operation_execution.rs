//! Short metadata lock; the returned guard owns no mutex across an await.
//! Single flight is shared by all hosts using the same durable registry. A
//! cancelled task releases it; the AuthBus admission tombstone separately fences
//! a reserve whose SQLite commit may finish after cancellation.
use crate::LeaseRegistryErrorV1;
use std::collections::BTreeSet;
use std::sync::{Arc, Mutex};

#[derive(Default)]
pub(crate) struct OperationExecutionSet {
    active: Arc<Mutex<BTreeSet<String>>>,
}
impl OperationExecutionSet {
    pub(crate) fn enter(&self, id: &str) -> Result<OperationExecutionGuard, LeaseRegistryErrorV1> {
        let mut active = self
            .active
            .lock()
            .map_err(|_| LeaseRegistryErrorV1::Fenced)?;
        if active.contains(id) {
            return Err(LeaseRegistryErrorV1::WriterBusy);
        }
        if active.len() >= 4096 {
            return Err(LeaseRegistryErrorV1::CapacityExceeded);
        }
        active.insert(id.to_owned());
        Ok(OperationExecutionGuard {
            active: Arc::clone(&self.active),
            id: id.to_owned(),
        })
    }
}
pub(crate) struct OperationExecutionGuard {
    active: Arc<Mutex<BTreeSet<String>>>,
    id: String,
}
impl Drop for OperationExecutionGuard {
    fn drop(&mut self) {
        if let Ok(mut active) = self.active.lock() {
            active.remove(&self.id);
        }
    }
}
#[cfg(test)]
#[path = "operation_execution_tests.rs"]
mod tests;
