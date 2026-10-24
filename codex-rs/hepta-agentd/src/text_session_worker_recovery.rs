//! Read-only recovery into bounded transient correlation, never dispatch.
use super::*;

pub(super) async fn restore(
    signer: &TextSignerEndpoint,
    owner: &TextOwnerReceipt,
    session: &AgentdTextSession,
    intents: &mut BTreeMap<String, String>,
    messages: &mut BTreeMap<String, String>,
    prepared: &Arc<Mutex<BTreeMap<String, (AuthBusTextIngress, bool)>>>,
    emit: &impl Fn(TextWorkerEvent) -> Result<(), TextSessionError>,
) -> Result<Option<String>, TextSessionError> {
    let entries = super::super::signer::pending(signer, owner).await?;
    let current = super::super::signer::owner(signer).await?;
    if !current.same_authorization(owner) {
        return Err(TextSessionError::Identity);
    }
    for entry in entries {
        let request_id = entry.request_id;
        let envelope = entry.envelope;
        if intents
            .get(&request_id)
            .is_some_and(|text| text != &envelope.body.text)
        {
            return Err(TextSessionError::Identity);
        }
        if !intents.contains_key(&request_id) && intents.len() >= MAX_RETAINED {
            return Err(TextSessionError::Capacity);
        }
        let pending = super::super::prepare(&owner.route, envelope.clone())?;
        let claims =
            crate::authbus_text_claims(&owner.route.agent_id, &envelope).map_err(unavailable)?;
        let bytes = serde_json::to_vec(&envelope).map_err(unavailable)?;
        let reference = TextPrepared {
            host_reference: request_id.clone(),
            issuer_id: envelope.issuer_id.clone(),
            key_epoch: envelope.key_epoch,
            message_id: envelope.message_id.clone(),
            sequence: envelope.sequence,
            expires_at_ms: envelope.expires_at_ms,
            payload_sha256: *claims.payload_digest.as_array(),
            envelope_sha256: *Digest32::of_bytes(&bytes).as_array(),
            text: envelope.body.text.clone(),
            delivery_id: pending.delivery_id,
            spawn_generation: envelope.body.spawn_generation,
            lookup_only: true,
        };
        // Retain before publishing the UI projection. Even an early UI command
        // can only status-lookup this recovered identity in AgentdTextRequests.
        session.requests.restore_signed(envelope.clone())?;
        intents.insert(request_id.clone(), envelope.body.text.clone());
        messages.insert(envelope.message_id.clone(), request_id.clone());
        if let Some((original, lookup)) = prepared
            .lock()
            .map_err(|_| TextSessionError::Fenced)?
            .get_mut(&request_id)
        {
            if original != &envelope {
                return Err(TextSessionError::Identity);
            }
            *lookup = true;
        }
        emit(TextWorkerEvent::Recovered {
            connection_id: session.requests.connection_id(),
            reference,
        })?;
    }
    let page = session.requests.history_page(None).await?;
    let earlier_cursor = page.earlier_cursor.clone();
    emit(TextWorkerEvent::History {
        connection_id: session.requests.connection_id(),
        page,
        viewing_earlier: false,
    })?;
    emit(TextWorkerEvent::RecoveryComplete {
        connection_id: session.requests.connection_id(),
    })?;
    Ok(earlier_cursor)
}

pub(super) fn next_work(
    session: &AgentdTextSession,
    prepared: &Arc<Mutex<BTreeMap<String, (AuthBusTextIngress, bool)>>>,
    messages: &BTreeMap<String, String>,
    after: &str,
) -> Result<Option<(String, bool)>, TextSessionError> {
    let now = crate::authbus_ingress::now_ms().map_err(unavailable)?;
    let mut candidates = BTreeMap::new();
    for pending in session.requests.shared.current()?.pending.values() {
        if pending.terminal || now >= pending.envelope.expires_at_ms {
            candidates.insert(pending.envelope.message_id.clone(), true);
        } else if pending.recovered || pending.cancellation_requested {
            candidates.insert(pending.envelope.message_id.clone(), false);
        }
    }
    for (envelope, _) in prepared
        .lock()
        .map_err(|_| TextSessionError::Fenced)?
        .values()
    {
        if now >= envelope.expires_at_ms && messages.contains_key(&envelope.message_id) {
            candidates.insert(envelope.message_id.clone(), true);
        }
    }
    Ok(candidates
        .iter()
        .find(|(id, _)| id.as_str() > after)
        .or_else(|| candidates.iter().next())
        .map(|(id, retire)| (id.clone(), *retire)))
}
