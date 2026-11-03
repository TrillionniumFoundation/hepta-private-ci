//! Checked submission seam after request construction and before HTTP entry.
//!
//! This is a child of `responses`. Production hosts supply their original
//! one-shot writer entry and retained currentness guard; this transport does
//! not construct a grant, operation identity or replacement retry.

use super::Context;
use super::ModelRequest;
use super::ResponsesModel;
use super::ResponsesStream;
use super::Result;
use super::SseDecoder;
use super::bail;
use http::header::CONTENT_TYPE;

impl ResponsesModel {
    /// Open the exact admitted request through a final synchronous host gate.
    ///
    /// The callback sees the actual configured endpoint and original request.
    /// It must compare both with durable admission, revalidate cancellation and
    /// the current owner, and consume the original FinalUse token. The returned
    /// guard is held through the initial transport. All asynchronous admission
    /// and writer checks must finish before this call; no application await is
    /// inserted between `enter` and starting the sole HTTP send.
    pub async fn open_with_entry<F, G>(
        &self,
        request: &ModelRequest,
        enter: F,
    ) -> Result<ResponsesStream>
    where
        F: FnOnce(&str, &ModelRequest) -> Result<G> + Send,
        G: Send,
    {
        if request.operation_id.is_empty() || request.body.is_empty() {
            bail!("model request must carry the original operation and exact bytes");
        }
        let mut post = self
            .client
            .post(&self.responses_url)
            .header("Content-Type", "application/json")
            .header("Accept", "text/event-stream")
            .header("Idempotency-Key", &request.operation_id)
            .body(request.body.clone());
        if let Some(bearer) = &self.bearer {
            post = post.bearer_auth(bearer);
        }
        let entry_guard = enter(&self.responses_url, request)?;
        let response = tokio::time::timeout(self.idle_timeout, post.send())
            .await
            .context("model response headers timed out; reconcile original operation")?
            .context("model transport uncertain; reconcile original operation")?;
        drop(entry_guard);
        if !response.status().is_success() {
            bail!(
                "model HTTP status {}; owner must classify the original request",
                response.status()
            );
        }
        if !response
            .headers()
            .get(CONTENT_TYPE)
            .and_then(|value| value.to_str().ok())
            .is_some_and(|value| value.starts_with("text/event-stream"))
        {
            bail!("model did not return an SSE response");
        }
        Ok(ResponsesStream {
            response,
            operation_id: request.operation_id.clone(),
            terminal_observer: None,
            decoder: SseDecoder::new(self.max_stream_bytes),
            idle_timeout: self.idle_timeout,
            response_id: None,
            output_items: Vec::new(),
            text: super::text::TextTracker::default(),
            completed: false,
        })
    }
}

#[cfg(test)]
#[path = "responses_entry_tests.rs"]
mod tests;
