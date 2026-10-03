//! Stable G→E input: derive the consumer from the original signed canonical
//! candidate bytes. A caller's digest, passing flag or policy rewrite is absent.
use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::IndependentEvaluationBundleV1;
use crate::ProductEvaluationError;
use crate::recorded_publication::archive::codec::Reader;
use crate::recorded_publication::archive::codec::Wire;
use crate::recorded_publication::archive::codec::Writer;

pub const MAX_SELF_ITERATION_FROZEN_CONSUMER_BYTES: usize = 280 * 1024;
pub const MAX_SELF_ITERATION_FROZEN_CANDIDATE_BYTES: usize = 272 * 1024;
const TRANSPORT: &[u8] = b"hepta.eval.self-iteration-frozen-consumer.v1\0";
const CANDIDATE: &[u8] = b"hepta.agentd.self-iteration-candidate.v1\0";
const CANONICAL_CANDIDATE: &[u8] = b"hepta.agentd.self-iteration-candidate.v2\0";

#[path = "self_iteration_unsigned_candidate.rs"]
mod unsigned;
pub use unsigned::UntrustedSelfIterationCandidateV1;
pub use unsigned::inspect_unsigned_self_iteration_candidate_v1;

struct Publication {
    candidate_payload: Vec<u8>,
    generator_attestation: SignedLearningEvidenceV1,
}
impl Wire for Publication {
    fn write(&self, writer: &mut Writer) -> Result<(), ProductEvaluationError> {
        if self.candidate_payload.is_empty()
            || self.candidate_payload.len() > MAX_SELF_ITERATION_FROZEN_CANDIDATE_BYTES
        {
            return Err(invalid());
        }
        (self.candidate_payload.len() as u32).write(writer)?;
        writer.put(&self.candidate_payload)?;
        self.generator_attestation.write(writer)
    }
    fn read(reader: &mut Reader<'_>) -> Result<Self, ProductEvaluationError> {
        // This is one bounded byte payload, not a qualification item list.
        // Retain the original u32 length + byte layout without lifting the
        // generic archive list limit for any other record or collection.
        let length = u32::read(reader)? as usize;
        if !(1..=MAX_SELF_ITERATION_FROZEN_CANDIDATE_BYTES).contains(&length) {
            return Err(invalid());
        }
        Ok(Self {
            candidate_payload: reader.take(length)?.to_vec(),
            generator_attestation: SignedLearningEvidenceV1::read(reader)?,
        })
    }
}

/// Actual signed frozen identity, authenticated by the current original G
/// principal and bound to the independently recomputed original evaluation.
pub struct VerifiedSelfIterationFrozenConsumerV1 {
    frozen_digest: Digest32,
    expires_at: u64,
    generator: VerifiedLearningEvidenceV1,
    candidate: Candidate,
}
impl VerifiedSelfIterationFrozenConsumerV1 {
    pub fn frozen_digest(&self) -> Digest32 {
        self.frozen_digest
    }
    pub fn expires_at(&self) -> u64 {
        self.expires_at
    }
    pub fn generator(&self) -> &VerifiedLearningEvidenceV1 {
        &self.generator
    }
    pub fn candidate_id(&self) -> &StableId {
        &self.candidate.ids[1]
    }
    pub fn baseline_id(&self) -> &StableId {
        &self.candidate.ids[4]
    }
    pub fn canary_tick_id(&self) -> &StableId {
        &self.candidate.ids[3]
    }
    pub fn objective_digest(&self) -> Digest32 {
        self.candidate.digests[2]
    }
    pub fn test_plan_digest(&self) -> Digest32 {
        self.candidate.digests[5]
    }
    pub fn base_generation(&self) -> u64 {
        self.candidate.values[0]
    }
    pub fn successor_body(&self) -> Digest32 {
        self.candidate.digests[13]
    }
    pub fn rollback_body(&self) -> Digest32 {
        self.candidate.digests[14]
    }
    pub fn successor_configuration(&self) -> Digest32 {
        self.candidate.digests[15]
    }
    pub fn rollback_configuration(&self) -> Digest32 {
        self.candidate.digests[16]
    }
    pub fn canary_input_digest(&self) -> Digest32 {
        self.candidate.digests[17]
    }
    /// All original canonical policy bytes under the actual G signature. Eval
    /// retains them without projecting or redefining the Agentd-owned policy.
    pub fn canonical_envelope_bytes(&self) -> Option<&[u8]> {
        self.candidate.canonical_envelope.as_deref()
    }
    pub fn canonical_envelope_digest(&self) -> Option<Digest32> {
        self.canonical_envelope_bytes().map(Digest32::of_bytes)
    }
    pub fn generator_round_bytes(&self) -> Option<&[u8]> {
        self.candidate.round_bytes.as_deref()
    }
    pub fn generator_model_request_id(&self) -> Option<&StableId> {
        self.candidate.model_request.as_ref()
    }
    pub fn generator_native_run_digest(&self) -> Option<Digest32> {
        self.candidate.native_run
    }
    pub fn generator_model_output_digest(&self) -> Option<Digest32> {
        self.candidate.output_digest
    }
}

