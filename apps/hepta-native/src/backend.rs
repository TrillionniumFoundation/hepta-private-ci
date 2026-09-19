use std::io::Read as _;
use std::io::Write as _;
use std::net::SocketAddr;
use std::net::TcpStream;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;

use serde_json::Value;

use crate::error::ShellError;
use crate::model::EndpointManifest;
use crate::model::SessionIncarnation;
use crate::security::now_unix_ms;

const MAX_HTTP_RESPONSE_BYTES: usize = 1024 * 1024;
const HTTP_TIMEOUT: Duration = Duration::from_secs(3);
static SESSION_COUNTER: AtomicU64 = AtomicU64::new(1);

pub trait BackendAdapter: Send {
    fn connect(&mut self, manifest: &EndpointManifest) -> Result<SessionIncarnation, ShellError>;
    fn runtime_status(&mut self) -> Result<Value, ShellError>;
    fn close(&mut self, session: &SessionIncarnation) -> Result<(), ShellError>;
}

pub struct LoopbackGatewayBackend {
    address: SocketAddr,
    bearer_token: String,
}

impl LoopbackGatewayBackend {
    pub fn new(address: SocketAddr, bearer_token: String) -> Result<Self, ShellError> {
        if !address.ip().is_loopback() || address.port() == 0 {
            return Err(ShellError::Backend(
                "native gateway must use an explicit non-zero loopback address".to_owned(),
            ));
        }
        validate_bearer_token(&bearer_token)?;
        Ok(Self {
            address,
            bearer_token,
        })
    }

    fn get_json(&self, path: &str) -> Result<Value, ShellError> {
        let mut stream = TcpStream::connect_timeout(&self.address, HTTP_TIMEOUT)
            .map_err(|error| ShellError::Backend(format!("connect gateway: {error}")))?;
        stream
            .set_read_timeout(Some(HTTP_TIMEOUT))
            .map_err(|error| ShellError::Backend(format!("set gateway read timeout: {error}")))?;
        stream
            .set_write_timeout(Some(HTTP_TIMEOUT))
            .map_err(|error| ShellError::Backend(format!("set gateway write timeout: {error}")))?;
        let request = format!(
            "GET {path} HTTP/1.1\r\nHost: {}\r\nAccept: application/json\r\nAuthorization: Bearer {}\r\nConnection: close\r\n\r\n",
            self.address, self.bearer_token
        );
        stream
            .write_all(request.as_bytes())
            .map_err(|error| ShellError::Backend(format!("write gateway request: {error}")))?;
        let mut response = Vec::with_capacity(4096);
        let mut limited = stream.take((MAX_HTTP_RESPONSE_BYTES + 1) as u64);
        limited
            .read_to_end(&mut response)
            .map_err(|error| ShellError::Backend(format!("read gateway response: {error}")))?;
        if response.len() > MAX_HTTP_RESPONSE_BYTES {
            return Err(ShellError::Backend(
                "gateway response exceeded native bound".to_owned(),
            ));
        }
        let header_end = response
            .windows(4)
            .position(|window| window == b"\r\n\r\n")
            .ok_or_else(|| ShellError::Backend("gateway response is missing headers".to_owned()))?;
        let headers = std::str::from_utf8(&response[..header_end])
            .map_err(|error| ShellError::Backend(format!("gateway headers are not UTF-8: {error}")))?;
        if !headers.lines().next().is_some_and(|line| line.contains(" 200 ")) {
            return Err(ShellError::Backend(format!(
                "gateway returned non-success response: {}",
                headers.lines().next().unwrap_or("missing status")
            )));
        }
        let body = &response[header_end + 4..];
        serde_json::from_slice(body).map_err(ShellError::from)
    }
}

fn validate_bearer_token(value: &str) -> Result<(), ShellError> {
    if value.len() < 32
        || value.len() > 256
        || !value.bytes().all(|byte| {
            byte.is_ascii_alphanumeric()
                || matches!(byte, b'-' | b'.' | b'_' | b'~' | b'+' | b'/' | b'=')
        })
    {
        return Err(ShellError::Security(
            "native gateway bearer capability has invalid syntax or length".to_owned(),
        ));
    }
    Ok(())
}

impl BackendAdapter for LoopbackGatewayBackend {
    fn connect(&mut self, manifest: &EndpointManifest) -> Result<SessionIncarnation, ShellError> {
        manifest.validate()?;
        let manifest_address: SocketAddr = manifest
            .address
            .parse()
            .map_err(|error| ShellError::Backend(format!("parse manifest address: {error}")))?;
        if manifest_address != self.address || !manifest_address.ip().is_loopback() {
            return Err(ShellError::Backend(
                "manifest endpoint does not match the configured loopback gateway".to_owned(),
            ));
        }
        let health = self.get_json("/healthz")?;
        if health.get("product").and_then(Value::as_str) != Some("hepta")
            || health.get("status").and_then(Value::as_str) != Some("ok")
            || health.get("native_auth").and_then(Value::as_str) != Some("keyring_bearer_v1")
        {
            return Err(ShellError::Backend(
                "gateway health identity is not the expected Hepta product".to_owned(),
            ));
        }
        let counter = SESSION_COUNTER.fetch_add(1, Ordering::Relaxed);
        let now = now_unix_ms()?.max(1);
        let session = SessionIncarnation {
            endpoint_id: manifest.endpoint_id.clone(),
            session_id: format!("native.{}.{}.{}", std::process::id(), now, counter),
            generation: now,
        };
        session.validate()?;
        Ok(session)
    }

    fn runtime_status(&mut self) -> Result<Value, ShellError> {
        self.get_json("/api/hepta/runtime")
    }

    fn close(&mut self, _session: &SessionIncarnation) -> Result<(), ShellError> {
        Ok(())
    }
}
