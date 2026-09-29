//! Durable observation rules. An unknown outcome is never a final terminal.
use super::*;

pub(super) const fn legacy_observation_version() -> u32 {
    2
}

impl StoredTerminal {
    pub(super) fn is_final(&self) -> bool {
        matches!(
            self.disposition.as_str(),
            "Delivered" | "Rejected" | "NotDispatched"
        )
    }

    fn same_semantics(&self, other: &Self) -> bool {
        self.attempt_id == other.attempt_id
            && self.provider_receipt_digest == other.provider_receipt_digest
            && self.final_request_proof_digest == other.final_request_proof_digest
            && self.disposition == other.disposition
    }
}

pub(super) fn migrate_state(
    state: &mut StoredExactDeliveryState,
) -> Result<(), ExactContextDeliveryError> {
    match state.schema {
        EXACT_DELIVERY_SCHEMA => return Ok(()),
        2 => {
            state.schema = EXACT_DELIVERY_SCHEMA;
            return Ok(());
        }
        1 if state.observations.is_empty() => {}
        _ => return Err(ExactContextDeliveryError::CorruptState),
    }
    let unresolved = state
        .terminals
        .iter()
        .filter(|(_, observation)| observation.disposition == "Indeterminate")
        .map(|(attempt, _)| attempt.clone())
        .collect::<Vec<_>>();
    for attempt in unresolved {
        let observation = state
            .terminals
            .remove(&attempt)
            .ok_or(ExactContextDeliveryError::CorruptState)?;
        if state
            .observations
            .insert(observation_key(&observation), observation)
            .is_some()
        {
            return Err(ExactContextDeliveryError::CorruptState);
        }
    }
    state.schema = EXACT_DELIVERY_SCHEMA;
    Ok(())
}

fn observation_key(observation: &StoredTerminal) -> String {
    // The receipt digest is semantic identity; local retry timestamps are not.
    let mut bytes = b"hepta.context-durable-observation.v2".to_vec();
    bytes.extend_from_slice(observation.attempt_id.as_bytes());
    bytes.extend_from_slice(&observation.provider_receipt_digest);
    bytes.extend_from_slice(&observation.final_request_proof_digest);
    bytes.extend_from_slice(observation.disposition.as_bytes());
    Digest32::of_bytes(&bytes).to_string()
}

pub(super) fn apply_observation(
    state: &mut StoredExactDeliveryState,
    observation: StoredTerminal,
) -> Result<bool, ExactContextDeliveryError> {
    let pre_send = state
        .pre_sends
        .get(&observation.attempt_id)
        .ok_or(ExactContextDeliveryError::MissingPreSendEvidence)?;
    validate_observation(pre_send, &observation)?;
    let key = observation_key(&observation);
    if let Some(existing) = state.observations.get(&key) {
        return if existing.same_semantics(&observation) {
            Ok(false)
        } else {
            Err(ExactContextDeliveryError::CorruptState)
        };
    }
    if let Some(existing) = state.terminals.get(&observation.attempt_id) {
        return if existing.same_semantics(&observation) {
            Ok(false)
        } else {
            Err(ExactContextDeliveryError::Conflict("terminal is immutable"))
        };
    }
    let latest = state
        .observations
        .values()
        .filter(|existing| existing.attempt_id == observation.attempt_id)
        .map(|existing| existing.observed_unix_ms)
        .max()
        .unwrap_or(pre_send.recorded_unix_ms);
    if observation.observed_unix_ms < latest {
        return Err(ExactContextDeliveryError::Clock);
    }
    if observation.is_final() {
        if state.terminals.len() >= MAX_TERMINAL_RECORDS {
            return Err(ExactContextDeliveryError::Capacity);
        }
        state
            .terminals
            .insert(observation.attempt_id.clone(), observation);
    } else {
        if state.observations.len() >= MAX_TERMINAL_OBSERVATIONS {
            return Err(ExactContextDeliveryError::Capacity);
        }
        state.observations.insert(key, observation);
    }
    Ok(true)
}

fn validate_observation(
    pre_send: &StoredPreSend,
    observation: &StoredTerminal,
) -> Result<(), ExactContextDeliveryError> {
    if observation.attempt_id != pre_send.attempt_id
        || observation.final_request_proof_digest != pre_send.final_request_proof_digest
        || observation.terminal_observation_digest == [0; 32]
        || observation.provider_receipt_digest == [0; 32]
        || observation.context_delivery_receipt_digest == [0; 32]
        || observation.observed_unix_ms < pre_send.recorded_unix_ms
        || !matches!(
            observation.disposition.as_str(),
            "Delivered" | "Rejected" | "NotDispatched" | "Indeterminate"
        )
        || !matches!(observation.observation_version, 2 | 3)
    {
        return Err(ExactContextDeliveryError::CorruptState);
    }
    if let Some(receipt) = &observation.provider_receipt {
        receipt
            .validate()
            .map_err(|_| ExactContextDeliveryError::CorruptState)?;
        let wire = receipt
            .canonical_wire_bytes()
            .map_err(|_| ExactContextDeliveryError::CorruptState)?;
        let intent = receipt
            .intent
            .canonical_wire_bytes()
            .map_err(|_| ExactContextDeliveryError::CorruptState)?;
        let expected = match &receipt.terminal {
            ProviderTerminal::Completed { .. } | ProviderTerminal::CompletedUnary { .. } => {
                "Delivered"
            }
            ProviderTerminal::Rejected { .. } => "Rejected",
            ProviderTerminal::NotDispatched { .. } => "NotDispatched",
            ProviderTerminal::Indeterminate { .. } => "Indeterminate",
        };
        if Digest32::of_bytes(&wire).into_array() != observation.provider_receipt_digest
            || Digest32::of_bytes(&intent).into_array() != pre_send.provider_intent_digest
            || expected != observation.disposition
        {
            return Err(ExactContextDeliveryError::CorruptState);
        }
    } else if observation.observation_version != 2 {
        // Digest-only V1 history remains audit-readable, not upgraded evidence.
        return Err(ExactContextDeliveryError::CorruptState);
    }
    Ok(())
}

