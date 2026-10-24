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
    if response.schema_version != 1
        || response.request_id != request_id
        || response.envelope.body.thread_id != config.thread_id
        || response.envelope.body.text != text
        || response.envelope.body.spawn_generation == 0
        || response.envelope.body.spawn_generation > config.spawn_generation
    {
        return Err(TextSessionError::Identity);
    }
    Ok(response.envelope)
}

#[cfg(unix)]
async fn exchange<T: serde::de::DeserializeOwned>(
    endpoint: &TextSignerEndpoint,
    request: &impl Serialize,
) -> Result<T, TextSessionError> {
    use tokio::io::AsyncReadExt;
    use tokio::io::AsyncWriteExt;
    let work = async {
        let mut stream = tokio::net::UnixStream::connect(&endpoint.socket_path)
            .await
            .map_err(unavailable)?;
        let peer = stream.peer_cred().map_err(unavailable)?;
        if peer.uid() != endpoint.owner_uid
            || peer.pid().and_then(|pid| u32::try_from(pid).ok()) != Some(endpoint.owner_pid)
        {
            return Err(TextSessionError::Identity);
        }
        let bytes = serde_json::to_vec(request).map_err(unavailable)?;
        let length = u32::try_from(bytes.len()).map_err(unavailable)?;
        if length == 0 || length > 32768 {
            return Err(TextSessionError::Capacity);
        }
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
