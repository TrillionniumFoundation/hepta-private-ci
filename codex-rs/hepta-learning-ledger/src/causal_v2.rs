//! Authenticated causal-learning boundaries layered over the stable V1 ledger.
//!
//! These types close the product-facing gaps that cannot safely be represented
//! by a plain `StableId` or an opaque support digest: credential-chain identity,
//! delayed-outcome watermarks, conserved credit batches, generator-relative
//! candidate completeness, and immutable dataset-freeze receipts. The existing
//! durable V1 encoding remains readable and unchanged. Identity fields here are
//! assertions, not signature proofs; external evidence admission uses
//! `LearningEvidenceVerifierV1` with host-owned trust state.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

const MAX_CANDIDATES: u32 = 128;
const MAX_CREDIT_ALLOCATIONS: usize = 256;
const MAX_DATASET_RECORDS: usize = 1_000_000;

/// Legacy identity metadata. `validate` checks structure and time, not a signature.
/// Authenticate external evidence with `LearningEvidenceVerifierV1` before use.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedPrincipalV1 {
    pub principal_id: StableId,
    pub credential_chain_digest: Digest32,
    pub signing_key_digest: Digest32,
    pub scope_digest: Digest32,
    pub authority_epoch: u64,
    pub authenticated_at: u64,
    pub expires_at: u64,
}

impl AuthenticatedPrincipalV1 {
    pub fn validate(&self, now: u64) -> Result<(), CausalV2Error> {
        require_digest(self.credential_chain_digest, "credential chain")?;
        require_digest(self.signing_key_digest, "signing key")?;
        require_digest(self.scope_digest, "authenticated scope")?;
        if self.authority_epoch == 0 {
            return Err(CausalV2Error::InvalidAuthorityEpoch);
        }
        if self.authenticated_at > self.expires_at
            || now < self.authenticated_at
            || now > self.expires_at
        {
            return Err(CausalV2Error::AuthenticationWindow);
        }
        Ok(())
    }
}

