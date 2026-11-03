//! Bounded, same-origin HTTP adapter. Credentials remain memory-only.

use std::io::Read;
use std::time::Duration;

use reqwest::blocking::Client;
use reqwest::header::{HeaderMap, HeaderValue};
use reqwest::{Method, Url};
use serde_json::{Value, json};
use zeroize::Zeroizing;

use crate::transport::ControlTransport;
use crate::{ControlError, ErrorCode, Result};

const MAX_REQUEST_BYTES: usize = 64 * 1024;
const MAX_RESPONSE_BYTES: usize = 1024 * 1024;

/// Explicit deployment credentials. No persistence, ambient cookie jar or Debug output.
pub struct MemoryCredentials {
    cookie: Zeroizing<String>,
    csrf: Zeroizing<String>,
}

impl MemoryCredentials {
    pub fn new(cookie: String, csrf: String) -> Result<Self> {
        if cookie.is_empty() || cookie.len() > 8192 || csrf.is_empty() || csrf.len() > 512 {
            return Err(ControlError::new(ErrorCode::InvalidInput).not_dispatched());
        }
        HeaderValue::from_str(&cookie)
            .map_err(|_| ControlError::new(ErrorCode::InvalidInput).not_dispatched())?;
        HeaderValue::from_str(&csrf)
            .map_err(|_| ControlError::new(ErrorCode::InvalidInput).not_dispatched())?;
        Ok(Self {
            cookie: Zeroizing::new(cookie),
            csrf: Zeroizing::new(csrf),
        })
    }
}

/// Real HTTP transport for the independently deployed ui.control API.
/// HTTPS is mandatory except explicit loopback test/development origins.
/// This is not an adapter from the read-only native gateway to mutation authority.
pub struct HttpTransport {
    base: Url,
    client: Client,
    credentials: MemoryCredentials,
    sequence: u64,
}

fn failure(code: ErrorCode, dispatched: bool) -> ControlError {
    ControlError {
        code,
        request_dispatched: Some(dispatched),
    }
}

impl HttpTransport {
    pub fn new(base: &str, credentials: MemoryCredentials, timeout: Duration) -> Result<Self> {
        let base = Url::parse(base).map_err(|_| failure(ErrorCode::InvalidInput, false))?;
        let loopback = base.host_str().is_some_and(|host| {
            host == "localhost"
                || host
                    .trim_matches(['[', ']'])
                    .parse::<std::net::IpAddr>()
                    .is_ok_and(|address| address.is_loopback())
        });
        if !(base.scheme() == "https" || (base.scheme() == "http" && loopback))
            || !base.username().is_empty()
            || base.password().is_some()
            || base.query().is_some()
            || base.fragment().is_some()
            || !base.path().ends_with('/')
            || timeout < Duration::from_millis(100)
            || timeout > Duration::from_secs(120)
        {
            return Err(failure(ErrorCode::InvalidInput, false));
        }
        let client = Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .no_proxy()
            .timeout(timeout)
            .connect_timeout(timeout)
            .build()
            .map_err(|_| failure(ErrorCode::Transport, false))?;
        Ok(Self {
            base,
            client,
            credentials,
            sequence: 0,
        })
    }

    pub fn endpoint(&self) -> &str {
        self.base.as_str()
    }

