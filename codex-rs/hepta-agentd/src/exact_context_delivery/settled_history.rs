//! Bounded, raw-free settlement history for the existing exact-delivery owner.
//!
//! Final attempts are compacted only after their terminal is durable in the
//! same state transition. Recent exact tombstones remain individually
//! verifiable. Older tombstones roll into a versioned digest chain plus fixed
//! fail-closed membership filters. The filters may conservatively reject a
//! fresh colliding identity, but they never authorize replay of archived work.

use super::*;

pub(super) const MAX_RECENT_SETTLED_ATTEMPTS: usize = 1024;
const SETTLEMENT_CHECKPOINT_SCHEMA: u32 = 1;
const FILTER_WORDS: usize = 128;
const FILTER_HASHES: usize = 4;
const SETTLED_RECORD_DOMAIN: &[u8] = b"hepta.context-settled-attempt.v1";
const SETTLED_OBSERVATIONS_DOMAIN: &[u8] = b"hepta.context-settled-observations.v1";
const CHECKPOINT_CHAIN_DOMAIN: &[u8] = b"hepta.context-settlement-checkpoint-chain.v1";
const CHECKPOINT_MEMBERSHIP_DOMAIN: &[u8] = b"hepta.context-settlement-membership.v1";
const ATTEMPT_FILTER_DOMAIN: &[u8] = b"hepta.context-settlement-attempt-filter.v1";
const TURN_FILTER_DOMAIN: &[u8] = b"hepta.context-settlement-turn-filter.v1";

#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct SettledAttempt {
    pub(super) sequence: u64,
    pub(super) thread_id: String,
    pub(super) turn_id: String,
    pub(super) attempt_id: String,
    pub(super) provider_intent_digest: [u8; 32],
    pub(super) authority_snapshot_digest: [u8; 32],
    pub(super) preparation_binding_digest: [u8; 32],
    pub(super) preparation_digest: [u8; 32],
    pub(super) final_request_proof_digest: [u8; 32],
    pub(super) provider_request_digest: [u8; 32],
    pub(super) provider_wire_semantic_digest: [u8; 32],
    pub(super) tokenizer_identity_digest: [u8; 32],
    pub(super) tokenization_receipt_digest: [u8; 32],
    pub(super) segment_map_digest: [u8; 32],
    pub(super) recovery_binding_digest: [u8; 32],
    pub(super) terminal_observation_digest: [u8; 32],
    pub(super) provider_receipt_digest: [u8; 32],
    pub(super) context_delivery_receipt_digest: [u8; 32],
    pub(super) observation_version: u32,
    pub(super) disposition: String,
    pub(super) end_turn: Option<bool>,
    pub(super) recorded_unix_ms: u64,
    pub(super) observed_unix_ms: u64,
    pub(super) nonfinal_observation_count: u64,
    pub(super) nonfinal_observations_digest: [u8; 32],
    pub(super) record_digest: [u8; 32],
}

impl SettledAttempt {
    fn new(
        sequence: u64,
        pre_send: &StoredPreSend,
        terminal: &StoredTerminal,
        observations: impl Iterator<Item = StoredTerminal>,
    ) -> Result<Self, ExactContextDeliveryError> {
        if sequence == 0 || !terminal.is_final() {
            return Err(ExactContextDeliveryError::CorruptState);
        }
        let (nonfinal_observation_count, nonfinal_observations_digest) =
            observation_summary(observations)?;
        let end_turn = terminal.provider_receipt.as_ref().and_then(|receipt| {
            if let ProviderTerminal::Completed { end_turn, .. } = &receipt.terminal {
                *end_turn
            } else {
                None
            }
        });
        let mut record = Self {
            sequence,
            thread_id: pre_send.thread_id.clone(),
            turn_id: pre_send.turn_id.clone(),
            attempt_id: pre_send.attempt_id.clone(),
            provider_intent_digest: pre_send.provider_intent_digest,
            authority_snapshot_digest: pre_send.authority_snapshot_digest,
            preparation_binding_digest: pre_send.preparation_binding_digest,
            preparation_digest: pre_send.preparation_digest,
            final_request_proof_digest: pre_send.final_request_proof_digest,
            provider_request_digest: pre_send.provider_request_digest,
            provider_wire_semantic_digest: pre_send.provider_wire_semantic_digest,
            tokenizer_identity_digest: pre_send.tokenizer_identity_digest,
            tokenization_receipt_digest: pre_send.tokenization_receipt_digest,
            segment_map_digest: pre_send.segment_map_digest,
            recovery_binding_digest: pre_send.recovery_binding_digest,
            terminal_observation_digest: terminal.terminal_observation_digest,
            provider_receipt_digest: terminal.provider_receipt_digest,
            context_delivery_receipt_digest: terminal.context_delivery_receipt_digest,
            observation_version: terminal.observation_version,
            disposition: terminal.disposition.clone(),
            end_turn,
            recorded_unix_ms: pre_send.recorded_unix_ms,
            observed_unix_ms: terminal.observed_unix_ms,
            nonfinal_observation_count,
            nonfinal_observations_digest,
            record_digest: [0; 32],
        };
        record.record_digest = record.compute_digest();
        record.validate()?;
        Ok(record)
    }

