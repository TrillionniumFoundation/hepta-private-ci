use std::net::SocketAddr;

use serde_json::Value;

use crate::error::ShellError;
use crate::model::EndpointManifest;
use crate::model::SessionIncarnation;
use crate::model::sha256_hex;
use crate::security::now_unix_ms;

#[derive(Debug, Clone)]
pub struct AuthenticatedRuntimeStatus {
    pub value: Value,
    pub body_digest: String,
}

pub trait BackendAdapter: Send {
    fn connect(&mut self, manifest: &EndpointManifest) -> Result<SessionIncarnation, ShellError>;
    fn runtime_status(&mut self) -> Result<AuthenticatedRuntimeStatus, ShellError>;
    fn close(&mut self, session: &SessionIncarnation) -> Result<(), ShellError>;
    fn fleet_lifecycle_available(&self) -> bool {
        false
    }
    fn fleet_lifecycle(
        &mut self,
        _operation: crate::fleet_lifecycle::FleetLifecycleOperation,
        _body: &Value,
    ) -> Result<AuthenticatedRuntimeStatus, ShellError> {
        Err(ShellError::State(
            "Agent lifecycle control is not supported by this backend".into(),
        ))
    }
}

pub struct LoopbackGatewayBackend {
    address: SocketAddr,
    bearer_token: zeroize::Zeroizing<String>,
    server_incarnation: [u8; 32],
    session: Option<SessionIncarnation>,
    lifecycle_capability: Option<zeroize::Zeroizing<String>>,
    server_lifecycle: bool,
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
            bearer_token: zeroize::Zeroizing::new(bearer_token),
            server_incarnation: [0; 32],
            session: None,
            lifecycle_capability: None,
            server_lifecycle: false,
        })
    }

    fn get_json(&self, path: &str) -> Result<AuthenticatedRuntimeStatus, ShellError> {
        crate::native_http::get_json(
            self.address,
            self.bearer_token.as_bytes(),
            path,
            self.server_incarnation,
        )
    }

    pub fn with_fleet_lifecycle_capability(
        mut self,
        capability: String,
    ) -> Result<Self, ShellError> {
        validate_bearer_token(&capability)?;
        if capability.as_bytes() == self.bearer_token.as_bytes() {
            return Err(ShellError::Security(
                "Agent lifecycle capability must differ from the read capability".into(),
            ));
        }
        self.lifecycle_capability = Some(zeroize::Zeroizing::new(capability));
        Ok(self)
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
        if self.session.is_some() {
            return Err(ShellError::State(
                "close the current native gateway session before reconnecting".into(),
            ));
        }
        self.server_incarnation = [0; 32];
        self.server_lifecycle = false;
        manifest.validate()?;
        if manifest.protocol_version
            != codex_hepta_contracts::native_gateway::NATIVE_GATEWAY_PROTOCOL_V2
        {
            return Err(ShellError::Security("product native gateway requires a signed protocol-v2 manifest; bearer-only fallback is disabled".into()));
        }
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
        if health.value.get("product").and_then(Value::as_str) != Some("hepta")
            || health.value.get("status").and_then(Value::as_str) != Some("ok")
            || health.value.get("native_auth").and_then(Value::as_str) != Some("keyring_mac_v2")
        {
            return Err(ShellError::Backend(
                "gateway health identity is not the expected Hepta product".to_owned(),
            ));
        }
        let observed_protocol = health
            .value
            .get("native_protocol_version")
            .and_then(Value::as_u64)
            .ok_or_else(|| {
                ShellError::Backend(
                    "gateway health is missing the native protocol version".to_owned(),
                )
            })?;
        if observed_protocol != u64::from(manifest.protocol_version) {
            return Err(ShellError::Backend(format!(
                "gateway native protocol version mismatch: manifest={}, observed={observed_protocol}",
                manifest.protocol_version
            )));
        }

        let server_incarnation =
            codex_hepta_contracts::native_gateway::parse_native_gateway_incarnation(
                health
                    .value
                    .get("native_incarnation")
                    .and_then(Value::as_str)
                    .ok_or_else(|| {
                        ShellError::Backend("gateway lacks its authenticated incarnation".into())
                    })?,
            )
            .map_err(|e| ShellError::Security(e.to_string()))?;
        let mut session_nonce = [0_u8; 32];
        getrandom::fill(&mut session_nonce).map_err(|error| {
            ShellError::Security(format!("generate native session incarnation: {error}"))
        })?;
        let now = now_unix_ms()?.max(1);
        let session = SessionIncarnation {
            endpoint_id: manifest.endpoint_id.clone(),
            session_id: format!("native.{}", sha256_hex(session_nonce)),
            generation: now,
        };
        session.validate()?;
        // Publish transport authority only after the complete session is valid.
        self.server_incarnation = server_incarnation;
        self.server_lifecycle = health
            .value
            .get("lifecycle_control")
            .and_then(Value::as_bool)
            == Some(true);
        self.session = Some(session.clone());
        Ok(session)
    }

    fn runtime_status(&mut self) -> Result<AuthenticatedRuntimeStatus, ShellError> {
        if self.server_incarnation == [0; 32] {
            return Err(ShellError::Backend(
                "gateway must authenticate before reading runtime state".into(),
            ));
        }
        self.get_json("/api/hepta/runtime")
    }

    fn close(&mut self, session: &SessionIncarnation) -> Result<(), ShellError> {
        session.validate()?;
        if self
            .session
            .as_ref()
            .is_some_and(|current| current != session)
        {
            return Err(ShellError::State(
                "cannot close a different native gateway session incarnation".into(),
            ));
        }
        self.server_incarnation = [0; 32];
        self.server_lifecycle = false;
        self.session = None;
        Ok(())
    }

    fn fleet_lifecycle_available(&self) -> bool {
        self.server_incarnation != [0; 32]
            && self.server_lifecycle
            && self.lifecycle_capability.is_some()
    }

    fn fleet_lifecycle(
        &mut self,
        operation: crate::fleet_lifecycle::FleetLifecycleOperation,
        body: &Value,
    ) -> Result<AuthenticatedRuntimeStatus, ShellError> {
        if !self.fleet_lifecycle_available() {
            return Err(ShellError::State(
                "Agent lifecycle control is not enabled".into(),
            ));
        }
        crate::native_http::post_lifecycle(
            self.address,
            self.lifecycle_capability
                .as_ref()
                .expect("enabled capability")
                .as_bytes(),
            operation,
            &serde_json::to_vec(body)?,
            self.server_incarnation,
        )
    }
}
