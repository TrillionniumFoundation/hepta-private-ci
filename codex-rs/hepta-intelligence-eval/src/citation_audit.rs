//! Signed, complete citation adjudication at the existing learning.eval owner.
//!
//! Signatures authenticate attestations, not their scientific truth. The caller
//! obtains current trust and source withdrawals from their owners. No automatic
//! entailment judge, production qualification, or activation authority is added.
use std::collections::BTreeSet;
use std::fmt;

use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_independent_roles_v1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CitationSourceV1 {
    pub label: String,
    pub identity: String,
    pub source_root: Digest32,
    /// Exact rendered excerpt delivered to the reader, including truncation.
    pub excerpt: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CitationAuditRequestV1 {
    pub query_id: String,
    pub scope: String,
    pub experiment_digest: Digest32,
    pub family_digest: Digest32,
    pub prompt_digest: Digest32,
    pub question: String,
    pub question_time: String,
    pub answer: String,
    pub sources: Vec<CitationSourceV1>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CitationClaimKindV1 { Factual, Nonfactual, Abstention, Unreviewed }
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CitationVerdictV1 { Entailed, Contradicted, Unsupported, Unreviewed }

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CitationClaimV1 {
    /// Half-open UTF-8 byte offsets, not character offsets or token offsets.
    pub start: u32,
    pub end: u32,
    pub kind: CitationClaimKindV1,
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CitationJudgementV1 {
    /// Start of one emitted `[E<number>]` occurrence in the original answer.
    pub start: u32,
    pub verdict: CitationVerdictV1,
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CitationAuditJudgementV1 {
    pub claims: Vec<CitationClaimV1>,
    pub citations: Vec<CitationJudgementV1>,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct CitationAuditCountsV1 {
    pub citations: u32,
    pub entailed: u32,
    pub contradicted: u32,
    pub unreviewed_citations: u32,
    pub factual_claims: u32,
    pub supported_factual_claims: u32,
    pub unreviewed_claims: u32,
}
impl CitationAuditCountsV1 {
    /// Observed precision only: no confidence or independence claim. Abstaining
    /// from citations returns None, never a vacuous perfect score.
    pub fn precision_ppm(&self) -> Option<u32> {
        (self.citations != 0).then(|| ((u64::from(self.entailed) * 1_000_000) / u64::from(self.citations)) as u32)
    }
}

#[derive(Debug)]
pub enum CitationAuditError {
    Invalid(&'static str),
    Authentication(SignedEvidenceError),
}
impl fmt::Display for CitationAuditError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result { write!(f, "{self:?}") }
}
impl std::error::Error for CitationAuditError {}
impl From<SignedEvidenceError> for CitationAuditError {
    fn from(value: SignedEvidenceError) -> Self { Self::Authentication(value) }
}

/// Only authenticated generator/evaluator separation produces this receipt.
/// It is an input to existing independent acceptance, not acceptance itself.
#[derive(Debug)]
pub struct VerifiedCitationAuditV1 {
    counts: CitationAuditCountsV1,
    request_digest: Digest32,
    judgement_digest: Digest32,
    trust_digest: Digest32,
}
impl VerifiedCitationAuditV1 {
    pub fn counts(&self) -> CitationAuditCountsV1 { self.counts }
    pub fn request_digest(&self) -> Digest32 { self.request_digest }
    pub fn judgement_digest(&self) -> Digest32 { self.judgement_digest }
    pub fn trust_digest(&self) -> Digest32 { self.trust_digest }
    pub fn authority(&self) -> AuthorityPosture { AuthorityPosture::DENY_ALL }
}

fn text(out: &mut Vec<u8>, value: &str, bound: usize) -> Result<(), CitationAuditError> {
    if value.is_empty() || value.len() > bound || value.contains('\0') {
        return Err(CitationAuditError::Invalid("text bound"));
    }
    out.extend_from_slice(&(value.len() as u64).to_be_bytes());
    out.extend_from_slice(value.as_bytes());
    Ok(())
}

/// Canonical V1 interchange shared with scripts/memory_cell/citation_audit.py.
pub fn citation_request_payload_v1(request: &CitationAuditRequestV1) -> Result<Vec<u8>, CitationAuditError> {
    let mut out = b"hepta.memory-citation.request.v1\0".to_vec();
    text(&mut out, &request.query_id, 1024)?;
    text(&mut out, &request.scope, 1024)?;
    for digest in [request.experiment_digest, request.family_digest, request.prompt_digest] {
        if digest.is_zero() { return Err(CitationAuditError::Invalid("zero context digest")); }
        out.extend_from_slice(digest.as_array());
    }
    text(&mut out, &request.question, 16384)?;
    text(&mut out, &request.question_time, 256)?;
    text(&mut out, &request.answer, 65536)?;
    if request.sources.len() > 256 { return Err(CitationAuditError::Invalid("source bound")); }
    out.extend_from_slice(&(request.sources.len() as u64).to_be_bytes());
    let mut labels = BTreeSet::new();
    let mut identities = BTreeSet::new();
    for source in &request.sources {
        let label = source.label.as_bytes();
        if label.len() < 2 || label.len() > 7 || label[0] != b'E'
            || !matches!(label[1], b'1'..=b'9') || !label[2..].iter().all(u8::is_ascii_digit)
            || !labels.insert(&source.label) || !identities.insert(&source.identity) || source.source_root.is_zero()
        { return Err(CitationAuditError::Invalid("source identity")); }
        text(&mut out, &source.label, 7)?;
        text(&mut out, &source.identity, 1024)?;
        out.extend_from_slice(source.source_root.as_array());
        text(&mut out, &source.excerpt, 32768)?;
        if out.len() > 1_048_576 { return Err(CitationAuditError::Invalid("payload bound")); }
    }
    Ok(out)
}

pub fn citation_judgement_payload_v1(
    request: &CitationAuditRequestV1, judgement: &CitationAuditJudgementV1,
) -> Result<Vec<u8>, CitationAuditError> {
    let raw = citation_request_payload_v1(request)?;
    if judgement.claims.is_empty() || judgement.claims.len() > 512 || judgement.citations.len() > 512 {
        return Err(CitationAuditError::Invalid("judgement bound"));
    }
    let mut out = b"hepta.memory-citation.judgement.v1\0".to_vec();
    out.extend_from_slice(Digest32::of_bytes(&raw).as_array());
    out.extend_from_slice(&(judgement.claims.len() as u64).to_be_bytes());
    for claim in &judgement.claims {
        out.extend_from_slice(&claim.start.to_be_bytes());
        out.extend_from_slice(&claim.end.to_be_bytes());
        out.push(match claim.kind { CitationClaimKindV1::Factual => 0, CitationClaimKindV1::Nonfactual => 1, CitationClaimKindV1::Abstention => 2, CitationClaimKindV1::Unreviewed => 3 });
    }
    out.extend_from_slice(&(judgement.citations.len() as u64).to_be_bytes());
    for citation in &judgement.citations {
        out.extend_from_slice(&citation.start.to_be_bytes());
        out.push(match citation.verdict { CitationVerdictV1::Entailed => 0, CitationVerdictV1::Contradicted => 1, CitationVerdictV1::Unsupported => 2, CitationVerdictV1::Unreviewed => 3 });
    }
    Ok(out)
}

fn markers(answer: &str) -> Vec<(usize, usize, &str)> {
    let bytes = answer.as_bytes();
    let mut result = Vec::new();
    let mut start = 0;
    while start + 3 < bytes.len() {
        if bytes[start..].starts_with(b"[E") {
            let mut end = start + 2;
            while end < bytes.len() && bytes[end].is_ascii_digit() { end += 1; }
            if end > start + 2 && bytes.get(end) == Some(&b']') {
                result.push((start, end + 1, &answer[start + 1..end]));
                start = end;
            }
        }
        start += 1;
    }
    result
}

pub fn validate_citation_judgement_v1(
    request: &CitationAuditRequestV1, judgement: &CitationAuditJudgementV1,
    revoked_roots: &BTreeSet<Digest32>,
) -> Result<CitationAuditCountsV1, CitationAuditError> {
    citation_judgement_payload_v1(request, judgement)?;
    if request.sources.iter().any(|source| revoked_roots.contains(&source.source_root)) {
        return Err(CitationAuditError::Invalid("revoked delivered source"));
    }
    let mut cursor = 0;
    let mut counts = CitationAuditCountsV1::default();
    for claim in &judgement.claims {
        let (start, end) = (claim.start as usize, claim.end as usize);
        if !(cursor <= start && start < end && end <= request.answer.len())
            || !request.answer.is_char_boundary(start) || !request.answer.is_char_boundary(end)
            || !request.answer[cursor..start].trim_matches([' ', '\t', '\r', '\n']).is_empty() || request.answer[start..end].trim_matches([' ', '\t', '\r', '\n']).is_empty()
        { return Err(CitationAuditError::Invalid("claim span coverage")); }
        cursor = end;
        counts.factual_claims += u32::from(claim.kind == CitationClaimKindV1::Factual);
        counts.unreviewed_claims += u32::from(claim.kind == CitationClaimKindV1::Unreviewed);
    }
    if !request.answer[cursor..].trim_matches([' ', '\t', '\r', '\n']).is_empty() { return Err(CitationAuditError::Invalid("unreviewed suffix")); }
    let occurrences = markers(&request.answer);
    if occurrences.len() != judgement.citations.len() { return Err(CitationAuditError::Invalid("citation coverage")); }
    let mut supported = BTreeSet::new();
    for ((start, end, label), citation) in occurrences.into_iter().zip(&judgement.citations) {
        if start != citation.start as usize { return Err(CitationAuditError::Invalid("citation order")); }
        let Some((index, claim)) = judgement.claims.iter().enumerate().find(|(_, claim)| {
            claim.start as usize <= start && end <= claim.end as usize
        }) else { return Err(CitationAuditError::Invalid("citation outside claim")); };
        if claim.kind != CitationClaimKindV1::Factual { return Err(CitationAuditError::Invalid("citation outside factual claim")); }
        counts.citations += 1;
        match citation.verdict {
            CitationVerdictV1::Entailed => {
                if !request.sources.iter().any(|source| source.label == label) { return Err(CitationAuditError::Invalid("undelivered citation")); }
                counts.entailed += 1;
                supported.insert(index);
            }
            CitationVerdictV1::Contradicted => counts.contradicted += 1,
            CitationVerdictV1::Unreviewed => counts.unreviewed_citations += 1,
            CitationVerdictV1::Unsupported => (),
        }
    }
    counts.supported_factual_claims = supported.len() as u32;
    Ok(counts)
}

/// Reverify BOTH attestations under live host trust on every import. A changed
/// answer, excerpt, occurrence, label, scope or context changes the signed bytes.
pub fn verify_signed_citation_audit_v1(
    request: &CitationAuditRequestV1, judgement: &CitationAuditJudgementV1,
    generator: &SignedLearningEvidenceV1, evaluator: &SignedLearningEvidenceV1,
    verifier: &LearningEvidenceVerifierV1, revoked_roots: &BTreeSet<Digest32>, now: u64,
) -> Result<VerifiedCitationAuditV1, CitationAuditError> {
    let request_bytes = citation_request_payload_v1(request)?;
    let judgement_bytes = citation_judgement_payload_v1(request, judgement)?;
    let generated = verifier.verify(LearningEvidenceRoleV1::Generator, generator, &request_bytes, now)?;
    let evaluated = verifier.verify(LearningEvidenceRoleV1::Evaluator, evaluator, &judgement_bytes, now)?;
    verify_signed_independent_roles_v1(&generated, &evaluated, now)?;
    let counts = validate_citation_judgement_v1(request, judgement, revoked_roots)?;
    Ok(VerifiedCitationAuditV1 { counts, request_digest: generated.payload_digest(),
        judgement_digest: evaluated.payload_digest(), trust_digest: verifier.trust_digest() })
}

#[cfg(test)]
#[path = "citation_audit_tests.rs"]
mod tests;
