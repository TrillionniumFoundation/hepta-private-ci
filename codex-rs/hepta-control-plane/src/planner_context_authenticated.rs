use std::error::Error as StdError;
use std::fmt;

use codex_hepta_cognitive_read::ReadIdsResultV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::EvaluatedPlanV1;
use crate::FeasiblePlanReceiptV1;
use crate::NduPlanningError;
use crate::ObservedContextV1;
use crate::PlannerCanonicalEnvelopeV1;
use crate::PlannerStoreEntryV1;
use crate::PlannerStoreRecordKindV1;
use crate::PlanningEvaluationDispositionV1;
use crate::SearchDisclosureV1;
use crate::plan_observed_context;

const DECISION_MAGIC: &[u8] = b"HEPTA-CONTEXT-DECISION-V1\0";
const MAX_CONTEXT_ITEMS: usize = 4;
const MAX_CONTEXT_BYTES: usize = 24 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ContextRequestBindingV1 {
    pub request_identity_digest: Digest32,
    pub query_digest: Digest32,
    pub retrieval_profile_digest: Digest32,
    pub ranker_policy_digest: Option<Digest32>,
    pub response_profile_digest: Digest32,
}

impl ContextRequestBindingV1 {
    pub fn validate(self) -> Result<(), AuthenticatedContextError> {
        if self.request_identity_digest.is_zero()
            || self.query_digest.is_zero()
            || self.retrieval_profile_digest.is_zero()
            || self.response_profile_digest.is_zero()
            || self.ranker_policy_digest.is_some_and(Digest32::is_zero)
        {
            return Err(AuthenticatedContextError::EmptyDigest);
        }
        Ok(())
    }

    #[must_use]
    pub fn binding_digest(self) -> Digest32 {
        let mut bytes = b"hepta.control.context-request-binding.v1".to_vec();
        push_digest(&mut bytes, self.request_identity_digest);
        push_digest(&mut bytes, self.query_digest);
        push_digest(&mut bytes, self.retrieval_profile_digest);
        push_optional_digest(&mut bytes, self.ranker_policy_digest);
        push_digest(&mut bytes, self.response_profile_digest);
        Digest32::of_bytes(&bytes)
    }
}

pub struct AuthenticatedContextV1<'a> {
    pub owner_id: StableId,
    pub body_generation: Generation,
    pub read: &'a ReadIdsResultV1,
    /// Complete current owner-cut binding, including the exact selected-read
    /// receipt and any current retrieval-generation binding.
    pub owner_cut_digest: Digest32,
    pub encoded_context: &'a [u8],
    pub maximum_context_bytes: u32,
    pub request: ContextRequestBindingV1,
    pub observed_at_micros: u64,
    pub expires_at_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedContextPlanV1 {
    pub read_allowed: bool,
    pub context_digest: Digest32,
    pub request_binding_digest: Digest32,
    pub decision_digest: Digest32,
    pub expires_at_micros: u64,
    pub evaluation: EvaluatedPlanV1,
    decision_body: Vec<u8>,
}

impl AuthenticatedContextPlanV1 {
    pub fn decision_envelope(&self) -> Result<PlannerCanonicalEnvelopeV1, AuthenticatedContextError> {
        PlannerCanonicalEnvelopeV1::new(
            PlannerStoreRecordKindV1::Decision,
            self.evaluation.plan.receipt_digest(),
            self.decision_digest,
            self.decision_body.clone(),
        )
        .map_err(AuthenticatedContextError::Store)
    }