struct Candidate {
    ids: Vec<StableId>,
    digests: [Digest32; 18],
    values: [u64; 8],
    canonical_envelope: Option<Vec<u8>>,
    round_bytes: Option<Vec<u8>>,
    model_request: Option<StableId>,
    native_run: Option<Digest32>,
    output_digest: Option<Digest32>,
}

/// Serialize the native Generator's already signed candidate. The independently
/// installed recipient authenticates these bytes before deriving a consumer.
pub fn encode_self_iteration_frozen_consumer_v1(
    candidate_payload: &[u8],
    generator_attestation: &SignedLearningEvidenceV1,
) -> Result<Vec<u8>, ProductEvaluationError> {
    if candidate_payload.is_empty()
        || candidate_payload.len() > MAX_SELF_ITERATION_FROZEN_CANDIDATE_BYTES
        || !(candidate_payload.starts_with(CANDIDATE)
            || candidate_payload.starts_with(CANONICAL_CANDIDATE))
        || generator_attestation.role != LearningEvidenceRoleV1::Generator
        || generator_attestation.payload_digest != Digest32::of_bytes(candidate_payload)
    {
        return Err(invalid());
    }
    let publication = Publication {
        candidate_payload: candidate_payload.to_vec(),
        generator_attestation: generator_attestation.clone(),
    };
    let mut writer = Writer::default();
    writer.put(TRANSPORT)?;
    publication.write(&mut writer)?;
    let bytes = writer.finish();
    if bytes.len() > MAX_SELF_ITERATION_FROZEN_CONSUMER_BYTES {
        return Err(invalid());
    }
    Ok(bytes)
}

/// Parse only the original v1 candidate profile and authenticate the current G
/// signature. The bundle comes from the original independent plan execution;
/// arbitrary caller metrics or a different plan cannot name this consumer.
pub fn decode_self_iteration_frozen_consumer_v1(
    bytes: &[u8],
    bundle: &IndependentEvaluationBundleV1,
    trust: &ActivatedLearningTrustV1,
    now_unix_ms: u64,
) -> Result<VerifiedSelfIterationFrozenConsumerV1, ProductEvaluationError> {
    let consumer = inspect_signed_self_iteration_frozen_consumer_v1(bytes, trust, now_unix_ms)?;
    if consumer.generator.principal() != &bundle.generator
        || consumer.candidate_id() != &bundle.candidate_id
        || consumer.baseline_id() != &bundle.baseline_id
        || consumer.objective_digest() != bundle.objective_digest
        || consumer.test_plan_digest() != bundle.frozen_plan.plan_digest
    {
        return Err(invalid());
    }
    Ok(consumer)
}

/// Authenticate the complete original G candidate before exposing its factual
/// identities. E/S/O must still bind it to their independently resolved evidence.
pub fn inspect_signed_self_iteration_frozen_consumer_v1(
    bytes: &[u8],
    trust: &ActivatedLearningTrustV1,
    now_unix_ms: u64,
) -> Result<VerifiedSelfIterationFrozenConsumerV1, ProductEvaluationError> {
    if bytes.is_empty() || bytes.len() > MAX_SELF_ITERATION_FROZEN_CONSUMER_BYTES {
        return Err(invalid());
    }
    trust.revalidate_at(now_unix_ms).map_err(|_| invalid())?;
    let mut reader = Reader::new(bytes)?;
    if reader.take(TRANSPORT.len())? != TRANSPORT {
        return Err(invalid());
    }
    let publication = Publication::read(&mut reader)?;
    reader.finish()?;
    if encode_self_iteration_frozen_consumer_v1(
        &publication.candidate_payload,
        &publication.generator_attestation,
    )? != bytes
    {
        return Err(invalid());
    }
    let generator = trust
        .verifier()
        .verify(
            LearningEvidenceRoleV1::Generator,
            &publication.generator_attestation,
            &publication.candidate_payload,
            now_unix_ms,
        )
        .map_err(|_| invalid())?;
    let candidate = validate_candidate(&publication.candidate_payload, now_unix_ms)?;
    if candidate.ids[2] != generator.principal().principal_id
        || candidate.digests[2] != trust.verifier().objective_digest()
    {
        return Err(invalid());
    }
    let expires_at = candidate.values[5]
        .checked_mul(1000)
        .ok_or_else(invalid)?
        .min(publication.generator_attestation.expires_at);
    if now_unix_ms >= expires_at {
        return Err(invalid());
    }
    Ok(VerifiedSelfIterationFrozenConsumerV1 {
        frozen_digest: Digest32::of_bytes(&publication.candidate_payload),
        expires_at,
        generator,
        candidate,
    })
}