    fn fetch(
        &mut self,
        path: &str,
        method: Method,
        body: Option<Value>,
        csrf: bool,
    ) -> Result<Value> {
        let url = self
            .base
            .join(path)
            .map_err(|_| failure(ErrorCode::InvalidInput, false))?;
        if url.origin() != self.base.origin() || !url.path().starts_with(self.base.path()) {
            return Err(failure(ErrorCode::InvalidInput, false));
        }
        self.sequence = self
            .sequence
            .checked_add(1)
            .ok_or_else(|| failure(ErrorCode::InvalidInput, false))?;
        let request_id = body
            .as_ref()
            .and_then(|body| body["operationId"].as_str())
            .map(str::to_owned)
            .unwrap_or_else(|| format!("rust:{}", self.sequence));
        let encoded = body
            .map(|value| {
                crate::canonical::canonical_json_with_limits(
                    &value,
                    crate::canonical::CanonicalLimits {
                        max_encoded_bytes: MAX_REQUEST_BYTES,
                        ..crate::canonical::CanonicalLimits::default()
                    },
                )
                .map(String::into_bytes)
                .map_err(|_| failure(ErrorCode::InvalidInput, false))
            })
            .transpose()?;
        if encoded
            .as_ref()
            .is_some_and(|bytes| bytes.len() > MAX_REQUEST_BYTES)
        {
            return Err(failure(ErrorCode::InvalidInput, false));
        }
        let mut headers = HeaderMap::new();
        headers.insert("accept", HeaderValue::from_static("application/json"));
        headers.insert("cache-control", HeaderValue::from_static("no-store"));
        headers.insert(
            "x-hepta-request-id",
            HeaderValue::from_str(&request_id)
                .map_err(|_| failure(ErrorCode::InvalidInput, false))?,
        );
        let mut cookie = HeaderValue::from_str(&self.credentials.cookie)
            .map_err(|_| failure(ErrorCode::InvalidInput, false))?;
        cookie.set_sensitive(true);
        headers.insert("cookie", cookie);
        if csrf {
            let mut token = HeaderValue::from_str(&self.credentials.csrf)
                .map_err(|_| failure(ErrorCode::PermissionDenied, false))?;
            token.set_sensitive(true);
            headers.insert("x-hepta-csrf-token", token);
        }
        let mut request = self.client.request(method, url).headers(headers);
        if let Some(encoded) = encoded {
            request = request
                .header("content-type", "application/json")
                .body(encoded);
        }
        let request = request
            .build()
            .map_err(|_| failure(ErrorCode::InvalidInput, false))?;
        // Conservatively classify every execute error as possibly dispatched.
        let mut response = self
            .client
            .execute(request)
            .map_err(|_| failure(ErrorCode::Transport, true))?;
        let status = response.status().as_u16();
        let content_type = response
            .headers()
            .get("content-type")
            .and_then(|v| v.to_str().ok())
            .and_then(|v| v.split(';').next())
            .unwrap_or_default()
            .trim()
            .to_ascii_lowercase();
        if !(content_type == "application/json"
            || content_type.starts_with("application/") && content_type.ends_with("+json"))
            || response
                .content_length()
                .is_some_and(|size| size > MAX_RESPONSE_BYTES as u64)
        {
            return Err(failure(ErrorCode::Transport, true));
        }
        let mut bytes = Vec::new();
        response
            .by_ref()
            .take(MAX_RESPONSE_BYTES as u64 + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| failure(ErrorCode::Transport, true))?;
        if bytes.len() > MAX_RESPONSE_BYTES {
            return Err(failure(ErrorCode::Transport, true));
        }
        let text = std::str::from_utf8(&bytes).map_err(|_| failure(ErrorCode::Transport, true))?;
        let payload = crate::canonical::parse_bounded_json(
            text,
            crate::canonical::CanonicalLimits {
                max_entries: 16_384,
                ..crate::canonical::CanonicalLimits::default()
            },
        )
        .map_err(|_| failure(ErrorCode::Transport, true))?;
        if !(200..300).contains(&status) {
            let code = match status {
                401 => ErrorCode::SessionExpired,
                403 => ErrorCode::PermissionDenied,
                409 => ErrorCode::OperationConflict,
                412 => ErrorCode::StaleRevision,
                400 | 404 | 422 => ErrorCode::BackendRejected,
                _ => ErrorCode::Transport,
            };
            return Err(failure(code, true));
        }
        if !payload.is_object() {
            return Err(failure(ErrorCode::Transport, true));
        }
        Ok(payload)
    }
}

fn session_reference(session: &Value) -> Value {
    json!({"sessionId":session["sessionId"], "connectionGeneration":session["connectionGeneration"]})
}

impl ControlTransport for HttpTransport {
    fn endpoint(&self) -> &str {
        self.base.as_str()
    }
    fn connect(&mut self, manifest: &Value) -> Result<Value> {
        self.fetch(
            "session/connect",
            Method::POST,
            Some(manifest.clone()),
            true,
        )
    }
    fn refresh_session(&mut self, session: &Value) -> Result<Value> {
        self.fetch("session/refresh", Method::POST, Some(json!({
            "sessionId":session["sessionId"], "connectionGeneration":session["connectionGeneration"],
            "permissionRevision":session["permissionRevision"]})), true)
    }
    fn read_snapshot(&mut self, session: &Value) -> Result<Value> {
        self.fetch(
            "view",
            Method::POST,
            Some(session_reference(session)),
            false,
        )
    }
    fn request(&mut self, method: &str, input: &Value) -> Result<Value> {
        if !matches!(method, "runtime/request" | "runtime/start" | "runtime/stop")
            || input
                .get("method")
                .is_some_and(|value| value.as_str() != Some(method))
        {
            return Err(failure(ErrorCode::InvalidInput, false));
        }
        let mut input = input
            .as_object()
            .cloned()
            .ok_or_else(|| failure(ErrorCode::InvalidInput, false))?;
        input.insert("method".into(), method.into());
        self.fetch("operations", Method::POST, Some(Value::Object(input)), true)
    }
    fn lookup(&mut self, input: &Value) -> Result<Value> {
        let id = input["operationId"]
            .as_str()
            .ok_or_else(|| failure(ErrorCode::InvalidInput, false))?;
        if id.is_empty()
            || id.len() > 128
            || !id
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || b"._:-".contains(&c))
        {
            return Err(failure(ErrorCode::InvalidInput, false));
        }
        let mut url = self
            .base
            .join(&format!("operations/{id}"))
            .map_err(|_| failure(ErrorCode::InvalidInput, false))?;
        url.query_pairs_mut()
            .append_pair("sessionId", input["sessionId"].as_str().unwrap_or_default())
            .append_pair(
                "connectionGeneration",
                &input["connectionGeneration"].to_string(),
            )
            .append_pair(
                "semanticDigest",
                input["semanticDigest"].as_str().unwrap_or_default(),
            );
        let relative = url
            .as_str()
            .strip_prefix(self.base.as_str())
            .ok_or_else(|| failure(ErrorCode::InvalidInput, false))?
            .to_owned();
        self.fetch(&relative, Method::GET, None, false)
    }
    fn close(&mut self, session: &Value) -> Result<()> {
        self.fetch(
            "session/close",
            Method::POST,
            Some(session_reference(session)),
            true,
        )
        .map(|_| ())
    }
    fn revoke(&mut self, session: &Value) -> Result<()> {
        self.fetch(
            "session/revoke",
            Method::POST,
            Some(session_reference(session)),
            true,
        )
        .map(|_| ())
    }
}

#[cfg(test)]
#[path = "transport_tests.rs"]
mod tests;
