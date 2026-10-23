//! An explicit signed capture observation, separate from text and qualification.
//! Only references/metadata enter AuthBus; PCM stays in the existing media root.
use crate::AgentdError;
use crate::AgentdState;
use crate::authbus_ingress::attached;
use crate::authbus_ingress::now_ms;
use crate::authbus_ingress::require_ready;
use crate::authbus_trust::hex_bytes;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_codex_adapter::hmi::HmiCapturedAudioRefV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_evidence::AuthBusDeliveryState;
use codex_hepta_evidence::AuthBusDeliveryStatus;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AudioObservationBodyV1 {
    pub spawn_generation: u64,
    pub thread_id: String,
    pub text: String,
    pub authority_sha256: String,
    pub source: HmiCapturedAudioRefV1,
}

/// The original registered producer signs this entire body in the audio domain.
/// No key, enrollment, hardware permission or effect authority is synthesized.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SignedAudioObservationV1 {
    pub issuer_id: String,
    pub key_epoch: u64,
    pub message_id: String,
    pub sequence: u64,
    pub expires_at_ms: u64,
    pub signature_hex: String,
    pub body: AudioObservationBodyV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub enum AudioObservationStateV1 {
    Queued,
    Leased,
    QueueAccepted,
    Expired,
    Quarantined,
}

/// A persisted source observation/admission, never a model/playback receipt.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AudioObservationReceiptV1 {
    pub delivery_id: String,
    pub observation_sha256: String,
    pub authority_sha256: String,
    pub source: HmiCapturedAudioRefV1,
    pub state: AudioObservationStateV1,
    pub queue_receipt_digest: Option<String>,
}

/// A failure may follow a known canonical commit. Preserve that receipt without
/// upgrading replay-checkpoint readiness, Core admission or external effects.
#[derive(Debug,thiserror::Error)]
#[error("{error}")]
pub(crate) struct AudioAdmissionFailure {
    #[source]
    pub error:Box<AgentdError>,
    pub committed_observation:Option<Box<AudioObservationReceiptV1>>,
}
impl From<AgentdError> for AudioAdmissionFailure {
    fn from(error:AgentdError)->Self {Self {error:Box::new(error),committed_observation:None}}
}

pub(crate) fn invalid(message: impl std::fmt::Display) -> AgentdError {
    AgentdError::Invalid(format!("signed audio observation: {message}"))
}

pub(crate) fn payload(body: &AudioObservationBodyV1) -> Result<Vec<u8>, AgentdError> {
    let source = &body.source;
    let stream = &source.stream;
    for id in [&stream.principal_id, &stream.device_id, &stream.organ_id] {
        StableId::new(id).map_err(invalid)?;
    }
    if body.spawn_generation == 0
        || body.thread_id.is_empty()
        || body.thread_id.len() > 128
        || body.text.trim().is_empty()
        || body.text.len() > 8192
        || stream.device_generation == 0
        || stream.organ_generation == 0
        || source.capture_generation == 0
        || source.sequence == 0
        || stream.logical_session_id != format!("thread:{}", body.thread_id)
        || source.sample_rate != 16000
        || source.num_channels != 1
        || source.byte_length == 0
        || source.byte_length > 1_048_576
        || source
            .end_sample
            .checked_sub(source.start_sample)
            .and_then(|n| n.checked_mul(2))
            != Some(source.byte_length)
        || source.asset_id
            != format!(
                "capture-{}-{}.pcm16",
                source.capture_generation, source.sequence
            )
    {
        return Err(invalid(
            "invalid capture scope, sample interval or PCM16LE reference",
        ));
    }
    for digest in [&body.authority_sha256, &source.sha256] {
        if digest.len() != 64
            || !digest
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        {
            return Err(invalid("invalid lowercase SHA-256"));
        }
    }
    let bytes = serde_json::to_vec(body)?;
    if bytes.len() > 16_384 {
        return Err(invalid("observation metadata exceeds 16 KiB"));
    }
    Ok(bytes)
}

/// Domain separation includes the capture incarnation, excluding the target
/// thread. One captured sequence cannot be replayed into another conversation.
pub fn audio_observation_claims(
    owner: &AgentId,
    request: &SignedAudioObservationV1,
) -> Result<SignedMessageClaims, AgentdError> {
    let body = payload(&request.body)?;
    if request.sequence != request.body.source.sequence {
        return Err(invalid("signed sequence must equal the captured sequence"));
    }
    Ok(SignedMessageClaims {
        issuer_id: StableId::new(&request.issuer_id).map_err(invalid)?,
        key_epoch: Generation::new(request.key_epoch).map_err(invalid)?,
        message_id: StableId::new(&request.message_id).map_err(invalid)?,
        subject_id: StableId::new(owner.as_str()).map_err(invalid)?,
        scope_digest: scope(
            owner,
            &request.body.source.stream,
            request.body.source.capture_generation,
        )?,
        payload_digest: Digest32::of_bytes(&body),
        sequence: request.sequence,
        expires_at_ms: request.expires_at_ms,
    })
}

pub(crate) fn scope(
    owner: &AgentId,
    s: &codex_hepta_codex_adapter::hmi::HmiCaptureStreamV1,
    capture_generation: u64,
) -> Result<Digest32, AgentdError> {
    Ok(Digest32::of_bytes(&serde_json::to_vec(&(
        "hepta.agentd.signed-audio-observation.v1",
        owner.as_str(),
        &s.principal_id,
        &s.device_id,
        s.device_generation,
        &s.organ_id,
        s.organ_generation,
        capture_generation,
    ))?))
}

