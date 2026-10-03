//! Separate chat-purpose authentication forwards to the physically enrolled Root composition.
use std::path::PathBuf;
use std::time::Duration;

use anyhow::Context;
use anyhow::Result;
use codex_hepta_contracts::native_gateway::chat::NativeGatewayChatOperationV2;
use codex_hepta_contracts::native_gateway::chat::NativeGatewayChatRequestV2;
use codex_keyring_store::DefaultKeyringStore;
use codex_keyring_store::KeyringStore;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::net::UnixStream;
use zeroize::Zeroizing;

use crate::GatewayAuth;
use crate::chat_protocol::root::NativeChatRootRequest;
use crate::chat_protocol::root::NativeChatRootResponse;
use crate::chat_protocol::wire::ChatCommand;
use crate::chat_protocol::wire::MAX_CHAT_FRAME_BYTES;
use crate::lifecycle_http::Request;
use crate::source_launch::ChatOptions;

const ROOT_EXCHANGE_TIMEOUT: Duration = Duration::from_secs(4);

pub(super) struct ChatSource {
    socket: PathBuf,
    owner_uid: u32,
    capability: Zeroizing<String>,
}

impl ChatSource {
    pub(super) fn new(
        options: ChatOptions,
        read: &GatewayAuth,
        lifecycle: Option<&crate::lifecycle_source::LifecycleSource>,
    ) -> Result<Self> {
        anyhow::ensure!(
            options.owner_uid == 0,
            "chat requires the original Root owner"
        );
        let capability = match options.capability_file {
            Some(path) => crate::capability_input::load(&path)?,
            None => DefaultKeyringStore
                .load(
                    crate::GATEWAY_CHAT_KEYRING_SERVICE,
                    &options.auth_keyring_account,
                )?
                .context("separate chat capability is not provisioned")?,
        };
        Self::with_capability(
            options.socket,
            options.owner_uid,
            capability,
            read,
            lifecycle.map(|source| source.capability.as_bytes()),
        )
    }

    fn with_capability(
        socket: PathBuf,
        owner_uid: u32,
        capability: String,
        read: &GatewayAuth,
        lifecycle: Option<&[u8]>,
    ) -> Result<Self> {
        crate::validate_bearer_token(&capability)?;
        anyhow::ensure!(socket.is_absolute(), "chat socket must be absolute");
        anyhow::ensure!(
            capability.as_bytes() != read.bearer_token.as_bytes()
                && lifecycle != Some(capability.as_bytes()),
            "chat, read and lifecycle capabilities must be independently provisioned"
        );
        Ok(Self {
            socket,
            owner_uid,
            capability: Zeroizing::new(capability),
        })
    }

    pub(super) async fn route(&self, request: Request<'_>, auth: &GatewayAuth) -> Result<Vec<u8>> {
        let decoded: NativeChatRootRequest = match serde_json::from_slice(request.body) {
            Ok(decoded) => decoded,
            Err(_) => return Ok(crate::unauthorized_response()),
        };
        if decoded.validate().is_err() {
            return Ok(crate::unauthorized_response());
        }
        let proof = match request
            .authorization
            .and_then(|value| NativeGatewayChatRequestV2::parse_header(value).ok())
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
                operation(&decoded),
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
        let mut may_have_effect = false;
        let result = tokio::time::timeout(
            ROOT_EXCHANGE_TIMEOUT,
            self.forward(request.body, &decoded, &mut may_have_effect),
        )
        .await;
        let (status, payload) = match result {
            Ok(Ok(payload)) => ("200 OK", payload),
            _ => (
                "503 Service Unavailable",
                NativeChatRootResponse::Rejected {
                    code: "bridge_transport_unavailable".into(),
                    outcome_unknown: may_have_effect,
                },
            ),
        };
        let mut response = crate::response(
            status,
            "application/json; charset=utf-8",
            &serde_json::to_vec(&payload)?,
        );
        let (status, split) = crate::native_mac::response_parts(&response)?;
        let tag = proof.response_tag(self.capability.as_bytes(), status, &response[split + 4..])?;
        response.splice(
            split + 2..split + 2,
            format!("X-Hepta-Response-MAC: {tag}\r\n").bytes(),
        );
        Ok(response)
    }

    async fn forward(
        &self,
        body: &[u8],
        request: &NativeChatRootRequest,
        may_have_effect: &mut bool,
    ) -> Result<NativeChatRootResponse> {
        let mut stream = UnixStream::connect(&self.socket).await?;
        anyhow::ensure!(
            stream.peer_cred()?.uid() == self.owner_uid,
            "chat Root peer differs"
        );
        // Any failure after this point preserves the original operation identity.
        // No transparent resend is permitted even when the caller lost the reply.
        *may_have_effect = true;
        stream.write_all(body).await?;
        stream.write_all(b"\n").await?;
        stream.shutdown().await?;
        let mut reader = BufReader::new(stream).take(MAX_CHAT_FRAME_BYTES as u64 + 1);
        let mut bytes = Vec::new();
        let count = reader.read_until(b'\n', &mut bytes).await?;
        anyhow::ensure!(
            count > 0 && count <= MAX_CHAT_FRAME_BYTES && bytes.last() == Some(&b'\n'),
            "invalid bounded Root chat response"
        );
        let mut trailing = [0; 1];
        anyhow::ensure!(
            reader.read(&mut trailing).await? == 0,
            "trailing Root chat response"
        );
        let response: NativeChatRootResponse = serde_json::from_slice(&bytes)?;
        response.validate_for(request).map_err(anyhow::Error::msg)?;
        Ok(response)
    }
}

fn operation(request: &NativeChatRootRequest) -> NativeGatewayChatOperationV2 {
    match request {
        NativeChatRootRequest::Attach { .. } => NativeGatewayChatOperationV2::Attach,
        NativeChatRootRequest::Recover { .. } => NativeGatewayChatOperationV2::Reconcile,
        NativeChatRootRequest::Dispatch { request, .. } => match &request.command {
            ChatCommand::List { .. } => NativeGatewayChatOperationV2::List,
            ChatCommand::Create => NativeGatewayChatOperationV2::Create,
            ChatCommand::Timeline { .. } => NativeGatewayChatOperationV2::Timeline,
            ChatCommand::Resume { .. } => NativeGatewayChatOperationV2::Resume,
            ChatCommand::Send { .. } => NativeGatewayChatOperationV2::Send,
            ChatCommand::Reconcile { .. } => NativeGatewayChatOperationV2::Reconcile,
            ChatCommand::Cancel { .. } => NativeGatewayChatOperationV2::Cancel,
        },
    }
}

#[cfg(test)]
#[path = "chat_source_tests.rs"]
mod tests;
