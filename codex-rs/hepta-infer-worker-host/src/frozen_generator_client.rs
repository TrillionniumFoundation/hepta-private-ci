//! Thin client for the independently installed, bounded Generator purpose.
//! The original compiler owns effect recovery. This client sends one request,
//! never retries unknown issuance, and cannot choose a role, key or frontier.
use crate::CpuNeuronGeneratorIssuancePortV2;
use crate::final_use_authorizer::validate_connected_issuer_with_attestation;
use crate::final_use_authorizer::validate_issuer_socket;
use codex_hepta_agent_components::frozen_generator_wire::*;
use codex_hepta_agent_components::learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_agent_components::learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::AgentdSelfIterationCandidateV1;
use codex_hepta_agentd::self_iteration_frozen_candidate_payload_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use std::future::Future;
use std::path::PathBuf;
use std::pin::Pin;
use std::time::Duration;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::UnixStream;

#[path = "frozen_generator_route.rs"]
mod routing;
use routing::Route;
#[path = "frozen_model_failure_client.rs"]
mod model_failure;

/// Installed route and original roster principal, with no signing material.
pub struct CpuNeuronFrozenGeneratorClientV1 {
    route_path: PathBuf,
    route_digest: Digest32,
    principal: StableId,
}

impl CpuNeuronFrozenGeneratorClientV1 {
    pub fn from_protected_route(
        route_path: PathBuf,
        route_digest: Digest32,
        principal: StableId,
    ) -> Result<Self, AgentdError> {
        Route::read(&route_path, route_digest).map_err(protocol)?;
        Ok(Self {
            route_path,
            route_digest,
            principal,
        })
    }

    async fn exchange(&self, payload: &[u8]) -> Result<SignedLearningEvidenceV1, AgentdError> {
        let request = encode_frozen_generator_request_v1(
            &FrozenGeneratorRequestV1::from_payload(payload).map_err(protocol)?,
        )
        .map_err(protocol)?;
        self.exchange_payload(payload, &request, PublicationMode::Issue)
            .await?
            .ok_or_else(|| AgentdError::Protocol("frozen Generator issuance absent".into()))
    }

    async fn observe_payload(
        &self,
        payload: &[u8],
    ) -> Result<Option<SignedLearningEvidenceV1>, AgentdError> {
        let request = encode_frozen_generator_observation_request_v2(
            &FrozenGeneratorObservationRequestV2::from_payload(payload).map_err(protocol)?,
        )
        .map_err(protocol)?;
        self.exchange_payload(payload, &request, PublicationMode::Observe)
            .await
    }

    async fn exchange_payload(
        &self,
        payload: &[u8],
        request: &[u8],
        mode: PublicationMode,
    ) -> Result<Option<SignedLearningEvidenceV1>, AgentdError> {
        let route = Route::read(&self.route_path, self.route_digest).map_err(protocol)?;
        let exchange = async {
            validate_issuer_socket(&route.socket, /*issuer_uid*/ 0).map_err(protocol)?;
            let mut stream = UnixStream::connect(&route.socket).await?;
            let response = exchange_connected(&mut stream, &route, request).await?;
            // Recheck the independently pinned route after the actual exchange.
            Route::read(&self.route_path, self.route_digest).map_err(protocol)?;
            let wire = match response {
                FrozenGeneratorResponseV1::Granted(wire) => wire,
                FrozenGeneratorResponseV1::Refused(refusal) => {
                    if matches!(mode, PublicationMode::Observe)
                        && matches!(
                            refusal.error,
                            FrozenGeneratorErrorCodeV1::Pending
                                | FrozenGeneratorErrorCodeV1::Unavailable
                        )
                    {
                        return Ok(None);
                    }
                    return Err(AgentdError::Protocol(format!(
                        "independent frozen Generator refused: {:?}",
                        refusal.error
                    )));
                }
            };
            let evidence = wire.native().map_err(protocol)?;
            if evidence.role != LearningEvidenceRoleV1::Generator
                || evidence.principal_id != self.principal
                || evidence.payload_digest != Digest32::of_bytes(payload)
            {
                return Err(AgentdError::Protocol(
                    "independent frozen Generator evidence binding mismatch".into(),
                ));
            }
            Ok(Some(evidence))
        };
        tokio::time::timeout(
            Duration::from_millis(route.maximum_request_duration_ms),
            exchange,
        )
        .await
        .map_err(|_| AgentdError::Protocol("frozen Generator exchange outcome unknown".into()))?
    }
}