pub(crate) fn message(
    state: &AgentdState,
    request: &SignedAudioObservationV1,
) -> Result<SignedMessage, AgentdError> {
    Ok(SignedMessage {
        claims: audio_observation_claims(&state.identity().agent_id, request)?,
        signature: hex_bytes(&request.signature_hex)?,
    })
}

enum Access {
    Admission,
    RetainedReceipt,
}
pub(crate) fn authenticate(
    state: &AgentdState,
    request: &SignedAudioObservationV1,
) -> Result<String, AgentdError> {
    authenticate_for(state, request, Access::Admission)
}
fn authenticate_for(
    state: &AgentdState,
    request: &SignedAudioObservationV1,
    access: Access,
) -> Result<String, AgentdError> {
    state.refresh_generation()?;
    require_ready(state)?;
    let host = attached(state)?;
    let policy = crate::audio_policy::AudioPolicy::current(state)?;
    policy.permits(&request.issuer_id, request.key_epoch, &request.body)?;
    let trust = host.trust(state)?;
    if !trust.permits(&request.body.thread_id)
        || (matches!(access, Access::Admission)
            && request.body.spawn_generation != state.identity().spawn_generation)
    {
        return Err(invalid(
            "current thread or Agentd generation is not permitted",
        ));
    }
    let now = now_ms()?;
    if request.expires_at_ms <= now || request.expires_at_ms.saturating_sub(now) > 300_000 {
        return Err(invalid("expiry must be within five minutes"));
    }
    let message = message(state, request)?;
    let verified = message
        .authenticate(
            &trust.issuer()?,
            message.claims.scope_digest,
            message.claims.payload_digest,
            now,
        )
        .map_err(invalid)?;
    Ok(verified.receipt().envelope_digest.to_string())
}

/// Read the exact retained observation after owner restart. Its independently
/// signed envelope, current device/thread policy and expiry still apply; only
/// the old process incarnation is historical. No insertion, lease, replay
/// advancement, source-availability claim or Core dispatch occurs on this path.
pub(crate) async fn reconcile(
    state: &AgentdState,
    request: SignedAudioObservationV1,
) -> Result<AudioObservationReceiptV1, AgentdError> {
    let delivery = authenticate_for(state, &request, Access::RetainedReceipt)?;
    let host = attached(state)?;
    let message = message(state, &request)?;
    let status = host
        .evidence
        .authbus_delivery_status(delivery.parse().map_err(invalid)?)
        .await
        .map_err(invalid)?;
    if status.subject_id != host.subject || status.scope_digest != message.claims.scope_digest {
        return Err(invalid(
            "retained observation belongs to another owner or capture route",
        ));
    }
    authenticate_for(state, &request, Access::RetainedReceipt)?;
    receipt(status, &request.body)
}

pub(crate) async fn submit(
    state: &AgentdState,
    request: SignedAudioObservationV1,
) -> Result<AudioObservationReceiptV1, AudioAdmissionFailure> {
    authenticate(state, &request)?;
    let policy = crate::audio_policy::AudioPolicy::current(state)?;
    policy
        .verify_media(state.identity(), &request.body.source)
        .await?;
    // Re-read real authorization after the asynchronous byte read, before any write.
    authenticate(state, &request)?;
    let host = attached(state)?;
    let message = message(state, &request)?;
    let body = payload(&request.body)?;
    let result = host
        .evidence
        .enqueue_authbus_message(
            &host.trust(state)?.issuer()?,
            &message,
            &host.subject,
            message.claims.scope_digest,
            &body,
        )
        .await
        .map_err(invalid)?;
    let committed_observation=receipt(result,&request.body)?;
    // A revocation after commit remains a real committed observation, but it
    // cannot authorize publication/dispatch. Recovery must use the original ID.
    let readiness=async {
        host.sync_replay_checkpoint().await?;
        authenticate(state,&request)?;
        Ok::<(),AgentdError>(())
    }.await;
    if let Err(error)=readiness {
        return Err(AudioAdmissionFailure {error:Box::new(error),committed_observation:Some(Box::new(committed_observation))});
    }
    Ok(committed_observation)
}

pub(crate) fn receipt(
    status: AuthBusDeliveryStatus,
    body: &AudioObservationBodyV1,
) -> Result<AudioObservationReceiptV1, AgentdError> {
    let state = match status.state {
        AuthBusDeliveryState::Queued => AudioObservationStateV1::Queued,
        AuthBusDeliveryState::Leased => AudioObservationStateV1::Leased,
        AuthBusDeliveryState::Acked => AudioObservationStateV1::QueueAccepted,
        AuthBusDeliveryState::Expired => AudioObservationStateV1::Expired,
        AuthBusDeliveryState::Quarantined => AudioObservationStateV1::Quarantined,
    };
    Ok(AudioObservationReceiptV1 {
        delivery_id: status.delivery_id.to_string(),
        observation_sha256: Digest32::of_bytes(&payload(body)?).to_string(),
        authority_sha256: body.authority_sha256.clone(),
        source: body.source.clone(),
        state,
        queue_receipt_digest: status.acknowledgement.map(|d| d.to_string()),
    })
}
