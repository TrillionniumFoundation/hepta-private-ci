//! Preserve an explicitly observed request across mutable authentication.
//! This is request integrity, not a late authority or model-load observation.

use bytes::Bytes;
use codex_client::Request;
use codex_client::RequestCompression;
use http::HeaderMap;
use http::HeaderName;
use http::HeaderValue;
use http::Method;
use std::fmt;
use std::time::Duration;

pub(crate) struct ObservedRequestSnapshot {
    method: Method,
    url: String,
    body: Option<Bytes>,
    compression: RequestCompression,
    timeout: Option<Duration>,
    framing: Vec<(HeaderName, Vec<HeaderValue>)>,
}

#[derive(Debug)]
pub(crate) enum ObservedRequestChange {
    Method,
    Destination,
    Body,
    Compression,
    Timeout,
    Framing,
}

impl fmt::Display for ObservedRequestChange {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        // Never include request bodies, URLs, credentials or header values.
        write!(
            formatter,
            "observed request changed after authentication: {self:?}"
        )
    }
}

impl ObservedRequestSnapshot {
    /// The caller first prepares the exact compressed wire bytes. Bytes clones
    /// share that allocation; no second model-payload allocation is retained.
    pub(crate) fn capture(request: &Request) -> Result<Self, ObservedRequestChange> {
        let prepared = request
            .prepare_body_for_send()
            .map_err(|_| ObservedRequestChange::Body)?;
        Ok(Self {
            method: request.method.clone(),
            url: request.url.clone(),
            body: prepared.body,
            compression: request.compression,
            timeout: request.timeout,
            framing: framing(&prepared.headers),
        })
    }

    pub(crate) fn validate(&self, request: &Request) -> Result<(), ObservedRequestChange> {
        if self.method != request.method {
            return Err(ObservedRequestChange::Method);
        }
        if self.url != request.url {
            return Err(ObservedRequestChange::Destination);
        }
        if self.compression != request.compression {
            return Err(ObservedRequestChange::Compression);
        }
        if self.timeout != request.timeout {
            return Err(ObservedRequestChange::Timeout);
        }
        let prepared = request
            .prepare_body_for_send()
            .map_err(|_| ObservedRequestChange::Body)?;
        if self.body != prepared.body {
            return Err(ObservedRequestChange::Body);
        }
        if self.framing != framing(&prepared.headers) {
            return Err(ObservedRequestChange::Framing);
        }
        Ok(())
    }
}

fn framing(headers: &HeaderMap) -> Vec<(HeaderName, Vec<HeaderValue>)> {
    [
        http::header::CONTENT_TYPE,
        http::header::CONTENT_ENCODING,
        http::header::CONTENT_LENGTH,
        http::header::TRANSFER_ENCODING,
        http::header::HOST,
    ]
    .into_iter()
    .map(|name| {
        let values = headers.get_all(&name).iter().cloned().collect();
        (name, values)
    })
    .collect()
}