impl CpuNeuronGeneratorIssuancePortV2 for CpuNeuronFrozenGeneratorClientV1 {
    fn principal_id(&self) -> &StableId {
        &self.principal
    }

    fn issue<'a>(
        &'a self,
        candidate: &'a AgentdSelfIterationCandidateV1,
    ) -> Pin<Box<dyn Future<Output = Result<SignedLearningEvidenceV1, AgentdError>> + Send + 'a>>
    {
        Box::pin(async move {
            if candidate.round.is_none()
                || candidate.canonical_envelope.is_none()
                || candidate.model_assessment.is_none()
            {
                return Err(AgentdError::Invalid(
                    "installed Generator requires original sealed round and full policy/model facts"
                        .into(),
                ));
            }
            let payload = self_iteration_frozen_candidate_payload_v1(candidate)?;
            self.exchange(&payload).await
        })
    }
    fn observe_publication<'a>(
        &'a self,
        candidate: &'a AgentdSelfIterationCandidateV1,
    ) -> Pin<
        Box<dyn Future<Output = Result<Option<SignedLearningEvidenceV1>, AgentdError>> + Send + 'a>,
    > {
        Box::pin(async move {
            if candidate.round.is_none()
                || candidate.canonical_envelope.is_none()
                || candidate.model_assessment.is_none()
            {
                return Err(AgentdError::Invalid("installed Generator observation requires original sealed round and full policy/model facts".into()));
            }
            self.observe_payload(&self_iteration_frozen_candidate_payload_v1(candidate)?)
                .await
        })
    }
}

#[derive(Clone, Copy)]
enum PublicationMode {
    Issue,
    Observe,
}

async fn exchange_connected(
    stream: &mut UnixStream,
    route: &Route,
    request: &[u8],
) -> Result<FrozenGeneratorResponseV1, AgentdError> {
    let bytes = exchange_connected_bytes(
        stream,
        route,
        request,
        MAX_FROZEN_GENERATOR_RESPONSE_BYTES_V1,
    )
    .await?;
    decode_frozen_generator_response_v1(&bytes).map_err(protocol)
}

async fn exchange_connected_bytes(
    stream: &mut UnixStream,
    route: &Route,
    request: &[u8],
    maximum_response_bytes: usize,
) -> Result<Vec<u8>, AgentdError> {
    let peer = stream.peer_cred()?;
    if peer.uid() != 0 {
        return Err(AgentdError::Protocol(
            "frozen Generator requires actual Root kernel peer".into(),
        ));
    }
    let guard = validate_connected_issuer_with_attestation(
        peer.pid()
            .map(u32::try_from)
            .transpose()
            .map_err(protocol)?,
        Some(&route.process_identity),
        Some(&route.process_attestation),
    )
    .map_err(protocol)?
    .ok_or_else(|| AgentdError::Protocol("frozen Generator process identity absent".into()))?;
    guard.revalidate().map_err(protocol)?;
    stream.write_all(request).await?;
    stream.write_all(b"\n").await?;
    stream.shutdown().await?;
    let mut bytes = Vec::new();
    (&mut *stream)
        .take(u64::try_from(maximum_response_bytes + 1).map_err(protocol)?)
        .read_to_end(&mut bytes)
        .await?;
    let final_peer = stream.peer_cred()?;
    if final_peer.uid() != 0 || final_peer.pid() != peer.pid() || final_peer.gid() != peer.gid() {
        return Err(AgentdError::Protocol(
            "frozen Generator kernel peer changed during exchange".into(),
        ));
    }
    guard.revalidate().map_err(protocol)?;
    validate_issuer_socket(&route.socket, /*issuer_uid*/ 0).map_err(protocol)?;
    if bytes.is_empty() || bytes.len() > maximum_response_bytes {
        return Err(AgentdError::Protocol(
            "whole Root service response byte bound".into(),
        ));
    }
    Ok(bytes)
}

fn protocol(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Protocol(error.to_string())
}

#[cfg(test)]
#[path = "frozen_generator_client_tests.rs"]
mod tests;
