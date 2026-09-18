use crate::MAX_JSON_BYTES;
use crate::PROTOCOL_VERSION;
use crate::sha256_hex;
use crate::types::NativeSession;
use crate::types::RuntimeManifest;
use crate::validate_digest;
use crate::validate_stable_id;
use serde_json::Value;
use std::io::Read as _;
use std::io::Write as _;
use std::net::IpAddr;
use std::net::SocketAddr;
use std::net::TcpStream;
use std::time::Duration;
use thiserror::Error;
use url::Url;

const CONNECT_TIMEOUT: Duration = Duration::from_secs(3);
const IO_TIMEOUT: Duration = Duration::from_secs(5);

#[derive(Debug, Error)]
pub enum BackendError {
    #[error("native backend endpoint is not an explicit loopback HTTP endpoint")]
    Endpoint,
    #[error("runtime manifest is invalid")]
    Manifest,
    #[error("backend transport failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("backend response is malformed or too large")]
    Response,
    #[error("backend returned HTTP status {0}")]
    Status(u16),
    #[error("runtime generation is missing")]
    Generation,
}

pub trait Backend: Send {
    fn connect(&mut self, manifest: &RuntimeManifest) -> Result<NativeSession, BackendError>;
    fn fetch_runtime(&mut self, session: &NativeSession) -> Result<Value, BackendError>;
    fn close(&mut self, _session: &NativeSession) -> Result<(), BackendError> {
        Ok(())
    }
}

#[derive(Clone, Debug)]
pub struct GatewayBackend {
    endpoint: Url,
    address: SocketAddr,
}

impl GatewayBackend {
    pub fn new(endpoint: &str) -> Result<Self, BackendError> {
        let endpoint = Url::parse(endpoint).map_err(|_| BackendError::Endpoint)?;
        if endpoint.scheme() != "http"
            || endpoint.username() != ""
            || endpoint.password().is_some()
            || endpoint.query().is_some()
            || endpoint.fragment().is_some()
        {
            return Err(BackendError::Endpoint);
        }
        let host = endpoint.host_str().ok_or(BackendError::Endpoint)?;
        let ip: IpAddr = host.parse().map_err(|_| BackendError::Endpoint)?;
        if !ip.is_loopback() {
            return Err(BackendError::Endpoint);
        }
        let port = endpoint
            .port_or_known_default()
            .ok_or(BackendError::Endpoint)?;
        if port == 0 {
            return Err(BackendError::Endpoint);
        }
        Ok(Self {
            endpoint,
            address: SocketAddr::new(ip, port),
        })
    }

    pub fn production_default() -> Result<Self, BackendError> {
        Self::new("http://127.0.0.1:7373")
    }

    pub fn manifest(&self) -> RuntimeManifest {
        let endpoint = self.endpoint.as_str().trim_end_matches('/').to_string();
        let manifest_digest = sha256_hex(format!(
            "hepta.native.gateway.manifest.v1\0{endpoint}\0{PROTOCOL_VERSION}"
        ));
        RuntimeManifest {
            endpoint,
            endpoint_id: "hepta.native-gateway.loopback".to_string(),
            manifest_digest,
            protocol_version: PROTOCOL_VERSION,
        }
    }

    fn get_json(&self, path: &str) -> Result<Value, BackendError> {
        let mut stream = TcpStream::connect_timeout(&self.address, CONNECT_TIMEOUT)?;
        stream.set_read_timeout(Some(IO_TIMEOUT))?;
        stream.set_write_timeout(Some(IO_TIMEOUT))?;
        let host = match self.address {
            SocketAddr::V4(address) => format!("{}:{}", address.ip(), address.port()),
            SocketAddr::V6(address) => format!("[{}]:{}", address.ip(), address.port()),
        };
        let request = format!(
            "GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\nAccept: application/json\r\n\r\n"
        );
        stream.write_all(request.as_bytes())?;
        let mut bytes = Vec::new();
        stream
            .take(u64::try_from(MAX_JSON_BYTES + 32 * 1024).unwrap_or(u64::MAX))
            .read_to_end(&mut bytes)?;
        if bytes.len() > MAX_JSON_BYTES + 32 * 1024 {
            return Err(BackendError::Response);
        }
        let split = bytes
            .windows(4)
            .position(|window| window == b"\r\n\r\n")
            .ok_or(BackendError::Response)?;
        let headers = std::str::from_utf8(&bytes[..split]).map_err(|_| BackendError::Response)?;
        let status = headers
            .lines()
            .next()
            .and_then(|line| line.split_whitespace().nth(1))
            .and_then(|status| status.parse::<u16>().ok())
            .ok_or(BackendError::Response)?;
        if status != 200 {
            return Err(BackendError::Status(status));
        }
        let body = &bytes[split + 4..];
        if body.len() > MAX_JSON_BYTES {
            return Err(BackendError::Response);
        }
        serde_json::from_slice(body).map_err(|_| BackendError::Response)
    }
}

impl Backend for GatewayBackend {
    fn connect(&mut self, manifest: &RuntimeManifest) -> Result<NativeSession, BackendError> {
        if manifest.endpoint != self.endpoint.as_str().trim_end_matches('/')
            || manifest.protocol_version != PROTOCOL_VERSION
            || !validate_stable_id(&manifest.endpoint_id)
            || !validate_digest(&manifest.manifest_digest)
        {
            return Err(BackendError::Manifest);
        }
        let health = self.get_json("/healthz")?;
        if health.get("status").and_then(Value::as_str) != Some("ok") {
            return Err(BackendError::Response);
        }
        let runtime = self.get_json("/api/hepta/runtime")?;
        let generation = runtime
            .pointer("/state/runtime_snapshot_generation")
            .and_then(Value::as_u64)
            .ok_or(BackendError::Generation)?;
        let session_id = format!(
            "session.{}",
            &sha256_hex(format!(
                "hepta.native.session.v1\0{}\0{}\0{}",
                manifest.endpoint_id, manifest.manifest_digest, generation
            ))[..32]
        );
        Ok(NativeSession {
            endpoint_id: manifest.endpoint_id.clone(),
            manifest_digest: manifest.manifest_digest.clone(),
            protocol_version: manifest.protocol_version,
            session_id,
            generation,
        })
    }

    fn fetch_runtime(&mut self, session: &NativeSession) -> Result<Value, BackendError> {
        let runtime = self.get_json("/api/hepta/runtime")?;
        let generation = runtime
            .pointer("/state/runtime_snapshot_generation")
            .and_then(Value::as_u64)
            .ok_or(BackendError::Generation)?;
        if generation != session.generation {
            return Err(BackendError::Generation);
        }
        Ok(runtime)
    }
}