    pub(super) fn matches_terminal(&self, terminal: &StoredTerminal) -> bool {
        self.attempt_id == terminal.attempt_id
            && self.terminal_observation_digest == terminal.terminal_observation_digest
            && self.provider_receipt_digest == terminal.provider_receipt_digest
            && self.context_delivery_receipt_digest == terminal.context_delivery_receipt_digest
            && self.final_request_proof_digest == terminal.final_request_proof_digest
            && self.observation_version == terminal.observation_version
            && self.disposition == terminal.disposition
    }

    pub(super) fn is_ended_turn(&self) -> bool {
        self.disposition == "Rejected" || self.end_turn == Some(true)
    }

    fn compute_digest(&self) -> [u8; 32] {
        let mut bytes = SETTLED_RECORD_DOMAIN.to_vec();
        bytes.extend_from_slice(&self.sequence.to_be_bytes());
        push_text(&mut bytes, &self.thread_id);
        push_text(&mut bytes, &self.turn_id);
        push_text(&mut bytes, &self.attempt_id);
        for digest in [
            self.provider_intent_digest,
            self.authority_snapshot_digest,
            self.preparation_binding_digest,
            self.preparation_digest,
            self.final_request_proof_digest,
            self.provider_request_digest,
            self.provider_wire_semantic_digest,
            self.tokenizer_identity_digest,
            self.tokenization_receipt_digest,
            self.segment_map_digest,
            self.recovery_binding_digest,
            self.terminal_observation_digest,
            self.provider_receipt_digest,
            self.context_delivery_receipt_digest,
        ] {
            bytes.extend_from_slice(&digest);
        }
        bytes.extend_from_slice(&self.observation_version.to_be_bytes());
        push_text(&mut bytes, &self.disposition);
        bytes.push(match self.end_turn {
            None => 0,
            Some(false) => 1,
            Some(true) => 2,
        });
        bytes.extend_from_slice(&self.recorded_unix_ms.to_be_bytes());
        bytes.extend_from_slice(&self.observed_unix_ms.to_be_bytes());
        bytes.extend_from_slice(&self.nonfinal_observation_count.to_be_bytes());
        bytes.extend_from_slice(&self.nonfinal_observations_digest);
        Digest32::of_bytes(&bytes).into_array()
    }

    fn validate(&self) -> Result<(), ExactContextDeliveryError> {
        validate_runtime_id(&self.thread_id, "settled thread")
            .map_err(|_| ExactContextDeliveryError::CorruptState)?;
        validate_runtime_id(&self.turn_id, "settled turn")
            .map_err(|_| ExactContextDeliveryError::CorruptState)?;
        validate_runtime_id(&self.attempt_id, "settled attempt")
            .map_err(|_| ExactContextDeliveryError::CorruptState)?;
        if self.sequence == 0
            || self.recorded_unix_ms == 0
            || self.observed_unix_ms < self.recorded_unix_ms
            || !matches!(self.observation_version, 2 | 3)
            || !matches!(
                self.disposition.as_str(),
                "Delivered" | "Rejected" | "NotDispatched"
            )
            || self.record_digest == [0; 32]
            || self.record_digest != self.compute_digest()
            || (self.nonfinal_observation_count == 0)
                != (self.nonfinal_observations_digest == [0; 32])
        {
            return Err(ExactContextDeliveryError::CorruptState);
        }
        for digest in [
            self.provider_intent_digest,
            self.authority_snapshot_digest,
            self.preparation_binding_digest,
            self.preparation_digest,
            self.final_request_proof_digest,
            self.provider_request_digest,
            self.provider_wire_semantic_digest,
            self.tokenizer_identity_digest,
            self.tokenization_receipt_digest,
            self.segment_map_digest,
            self.terminal_observation_digest,
            self.provider_receipt_digest,
            self.context_delivery_receipt_digest,
        ] {
            if digest == [0; 32] {
                return Err(ExactContextDeliveryError::CorruptState);
            }
        }
        Ok(())
    }
}