    #[must_use]
    pub fn decision_body(&self) -> &[u8] {
        &self.decision_body
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct VerifiedContextDecisionV1 {
    pub plan_receipt_digest: Digest32,
    pub context_digest: Digest32,
    pub request_binding_digest: Digest32,
    pub read_receipt_digest: Digest32,
    pub owner_cut_digest: Digest32,
    pub verified_item_count: u32,
    pub read_allowed: bool,
    pub expires_at_micros: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AuthenticatedContextError {
    EmptyDigest,
    InvalidTime,
    InvalidReadReceipt,
    ReadAuthority,
    MissingRecord,
    InvalidRecord,
    LimitExceeded,
    DecisionMismatch,
    DecisionExpired,
    Planning,
    Store(crate::PlannerStoreError),
}

impl fmt::Display for AuthenticatedContextError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for AuthenticatedContextError {}

impl From<NduPlanningError> for AuthenticatedContextError {
    fn from(_: NduPlanningError) -> Self {
        Self::Planning
    }
}

pub fn plan_authenticated_context(
    input: AuthenticatedContextV1<'_>,
) -> Result<AuthenticatedContextPlanV1, AuthenticatedContextError> {
    input.request.validate()?;
    if input.owner_cut_digest.is_zero() {
        return Err(AuthenticatedContextError::EmptyDigest);
    }
    if input.expires_at_micros <= input.observed_at_micros {
        return Err(AuthenticatedContextError::InvalidTime);
    }
    if input.maximum_context_bytes == 0
        || usize::try_from(input.maximum_context_bytes)
            .ok()
            .is_none_or(|maximum| maximum > MAX_CONTEXT_BYTES)
        || input.encoded_context.len() > MAX_CONTEXT_BYTES
    {
        return Err(AuthenticatedContextError::LimitExceeded);
    }
    validate_read(input.read)?;
    if input.read.records().len() > MAX_CONTEXT_ITEMS {
        return Err(AuthenticatedContextError::LimitExceeded);
    }
    let verified_item_count = u32::try_from(input.read.records().len())
        .map_err(|_| AuthenticatedContextError::LimitExceeded)?;
    let request_binding_digest = input.request.binding_digest();
    let read_binding_digest = bind_authenticated_read(
        input.owner_cut_digest,
        input.read.receipt_digest(),
        input.read.request_binding_digest(),
        request_binding_digest,
    );
    let planned = plan_observed_context(ObservedContextV1 {
        owner_id: input.owner_id,
        body_generation: input.body_generation,
        source_snapshot_digest: input.read.snapshot_digest(),
        read_digest: read_binding_digest,
        verified_item_count,
        encoded_context: input.encoded_context,
        maximum_context_bytes: input.maximum_context_bytes,
        observed_at_micros: input.observed_at_micros,
        expires_at_micros: input.expires_at_micros,
    })?;
    let plan_receipt_material = encode_plan_receipt_material(&planned.evaluation.plan);
    if Digest32::of_bytes(&plan_receipt_material) != planned.evaluation.plan.receipt_digest() {
        return Err(AuthenticatedContextError::DecisionMismatch);
    }
    let decision_body = encode_context_decision(
        planned.evaluation.plan.receipt_digest(),
        planned.context_digest,
        request_binding_digest,
        input.read.receipt_digest(),
        input.read.request_binding_digest(),
        input.owner_cut_digest,
        verified_item_count,
        input.observed_at_micros,
        input.expires_at_micros,
        planned.read_allowed,
        &plan_receipt_material,
    )?;
    let decision_digest = Digest32::of_bytes(&decision_body);
    Ok(AuthenticatedContextPlanV1 {
        read_allowed: planned.read_allowed,
        context_digest: planned.context_digest,
        request_binding_digest,
        decision_digest,
        expires_at_micros: input.expires_at_micros,
        evaluation: planned.evaluation,
        decision_body,
    })
}

#[allow(clippy::too_many_arguments)]
pub fn verify_context_decision_entry(
    entry: &PlannerStoreEntryV1,
    expected_plan_receipt_digest: Digest32,
    expected_context_digest: Digest32,
    expected_request_binding_digest: Digest32,
    expected_read_receipt_digest: Digest32,
    expected_owner_cut_digest: Digest32,
    expected_item_count: u32,
    expected_read_allowed: bool,
    now_micros: u64,
) -> Result<VerifiedContextDecisionV1, AuthenticatedContextError> {
    if entry.kind != PlannerStoreRecordKindV1::Decision
        || entry.identity_digest != expected_plan_receipt_digest
        || entry.body_digest != Digest32::of_bytes(&entry.canonical_body)
        || entry.semantic_digest != Digest32::of_bytes(&entry.canonical_body)
    {
        return Err(AuthenticatedContextError::DecisionMismatch);
    }
    let parsed = parse_context_decision(&entry.canonical_body)?;
    if parsed.plan_receipt_digest != expected_plan_receipt_digest
        || parsed.context_digest != expected_context_digest
        || parsed.request_binding_digest != expected_request_binding_digest
        || parsed.read_receipt_digest != expected_read_receipt_digest
        || parsed.owner_cut_digest != expected_owner_cut_digest
        || parsed.verified_item_count != expected_item_count
        || parsed.read_allowed != expected_read_allowed
    {
        return Err(AuthenticatedContextError::DecisionMismatch);
    }
    if now_micros >= parsed.expires_at_micros {
        return Err(AuthenticatedContextError::DecisionExpired);
    }
    Ok(parsed)
}

fn validate_read(read: &ReadIdsResultV1) -> Result<(), AuthenticatedContextError> {
    if read.snapshot_digest().is_zero()
        || read.request_binding_digest().is_zero()
        || read.receipt_digest().is_zero()
    {
        return Err(AuthenticatedContextError::EmptyDigest);
    }
    if read.authority().grants_any() {
        return Err(AuthenticatedContextError::ReadAuthority);
    }
    if !read.missing_ids().is_empty() {
        return Err(AuthenticatedContextError::MissingRecord);
    }
    if read
        .records()
        .iter()
        .any(|record| !record.is_live() || record.content_digest.is_none())
    {
        return Err(AuthenticatedContextError::InvalidRecord);
    }
    let canonical = read.canonical_bytes();
    if canonical.len() < 32 {
        return Err(AuthenticatedContextError::InvalidReadReceipt);
    }
    let split = canonical.len() - 32;
    let encoded_receipt = digest_from_slice(&canonical[split..])?;
    if encoded_receipt != read.receipt_digest()
        || Digest32::of_bytes(&canonical[..split]) != read.receipt_digest()
    {
        return Err(AuthenticatedContextError::InvalidReadReceipt);
    }
    Ok(())
}

fn bind_authenticated_read(
    owner_cut_digest: Digest32,
    read_receipt_digest: Digest32,
    read_request_binding_digest: Digest32,
    context_request_binding_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.control.authenticated-context-read.v1".to_vec();
    push_digest(&mut bytes, owner_cut_digest);
    push_digest(&mut bytes, read_receipt_digest);
    push_digest(&mut bytes, read_request_binding_digest);
    push_digest(&mut bytes, context_request_binding_digest);
    Digest32::of_bytes(&bytes)
}

#[allow(clippy::too_many_arguments)]
fn encode_context_decision(
    plan_receipt_digest: Digest32,
    context_digest: Digest32,
    request_binding_digest: Digest32,
    read_receipt_digest: Digest32,
    read_request_binding_digest: Digest32,
    owner_cut_digest: Digest32,
    verified_item_count: u32,
    observed_at_micros: u64,
    expires_at_micros: u64,
    read_allowed: bool,
    plan_receipt_material: &[u8],
) -> Result<Vec<u8>, AuthenticatedContextError> {
    if [
        plan_receipt_digest,
        context_digest,
        request_binding_digest,
        read_receipt_digest,
        read_request_binding_digest,
        owner_cut_digest,
    ]
    .into_iter()
    .any(Digest32::is_zero)
    {
        return Err(AuthenticatedContextError::EmptyDigest);
    }
    if plan_receipt_material.is_empty() || plan_receipt_material.len() > MAX_CONTEXT_BYTES {
        return Err(AuthenticatedContextError::LimitExceeded);
    }
    let mut bytes = DECISION_MAGIC.to_vec();
    push_digest(&mut bytes, plan_receipt_digest);
    push_digest(&mut bytes, context_digest);
    push_digest(&mut bytes, request_binding_digest);
    push_digest(&mut bytes, read_receipt_digest);
    push_digest(&mut bytes, read_request_binding_digest);
    push_digest(&mut bytes, owner_cut_digest);
    bytes.extend_from_slice(&verified_item_count.to_be_bytes());
    bytes.extend_from_slice(&observed_at_micros.to_be_bytes());
    bytes.extend_from_slice(&expires_at_micros.to_be_bytes());
    bytes.push(u8::from(read_allowed));
    bytes.extend_from_slice(
        &u32::try_from(plan_receipt_material.len())
            .map_err(|_| AuthenticatedContextError::LimitExceeded)?
            .to_be_bytes(),
    );
    bytes.extend_from_slice(plan_receipt_material);
    Ok(bytes)
}

fn parse_context_decision(
    bytes: &[u8],
) -> Result<VerifiedContextDecisionV1, AuthenticatedContextError> {
    if !bytes.starts_with(DECISION_MAGIC) {
        return Err(AuthenticatedContextError::DecisionMismatch);
    }
    let mut offset = DECISION_MAGIC.len();
    let plan_receipt_digest = read_digest(bytes, &mut offset)?;
    let context_digest = read_digest(bytes, &mut offset)?;
    let request_binding_digest = read_digest(bytes, &mut offset)?;
    let read_receipt_digest = read_digest(bytes, &mut offset)?;
    let _read_request_binding_digest = read_digest(bytes, &mut offset)?;
    let owner_cut_digest = read_digest(bytes, &mut offset)?;
    let verified_item_count = read_u32(bytes, &mut offset)?;
    let _observed_at_micros = read_u64(bytes, &mut offset)?;
    let expires_at_micros = read_u64(bytes, &mut offset)?;
    let read_allowed = match *bytes
        .get(offset)
        .ok_or(AuthenticatedContextError::DecisionMismatch)?
    {
        0 => false,
        1 => true,
        _ => return Err(AuthenticatedContextError::DecisionMismatch),
    };
    offset += 1;
    let material_len = usize::try_from(read_u32(bytes, &mut offset)?)
        .map_err(|_| AuthenticatedContextError::DecisionMismatch)?;
    let end = offset
        .checked_add(material_len)
        .ok_or(AuthenticatedContextError::DecisionMismatch)?;
    let material = bytes
        .get(offset..end)
        .ok_or(AuthenticatedContextError::DecisionMismatch)?;
    if end != bytes.len() || Digest32::of_bytes(material) != plan_receipt_digest {
        return Err(AuthenticatedContextError::DecisionMismatch);
    }
    Ok(VerifiedContextDecisionV1 {
        plan_receipt_digest,
        context_digest,
        request_binding_digest,
        read_receipt_digest,
        owner_cut_digest,
        verified_item_count,
        read_allowed,
        expires_at_micros,
    })
}

fn encode_plan_receipt_material(receipt: &FeasiblePlanReceiptV1) -> Vec<u8> {
    let mut bytes = b"hepta.control.feasible-plan-receipt.v1".to_vec();
    push_id(&mut bytes, receipt.plan_id());
    push_digest(&mut bytes, receipt.objective_digest());
    bytes.extend_from_slice(&receipt.body_generation().get().to_be_bytes());
    push_digest(&mut bytes, receipt.configuration_digest());
    push_digest(&mut bytes, receipt.revocation_frontier_digest());
    push_digest(&mut bytes, receipt.snapshot_digest());
    push_digest(&mut bytes, receipt.source_candidate_set_digest());
    push_digest(&mut bytes, receipt.candidate_set_digest());
    push_digest(&mut bytes, receipt.prepared_digest());
    push_digest(&mut bytes, receipt.resource_profile_digest());
    push_ids(&mut bytes, receipt.resource_rejected_candidate_ids());
    push_digest(&mut bytes, receipt.evaluation_policy_digest());
    push_digest(&mut bytes, receipt.ndu_evaluation_digest());
    push_digest(&mut bytes, receipt.ndu_binding_digest());
    bytes.push(evaluation_disposition_tag(receipt.evaluation_disposition()));
    push_optional_id(&mut bytes, receipt.chosen_candidate_id());
    push_optional_digest(&mut bytes, receipt.chosen_plan_digest());
    push_digest(&mut bytes, receipt.uncertainty_digest());
    bytes.extend_from_slice(&receipt.expires_at_micros().to_be_bytes());
    bytes.push(search_disclosure_tag(receipt.search_disclosure()));
    bytes
}

const fn evaluation_disposition_tag(value: PlanningEvaluationDispositionV1) -> u8 {
    match value {
        PlanningEvaluationDispositionV1::InfeasibleExplicitAbstain => 0,
        PlanningEvaluationDispositionV1::UniqueParetoRecommendation => 1,
        PlanningEvaluationDispositionV1::ParetoSetRequiresSlowPath => 2,
        PlanningEvaluationDispositionV1::ScalarizedRecommendation => 3,
        PlanningEvaluationDispositionV1::ScalarizationTieRequiresSlowPath => 4,
    }
}

const fn search_disclosure_tag(value: SearchDisclosureV1) -> u8 {
    match value {
        SearchDisclosureV1::BoundedCandidateSetOnly => 0,
        SearchDisclosureV1::UniqueParetoOnBoundedSet => 1,
        SearchDisclosureV1::ScalarizedBoundedSet => 2,
        SearchDisclosureV1::UnresolvedParetoFrontier => 3,
    }
}

fn push_ids(bytes: &mut Vec<u8>, values: &[StableId]) {
    bytes.extend_from_slice(
        &u32::try_from(values.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    for value in values {
        push_id(bytes, value);
    }
}

fn push_optional_id(bytes: &mut Vec<u8>, value: Option<&StableId>) {
    if let Some(value) = value {
        bytes.push(1);
        push_id(bytes, value);
    } else {
        bytes.push(0);
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(
        &u32::try_from(raw.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    bytes.extend_from_slice(raw);
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

fn push_optional_digest(bytes: &mut Vec<u8>, value: Option<Digest32>) {
    if let Some(value) = value {
        bytes.push(1);
        push_digest(bytes, value);
    } else {
        bytes.push(0);
    }
}

fn read_u32(bytes: &[u8], offset: &mut usize) -> Result<u32, AuthenticatedContextError> {
    let end = (*offset)
        .checked_add(4)
        .ok_or(AuthenticatedContextError::DecisionMismatch)?;
    let value = u32::from_be_bytes(
        bytes
            .get(*offset..end)
            .ok_or(AuthenticatedContextError::DecisionMismatch)?
            .try_into()
            .map_err(|_| AuthenticatedContextError::DecisionMismatch)?,
    );
    *offset = end;
    Ok(value)
}

fn read_u64(bytes: &[u8], offset: &mut usize) -> Result<u64, AuthenticatedContextError> {
    let end = (*offset)
        .checked_add(8)
        .ok_or(AuthenticatedContextError::DecisionMismatch)?;
    let value = u64::from_be_bytes(
        bytes
            .get(*offset..end)
            .ok_or(AuthenticatedContextError::DecisionMismatch)?
            .try_into()
            .map_err(|_| AuthenticatedContextError::DecisionMismatch)?,
    );
    *offset = end;
    Ok(value)
}

fn read_digest(
    bytes: &[u8],
    offset: &mut usize,
) -> Result<Digest32, AuthenticatedContextError> {
    let end = (*offset)
        .checked_add(32)
        .ok_or(AuthenticatedContextError::DecisionMismatch)?;
    let digest = digest_from_slice(
        bytes
            .get(*offset..end)
            .ok_or(AuthenticatedContextError::DecisionMismatch)?,
    )?;
    *offset = end;
    Ok(digest)
}

fn digest_from_slice(bytes: &[u8]) -> Result<Digest32, AuthenticatedContextError> {
    let array: [u8; 32] = bytes
        .try_into()
        .map_err(|_| AuthenticatedContextError::DecisionMismatch)?;
    Ok(Digest32::from_array(array))
}

#[cfg(test)]
#[path = "planner_context_authenticated_tests.rs"]
mod tests;
