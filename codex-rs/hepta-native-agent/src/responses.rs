//! Bounded streaming Responses transport. It never retries an ambiguous POST.

use std::collections::VecDeque;
use std::time::Duration;

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use codex_http_client::ClientRouteClass;
use codex_http_client::HttpClient;
use codex_http_client::HttpClientBuilder;
use codex_http_client::HttpClientFactory;
use codex_http_client::HttpResponse;
use http::StatusCode;
use http::header::CONTENT_TYPE;
use serde_json::Value;
use url::Url;

/// One exact request already persisted by the turn owner.
#[derive(Clone, Debug)]
pub struct ModelRequest {
    pub operation_id: String,
    pub body: Vec<u8>,
}

/// Observations from one provider response; only Completed is terminal success.
#[derive(Clone, Debug, PartialEq)]
pub enum ModelEvent {
    Created(String),
    TextDelta(String),
    Item(Value),
    Completed { response_id: String, usage: Value },
}

/// Explicit transport configuration; routing policy and credentials come from the host.
pub struct ResponsesModel {
    client: HttpClient,
    responses_url: String,
    bearer: Option<String>,
    idle_timeout: Duration,
    max_stream_bytes: usize,
}

impl ResponsesModel {
    pub fn new(
        http_client_factory: &HttpClientFactory,
        responses_url: String,
        bearer: Option<String>,
        idle_timeout: Duration,
        max_stream_bytes: usize,
    ) -> Result<Self> {
        let url = Url::parse(&responses_url)?;
        if !matches!(url.scheme(), "http" | "https")
            || !url.username().is_empty()
            || url.password().is_some()
            || idle_timeout.is_zero()
            || max_stream_bytes == 0
        {
            bail!("invalid Responses transport configuration");
        }
        Ok(Self {
            client: HttpClientBuilder::new()
                .connect_timeout(idle_timeout)
                .without_redirects()
                .without_retries()
                .build_respecting_outbound_proxy_policy(
                    http_client_factory,
                    &responses_url,
                    ClientRouteClass::Api,
                )?,
            responses_url,
            bearer,
            idle_timeout,
            max_stream_bytes,
        })
    }

    /// The header preserves identity; it does not assert provider deduplication.
    /// Any error is reconciled by the owner, never retried with a new operation.
    pub async fn open(&self, request: &ModelRequest) -> Result<ResponsesStream> {
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
        let response = tokio::time::timeout(self.idle_timeout, post.send())
            .await
            .context("model response headers timed out; reconcile original operation")?
            .context("model transport uncertain; reconcile original operation")?;
        if !response.status().is_success() {
            bail!(
                "model HTTP status {}; owner must classify the original request",
                response.status()
            );
        }
        if !response
            .headers()
            .get(CONTENT_TYPE)
            .and_then(|v| v.to_str().ok())
            .is_some_and(|v| v.starts_with("text/event-stream"))
        {
            bail!("model did not return an SSE response");
        }
        Ok(ResponsesStream {
            response,
            decoder: SseDecoder::new(self.max_stream_bytes),
            idle_timeout: self.idle_timeout,
            response_id: None,
            completed: false,
        })
    }
    /// Observe the original response through the same provider without another POST.
    /// Providers which do not retain responses return no recovery evidence.
    pub async fn reconcile(
        &self,
        request: &ModelRequest,
        response_id: &str,
    ) -> Result<Option<ObservedModelCompletion>> {
        if response_id.is_empty() || response_id.len() > 512 {
            bail!("invalid original model response identity");
        }
        let mut url = Url::parse(&self.responses_url)?;
        url.path_segments_mut()
            .map_err(|_| anyhow::anyhow!("provider URL has no path"))?
            .pop_if_empty()
            .push(response_id);
        let mut get = self.client.get(url).header("Accept", "application/json");
        if let Some(bearer) = &self.bearer {
            get = get.bearer_auth(bearer);
        }
        let mut response = tokio::time::timeout(self.idle_timeout, get.send()).await??;
        if response.status() == StatusCode::NOT_FOUND {
            return Ok(None);
        }
        if !response.status().is_success() {
            bail!(
                "original model response observation unavailable: {}",
                response.status()
            );
        }
        let mut bytes = Vec::new();
        loop {
            let chunk = tokio::time::timeout(self.idle_timeout, response.chunk()).await??;
            let Some(chunk) = chunk else { break };
            if bytes.len().saturating_add(chunk.len()) > self.max_stream_bytes {
                bail!("model reconciliation byte budget exceeded");
            }
            bytes.extend_from_slice(&chunk);
        }
        let value: Value = serde_json::from_slice(&bytes)?;
        if value["id"] != response_id {
            bail!("provider reconciliation returned a different response");
        }
        if value["status"] != "completed" {
            return Ok(None);
        }
        Ok(Some(ObservedModelCompletion {
            operation_id: request.operation_id.clone(),
            response_id: response_id.to_owned(),
            items: value["output"]
                .as_array()
                .context("reconciled model output missing")?
                .clone(),
            usage: value["usage"].clone(),
        }))
    }
}