pub(super) fn validate(state: &StoredExactDeliveryState) -> Result<(), ExactContextDeliveryError> {
    if state.schema != EXACT_DELIVERY_SCHEMA
        || state.pre_sends.len() > MAX_PRE_SEND_RECORDS
        || state.terminals.len() > MAX_TERMINAL_RECORDS
        || state.observations.len() > MAX_TERMINAL_OBSERVATIONS
    {
        return Err(ExactContextDeliveryError::CorruptState);
    }
    for (attempt, pre_send) in &state.pre_sends {
        for identity in [
            attempt,
            &pre_send.thread_id,
            &pre_send.turn_id,
            &pre_send.attempt_id,
        ] {
            validate_runtime_id(identity, "durable identity")
                .map_err(|_| ExactContextDeliveryError::CorruptState)?;
        }
        if attempt != &pre_send.attempt_id
            || pre_send.recorded_unix_ms == 0
            || pre_send.token_count == 0
            || pre_send.token_count > codex_hepta_context_compiler::MAX_CONTEXT_TOKENS_V2
        {
            return Err(ExactContextDeliveryError::CorruptState);
        }
        for digest in [
            pre_send.provider_intent_digest,
            pre_send.authority_snapshot_digest,
            pre_send.preparation_binding_digest,
            pre_send.preparation_digest,
            pre_send.final_request_proof_digest,
            pre_send.provider_request_digest,
            pre_send.provider_wire_semantic_digest,
            pre_send.tokenizer_identity_digest,
            pre_send.tokenization_receipt_digest,
            pre_send.segment_map_digest,
        ] {
            if digest == [0; 32] {
                return Err(ExactContextDeliveryError::CorruptState);
            }
        }
        match &pre_send.recovery_archive {
            Some(archive) => {
                if archive.is_empty()
                    || archive.len() > MAX_RECOVERY_ARCHIVE_BYTES
                    || pre_send.recovery_binding_digest == [0; 32]
                {
                    return Err(ExactContextDeliveryError::CorruptState);
                }
                let recovery = ContextDeliveryRecoveryBindingV2::reopen_canonical_archive(archive)
                    .map_err(|_| ExactContextDeliveryError::CorruptState)?;
                if recovery.binding_digest().into_array() != pre_send.recovery_binding_digest
                    || recovery.final_request_proof_digest().into_array()
                        != pre_send.final_request_proof_digest
                    || recovery.provider_request_digest().into_array()
                        != pre_send.provider_request_digest
                    || recovery.provider_wire_semantic_digest().into_array()
                        != pre_send.provider_wire_semantic_digest
                    || Digest32::of_bytes(
                        &recovery
                            .provider_intent()
                            .canonical_wire_bytes()
                            .map_err(|_| ExactContextDeliveryError::CorruptState)?,
                    )
                    .into_array()
                        != pre_send.provider_intent_digest
                {
                    return Err(ExactContextDeliveryError::CorruptState);
                }
            }
            None if pre_send.recovery_binding_digest == [0; 32] => {}
            None => return Err(ExactContextDeliveryError::CorruptState),
        }
    }
    for (key, observation) in &state.terminals {
        if key != &observation.attempt_id || !observation.is_final() {
            return Err(ExactContextDeliveryError::CorruptState);
        }
        let pre_send = state
            .pre_sends
            .get(key)
            .ok_or(ExactContextDeliveryError::CorruptState)?;
        validate_observation(pre_send, observation)?;
    }
    for (key, observation) in &state.observations {
        if key != &observation_key(observation) || observation.is_final() {
            return Err(ExactContextDeliveryError::CorruptState);
        }
        let pre_send = state
            .pre_sends
            .get(&observation.attempt_id)
            .ok_or(ExactContextDeliveryError::CorruptState)?;
        validate_observation(pre_send, observation)?;
        if state
            .terminals
            .get(&observation.attempt_id)
            .is_some_and(|terminal| terminal.observed_unix_ms < observation.observed_unix_ms)
        {
            return Err(ExactContextDeliveryError::CorruptState);
        }
    }
    Ok(())
}

// Includes the serialized map key, record and punctuation. This is an explicit
// native record bound, not an estimate of provider usage or a disk-space grant.
const FINAL_COMPLETION_BYTES: u64 = 64 * 1024;

pub(super) fn completion_reserve(
    state: &StoredExactDeliveryState,
) -> Result<u64, ExactContextDeliveryError> {
    let pending = state
        .pre_sends
        .keys()
        .filter(|attempt| state.has_unresolved_attempt(attempt))
        .count();
    u64::try_from(pending)
        .ok()
        .and_then(|count| count.checked_mul(FINAL_COMPLETION_BYTES))
        .ok_or(ExactContextDeliveryError::Capacity)
}

pub(super) fn validate_terminal_size(
    terminal: &StoredTerminal,
) -> Result<(), ExactContextDeliveryError> {
    let encoded = serde_json::to_vec(&(&terminal.attempt_id, terminal))
        .map_err(|_| ExactContextDeliveryError::Unavailable)?;
    if u64::try_from(encoded.len())
        .ok()
        .and_then(|length| length.checked_add(4))
        .is_none_or(|length| length > FINAL_COMPLETION_BYTES)
    {
        return Err(ExactContextDeliveryError::Capacity);
    }
    Ok(())
}
