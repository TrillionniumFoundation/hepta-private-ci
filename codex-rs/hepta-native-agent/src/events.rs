//! Provisional observations published through the existing host turn owner.
//!
//! Events do not commit history or authorize effects. The host fences each
//! delivery and derives its canonical item id from the immutable context index.

use std::future::Future;

use anyhow::Result;

use crate::TurnBinding;

/// A bounded text fragment from the original in-flight provider response.
#[derive(Clone, Debug, PartialEq)]
pub struct NativeTextDelta {
    pub operation_id: String,
    pub response_id: String,
    pub provider_item_id: String,
    /// Absolute index in the owner's append-only context, including its prefix.
    pub context_index: usize,
    pub output_index: usize,
    pub content_index: usize,
    pub text: String,
    pub phase: Option<String>,
}

#[derive(Clone, Debug, PartialEq)]
pub enum NativeEvent {
    TextDelta(NativeTextDelta),
}

/// Delivery failure stops observation and retains the original pending model
/// operation. Implementations must not replay the model POST to recover the UI.
pub trait NativeEventSink: Send + Sync {
    fn emit(
        &self,
        binding: &TurnBinding,
        event: NativeEvent,
    ) -> impl Future<Output = Result<()>> + Send;
}

pub(crate) struct NoopEventSink;

impl NativeEventSink for NoopEventSink {
    async fn emit(&self, _: &TurnBinding, _: NativeEvent) -> Result<()> {
        Ok(())
    }
}

pub(crate) const MAX_TEXT_DELTA_BYTES: usize = 32 * 1024;
