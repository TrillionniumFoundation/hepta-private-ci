//! Unsigned attempts require a pre-write proof or the original Root CAS. No
//! timeout, local eviction, or absence-only lookup releases an ambiguous ID.
use super::*;

pub(super) fn intent_number(
    owner: &TextOwnerReceipt,
    request_id: &str,
) -> Result<u64, TextSessionError> {
    let prefix = format!("{}:", owner.intent_namespace);
    let number = request_id
        .strip_prefix(&prefix)
        .and_then(|suffix| suffix.parse::<u64>().ok())
        .ok_or(TextSessionError::Identity)?;
    if number == 0 || request_id != format!("{prefix}{number}") {
        return Err(TextSessionError::Identity);
    }
    Ok(number)
}

pub(super) fn closed(
    connection_id: u64,
    request_id: String,
    text: &str,
    message: &str,
) -> TextWorkerEvent {
    TextWorkerEvent::PreparationClosed {
        connection_id,
        request_id,
        text_sha256: *Digest32::of_bytes(text.as_bytes()).as_array(),
        original_watermark: None,
        message: format!("Original preparation closed; your draft is preserved. {message}"),
    }
}

pub(super) fn next(
    intents: &BTreeMap<String, String>,
    messages: &BTreeMap<String, String>,
    prepared: &Arc<Mutex<BTreeMap<String, (AuthBusTextIngress, bool)>>>,
    after: &str,
) -> Result<Option<(String, String)>, TextSessionError> {
    let prepared = prepared.lock().map_err(|_| TextSessionError::Fenced)?;
    let eligible =
        |id: &String| !messages.values().any(|known| known == id) && !prepared.contains_key(id);
    Ok(intents
        .iter()
        .find(|(id, _)| id.as_str() > after && eligible(id))
        .or_else(|| intents.iter().find(|(id, _)| eligible(id)))
        .map(|(id, text)| (id.clone(), text.clone())))
}

pub(super) async fn close(
    signer: &TextSignerEndpoint,
    config: &AgentdTextSessionConfig,
    requests: &AgentdTextRequests,
    request_id: &str,
    text: &str,
) -> Result<TextWorkerEvent, TextSessionError> {
    match super::super::signer::close_unsigned(signer, config, request_id, text).await? {
        TextUnsignedClosure::Retained { envelope } => {
            // An earlier Sign committed but its response was lost. Only an
            // original reference/status lookup is permitted, never dispatch.
            requests.restore_signed(envelope.clone())?;
            let reference = recovery::reference(config, request_id, &envelope, true)?;
            Ok(TextWorkerEvent::Recovered {
                connection_id: requests.connection_id(),
                reference,
            })
        }
        TextUnsignedClosure::Closed {
            through_sequence, ..
        } => Ok(TextWorkerEvent::PreparationClosed {
            connection_id: requests.connection_id(),
            request_id: request_id.into(),
            text_sha256: *Digest32::of_bytes(text.as_bytes()).as_array(),
            original_watermark: Some(through_sequence),
            message:
                "The original Root owner durably closed this preparation. Your draft is preserved."
                    .into(),
        }),
    }
}
