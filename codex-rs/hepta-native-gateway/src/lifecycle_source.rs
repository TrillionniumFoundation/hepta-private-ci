//! Explicit lifecycle capability forwards only the original owner's finite wire.

use anyhow::Context;
use anyhow::Result;
use codex_hepta_contracts::native_gateway::lifecycle::NativeGatewayLifecycleOperationV2;
use codex_hepta_contracts::native_gateway::lifecycle::NativeGatewayLifecycleRequestV2;
use codex_hepta_supervisor::SupervisorControllerClient;
use codex_hepta_supervisor::SupervisorControllerMethod;
use codex_hepta_supervisor::SupervisorControllerRequest;
use codex_keyring_store::DefaultKeyringStore;
use codex_keyring_store::KeyringStore;
use zeroize::Zeroizing;

use crate::GatewayAuth;
use crate::lifecycle_http::Request;
use crate::source_launch::ControllerOptions;

pub(super) struct LifecycleSource {
    client: SupervisorControllerClient,
    capability: Zeroizing<String>,
}

impl LifecycleSource {
    pub(super) fn new(options: ControllerOptions, read: &GatewayAuth) -> Result<Self> {
        let capability = match options.capability_file {
            Some(path) => crate::capability_input::load(&path)?,
            None => DefaultKeyringStore
                .load(
                    crate::GATEWAY_LIFECYCLE_KEYRING_SERVICE,
                    &options.auth_keyring_account,
                )?
                .context("separate lifecycle capability is not provisioned")?,
        };
        Self::with_capability(options.socket, options.owner_uid, capability, read)
    }

    fn with_capability(
        socket: std::path::PathBuf,
        owner_uid: u32,
        capability: String,
        read: &GatewayAuth,
    ) -> Result<Self> {
        crate::validate_bearer_token(&capability)?;
        if capability.as_bytes() == read.bearer_token.as_bytes() {
            anyhow::bail!("lifecycle and read capabilities must be independently provisioned");
        }
        Ok(Self {
            client: SupervisorControllerClient::new(socket, owner_uid)?,
            capability: Zeroizing::new(capability),
        })
    }

    pub(super) async fn route(&self, request: Request<'_>, auth: &GatewayAuth) -> Result<Vec<u8>> {
        let decoded: SupervisorControllerRequest = match serde_json::from_slice(request.body) {
            Ok(request) => request,
            Err(_) => return Ok(crate::unauthorized_response()),
        };
        if decoded.validate().is_err() {
            return Ok(crate::unauthorized_response());
        }
        let operation = operation(&decoded.method);
        let proof = match request
            .authorization
            .and_then(|value| NativeGatewayLifecycleRequestV2::parse_header(value).ok())
        {
            Some(proof) => proof,
            None => return Ok(crate::unauthorized_response()),
        };
        let now = crate::native_mac::now_unix_ms()?;
        if proof
            .verify(
                self.capability.as_bytes(),
                request.method,
                request.path,
                operation,
                request.body,
                now,
                &auth.server_incarnation,
            )
            .is_err()
            || crate::native_mac::remember_nonce(auth, proof.nonce(), proof.expires_unix_ms(), now)
                .is_err()
        {
            return Ok(crate::unauthorized_response());
        }
        let request_id = decoded.request_id;
        let response = match self.client.request(decoded).await {
            Ok(payload) => crate::response(
                "200 OK",
                "application/json; charset=utf-8",
                &serde_json::to_vec(&payload)?,
            ),
            Err(_) => crate::response(
                "503 Service Unavailable",
                "application/json; charset=utf-8",
                &serde_json::to_vec(&serde_json::json!({
                    "type": "transport_indeterminate", "request_id": request_id,
                    "message": "inspect the original lifecycle receipt before any new request",
                }))?,
            ),
        };
        let (status, split) = crate::native_mac::response_parts(&response)?;
        let tag = proof.response_tag(self.capability.as_bytes(), status, &response[split + 4..])?;
        let mut response = response;
        response.splice(
            split + 2..split + 2,
            format!("X-Hepta-Response-MAC: {tag}\r\n").bytes(),
        );
        Ok(response)
    }
}

fn operation(method: &SupervisorControllerMethod) -> NativeGatewayLifecycleOperationV2 {
    match method {
        SupervisorControllerMethod::Start { .. } => NativeGatewayLifecycleOperationV2::Start,
        SupervisorControllerMethod::Stop { .. } => NativeGatewayLifecycleOperationV2::Stop,
        SupervisorControllerMethod::Restart { .. } => NativeGatewayLifecycleOperationV2::Restart,
        SupervisorControllerMethod::Receipt { .. } => NativeGatewayLifecycleOperationV2::Receipt,
    }
}

#[cfg(test)]
#[path = "lifecycle_source_tests.rs"]
mod tests;
