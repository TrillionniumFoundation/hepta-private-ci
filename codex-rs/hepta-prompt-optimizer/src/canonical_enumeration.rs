use std::collections::BTreeSet;
use std::ops::Deref;

use codex_hepta_prompt_registry::PromptModelTupleV2;
use codex_hepta_prompt_registry::PromptRegistry;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::error::CanonicalPromptError;
use super::error::ensure_digest;
use super::error::push_id;
use super::error::push_ids;
use super::raw;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptEnumerationRequestV1 {
    pub set_id: StableId,
    pub objective_digest: Digest32,
    pub scope_digest: Digest32,
    pub state_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub model_tuple: PromptModelTupleV2,
    pub now_unix_ms: u64,
    pub required_factor_ids: Vec<StableId>,
    pub maximum_candidates: u32,
    pub selection_grammar_digest: Digest32,
}

impl PromptEnumerationRequestV1 {
    fn into_raw(self) -> raw::PromptEnumerationRequestV1 {
        raw::PromptEnumerationRequestV1 {
            set_id: self.set_id,
            objective_digest: self.objective_digest,
            state_digest: self.state_digest,
            generation_vector_digest: self.generation_vector_digest,
            model_tuple: self.model_tuple,
            now_unix_ms: self.now_unix_ms,
            required_factor_ids: self.required_factor_ids,
            maximum_candidates: self.maximum_candidates,
            selection_grammar_digest: self.selection_grammar_digest,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedEnumeratedPromptCandidatesV1 {
    raw: raw::EnumeratedPromptCandidatesV1,
    scope_digest: Digest32,
    verification_digest: Digest32,
}

impl Deref for VerifiedEnumeratedPromptCandidatesV1 {
    type Target = raw::EnumeratedPromptCandidatesV1;

    fn deref(&self) -> &Self::Target {
        &self.raw
    }
}

impl VerifiedEnumeratedPromptCandidatesV1 {
    pub fn scope_digest(&self) -> Digest32 {
        self.scope_digest
    }

    pub fn verification_digest(&self) -> Digest32 {
        self.verification_digest
    }

    pub(crate) fn as_raw(&self) -> &raw::EnumeratedPromptCandidatesV1 {
        &self.raw
    }

    pub(crate) fn into_raw(self) -> raw::EnumeratedPromptCandidatesV1 {
        self.raw
    }
}

pub fn enumerate_factors_v1(
    registry: &PromptRegistry,
    request: PromptEnumerationRequestV1,
) -> Result<VerifiedEnumeratedPromptCandidatesV1, CanonicalPromptError> {
    ensure_digest("scope", request.scope_digest)?;
    let scope_digest = request.scope_digest;
    let raw = raw::enumerate_factors_v1(registry, request.into_raw())?;
    verify_enumerated(raw, scope_digest)
}

pub(crate) fn verify_raw_enumerated_v1(
    raw: raw::EnumeratedPromptCandidatesV1,
    scope_digest: Digest32,
) -> Result<VerifiedEnumeratedPromptCandidatesV1, CanonicalPromptError> {
    verify_enumerated(raw, scope_digest)
}

fn verify_enumerated(
    raw: raw::EnumeratedPromptCandidatesV1,
    scope_digest: Digest32,
) -> Result<VerifiedEnumeratedPromptCandidatesV1, CanonicalPromptError> {
    ensure_digest("scope", scope_digest)?;
    if raw.candidates.len() > super::MAX_CANONICAL_PROMPT_FACTORS
        || raw.candidates.len() != raw.receipt.candidate_factor_ids.len()
        || raw.receipt.authority.grants_any()
        || raw.registry_snapshot.authority.grants_any()
        || raw.registry_snapshot.registry_digest != raw.receipt.registry_digest
        || raw.registry_snapshot.generation_vector_digest != raw.generation_vector_digest
        || raw.registry_snapshot.model_tuple_digest != raw.model_tuple.digest()
    {
        return Err(CanonicalPromptError::Corrupt(
            "enumerated candidate envelope".to_owned(),
        ));
    }
    let mut factors = BTreeSet::new();
    let mut realizations = BTreeSet::new();
    let mut previous: Option<&StableId> = None;
    for (candidate, receipt_factor) in raw
        .candidates
        .iter()
        .zip(&raw.receipt.candidate_factor_ids)
    {
        if candidate.factor_id != *receipt_factor
            || candidate.factor_id != candidate.realization.factor_id
            || candidate.binding_digest != candidate.realization.digest()
            || !factors.insert(candidate.factor_id.clone())
            || !realizations.insert(candidate.realization.realization_id.clone())
            || previous.is_some_and(|value| value >= &candidate.factor_id)
        {
            return Err(CanonicalPromptError::Corrupt(
                "candidate identity/order/binding".to_owned(),
            ));
        }
        previous = Some(&candidate.factor_id);
    }
    let candidates_digest = digest_candidates(&raw.candidates);
    let order_digest = digest_candidate_order(&raw.candidates);
    let verification_digest = digest_candidate_verification(
        &raw.receipt.set_id,
        raw.receipt.objective_digest,
        scope_digest,
        raw.receipt.state_digest,
        raw.receipt.registry_digest,
        raw.registry_snapshot.snapshot_digest,
        raw.model_tuple.digest(),
        raw.receipt.selection_grammar_digest,
        &raw.receipt.candidate_factor_ids,
        candidates_digest,
        order_digest,
        raw.omitted_count,
    );
    if raw.candidates_digest != candidates_digest
        || raw.canonical_order_digest != order_digest
        || raw.receipt.receipt_digest
            != legacy_candidate_receipt_digest(
                &raw.receipt.set_id,
                raw.receipt.objective_digest,
                raw.receipt.state_digest,
                raw.receipt.registry_digest,
                raw.registry_snapshot.snapshot_digest,
                raw.model_tuple.digest(),
                raw.receipt.selection_grammar_digest,
                &raw.receipt.candidate_factor_ids,
                candidates_digest,
                order_digest,
                raw.omitted_count,
            )
    {
        return Err(CanonicalPromptError::Corrupt(
            "candidate digest mismatch".to_owned(),
        ));
    }
    Ok(VerifiedEnumeratedPromptCandidatesV1 {
        raw,
        scope_digest,
        verification_digest,
    })
}

fn digest_candidates(candidates: &[raw::PromptCandidateBindingV1]) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.candidates.v1".to_vec();
    bytes.extend_from_slice(&u64::try_from(candidates.len()).unwrap_or(u64::MAX).to_be_bytes());
    for candidate in candidates {
        push_id(&mut bytes, &candidate.factor_id);
        push_id(&mut bytes, &candidate.realization.realization_id);
        bytes.extend_from_slice(candidate.binding_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn digest_candidate_order(candidates: &[raw::PromptCandidateBindingV1]) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.candidate-order.v1".to_vec();
    for candidate in candidates {
        push_id(&mut bytes, &candidate.factor_id);
        push_id(&mut bytes, &candidate.realization.realization_id);
    }
    Digest32::of_bytes(&bytes)
}

#[allow(clippy::too_many_arguments)]
fn legacy_candidate_receipt_digest(
    set_id: &StableId,
    objective_digest: Digest32,
    state_digest: Digest32,
    registry_digest: Digest32,
    registry_snapshot_digest: Digest32,
    model_tuple_digest: Digest32,
    grammar_digest: Digest32,
    factor_ids: &[StableId],
    candidates_digest: Digest32,
    order_digest: Digest32,
    omitted_count: u32,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.candidate-set-receipt.v1".to_vec();
    push_id(&mut bytes, set_id);
    for digest in [
        objective_digest,
        state_digest,
        registry_digest,
        registry_snapshot_digest,
        model_tuple_digest,
        grammar_digest,
        candidates_digest,
        order_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_ids(&mut bytes, factor_ids);
    bytes.extend_from_slice(&omitted_count.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

#[allow(clippy::too_many_arguments)]
fn digest_candidate_verification(
    set_id: &StableId,
    objective_digest: Digest32,
    scope_digest: Digest32,
    state_digest: Digest32,
    registry_digest: Digest32,
    registry_snapshot_digest: Digest32,
    model_tuple_digest: Digest32,
    grammar_digest: Digest32,
    factor_ids: &[StableId],
    candidates_digest: Digest32,
    order_digest: Digest32,
    omitted_count: u32,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.verified-candidate-set.v2".to_vec();
    push_id(&mut bytes, set_id);
    for digest in [
        objective_digest,
        scope_digest,
        state_digest,
        registry_digest,
        registry_snapshot_digest,
        model_tuple_digest,
        grammar_digest,
        candidates_digest,
        order_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_ids(&mut bytes, factor_ids);
    bytes.extend_from_slice(&omitted_count.to_be_bytes());
    Digest32::of_bytes(&bytes)
}
