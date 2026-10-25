//! Native text signer entry for the already installed Root/Host session.
//! The launcher passes the original Root session/provider and a pre-accepted
//! authenticated UI channel with its pre-held pidfd. Nothing here discovers an
//! issuer, creates trust, reads a private key, or registers a writer.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerTransportError;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentdRootAuthoritySession;
use crate::AgentdUnixFinalUseGrantProvider;
use crate::AuthBusTextBody;
use crate::AuthBusTextIngress;
use crate::TextIssuerOperation;
use crate::text_session::AgentdTextSessionConfig;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    schema_version: u32,
    operation: TextIssuerOperation,
    request_id: String,
    agent_id: codex_hepta_contracts::AgentId,
    spawn_generation: u64,
    thread_id: String,
    text: String,
}

#[derive(Serialize)]
struct Response {
    schema_version: u32,
    request_id: String,
    envelope: AuthBusTextIngress,
}

impl AgentdRootAuthoritySession {
    /// Runs the actual private host endpoint on a bounded blocking worker.
    /// Admission requires the same live original writer, exact fixed thread,
    /// registered UI peer and kernel-held UI lifetime for EVERY request.
    /// The authenticated caller retains its existing OwnerSession; this method
    /// neither creates a human principal nor interprets a DTO as authority.
    pub fn serve_authenticated_text_signer(
        &self,
        issuer: &Arc<AgentdUnixFinalUseGrantProvider>,
        config: &AgentdTextSessionConfig,
        stream: UnixStream,
        mut ui_policy: HostAuthorityPeerPolicy,
        ui_pidfd: OwnedFd,
    ) -> Result<(), HostIssuerTransportError> {
        ui_policy.request_bound = 32 * 1024;
        ui_policy.response_bound = 32 * 1024;
        let mut channel = HostAuthorityPeerChannel::from_stream(stream, ui_policy, ui_pidfd)?;
        let authority = self.authority();
        if authority.agent_id != config.agent_id {
            return Err(HostIssuerTransportError::InvalidRequest);
        }
        while channel.exchange(|bytes| {
            let request: Request = serde_json::from_slice(bytes)
                .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
            if request.schema_version != 1
                || request.agent_id != config.agent_id
                || request.spawn_generation != config.spawn_generation
                || request.thread_id != config.thread_id
                || request.text.trim().is_empty()
                || request.text.len() > 8192
            {
                return Err(HostIssuerTransportError::InvalidRequest);
            }
            self.verifier()
                .verify(&authority, &config.agent_id)
                .map_err(|_| HostIssuerTransportError::Unavailable)?;
            let envelope = issuer
                .text(
                    &request.request_id,
                    &AuthBusTextBody {
                        spawn_generation: config.spawn_generation,
                        thread_id: config.thread_id.clone(),
                        text: request.text,
                    },
                    request.operation,
                )
                .map_err(|_| HostIssuerTransportError::Unavailable)?;
            // A grant/signature returned just as the original Root feed expires
            // is retained at the issuer but cannot be presented as a new ready send.
            self.verifier()
                .verify(&authority, &config.agent_id)
                .map_err(|_| HostIssuerTransportError::Unavailable)?;
            let response = serde_json::to_vec(&Response {
                schema_version: 1,
                request_id: request.request_id,
                envelope,
            })
            .map_err(|_| HostIssuerTransportError::Unavailable)?;
            if response.len() > 32 * 1024 {
                return Err(HostIssuerTransportError::Unavailable);
            }
            Ok(response)
        })? {}
        Ok(())
    }
}