#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct SettlementCheckpoint {
    #[serde(default = "checkpoint_schema")]
    pub(super) schema: u32,
    #[serde(default)]
    pub(super) archived_count: u64,
    #[serde(default)]
    pub(super) last_sequence: u64,
    #[serde(default)]
    pub(super) records_chain_digest: [u8; 32],
    #[serde(default)]
    pub(super) membership_digest: [u8; 32],
    #[serde(default)]
    attempt_filter: Vec<u64>,
    #[serde(default)]
    turn_filter: Vec<u64>,
}

impl Default for SettlementCheckpoint {
    fn default() -> Self {
        Self {
            schema: SETTLEMENT_CHECKPOINT_SCHEMA,
            archived_count: 0,
            last_sequence: 0,
            records_chain_digest: [0; 32],
            membership_digest: [0; 32],
            attempt_filter: Vec::new(),
            turn_filter: Vec::new(),
        }
    }
}

const fn checkpoint_schema() -> u32 {
    SETTLEMENT_CHECKPOINT_SCHEMA
}

pub(super) fn settle_final_attempt(
    state: &mut StoredExactDeliveryState,
    attempt_id: &str,
) -> Result<(), ExactContextDeliveryError> {
    if state.settled_attempts.contains_key(attempt_id) {
        return Ok(());
    }
    if has_checkpointed_attempt(state, attempt_id) {
        return Err(ExactContextDeliveryError::RecoveryRequired);
    }
    let pre_send = state
        .pre_sends
        .get(attempt_id)
        .cloned()
        .ok_or(ExactContextDeliveryError::CorruptState)?;
    let terminal = state
        .terminals
        .get(attempt_id)
        .cloned()
        .filter(StoredTerminal::is_final)
        .ok_or(ExactContextDeliveryError::CorruptState)?;
    terminal_state::validate_observation(&pre_send, &terminal)?;
    let observations = state
        .observations
        .iter()
        .filter(|(_, observation)| observation.attempt_id == attempt_id)
        .map(|(key, observation)| {
            if key != &terminal_state::observation_key(observation) || observation.is_final() {
                return Err(ExactContextDeliveryError::CorruptState);
            }
            terminal_state::validate_observation(&pre_send, observation)?;
            Ok(observation.clone())
        })
        .collect::<Result<Vec<_>, _>>()?;
    let sequence = next_sequence(state)?;
    let settled = SettledAttempt::new(sequence, &pre_send, &terminal, observations.into_iter())?;

    state.pre_sends.remove(attempt_id);
    state.terminals.remove(attempt_id);
    state
        .observations
        .retain(|_, observation| observation.attempt_id != attempt_id);
    if state
        .settled_attempts
        .insert(attempt_id.to_owned(), settled)
        .is_some()
    {
        return Err(ExactContextDeliveryError::CorruptState);
    }
    while state.settled_attempts.len() > MAX_RECENT_SETTLED_ATTEMPTS {
        archive_oldest(state)?;
    }
    Ok(())
}

pub(super) fn has_seen_attempt(state: &StoredExactDeliveryState, attempt_id: &str) -> bool {
    state.settled_attempts.contains_key(attempt_id) || has_checkpointed_attempt(state, attempt_id)
}

pub(super) fn has_checkpointed_attempt(
    state: &StoredExactDeliveryState,
    attempt_id: &str,
) -> bool {
    state.settlement_checkpoint.archived_count > 0
        && filter_contains(
            &state.settlement_checkpoint.attempt_filter,
            ATTEMPT_FILTER_DOMAIN,
            attempt_id.as_bytes(),
        )
}

pub(super) fn has_seen_turn(
    state: &StoredExactDeliveryState,
    thread_id: &str,
    turn_id: &str,
) -> bool {
    state
        .settled_attempts
        .values()
        .any(|record| record.thread_id == thread_id && record.turn_id == turn_id)
        || (state.settlement_checkpoint.archived_count > 0
            && filter_contains(
                &state.settlement_checkpoint.turn_filter,
                TURN_FILTER_DOMAIN,
                &turn_identity(thread_id, turn_id),
            ))
}

