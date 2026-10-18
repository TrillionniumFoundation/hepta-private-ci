//! Read a complete original record under the existing control owner's lease.
use super::ModelControlOwner;
use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::AgentdNativeModelReceiptReaderV1;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::time::Duration;

pub struct NativeModelReceiptReaderV1 {
    owner: ModelControlOwner,
}
impl NativeModelReceiptReaderV1 {
    /// Borrow the installed model and CPU composition's existing Arc. This
    /// constructor cannot open another writer or choose a different journal.
    pub fn new_shared(control: Arc<tokio::sync::Mutex<DurableInferenceControl>>) -> Self {
        Self {
            owner: ModelControlOwner(control),
        }
    }
}
impl AgentdNativeModelReceiptReaderV1 for NativeModelReceiptReaderV1 {
    fn read<'a>(
        &'a self,
        request_id: &'a str,
    ) -> Pin<Box<dyn Future<Output = Result<Option<String>, AgentdError>> + Send + 'a>> {
        Box::pin(async move {
            let control = self
                .owner
                .acquire(Duration::from_millis(1000))
                .await
                .map_err(|error| {
                    AgentdError::Invalid(format!(
                        "original native receipt owner unavailable: {error}"
                    ))
                })?;
            let record = control
                .native_record_resolved(request_id)
                .map_err(|error| {
                    AgentdError::Invalid(format!("original native receipt read failed: {error}"))
                })?;
            record
                .map(|record| serde_json::to_string(&record).map_err(AgentdError::from))
                .transpose()
        })
    }
}

#[cfg(test)]
#[path = "native_model_receipt_reader_tests.rs"]
mod tests;
