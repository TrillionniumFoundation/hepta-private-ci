//! Two closed original operations on the single registered Root issuer lane.

use super::*;
use crate::AuthBusObjectiveBody;
use crate::AuthBusObjectiveIngress;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use std::os::fd::OwnedFd;

const SIGN_OBJECTIVE: &str = "runtime.authbus.objective.sign.v1";
const SIGNED_OBJECTIVE: &str = "runtime.authbus.objective.signed.v1";

impl AgentdUnixFinalUseGrantProvider {
    /// Typed text signing/lookup over the SAME pre-held registered Root lane.
    /// The original service retains request_id and its exact signed identity.
    /// This never opens a new connection or installs a text policy or signer.
    pub fn text(
        &self,
        request_id: &str,
        body: &crate::AuthBusTextBody,
        mode: crate::TextIssuerOperation,
    ) -> Result<crate::AuthBusTextIngress, AgentdFinalUseIssuerError> {
        if self.protected_root.is_none()
            || request_id.is_empty()
            || request_id.len() > 192
            || body.spawn_generation == 0
            || body.thread_id.len() > 128
            || body.text.len() > 8192
        {
            return Err(AgentdFinalUseIssuerError::InvalidConfiguration);
        }
        let request = serde_json::to_vec(&TextRequest {
            schema_version: 1,
            operation: "runtime.authbus.text.v1",
            request_id,
            body,
            mode,
        })
        .map_err(|_| AgentdFinalUseIssuerError::InvalidGrant)?;
        if request.len() > 32 * 1024 {
            return Err(AgentdFinalUseIssuerError::InvalidGrant);
        }
        self.exchange_guarded(|stream, deadline| {
            let bytes = exchange_frame(stream, &request, deadline)?;
            let response: TextResponse = serde_json::from_slice(&bytes)
                .map_err(|_| AgentdFinalUseIssuerError::MalformedResponse)?;
            if response.schema_version != 1
                || response.operation != "runtime.authbus.text.signed.v1"
                || response.request_id != request_id
                || response.ingress.body.thread_id != body.thread_id
                || response.ingress.body.text != body.text
                || response.ingress.body.spawn_generation == 0
                || response.ingress.body.spawn_generation > body.spawn_generation
                || response.ingress.sequence == 0
                || response.ingress.key_epoch == 0
                || response.ingress.signature_hex.len() != 128
                || !response
                    .ingress
                    .signature_hex
                    .bytes()
                    .all(|byte| matches!(byte, b'0'..=b'9' | b'a'..=b'f'))
            {
                return Err(AgentdFinalUseIssuerError::MalformedResponse);
            }
            Ok(response.ingress)
        })
    }

