//! Installed read-only access to the original serial native control owner.
use super::AgentdConfig;
use crate::AgentdError;
use crate::AgentdPayload;
use crate::AgentdState;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;

/// Host composition borrows its sole native journal through this reader. It
/// returns the complete original NativeRunRecord JSON or a definite absence;
/// busy and corrupt reads are errors; unsettled records retain their complete
/// original state and cannot be interpreted as a terminal success.
pub trait AgentdNativeModelReceiptReaderV1: Send + Sync {
    fn read<'a>(
        &'a self,
        request_id: &'a str,
    ) -> Pin<Box<dyn Future<Output = Result<Option<String>, AgentdError>> + Send + 'a>>;
}
impl AgentdConfig {
    pub fn with_native_model_receipt_reader(
        mut self,
        reader: Arc<dyn AgentdNativeModelReceiptReaderV1>,
    ) -> Result<Self, AgentdError> {
        if self.native_model_receipt_reader.is_some() {
            return Err(AgentdError::Invalid(
                "original native receipt reader already installed".into(),
            ));
        }
        self.native_model_receipt_reader = Some(reader);
        Ok(self)
    }
    pub(crate) fn take_native_model_receipt_reader(
        &mut self,
    ) -> Option<Arc<dyn AgentdNativeModelReceiptReaderV1>> {
        self.native_model_receipt_reader.take()
    }
}
impl AgentdState {
    pub(crate) async fn native_model_receipt(
        &self,
        request_id: String,
    ) -> Result<AgentdPayload, AgentdError> {
        if request_id.len() > 256
            || codex_hepta_agent_components::types::StableId::new(&request_id).is_err()
        {
            return Err(AgentdError::Invalid(
                "native receipt request identity".into(),
            ));
        }
        let reader = self.native_model_receipt_reader.get().ok_or_else(|| {
            AgentdError::Invalid("original native receipt reader unavailable".into())
        })?;
        let native_record_json = reader.read(&request_id).await?;
        // The existing control encoder additionally bounds the complete escaped
        // response frame. Never truncate an original record to fit transport.
        if native_record_json
            .as_ref()
            .is_some_and(|json| json.len() as u64 > crate::MAX_CONTROL_FRAME_BYTES)
        {
            return Err(AgentdError::Protocol(
                "complete native receipt exceeds control frame".into(),
            ));
        }
        Ok(AgentdPayload::NativeModelReceipt {
            request_id,
            native_record_json,
        })
    }
}