pub fn verify_independent_roles(
    generator: &AuthenticatedPrincipalV1,
    observer: &AuthenticatedPrincipalV1,
    now: u64,
) -> Result<(), CausalV2Error> {
    generator.validate(now)?;
    observer.validate(now)?;
    if generator.principal_id == observer.principal_id {
        return Err(CausalV2Error::RoleCollision("principal"));
    }
    if generator.credential_chain_digest == observer.credential_chain_digest {
        return Err(CausalV2Error::RoleCollision("credential chain"));
    }
    if generator.signing_key_digest == observer.signing_key_digest {
        return Err(CausalV2Error::RoleCollision("signing key"));
    }
    Ok(())
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OutcomeTerminalityV1 {
    Pending,
    Censored,
    Terminal,
}

impl OutcomeTerminalityV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Pending => 0,
            Self::Censored => 1,
            Self::Terminal => 2,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OutcomeWatermarkV1 {
    pub latest_observable_at: u64,
    pub expected_delay_profile_digest: Digest32,
    pub terminality: OutcomeTerminalityV1,
    pub censoring_reason: Option<StableId>,
    pub correction_predecessor: Option<StableId>,
    pub finalized_at: Option<u64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedOutcomeV1 {
    pub record_id: StableId,
    pub outcome_id: StableId,
    pub episode_id: StableId,
    pub observer: AuthenticatedPrincipalV1,
    pub observed_at: Option<u64>,
    pub value: Option<FixedQ32>,
    pub unit_profile_digest: Digest32,
    pub support_digest: Digest32,
    pub watermark: OutcomeWatermarkV1,
}

pub fn validate_authenticated_outcome(
    generator: &AuthenticatedPrincipalV1,
    outcome: &AuthenticatedOutcomeV1,
    now: u64,
) -> Result<Digest32, CausalV2Error> {
    verify_independent_roles(generator, &outcome.observer, now)?;
    require_digest(outcome.unit_profile_digest, "outcome unit profile")?;
    require_digest(outcome.support_digest, "outcome support")?;
    validate_watermark(outcome, now)?;

    let mut bytes = b"hepta.learning-ledger.authenticated-outcome.v1".to_vec();
    push_id(&mut bytes, &outcome.record_id);
    push_id(&mut bytes, &outcome.outcome_id);
    push_id(&mut bytes, &outcome.episode_id);
    push_principal(&mut bytes, &outcome.observer);
    push_optional_u64(&mut bytes, outcome.observed_at);
    push_optional_fixed(&mut bytes, outcome.value);
    bytes.extend_from_slice(outcome.unit_profile_digest.as_array());
    bytes.extend_from_slice(outcome.support_digest.as_array());
    push_watermark(&mut bytes, &outcome.watermark);
    Ok(Digest32::of_bytes(&bytes))
}

fn validate_watermark(outcome: &AuthenticatedOutcomeV1, now: u64) -> Result<(), CausalV2Error> {
    let watermark = &outcome.watermark;
    require_digest(
        watermark.expected_delay_profile_digest,
        "expected delay profile",
    )?;
    if watermark.latest_observable_at > now {
        return Err(CausalV2Error::InvalidWatermark);
    }
    match watermark.terminality {
        OutcomeTerminalityV1::Pending => {
            if outcome.observed_at.is_some()
                || outcome.value.is_some()
                || watermark.finalized_at.is_some()
                || watermark.censoring_reason.is_some()
                || watermark.correction_predecessor.is_some()
            {
                return Err(CausalV2Error::OutcomeStateMismatch);
            }
        }
        OutcomeTerminalityV1::Censored => {
            let Some(finalized_at) = watermark.finalized_at else {
                return Err(CausalV2Error::OutcomeStateMismatch);
            };
            if outcome.observed_at.is_some()
                || outcome.value.is_some()
                || watermark.censoring_reason.is_none()
                || finalized_at < watermark.latest_observable_at
                || finalized_at > now
            {
                return Err(CausalV2Error::OutcomeStateMismatch);
            }
        }
        OutcomeTerminalityV1::Terminal => {
            let (Some(observed_at), Some(_), Some(finalized_at)) =
                (outcome.observed_at, outcome.value, watermark.finalized_at)
            else {
                return Err(CausalV2Error::OutcomeStateMismatch);
            };
            if watermark.censoring_reason.is_some()
                || observed_at > watermark.latest_observable_at
                || finalized_at < observed_at
                || finalized_at > now
            {
                return Err(CausalV2Error::OutcomeStateMismatch);
            }
        }
    }
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CandidateSetCompletenessReceiptV1 {
    pub set_id: StableId,
    pub state_digest: Digest32,
    pub generator_id: StableId,
    pub generator_code_digest: Digest32,
    pub grammar_digest: Digest32,
    pub hard_filter_digest: Digest32,
    pub truncation_digest: Digest32,
    pub candidates_digest: Digest32,
    pub candidate_count: u32,
    pub omitted_count_bound: u32,
    pub canonical_order_digest: Digest32,
    pub complete_for_generator: bool,
}

pub fn validate_candidate_set_completeness(
    receipt: &CandidateSetCompletenessReceiptV1,
) -> Result<Digest32, CausalV2Error> {
    if !receipt.complete_for_generator {
        return Err(CausalV2Error::IncompleteCandidateSet);
    }
    if receipt.candidate_count == 0 || receipt.candidate_count > MAX_CANDIDATES {
        return Err(CausalV2Error::CandidateLimit);
    }
    for (label, digest) in [
        ("candidate state", receipt.state_digest),
        ("generator code", receipt.generator_code_digest),
        ("candidate grammar", receipt.grammar_digest),
        ("hard filter", receipt.hard_filter_digest),
        ("truncation", receipt.truncation_digest),
        ("candidate set", receipt.candidates_digest),
        ("canonical candidate order", receipt.canonical_order_digest),
    ] {
        require_digest(digest, label)?;
    }

    let mut bytes = b"hepta.learning-ledger.candidate-completeness.v1".to_vec();
    push_id(&mut bytes, &receipt.set_id);
    bytes.extend_from_slice(receipt.state_digest.as_array());
    push_id(&mut bytes, &receipt.generator_id);
    bytes.extend_from_slice(receipt.generator_code_digest.as_array());
    bytes.extend_from_slice(receipt.grammar_digest.as_array());
    bytes.extend_from_slice(receipt.hard_filter_digest.as_array());
    bytes.extend_from_slice(receipt.truncation_digest.as_array());
    bytes.extend_from_slice(receipt.candidates_digest.as_array());
    bytes.extend_from_slice(&receipt.candidate_count.to_be_bytes());
    bytes.extend_from_slice(&receipt.omitted_count_bound.to_be_bytes());
    bytes.extend_from_slice(receipt.canonical_order_digest.as_array());
    bytes.push(u8::from(receipt.complete_for_generator));
    Ok(Digest32::of_bytes(&bytes))
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CreditAllocationV1 {
    pub target_id: StableId,
    pub credit: FixedQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CreditAllocationBatchV1 {
    pub batch_id: StableId,
    pub episode_id: StableId,
    pub outcome_id: StableId,
    pub allocator: AuthenticatedPrincipalV1,
    pub terminal_outcome: FixedQ32,
    pub allocations: Vec<CreditAllocationV1>,
    pub conservation_residual: FixedQ32,
    pub support_digest: Digest32,
    pub finalized: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CreditAllocationReceiptV1 {
    pub batch_id: StableId,
    pub allocation_count: u32,
    pub conservation_residual: FixedQ32,
    pub batch_digest: Digest32,
    pub authority: AuthorityPosture,
}

pub fn finalize_credit_batch(
    mut batch: CreditAllocationBatchV1,
    now: u64,
) -> Result<CreditAllocationReceiptV1, CausalV2Error> {
    batch.allocator.validate(now)?;
    require_digest(batch.support_digest, "credit support")?;
    if !batch.finalized {
        return Err(CausalV2Error::CreditNotFinalized);
    }
    if batch.allocations.is_empty() || batch.allocations.len() > MAX_CREDIT_ALLOCATIONS {
        return Err(CausalV2Error::CreditLimit);
    }
    batch
        .allocations
        .sort_by_key(|allocation| allocation.target_id.clone());
    for adjacent in batch.allocations.windows(2) {
        if adjacent[0].target_id == adjacent[1].target_id {
            return Err(CausalV2Error::DuplicateCreditTarget(
                adjacent[0].target_id.to_string(),
            ));
        }
    }

    let allocated = batch
        .allocations
        .iter()
        .try_fold(0_i128, |sum, allocation| {
            sum.checked_add(i128::from(allocation.credit.raw()))
                .ok_or(CausalV2Error::Arithmetic)
        })?;
    let conserved = allocated
        .checked_add(i128::from(batch.conservation_residual.raw()))
        .ok_or(CausalV2Error::Arithmetic)?;
    if conserved != i128::from(batch.terminal_outcome.raw()) {
        return Err(CausalV2Error::CreditConservation);
    }

    let mut bytes = b"hepta.learning-ledger.credit-allocation-batch.v1".to_vec();
    push_id(&mut bytes, &batch.batch_id);
    push_id(&mut bytes, &batch.episode_id);
    push_id(&mut bytes, &batch.outcome_id);
    push_principal(&mut bytes, &batch.allocator);
    bytes.extend_from_slice(&batch.terminal_outcome.raw().to_be_bytes());
    bytes.extend_from_slice(
        &u32::try_from(batch.allocations.len())
            .map_err(|_| CausalV2Error::Arithmetic)?
            .to_be_bytes(),
    );
    for allocation in &batch.allocations {
        push_id(&mut bytes, &allocation.target_id);
        bytes.extend_from_slice(&allocation.credit.raw().to_be_bytes());
    }
    bytes.extend_from_slice(&batch.conservation_residual.raw().to_be_bytes());
    bytes.extend_from_slice(batch.support_digest.as_array());
    bytes.push(u8::from(batch.finalized));
    Ok(CreditAllocationReceiptV1 {
        batch_id: batch.batch_id,
        allocation_count: u32::try_from(batch.allocations.len())
            .map_err(|_| CausalV2Error::Arithmetic)?,
        conservation_residual: batch.conservation_residual,
        batch_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DatasetFreezeRequestV1 {
    pub snapshot_id: StableId,
    pub producer: AuthenticatedPrincipalV1,
    pub ledger_head_digest: Digest32,
    pub objective_digest: Digest32,
    pub eligible_frontier: u64,
    pub outcome_watermark: u64,
    pub correction_cut_digest: Digest32,
    pub revocation_cut_digest: Digest32,
    pub inclusion_policy_digest: Digest32,
    pub source_record_digests: Vec<Digest32>,
    pub pending_outcomes: u32,
    pub censored_outcomes: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DatasetSnapshotV2 {
    pub snapshot_id: StableId,
    pub ledger_head_digest: Digest32,
    pub objective_digest: Digest32,
    pub eligible_frontier: u64,
    pub outcome_watermark: u64,
    pub source_record_digests: Vec<Digest32>,
    pub pending_outcomes: u32,
    pub censored_outcomes: u32,
    pub dataset_digest: Digest32,
    pub authority: AuthorityPosture,
}

pub fn freeze_dataset(
    mut request: DatasetFreezeRequestV1,
    now: u64,
) -> Result<DatasetSnapshotV2, CausalV2Error> {
    request.producer.validate(now)?;
    for (label, digest) in [
        ("ledger head", request.ledger_head_digest),
        ("objective", request.objective_digest),
        ("correction cut", request.correction_cut_digest),
        ("revocation cut", request.revocation_cut_digest),
        ("inclusion policy", request.inclusion_policy_digest),
    ] {
        require_digest(digest, label)?;
    }
    if request.eligible_frontier == 0 || request.outcome_watermark == 0 {
        return Err(CausalV2Error::InvalidDatasetFrontier);
    }
    if request.source_record_digests.is_empty() {
        return Err(CausalV2Error::DatasetEmpty);
    }
    if request.source_record_digests.len() > MAX_DATASET_RECORDS {
        return Err(CausalV2Error::DatasetLimit);
    }
    if request
        .source_record_digests
        .iter()
        .any(|digest| digest.is_zero())
    {
        return Err(CausalV2Error::EmptyDigest("dataset source record"));
    }
    request.source_record_digests.sort_unstable();
    if request
        .source_record_digests
        .windows(2)
        .any(|adjacent| adjacent[0] == adjacent[1])
    {
        return Err(CausalV2Error::DuplicateSourceRecord);
    }

    let mut bytes = b"hepta.learning-ledger.dataset-snapshot.v2".to_vec();
    push_id(&mut bytes, &request.snapshot_id);
    push_principal(&mut bytes, &request.producer);
    bytes.extend_from_slice(request.ledger_head_digest.as_array());
    bytes.extend_from_slice(request.objective_digest.as_array());
    bytes.extend_from_slice(&request.eligible_frontier.to_be_bytes());
    bytes.extend_from_slice(&request.outcome_watermark.to_be_bytes());
    bytes.extend_from_slice(request.correction_cut_digest.as_array());
    bytes.extend_from_slice(request.revocation_cut_digest.as_array());
    bytes.extend_from_slice(request.inclusion_policy_digest.as_array());
    bytes.extend_from_slice(
        &u64::try_from(request.source_record_digests.len())
            .map_err(|_| CausalV2Error::Arithmetic)?
            .to_be_bytes(),
    );
    for digest in &request.source_record_digests {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&request.pending_outcomes.to_be_bytes());
    bytes.extend_from_slice(&request.censored_outcomes.to_be_bytes());
    let dataset_digest = Digest32::of_bytes(&bytes);

    Ok(DatasetSnapshotV2 {
        snapshot_id: request.snapshot_id,
        ledger_head_digest: request.ledger_head_digest,
        objective_digest: request.objective_digest,
        eligible_frontier: request.eligible_frontier,
        outcome_watermark: request.outcome_watermark,
        source_record_digests: request.source_record_digests,
        pending_outcomes: request.pending_outcomes,
        censored_outcomes: request.censored_outcomes,
        dataset_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CausalV2Error {
    EmptyDigest(&'static str),
    InvalidAuthorityEpoch,
    AuthenticationWindow,
    RoleCollision(&'static str),
    InvalidWatermark,
    OutcomeStateMismatch,
    IncompleteCandidateSet,
    CandidateLimit,
    CreditNotFinalized,
    CreditLimit,
    DuplicateCreditTarget(String),
    CreditConservation,
    InvalidDatasetFrontier,
    DatasetEmpty,
    DatasetLimit,
    DuplicateSourceRecord,
    Arithmetic,
}

impl fmt::Display for CausalV2Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CausalV2Error {}

fn require_digest(digest: Digest32, label: &'static str) -> Result<(), CausalV2Error> {
    if digest.is_zero() {
        return Err(CausalV2Error::EmptyDigest(label));
    }
    Ok(())
}

fn push_principal(bytes: &mut Vec<u8>, principal: &AuthenticatedPrincipalV1) {
    push_id(bytes, &principal.principal_id);
    bytes.extend_from_slice(principal.credential_chain_digest.as_array());
    bytes.extend_from_slice(principal.signing_key_digest.as_array());
    bytes.extend_from_slice(principal.scope_digest.as_array());
    bytes.extend_from_slice(&principal.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&principal.authenticated_at.to_be_bytes());
    bytes.extend_from_slice(&principal.expires_at.to_be_bytes());
}

fn push_watermark(bytes: &mut Vec<u8>, watermark: &OutcomeWatermarkV1) {
    bytes.extend_from_slice(&watermark.latest_observable_at.to_be_bytes());
    bytes.extend_from_slice(watermark.expected_delay_profile_digest.as_array());
    bytes.push(watermark.terminality.tag());
    push_optional_id(bytes, watermark.censoring_reason.as_ref());
    push_optional_id(bytes, watermark.correction_predecessor.as_ref());
    push_optional_u64(bytes, watermark.finalized_at);
}

fn push_optional_id(bytes: &mut Vec<u8>, value: Option<&StableId>) {
    match value {
        Some(value) => {
            bytes.push(1);
            push_id(bytes, value);
        }
        None => bytes.push(0),
    }
}

fn push_optional_u64(bytes: &mut Vec<u8>, value: Option<u64>) {
    match value {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        None => bytes.push(0),
    }
}

fn push_optional_fixed(bytes: &mut Vec<u8>, value: Option<FixedQ32>) {
    match value {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(&value.raw().to_be_bytes());
        }
        None => bytes.push(0),
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "causal_v2_tests.rs"]
mod tests;