pub(super) fn ended_turn(
    state: &StoredExactDeliveryState,
    thread_id: &str,
    turn_id: &str,
) -> bool {
    state.settled_attempts.values().any(|record| {
        record.thread_id == thread_id && record.turn_id == turn_id && record.is_ended_turn()
    })
}

pub(super) fn validate(state: &StoredExactDeliveryState) -> Result<(), ExactContextDeliveryError> {
    validate_checkpoint(&state.settlement_checkpoint)?;
    if state.settled_attempts.len() > MAX_RECENT_SETTLED_ATTEMPTS {
        return Err(ExactContextDeliveryError::CorruptState);
    }
    let mut sequences = BTreeSet::new();
    for (attempt_id, record) in &state.settled_attempts {
        if attempt_id != &record.attempt_id
            || record.sequence <= state.settlement_checkpoint.last_sequence
            || !sequences.insert(record.sequence)
            || state.pre_sends.contains_key(attempt_id)
            || state.terminals.contains_key(attempt_id)
            || state
                .observations
                .values()
                .any(|observation| observation.attempt_id == *attempt_id)
        {
            return Err(ExactContextDeliveryError::CorruptState);
        }
        record.validate()?;
    }
    let mut expected = state
        .settlement_checkpoint
        .last_sequence
        .checked_add(1)
        .ok_or(ExactContextDeliveryError::CorruptState)?;
    for sequence in sequences {
        if sequence != expected {
            return Err(ExactContextDeliveryError::CorruptState);
        }
        expected = expected
            .checked_add(1)
            .ok_or(ExactContextDeliveryError::CorruptState)?;
    }
    Ok(())
}

fn observation_summary(
    observations: impl Iterator<Item = StoredTerminal>,
) -> Result<(u64, [u8; 32]), ExactContextDeliveryError> {
    let mut observations = observations.collect::<Vec<_>>();
    observations.sort_by(|left, right| {
        left.observed_unix_ms
            .cmp(&right.observed_unix_ms)
            .then_with(|| left.provider_receipt_digest.cmp(&right.provider_receipt_digest))
    });
    if observations.is_empty() {
        return Ok((0, [0; 32]));
    }
    let mut bytes = SETTLED_OBSERVATIONS_DOMAIN.to_vec();
    for observation in &observations {
        if observation.is_final() {
            return Err(ExactContextDeliveryError::CorruptState);
        }
        bytes.extend_from_slice(&observation.terminal_observation_digest);
        bytes.extend_from_slice(&observation.provider_receipt_digest);
        bytes.extend_from_slice(&observation.context_delivery_receipt_digest);
        bytes.extend_from_slice(&observation.final_request_proof_digest);
        push_text(&mut bytes, &observation.disposition);
        bytes.extend_from_slice(&observation.observed_unix_ms.to_be_bytes());
    }
    Ok((
        u64::try_from(observations.len()).map_err(|_| ExactContextDeliveryError::Capacity)?,
        Digest32::of_bytes(&bytes).into_array(),
    ))
}

fn next_sequence(state: &StoredExactDeliveryState) -> Result<u64, ExactContextDeliveryError> {
    let latest = state
        .settled_attempts
        .values()
        .map(|record| record.sequence)
        .max()
        .unwrap_or(state.settlement_checkpoint.last_sequence)
        .max(state.settlement_checkpoint.last_sequence);
    latest.checked_add(1).ok_or(ExactContextDeliveryError::Capacity)
}

fn archive_oldest(state: &mut StoredExactDeliveryState) -> Result<(), ExactContextDeliveryError> {
    let attempt_id = state
        .settled_attempts
        .iter()
        .min_by_key(|(_, record)| record.sequence)
        .map(|(attempt_id, _)| attempt_id.clone())
        .ok_or(ExactContextDeliveryError::CorruptState)?;
    let record = state
        .settled_attempts
        .remove(&attempt_id)
        .ok_or(ExactContextDeliveryError::CorruptState)?;
    let checkpoint = &mut state.settlement_checkpoint;
    if checkpoint.archived_count == 0 {
        checkpoint.attempt_filter = vec![0; FILTER_WORDS];
        checkpoint.turn_filter = vec![0; FILTER_WORDS];
    }
    if checkpoint.attempt_filter.len() != FILTER_WORDS
        || checkpoint.turn_filter.len() != FILTER_WORDS
        || record.sequence != checkpoint.last_sequence.saturating_add(1)
    {
        return Err(ExactContextDeliveryError::CorruptState);
    }
    filter_insert(
        &mut checkpoint.attempt_filter,
        ATTEMPT_FILTER_DOMAIN,
        record.attempt_id.as_bytes(),
    );
    filter_insert(
        &mut checkpoint.turn_filter,
        TURN_FILTER_DOMAIN,
        &turn_identity(&record.thread_id, &record.turn_id),
    );
    let mut chain = CHECKPOINT_CHAIN_DOMAIN.to_vec();
    chain.extend_from_slice(&checkpoint.records_chain_digest);
    chain.extend_from_slice(&record.sequence.to_be_bytes());
    chain.extend_from_slice(&record.record_digest);
    checkpoint.records_chain_digest = Digest32::of_bytes(&chain).into_array();
    checkpoint.archived_count = checkpoint
        .archived_count
        .checked_add(1)
        .ok_or(ExactContextDeliveryError::Capacity)?;
    checkpoint.last_sequence = record.sequence;
    checkpoint.membership_digest = membership_digest(checkpoint);
    Ok(())
}