    /// Transfer an already connected UID-0 issuer lane and the launcher's
    /// pre-held pidfd for that exact Root process. There is no PID discovery,
    /// connect, renewal or retry. The absolute lifetime applies across both
    /// original operations; a Root death or uncertain reply closes both.
    pub fn from_root_stream(
        stream: UnixStream,
        root_pid: u32,
        root_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, AgentdFinalUseIssuerError> {
        Self::protected_stream(stream, root_pid, root_pidfd, timeout, lifetime, 0)
    }

    fn protected_stream(
        stream: UnixStream,
        root_pid: u32,
        root_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
        uid: u32,
    ) -> Result<Self, AgentdFinalUseIssuerError> {
        let end = Instant::now()
            .checked_add(lifetime)
            .ok_or(AgentdFinalUseIssuerError::InvalidConfiguration)?;
        let channel = HostAuthorityPeerChannel::from_stream(
            stream.try_clone().map_err(io_error)?,
            HostAuthorityPeerPolicy {
                peer: HostIssuerPeer { uid, pid: root_pid },
                timeout,
                lifetime,
                request_bound: MAX_RESPONSE_BYTES,
                response_bound: MAX_RESPONSE_BYTES,
            },
            root_pidfd,
        )
        .map_err(|_| AgentdFinalUseIssuerError::PeerDenied)?;
        let mut provider = Self::from_stream(
            stream,
            AgentdFinalUseIssuerPeer { uid, pid: root_pid },
            timeout,
        )?;
        provider.protected_root = Some(ProtectedRootIssuer { channel, end });
        Ok(provider)
    }

    /// Request the canonical service's original AuthBus signature. Call only
    /// from a bounded blocking worker, after the original operation is retained.
    /// This accepts a typed body, never an arbitrary signing preimage. The
    /// returned ingress still needs the original pinned AuthBus verifier at
    /// admission; neither a transport ACK nor structural parsing grants effects.
    pub fn sign_objective(
        &self,
        body: &AuthBusObjectiveBody,
    ) -> Result<AuthBusObjectiveIngress, AgentdFinalUseIssuerError> {
        if self.protected_root.is_none() {
            return Err(AgentdFinalUseIssuerError::InvalidConfiguration);
        }
        // Prevent unbounded serialization of caller-owned strings before the
        // complete encoded request receives its independent 64-KiB check.
        let size = [
            &body.run_id,
            &body.source_envelope_json,
            &body.runtime_body_digest,
            &body.preference_state_digest,
            &body.model_tuple_digest,
            &body.prompt_registry_digest,
            &body.artifact_set_digest,
        ]
        .into_iter()
        .try_fold(0usize, |total, field| total.checked_add(field.len()));
        if size.is_none_or(|size| size > MAX_RESPONSE_BYTES)
            || body.spawn_generation == 0
            || body.authority_epoch == 0
        {
            return Err(AgentdFinalUseIssuerError::InvalidGrant);
        }
        let request = serde_json::to_vec(&ObjectiveSignRequest {
            schema_version: SCHEMA_VERSION,
            operation: SIGN_OBJECTIVE,
            body,
        })
        .map_err(|_| AgentdFinalUseIssuerError::InvalidGrant)?;
        if request.len() > MAX_RESPONSE_BYTES {
            return Err(AgentdFinalUseIssuerError::InvalidGrant);
        }
        self.exchange_guarded(|stream, deadline| {
            let bytes = exchange_frame(stream, &request, deadline)?;
            let reply: ObjectiveSignResponse = serde_json::from_slice(&bytes)
                .map_err(|_| AgentdFinalUseIssuerError::MalformedResponse)?;
            if reply.schema_version != SCHEMA_VERSION
                || reply.operation != SIGNED_OBJECTIVE
                || reply.ingress.body != *body
                || reply.ingress.key_epoch != body.authority_epoch
                || reply.ingress.sequence == 0
                || reply.ingress.issuer_id.is_empty()
                || reply.ingress.message_id.is_empty()
                || reply.ingress.expires_at_ms == 0
                || reply.ingress.signature_hex.len() != 128
                || !reply
                    .ingress
                    .signature_hex
                    .bytes()
                    .all(|byte| matches!(byte, b'0'..=b'9' | b'a'..=b'f'))
            {
                return Err(AgentdFinalUseIssuerError::MalformedResponse);
            }
            Ok(reply.ingress)
        })
    }
}

#[derive(Serialize)]
struct ObjectiveSignRequest<'a> {
    schema_version: u32,
    operation: &'static str,
    body: &'a AuthBusObjectiveBody,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ObjectiveSignResponse {
    schema_version: u32,
    operation: String,
    ingress: AuthBusObjectiveIngress,
}

#[derive(Serialize)]
struct TextRequest<'a> {
    schema_version: u32,
    operation: &'static str,
    request_id: &'a str,
    body: &'a crate::AuthBusTextBody,
    mode: crate::TextIssuerOperation,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct TextResponse {
    schema_version: u32,
    operation: String,
    request_id: String,
    ingress: crate::AuthBusTextIngress,
}

#[cfg(test)]
#[path = "root_issuer_client_tests.rs"]
mod tests;