/// Completion observed by this provider transport; raw JSON cannot construct it.
#[derive(Debug)]
pub struct ObservedModelCompletion {
    pub(crate) operation_id: String,
    pub(crate) response_id: String,
    pub(crate) items: Vec<Value>,
    pub(crate) usage: Value,
}

/// A response stream owns its transport; dropping it closes local observation.
pub struct ResponsesStream {
    response: HttpResponse,
    decoder: SseDecoder,
    idle_timeout: Duration,
    response_id: Option<String>,
    completed: bool,
}

impl ResponsesStream {
    pub async fn next(&mut self) -> Result<Option<ModelEvent>> {
        if self.completed {
            return Ok(None);
        }
        loop {
            while let Some(value) = self.decoder.pop()? {
                let Some(kind) = value["type"].as_str() else {
                    bail!("model event has no type");
                };
                match kind {
                    "response.created" => {
                        let id = response_id(&value)?;
                        if self.response_id.as_ref().is_some_and(|old| old != &id) {
                            bail!("provider changed response identity within one stream");
                        }
                        self.response_id = Some(id.clone());
                        return Ok(Some(ModelEvent::Created(id)));
                    }
                    "response.output_text.delta" => {
                        let text = value["delta"].as_str().context("text delta missing")?;
                        return Ok(Some(ModelEvent::TextDelta(text.to_owned())));
                    }
                    "response.output_item.done" => {
                        let item = value
                            .get("item")
                            .filter(|v| v.is_object())
                            .context("completed output item missing")?;
                        return Ok(Some(ModelEvent::Item(item.clone())));
                    }
                    "response.completed" => {
                        let id = response_id(&value)?;
                        if self.response_id.as_ref() != Some(&id)
                            || value["response"]["status"]
                                .as_str()
                                .is_some_and(|status| status != "completed")
                        {
                            bail!("terminal response does not match the observed response");
                        }
                        self.completed = true;
                        return Ok(Some(ModelEvent::Completed {
                            response_id: id,
                            usage: value["response"]["usage"].clone(),
                        }));
                    }
                    "error" | "response.failed" | "response.incomplete" => {
                        bail!("provider ended with {kind}; no terminal success");
                    }
                    _ => {}
                }
            }
            let chunk = tokio::time::timeout(self.idle_timeout, self.response.chunk())
                .await
                .context("model stream idle timeout; reconcile original operation")?
                .context("model stream disconnected; reconcile original operation")?;
            let Some(chunk) = chunk else {
                bail!("model stream ended without response.completed");
            };
            self.decoder.push(&chunk)?;
        }
    }
}

fn response_id(value: &Value) -> Result<String> {
    let id = value["response"]["id"]
        .as_str()
        .context("response identity missing")?;
    if id.is_empty() || id.len() > 512 {
        bail!("invalid response identity");
    }
    Ok(id.to_owned())
}

/// Bounds the entire stream before parsing frames, including incomplete frames.
struct SseDecoder {
    bytes: Vec<u8>,
    frames: VecDeque<Vec<u8>>,
    received: usize,
    limit: usize,
}

impl SseDecoder {
    fn new(limit: usize) -> Self {
        Self {
            bytes: Vec::new(),
            frames: VecDeque::new(),
            received: 0,
            limit,
        }
    }

    fn push(&mut self, chunk: &[u8]) -> Result<()> {
        self.received = self
            .received
            .checked_add(chunk.len())
            .context("stream size overflow")?;
        if self.received > self.limit {
            bail!("model stream byte budget exceeded");
        }
        self.bytes.extend_from_slice(chunk);
        loop {
            let boundary = self
                .bytes
                .windows(2)
                .position(|v| v == b"\n\n")
                .map(|at| (at, 2))
                .into_iter()
                .chain(
                    self.bytes
                        .windows(4)
                        .position(|v| v == b"\r\n\r\n")
                        .map(|at| (at, 4)),
                )
                .min_by_key(|(at, _)| *at);
            let Some((at, width)) = boundary else { break };
            self.frames.push_back(self.bytes[..at].to_vec());
            self.bytes.drain(..at + width);
        }
        Ok(())
    }

    fn pop(&mut self) -> Result<Option<Value>> {
        while let Some(frame) = self.frames.pop_front() {
            let frame = std::str::from_utf8(&frame).context("SSE frame is not UTF-8")?;
            let data = frame
                .lines()
                .filter_map(|line| line.strip_prefix("data:"))
                .map(|line| line.strip_prefix(' ').unwrap_or(line))
                .collect::<Vec<_>>()
                .join("\n");
            if data.is_empty() || data == "[DONE]" {
                continue;
            }
            return Ok(Some(
                serde_json::from_str(&data).context("invalid SSE JSON")?,
            ));
        }
        Ok(None)
    }
}

#[cfg(test)]
#[path = "responses_tests.rs"]
mod tests;