fn validate_checkpoint(
    checkpoint: &SettlementCheckpoint,
) -> Result<(), ExactContextDeliveryError> {
    if checkpoint.schema != SETTLEMENT_CHECKPOINT_SCHEMA {
        return Err(ExactContextDeliveryError::CorruptState);
    }
    if checkpoint.archived_count == 0 {
        if checkpoint.last_sequence != 0
            || checkpoint.records_chain_digest != [0; 32]
            || checkpoint.membership_digest != [0; 32]
            || !checkpoint.attempt_filter.is_empty()
            || !checkpoint.turn_filter.is_empty()
        {
            return Err(ExactContextDeliveryError::CorruptState);
        }
        return Ok(());
    }
    if checkpoint.last_sequence != checkpoint.archived_count
        || checkpoint.records_chain_digest == [0; 32]
        || checkpoint.attempt_filter.len() != FILTER_WORDS
        || checkpoint.turn_filter.len() != FILTER_WORDS
        || checkpoint.membership_digest == [0; 32]
        || checkpoint.membership_digest != membership_digest(checkpoint)
    {
        return Err(ExactContextDeliveryError::CorruptState);
    }
    Ok(())
}

fn membership_digest(checkpoint: &SettlementCheckpoint) -> [u8; 32] {
    let mut bytes = CHECKPOINT_MEMBERSHIP_DOMAIN.to_vec();
    bytes.extend_from_slice(&checkpoint.archived_count.to_be_bytes());
    bytes.extend_from_slice(&checkpoint.last_sequence.to_be_bytes());
    for word in &checkpoint.attempt_filter {
        bytes.extend_from_slice(&word.to_be_bytes());
    }
    for word in &checkpoint.turn_filter {
        bytes.extend_from_slice(&word.to_be_bytes());
    }
    Digest32::of_bytes(&bytes).into_array()
}

fn filter_insert(filter: &mut [u64], domain: &[u8], value: &[u8]) {
    for bit in filter_bits(domain, value) {
        let word = bit / 64;
        let offset = bit % 64;
        filter[word] |= 1_u64 << offset;
    }
}

fn filter_contains(filter: &[u64], domain: &[u8], value: &[u8]) -> bool {
    if filter.len() != FILTER_WORDS {
        return false;
    }
    filter_bits(domain, value).into_iter().all(|bit| {
        let word = bit / 64;
        let offset = bit % 64;
        filter[word] & (1_u64 << offset) != 0
    })
}

fn filter_bits(domain: &[u8], value: &[u8]) -> [usize; FILTER_HASHES] {
    let mut bits = [0; FILTER_HASHES];
    for index in 0..FILTER_HASHES {
        let mut bytes = domain.to_vec();
        bytes.push(u8::try_from(index).unwrap_or_default());
        bytes.extend_from_slice(value);
        let digest = Digest32::of_bytes(&bytes);
        let mut number = [0; 8];
        number.copy_from_slice(&digest.as_array()[..8]);
        let modulus = u64::try_from(FILTER_WORDS * 64).unwrap_or(1);
        bits[index] =
            usize::try_from(u64::from_be_bytes(number) % modulus).unwrap_or_default();
    }
    bits
}

fn turn_identity(thread_id: &str, turn_id: &str) -> Vec<u8> {
    let mut bytes = Vec::new();
    push_text(&mut bytes, thread_id);
    push_text(&mut bytes, turn_id);
    bytes
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&u64::try_from(value.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}
