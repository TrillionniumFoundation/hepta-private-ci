//! Digest-only decision audit. Relaxed bounds ignore constraints and budgets;
//! they are valid upper bounds, not claims of global optimality or causal truth.
use super::*;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptCandidateDispositionV1 { Selected, HeuristicExcluded }

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateAuditV1 {
    pub factor_id: StableId,
    pub disposition: PromptCandidateDispositionV1,
    pub net_utility_q32: FixedQ32,
    pub token_cost: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioAuditV1 {
    pub candidate_receipt_digest: Digest32,
    pub completeness_digest: Digest32,
    pub omitted_count: u32,
    pub source_id: StableId,
    pub trust_digest: Digest32,
    pub scope_digest: Digest32,
    pub pricing_binding_digest: Digest32,
    pub interaction_binding_digest: Digest32,
    pub pricing_policy_digest: Digest32,
    pub graph_generation_digest: Digest32,
    pub portfolio_receipt_digest: Digest32,
    pub oldest_evidence_age_ms: u64,
    pub valid_until_unix_ms: u64,
    pub token_budget: u64,
    pub used_tokens: u32,
    pub incumbent_q32: FixedQ32,
    pub relaxed_upper_bound_q32: Option<FixedQ32>,
    pub relaxed_gap_q32: Option<FixedQ32>,
    /// The legacy arithmetic engine does not instrument its loop. Absence is
    /// explicit rather than equating selected-factor count with solver rounds.
    pub solver_rounds: Option<u32>,
    pub candidates: Vec<PromptCandidateAuditV1>,
    pub audit_digest: Digest32,
}

pub(super) fn build_audit(
    priced: &PricedPromptCandidatesV1,
    portfolio: &RawSelectedPromptPortfolioV1,
    interactions: &PromptInteractionAdmissionV1,
    token_budget: u64,
    now: u64,
) -> Result<PromptPortfolioAuditV1, CanonicalPromptError> {
    let upper = priced.rows.iter().map(|row| i128::from(row.net_utility_q32.raw().max(0))).sum::<i128>()
        + interactions.pairs.iter().map(|pair| i128::from(pair.marginal_utility_q32.raw().max(0))).sum::<i128>();
    let incumbent = i128::from(portfolio.receipt.expected_utility_q32.raw());
    if upper < incumbent { return Err(CanonicalPromptError::Integrity("invalid relaxation bound")); }
    let oldest = priced.admission.estimates.iter().map(|row| row.evidence.issued_at)
        .chain(interactions.pairs.iter().map(|pair| pair.evidence.issued_at))
        .chain([priced.admission.completeness_evidence.issued_at,
            priced.admission.binding_evidence.issued_at, interactions.binding_evidence.issued_at])
        .min().ok_or(CanonicalPromptError::Integrity("missing evidence clock"))?;
    let age = now.checked_sub(oldest).ok_or(CanonicalPromptError::Integrity("future evidence"))?;
    let candidates = priced.rows.iter().map(|row| PromptCandidateAuditV1 {
        factor_id: row.binding.factor_id.clone(),
        disposition: if portfolio.receipt.factor_ids.contains(&row.binding.factor_id) {
            PromptCandidateDispositionV1::Selected
        } else { PromptCandidateDispositionV1::HeuristicExcluded },
        net_utility_q32: row.net_utility_q32,
        token_cost: row.pricing.token_cost,
    }).collect::<Vec<_>>();
    let mut audit = PromptPortfolioAuditV1 {
        candidate_receipt_digest: priced.candidates.receipt.receipt_digest,
        completeness_digest: priced.completeness_digest,
        omitted_count: priced.candidates.omitted_count,
        source_id: priced.source_id.clone(),
        trust_digest: priced.trust_digest,
        scope_digest: priced.scope_digest,
        pricing_binding_digest: priced.admission.binding_evidence.payload_digest,
        interaction_binding_digest: interactions.binding_evidence.payload_digest,
        pricing_policy_digest: priced.pricing_policy_digest,
        graph_generation_digest: portfolio.graph_generation_digest,
        portfolio_receipt_digest: portfolio.receipt.receipt_digest,
        oldest_evidence_age_ms: age,
        valid_until_unix_ms: portfolio.receipt.valid_until_unix_ms,
        token_budget,
        used_tokens: portfolio.receipt.total_token_upper_bound,
        incumbent_q32: portfolio.receipt.expected_utility_q32,
        relaxed_upper_bound_q32: i64::try_from(upper).ok().map(FixedQ32::from_raw),
        relaxed_gap_q32: i64::try_from(upper - incumbent).ok().map(FixedQ32::from_raw),
        solver_rounds: None,
        candidates,
        audit_digest: Digest32::ZERO,
    };
    audit.audit_digest = audit.compute_digest();
    Ok(audit)
}

impl PromptPortfolioAuditV1 {
    pub fn compute_digest(&self) -> Digest32 {
        let mut out = b"hepta.prompt-optimizer.verified-audit.v1".to_vec();
        let source = self.source_id.as_str().as_bytes();
        out.extend_from_slice(&(source.len() as u64).to_be_bytes());
        out.extend_from_slice(source);
        for digest in [self.candidate_receipt_digest, self.completeness_digest, self.trust_digest,
            self.scope_digest, self.pricing_binding_digest, self.interaction_binding_digest,
            self.pricing_policy_digest, self.graph_generation_digest, self.portfolio_receipt_digest] {
            out.extend_from_slice(digest.as_array());
        }
        out.extend_from_slice(&self.omitted_count.to_be_bytes());
        out.extend_from_slice(&self.oldest_evidence_age_ms.to_be_bytes());
        out.extend_from_slice(&self.valid_until_unix_ms.to_be_bytes());
        out.extend_from_slice(&self.token_budget.to_be_bytes());
        out.extend_from_slice(&self.used_tokens.to_be_bytes());
        out.extend_from_slice(&self.incumbent_q32.raw().to_be_bytes());
        for value in [self.relaxed_upper_bound_q32, self.relaxed_gap_q32] {
            match value {
                Some(value) => { out.push(1); out.extend_from_slice(&value.raw().to_be_bytes()); }
                None => out.push(0),
            }
        }
        match self.solver_rounds {
            Some(rounds) => { out.push(1); out.extend_from_slice(&rounds.to_be_bytes()); }
            None => out.push(0),
        }
        out.extend_from_slice(&(self.candidates.len() as u64).to_be_bytes());
        for candidate in &self.candidates {
            let id = candidate.factor_id.as_str().as_bytes();
            out.extend_from_slice(&(id.len() as u64).to_be_bytes());
            out.extend_from_slice(id);
            out.push(match candidate.disposition {
                PromptCandidateDispositionV1::Selected => 0,
                PromptCandidateDispositionV1::HeuristicExcluded => 1,
            });
            out.extend_from_slice(&candidate.net_utility_q32.raw().to_be_bytes());
            out.extend_from_slice(&candidate.token_cost.to_be_bytes());
        }
        Digest32::of_bytes(&out)
    }
}