fn validate_candidate(payload: &[u8], now: u64) -> Result<Candidate, ProductEvaluationError> {
    let (canonical_envelope, round_bytes, model_request, native_run, output_digest, payload) =
        if payload.starts_with(CANONICAL_CANDIDATE) {
            let mut reader = Reader::new(payload)?;
            reader.take(CANONICAL_CANDIDATE.len())?;
            let length = usize::try_from(u64::read(&mut reader)?).map_err(|_| invalid())?;
            if !(1..=262_144).contains(&length) {
                return Err(invalid());
            }
            let canonical = reader.take(length)?.to_vec();
            let round_length = usize::try_from(u64::read(&mut reader)?).map_err(|_| invalid())?;
            if !(1..=4096).contains(&round_length) {
                return Err(invalid());
            }
            let round_bytes = reader.take(round_length)?.to_vec();
            let request_length = usize::try_from(u64::read(&mut reader)?).map_err(|_| invalid())?;
            if !(1..=128).contains(&request_length) {
                return Err(invalid());
            }
            let request_id = StableId::new(
                std::str::from_utf8(reader.take(request_length)?).map_err(|_| invalid())?,
            )
            .map_err(|_| invalid())?;
            let native_run = Digest32::read(&mut reader)?;
            let output_digest = Digest32::read(&mut reader)?;
            if native_run.is_zero() || output_digest.is_zero() {
                return Err(invalid());
            }
            let start = CANONICAL_CANDIDATE
                .len()
                .checked_add(8)
                .and_then(|value| value.checked_add(length))
                .and_then(|value| value.checked_add(8))
                .and_then(|value| value.checked_add(round_length))
                .and_then(|value| value.checked_add(8))
                .and_then(|value| value.checked_add(request_length))
                .and_then(|value| value.checked_add(64))
                .ok_or_else(invalid)?;
            (
                Some(canonical),
                Some(round_bytes),
                Some(request_id),
                Some(native_run),
                Some(output_digest),
                payload.get(start..).ok_or_else(invalid)?,
            )
        } else {
            (None, None, None, None, None, payload)
        };
    if payload.len() > 4096 {
        return Err(invalid());
    }
    let mut reader = Reader::new(payload)?;
    if reader.take(CANDIDATE.len())? != CANDIDATE {
        return Err(invalid());
    }
    let mut ids = Vec::with_capacity(5);
    for _ in 0..5 {
        let length = usize::try_from(u64::read(&mut reader)?).map_err(|_| invalid())?;
        if !(1..=128).contains(&length) {
            return Err(invalid());
        }
        let text = std::str::from_utf8(reader.take(length)?).map_err(|_| invalid())?;
        ids.push(StableId::new(text).map_err(|_| invalid())?);
    }
    // Original candidate payload v1: eighteen digest identities followed by
    // eight bounded integers. No trailing or projected policy fields are read.
    let mut digests = [Digest32::ZERO; 18];
    for digest in &mut digests {
        *digest = Digest32::read(&mut reader)?;
    }
    let mut values = [0_u64; 8];
    for value in &mut values {
        *value = u64::read(&mut reader)?;
    }
    reader.finish()?;
    let expiry = values[5].checked_mul(1000).ok_or_else(invalid)?;
    if [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 13, 14, 15, 16, 17]
        .into_iter()
        .any(|index| digests[index].is_zero())
        || values[0] == 0
        || !(1..=100).contains(&values[1])
        || !(1..=1_048_576).contains(&values[2])
        || !(1..=32).contains(&values[3])
        || !(1..=8).contains(&values[4])
        || values[6] == 0
        || values[6] > values[1]
        || !(1..=10_000_000).contains(&values[7])
        || expiry <= now
        || expiry > now.saturating_add(3_600_000)
    {
        return Err(invalid());
    }
    Ok(Candidate {
        ids,
        digests,
        values,
        canonical_envelope,
        round_bytes,
        model_request,
        native_run,
        output_digest,
    })
}

fn invalid() -> ProductEvaluationError {
    ProductEvaluationError::Integrity("original signed frozen self-iteration consumer")
}

#[cfg(test)]
#[path = "self_iteration_frozen_consumer_tests.rs"]
mod tests;
