//! Bounded one-request connections to the independently installed Root lane.
use super::*;

#[derive(Serialize)]
struct SignerRequest<'a> {
    schema_version: u32,
    operation: &'a str,
    request_id: &'a str,
    agent_id: &'a AgentId,
    spawn_generation: u64,
    thread_id: &'a str,
    text: &'a str,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SignerResponse {
    schema_version: u32,
    request_id: String,
    envelope: AuthBusTextIngress,
}

/// Wire proof is accepted only from the original credential-bound Root lane.
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum TextUnsignedClosure {
    Retained {
        envelope: AuthBusTextIngress,
    },
    Closed {
        through_sequence: u64,
        payload_sha256: [u8; 32],
    },
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct UnsignedClosureResponse {
    schema_version: u32,
    operation: String,
    request_id: String,
    outcome: TextUnsignedClosure,
}

pub(super) async fn close_unsigned(
    endpoint: &TextSignerEndpoint,
    config: &AgentdTextSessionConfig,
    request_id: &str,
    text: &str,
) -> Result<TextUnsignedClosure, TextSessionError> {
    let response: UnsignedClosureResponse = exchange(
        endpoint,
        &SignerRequest {
            schema_version: 1,
            operation: "close_unsigned",
            request_id,
            agent_id: &config.agent_id,
            spawn_generation: config.spawn_generation,
            thread_id: &config.thread_id,
            text,
        },
    )
    .await?;
    if response.schema_version != 1
        || response.operation != "close_unsigned"
        || response.request_id != request_id
    {
        return Err(TextSessionError::Identity);
    }
    match &response.outcome {
        TextUnsignedClosure::Retained { envelope } => {
            validate_input(config, text, envelope)?;
        }
        TextUnsignedClosure::Closed {
            through_sequence,
            payload_sha256,
        } => {
            let number = request_id
                .rsplit_once(':')
                .and_then(|(_, suffix)| suffix.parse::<u64>().ok())
                .ok_or(TextSessionError::Identity)?;
            let body = crate::AuthBusTextBody {
                spawn_generation: config.spawn_generation,
                thread_id: config.thread_id.clone(),
                text: text.into(),
            };
            let bytes = crate::authbus_ingress::payload(&body).map_err(unavailable)?;
            if number == 0
                || *through_sequence < number
                || payload_sha256 != codex_hepta_types::Digest32::of_bytes(&bytes).as_array()
            {
                return Err(TextSessionError::Identity);
            }
        }
    }
    Ok(response.outcome)
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct RetainedInput {
    pub(super) request_id: String,
    pub(super) envelope: AuthBusTextIngress,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct PendingResponse {
    schema_version: u32,
    operation: String,
    through_sequence: u64,
    entry: Option<RetainedInput>,
}

pub(super) async fn pending(
    endpoint: &TextSignerEndpoint,
    owner: &TextOwnerReceipt,
) -> Result<Vec<RetainedInput>, TextSessionError> {
    let through = owner
        .next_intent_sequence
        .checked_sub(1)
        .ok_or(TextSessionError::Identity)?;
    let prefix = format!("{}:", owner.intent_namespace);
    let mut after = 0;
    let mut retained = Vec::new();
    for _ in 0..=MAX_RETAINED {
        let page: PendingResponse = exchange(
            endpoint,
            &serde_json::json!({
                "schema_version": 1, "operation": "pending",
                "after_sequence": after, "through_sequence": through,
            }),
        )
        .await?;
        if page.schema_version != 1
            || page.operation != "pending"
            || page.through_sequence != through
        {
            return Err(TextSessionError::Identity);
        }
        let Some(entry) = page.entry else {
            return Ok(retained);
        };
        let number = entry
            .request_id
            .strip_prefix(&prefix)
            .and_then(|suffix| suffix.parse::<u64>().ok())
            .ok_or(TextSessionError::Identity)?;
        if number <= after
            || number > through
            || entry.request_id != format!("{prefix}{number}")
            || entry.envelope.body.thread_id != owner.route.thread_id
            || entry.envelope.body.spawn_generation == 0
            || entry.envelope.body.spawn_generation > owner.route.spawn_generation
        {
            return Err(TextSessionError::Identity);
        }
        if retained.len() >= MAX_RETAINED {
            return Err(TextSessionError::Capacity);
        }
        after = number;
        retained.push(entry);
    }
    Err(TextSessionError::Capacity)
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RetirementResponse {
    schema_version: u32,
    operation: String,
    request_id: String,
}

pub(super) async fn retire_input(
    endpoint: &TextSignerEndpoint,
    config: &AgentdTextSessionConfig,
    request_id: &str,
    text: &str,
) -> Result<(), TextSessionError> {
    let response: RetirementResponse = exchange(
        endpoint,
        &SignerRequest {
            schema_version: 1,
            operation: "retire",
            request_id,
            agent_id: &config.agent_id,
            spawn_generation: config.spawn_generation,
            thread_id: &config.thread_id,
            text,
        },
    )
    .await?;
    if response.schema_version != 1
        || response.operation != "retired"
        || response.request_id != request_id
    {
        return Err(TextSessionError::Identity);
    }
    Ok(())
}

pub(super) async fn owner(
    endpoint: &TextSignerEndpoint,
) -> Result<TextOwnerReceipt, TextSessionError> {
    // A renderer-provided ordinary user socket cannot establish a chat owner.
    if endpoint.owner_uid != 0 {
        return Err(TextSessionError::Identity);
    }
    let receipt: TextOwnerReceipt = exchange(
        endpoint,
        &serde_json::json!({"schema_version":1,"operation":"hello"}),
    )
    .await?;
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(unavailable)?
        .as_millis();
    if !receipt.validate() || now >= u128::from(receipt.expires_at_ms) {
        return Err(TextSessionError::Identity);
    }
    Ok(receipt)
}

pub(super) async fn signed_input(
    endpoint: &TextSignerEndpoint,
    config: &AgentdTextSessionConfig,
    request_id: &str,
    text: &str,
    lookup: bool,
) -> Result<AuthBusTextIngress, TextSessionError> {
    let response: SignerResponse = exchange(
        endpoint,
        &SignerRequest {
            schema_version: 1,
            operation: if lookup { "lookup" } else { "sign" },
            request_id,
            agent_id: &config.agent_id,
            spawn_generation: config.spawn_generation,
            thread_id: &config.thread_id,
            text,
        },
    )
    .await?;
    if response.schema_version != 1 || response.request_id != request_id {
        return Err(TextSessionError::Identity);
    }
    validate_input(config, text, &response.envelope)?;
    Ok(response.envelope)
}

fn validate_input(
    config: &AgentdTextSessionConfig,
    text: &str,
    envelope: &AuthBusTextIngress,
) -> Result<(), TextSessionError> {
    if envelope.body.thread_id != config.thread_id
        || envelope.body.text != text
        || envelope.body.spawn_generation == 0
        || envelope.body.spawn_generation > config.spawn_generation
    {
        return Err(TextSessionError::Identity);
    }
    Ok(())
}

#[cfg(unix)]
async fn exchange<T: serde::de::DeserializeOwned>(
    endpoint: &TextSignerEndpoint,
    request: &impl Serialize,
) -> Result<T, TextSessionError> {
    use tokio::io::AsyncReadExt;
    use tokio::io::AsyncWriteExt;
    let not_transmitted = |error: String| TextSessionError::NotTransmitted(error);
    let bytes = serde_json::to_vec(request).map_err(|error| not_transmitted(error.to_string()))?;
    let length = u32::try_from(bytes.len()).map_err(|error| not_transmitted(error.to_string()))?;
    if length == 0 || length > 32768 {
        return Err(not_transmitted(
            "request exceeds the Root lane bound".into(),
        ));
    }
    let connect = async {
        let stream = tokio::net::UnixStream::connect(&endpoint.socket_path)
            .await
            .map_err(|error| not_transmitted(error.to_string()))?;
        let peer = stream
            .peer_cred()
            .map_err(|error| not_transmitted(error.to_string()))?;
        if peer.uid() != endpoint.owner_uid
            || peer.pid().and_then(|pid| u32::try_from(pid).ok()) != Some(endpoint.owner_pid)
        {
            return Err(not_transmitted(
                "Root peer identity mismatch before request write".into(),
            ));
        }
        Ok(stream)
    };
    let mut stream = tokio::time::timeout(REQUEST_TIMEOUT, connect)
        .await
        .map_err(|error| not_transmitted(error.to_string()))??;
    // From the FIRST write call onward all errors and timeouts are ambiguous.
    // Even a partial frame is never returned as a non-transmission proof.
    let work = async {
        stream
            .write_all(&length.to_be_bytes())
            .await
            .map_err(unavailable)?;
        stream.write_all(&bytes).await.map_err(unavailable)?;
        let length = stream.read_u32().await.map_err(unavailable)?;
        if length == 0 || length > 32768 {
            return Err(TextSessionError::Capacity);
        }
        let mut bytes = vec![0; length as usize];
        stream.read_exact(&mut bytes).await.map_err(unavailable)?;
        serde_json::from_slice(&bytes).map_err(unavailable)
    };
    tokio::time::timeout(REQUEST_TIMEOUT, work)
        .await
        .map_err(unavailable)?
}

#[cfg(all(test, unix))]
#[path = "text_session_signer_tests.rs"]
mod tests;

#[cfg(not(unix))]
async fn exchange<T: serde::de::DeserializeOwned>(
    _endpoint: &TextSignerEndpoint,
    _request: &impl Serialize,
) -> Result<T, TextSessionError> {
    Err(unavailable(
        "the installed Unix Root text lane is unavailable on this platform",
    ))
}
