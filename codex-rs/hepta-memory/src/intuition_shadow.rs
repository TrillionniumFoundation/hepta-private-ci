//! Deterministic H6 intuition-policy shadow surface.
//!
//! This module is intentionally a pure read-only contract.  It evaluates a
//! bounded caller-supplied candidate set against hard gates, performs an
//! integer-only rank/tie-break, and emits either a `Suggested` decision or an
//! explicit abstain.  It does not read or write the cognitive store, mutate
//! KG facts, invoke a model, route a workflow, or dispatch an effect.
//!
//! Every receipt is bound to an immutable snapshot digest, this module's
//! schema digest, and the caller's policy digest.  The bindings make stale or
//! cross-policy replay fail closed without granting runtime authority.

use std::collections::BTreeSet;

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use thiserror::Error;

use crate::framing::frame_part;

pub const H6_INTUITION_SHADOW_SCHEMA_VERSION: u32 = 1;
pub const H6_INTUITION_SHADOW_NAMESPACE: &str = "local_development_only";
pub const MAX_INTUITION_CANDIDATES: usize = 16;
pub const MAX_INTUITION_CANDIDATE_ID_BYTES: usize = 128;

/// The only modes this shadow evaluator can describe.  Neither mode grants
/// permission to execute an effect; `PrepareOnly` merely records that a
/// future human approval would be required.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum IntuitionMode {
    SuggestOnly,
    PrepareOnly,
}

impl IntuitionMode {
    const fn as_str(self) -> &'static str {
        match self {
            Self::SuggestOnly => "suggest_only",
            Self::PrepareOnly => "prepare_only",
        }
    }
}

/// A fixed schema identity.  Callers must supply this digest in the input;
/// accepting another digest would make a receipt unverifiable after a schema
/// upgrade.
pub fn intuition_schema_digest() -> Sha256Digest {
    Sha256Digest::for_bytes(b"hepta:h6:intuition-shadow-schema:v1")
}

/// One candidate from an already materialized, immutable read snapshot.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct IntuitionCandidate {
    pub candidate_id: String,
    pub score_bps: u16,
    pub risk_bps: u16,
    pub allowed_modes: Vec<IntuitionMode>,
    pub evidence_ready: bool,
}

impl IntuitionCandidate {
    pub fn new(
        candidate_id: impl Into<String>,
        score_bps: u16,
        risk_bps: u16,
        allowed_modes: Vec<IntuitionMode>,
        evidence_ready: bool,
    ) -> Result<Self, IntuitionShadowError> {
        let candidate = Self {
            candidate_id: candidate_id.into(),
            score_bps,
            risk_bps,
            allowed_modes,
            evidence_ready,
        };
        candidate.validate()?;
        Ok(candidate)
    }

    fn validate(&self) -> Result<(), IntuitionShadowError> {
        validate_text(
            &self.candidate_id,
            "candidate id",
            MAX_INTUITION_CANDIDATE_ID_BYTES,
        )?;
        if self.score_bps > 10_000 || self.risk_bps > 10_000 {
            return Err(IntuitionShadowError::Invalid(
                "candidate score and risk must be within 0..=10000 bps".to_string(),
            ));
        }
        if self.allowed_modes.is_empty() {
            return Err(IntuitionShadowError::Invalid(
                "candidate must allow at least one shadow mode".to_string(),
            ));
        }
        let mut modes = BTreeSet::new();
        for mode in &self.allowed_modes {
            if !modes.insert(*mode) {
                return Err(IntuitionShadowError::Invalid(
                    "candidate modes must be unique".to_string(),
                ));
            }
        }
        Ok(())
    }
}

/// Immutable input for one H6 shadow decision.  `snapshot_digest` is the
/// digest of the KG/read snapshot selected by the caller; this function does
/// not access that snapshot itself.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct IntuitionShadowInput {
    pub snapshot_digest: Sha256Digest,
    pub schema_digest: Sha256Digest,
    pub policy_digest: Sha256Digest,
    pub authority_epoch: u64,
    pub mode: IntuitionMode,
    pub max_risk_bps: u16,
    pub min_confidence_bps: u16,
    pub require_evidence: bool,
    pub candidates: Vec<IntuitionCandidate>,
}

impl IntuitionShadowInput {
    pub fn validate(&self) -> Result<(), IntuitionShadowError> {
        validate_digest(&self.snapshot_digest, "snapshot digest")?;
        validate_digest(&self.schema_digest, "schema digest")?;
        validate_digest(&self.policy_digest, "policy digest")?;
        if self.schema_digest != intuition_schema_digest() {
            return Err(IntuitionShadowError::SchemaMismatch);
        }
        if self.authority_epoch == 0 {
            return Err(IntuitionShadowError::Invalid(
                "authority epoch must be non-zero".to_string(),
            ));
        }
        if self.max_risk_bps > 10_000 || self.min_confidence_bps > 10_000 {
            return Err(IntuitionShadowError::Invalid(
                "risk and confidence thresholds must be within 0..=10000 bps".to_string(),
            ));
        }
        if self.candidates.is_empty() {
            return Err(IntuitionShadowError::Invalid(
                "at least one intuition candidate is required".to_string(),
            ));
        }
        if self.candidates.len() > MAX_INTUITION_CANDIDATES {
            return Err(IntuitionShadowError::Invalid(format!(
                "candidate count exceeds {MAX_INTUITION_CANDIDATES}"
            )));
        }
        let mut ids = BTreeSet::new();
        for candidate in &self.candidates {
            candidate.validate()?;
            if !ids.insert(candidate.candidate_id.as_str()) {
                return Err(IntuitionShadowError::Invalid(
                    "candidate ids must be unique".to_string(),
                ));
            }
        }
        Ok(())
    }

    /// Computes a canonical digest without preserving candidate input order.
    pub fn digest(&self) -> Result<Sha256Digest, IntuitionShadowError> {
        self.validate()?;
        let mut hasher = Sha256::new();
        frame_part(&mut hasher, b"hepta:h6:intuition-input:v1");
        frame_part(&mut hasher, self.snapshot_digest.as_str().as_bytes());
        frame_part(&mut hasher, self.schema_digest.as_str().as_bytes());
        frame_part(&mut hasher, self.policy_digest.as_str().as_bytes());
        frame_part(&mut hasher, &self.authority_epoch.to_be_bytes());
        frame_part(&mut hasher, self.mode.as_str().as_bytes());
        frame_part(&mut hasher, &self.max_risk_bps.to_be_bytes());
        frame_part(&mut hasher, &self.min_confidence_bps.to_be_bytes());
        frame_part(&mut hasher, &[u8::from(self.require_evidence)]);
        let mut candidates = self.candidates.iter().collect::<Vec<_>>();
        candidates.sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
        frame_part(
            &mut hasher,
            &u64::try_from(candidates.len())
                .unwrap_or(u64::MAX)
                .to_be_bytes(),
        );
        for candidate in candidates {
            frame_part(&mut hasher, candidate.candidate_id.as_bytes());
            frame_part(&mut hasher, &candidate.score_bps.to_be_bytes());
            frame_part(&mut hasher, &candidate.risk_bps.to_be_bytes());
            frame_part(&mut hasher, &[u8::from(candidate.evidence_ready)]);
            let mut modes = candidate.allowed_modes.clone();
            modes.sort();
            frame_part(
                &mut hasher,
                &u64::try_from(modes.len()).unwrap_or(u64::MAX).to_be_bytes(),
            );
            for mode in modes {
                frame_part(&mut hasher, mode.as_str().as_bytes());
            }
        }
        Ok(Sha256Digest::from_sha256_output(hasher.finalize()))
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum IntuitionAbstainReason {
    NoEligibleCandidates,
    ConfidenceBelowThreshold,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case", tag = "decision")]
pub enum IntuitionDecision {
    Suggested {
        candidate_id: String,
        confidence_bps: u16,
    },
    Abstained {
        reason: IntuitionAbstainReason,
    },
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum IntuitionShadowPhase {
    Shadow,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum IntuitionShadowAuthority {
    SuggestOnly,
}

/// A self-validating, non-executable H6 receipt.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct IntuitionShadowReceipt {
    pub schema_version: u32,
    pub namespace: String,
    pub receipt_digest: Sha256Digest,
    pub input_digest: Sha256Digest,
    pub snapshot_digest: Sha256Digest,
    pub schema_digest: Sha256Digest,
    pub policy_digest: Sha256Digest,
    pub authority_epoch: u64,
    pub mode: IntuitionMode,
    pub decision: IntuitionDecision,
    pub phase: IntuitionShadowPhase,
    pub authority: IntuitionShadowAuthority,
    pub production_effects: bool,
    pub execute_allowed: bool,
    pub kg_write_allowed: bool,
    pub online_routing: bool,
    pub runtime_consumer: bool,
}

impl IntuitionShadowReceipt {
    pub fn validate(&self) -> Result<(), IntuitionShadowError> {
        if self.schema_version != H6_INTUITION_SHADOW_SCHEMA_VERSION
            || self.namespace != H6_INTUITION_SHADOW_NAMESPACE
            || self.schema_digest != intuition_schema_digest()
        {
            return Err(IntuitionShadowError::SchemaMismatch);
        }
        validate_digest(&self.receipt_digest, "receipt digest")?;
        validate_digest(&self.input_digest, "input digest")?;
        validate_digest(&self.snapshot_digest, "snapshot digest")?;
        validate_digest(&self.policy_digest, "policy digest")?;
        if self.authority_epoch == 0 {
            return Err(IntuitionShadowError::Invalid(
                "authority epoch must be non-zero".to_string(),
            ));
        }
        if self.phase != IntuitionShadowPhase::Shadow
            || self.authority != IntuitionShadowAuthority::SuggestOnly
            || self.production_effects
            || self.execute_allowed
            || self.kg_write_allowed
            || self.online_routing
            || self.runtime_consumer
        {
            return Err(IntuitionShadowError::AuthorityBoundary);
        }
        if let IntuitionDecision::Suggested { candidate_id, .. } = &self.decision {
            validate_text(
                candidate_id,
                "suggested candidate id",
                MAX_INTUITION_CANDIDATE_ID_BYTES,
            )?;
        }
        if self.receipt_digest != receipt_digest(self) {
            return Err(IntuitionShadowError::DigestMismatch);
        }
        Ok(())
    }

    pub fn validate_against(
        &self,
        input: &IntuitionShadowInput,
    ) -> Result<(), IntuitionShadowError> {
        input.validate()?;
        self.validate()?;
        if self.input_digest != input.digest()?
            || self.snapshot_digest != input.snapshot_digest
            || self.schema_digest != input.schema_digest
            || self.policy_digest != input.policy_digest
            || self.authority_epoch != input.authority_epoch
            || self.mode != input.mode
        {
            return Err(IntuitionShadowError::BindingMismatch);
        }
        if self.decision != deterministic_decision(input) {
            return Err(IntuitionShadowError::BindingMismatch);
        }
        Ok(())
    }

    pub fn is_shadow_only(&self) -> bool {
        self.phase == IntuitionShadowPhase::Shadow
            && self.authority == IntuitionShadowAuthority::SuggestOnly
            && !self.production_effects
            && !self.execute_allowed
            && !self.kg_write_allowed
            && !self.online_routing
            && !self.runtime_consumer
    }
}

#[derive(Debug, Error, Eq, PartialEq)]
pub enum IntuitionShadowError {
    #[error("invalid intuition shadow input: {0}")]
    Invalid(String),
    #[error("intuition schema digest is not supported")]
    SchemaMismatch,
    #[error("intuition receipt digest does not match its contents")]
    DigestMismatch,
    #[error("intuition receipt is not bound to its input snapshot")]
    BindingMismatch,
    #[error("intuition receipt crosses the shadow authority boundary")]
    AuthorityBoundary,
}

/// Evaluate one immutable candidate set deterministically.  Hard filters are
/// applied before rank; ties are broken by candidate id ascending.  A result
/// is always a proposal-only receipt or an explicit abstain.
pub fn shadow_intuition_decide(
    input: &IntuitionShadowInput,
) -> Result<IntuitionShadowReceipt, IntuitionShadowError> {
    input.validate()?;
    let input_digest = input.digest()?;
    let decision = deterministic_decision(input);
    let mut receipt = IntuitionShadowReceipt {
        schema_version: H6_INTUITION_SHADOW_SCHEMA_VERSION,
        namespace: H6_INTUITION_SHADOW_NAMESPACE.to_string(),
        receipt_digest: Sha256Digest::for_bytes(b"pending"),
        input_digest,
        snapshot_digest: input.snapshot_digest.clone(),
        schema_digest: input.schema_digest.clone(),
        policy_digest: input.policy_digest.clone(),
        authority_epoch: input.authority_epoch,
        mode: input.mode,
        decision,
        phase: IntuitionShadowPhase::Shadow,
        authority: IntuitionShadowAuthority::SuggestOnly,
        production_effects: false,
        execute_allowed: false,
        kg_write_allowed: false,
        online_routing: false,
        runtime_consumer: false,
    };
    receipt.receipt_digest = receipt_digest(&receipt);
    receipt.validate_against(input)?;
    Ok(receipt)
}

fn deterministic_decision(input: &IntuitionShadowInput) -> IntuitionDecision {
    let mut eligible = input
        .candidates
        .iter()
        .filter(|candidate| {
            candidate.allowed_modes.contains(&input.mode)
                && candidate.risk_bps <= input.max_risk_bps
                && (!input.require_evidence || candidate.evidence_ready)
        })
        .collect::<Vec<_>>();
    eligible.sort_by(|left, right| {
        right
            .score_bps
            .cmp(&left.score_bps)
            .then_with(|| left.candidate_id.cmp(&right.candidate_id))
    });

    match eligible.first() {
        None => IntuitionDecision::Abstained {
            reason: IntuitionAbstainReason::NoEligibleCandidates,
        },
        Some(candidate) if candidate.score_bps < input.min_confidence_bps => {
            IntuitionDecision::Abstained {
                reason: IntuitionAbstainReason::ConfidenceBelowThreshold,
            }
        }
        Some(candidate) => IntuitionDecision::Suggested {
            candidate_id: candidate.candidate_id.clone(),
            confidence_bps: candidate.score_bps,
        },
    }
}

fn receipt_digest(receipt: &IntuitionShadowReceipt) -> Sha256Digest {
    let mut hasher = Sha256::new();
    frame_part(&mut hasher, b"hepta:h6:intuition-receipt:v1");
    frame_part(&mut hasher, &receipt.schema_version.to_be_bytes());
    frame_part(&mut hasher, receipt.namespace.as_bytes());
    frame_part(&mut hasher, receipt.input_digest.as_str().as_bytes());
    frame_part(&mut hasher, receipt.snapshot_digest.as_str().as_bytes());
    frame_part(&mut hasher, receipt.schema_digest.as_str().as_bytes());
    frame_part(&mut hasher, receipt.policy_digest.as_str().as_bytes());
    frame_part(&mut hasher, &receipt.authority_epoch.to_be_bytes());
    frame_part(&mut hasher, receipt.mode.as_str().as_bytes());
    match &receipt.decision {
        IntuitionDecision::Suggested {
            candidate_id,
            confidence_bps,
        } => {
            frame_part(&mut hasher, b"suggested");
            frame_part(&mut hasher, candidate_id.as_bytes());
            frame_part(&mut hasher, &confidence_bps.to_be_bytes());
        }
        IntuitionDecision::Abstained { reason } => {
            frame_part(&mut hasher, b"abstained");
            frame_part(
                &mut hasher,
                match reason {
                    IntuitionAbstainReason::NoEligibleCandidates => b"no_eligible_candidates",
                    IntuitionAbstainReason::ConfidenceBelowThreshold => {
                        b"confidence_below_threshold"
                    }
                },
            );
        }
    }
    frame_part(&mut hasher, b"shadow");
    frame_part(&mut hasher, b"suggest_only");
    frame_part(&mut hasher, &[0, 0, 0, 0, 0]);
    Sha256Digest::from_sha256_output(hasher.finalize())
}

fn validate_digest(digest: &Sha256Digest, label: &str) -> Result<(), IntuitionShadowError> {
    if Sha256Digest::parse(digest.as_str().to_string()).is_err() {
        return Err(IntuitionShadowError::Invalid(format!(
            "{label} must be a lowercase SHA-256 digest"
        )));
    }
    Ok(())
}

fn validate_text(value: &str, label: &str, max_bytes: usize) -> Result<(), IntuitionShadowError> {
    if value.trim().is_empty()
        || value.len() > max_bytes
        || value.as_bytes().contains(&0)
        || value.chars().any(char::is_control)
    {
        return Err(IntuitionShadowError::Invalid(format!(
            "{label} must contain 1..={max_bytes} non-control bytes"
        )));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::IntuitionAbstainReason;
    use super::IntuitionCandidate;
    use super::IntuitionDecision;
    use super::IntuitionMode;
    use super::IntuitionShadowError;
    use super::IntuitionShadowInput;
    use super::intuition_schema_digest;
    use super::shadow_intuition_decide;
    use codex_hepta_contracts::Sha256Digest;

    fn input(candidates: Vec<IntuitionCandidate>) -> IntuitionShadowInput {
        IntuitionShadowInput {
            snapshot_digest: Sha256Digest::for_bytes(b"kg-snapshot:v1"),
            schema_digest: intuition_schema_digest(),
            policy_digest: Sha256Digest::for_bytes(b"policy:v1"),
            authority_epoch: 7,
            mode: IntuitionMode::SuggestOnly,
            max_risk_bps: 7_000,
            min_confidence_bps: 5_000,
            require_evidence: true,
            candidates,
        }
    }

    fn candidate(id: &str, score: u16, risk: u16, evidence: bool) -> IntuitionCandidate {
        IntuitionCandidate::new(id, score, risk, vec![IntuitionMode::SuggestOnly], evidence)
            .expect("valid candidate")
    }

    #[test]
    fn hard_filters_run_before_deterministic_tie_break() {
        let first = input(vec![
            candidate("zeta", 8_000, 3_000, true),
            candidate("alpha", 8_000, 3_000, true),
            candidate("unsafe", 9_900, 9_000, true),
            candidate("missing-evidence", 9_800, 1_000, false),
        ]);
        let mut second = first.clone();
        second.candidates.reverse();
        let first_receipt = shadow_intuition_decide(&first).expect("decision");
        let second_receipt = shadow_intuition_decide(&second).expect("decision");
        assert_eq!(first_receipt, second_receipt);
        assert!(matches!(
            first_receipt.decision,
            IntuitionDecision::Suggested {
                ref candidate_id,
                confidence_bps: 8_000
            } if candidate_id == "alpha"
        ));
        assert!(first_receipt.is_shadow_only());
    }

    #[test]
    fn no_eligible_candidate_is_an_explicit_abstain() {
        let input = IntuitionShadowInput {
            mode: IntuitionMode::PrepareOnly,
            ..input(vec![candidate("suggest", 9_000, 1_000, true)])
        };
        let receipt = shadow_intuition_decide(&input).expect("decision");
        assert!(matches!(
            receipt.decision,
            IntuitionDecision::Abstained {
                reason: IntuitionAbstainReason::NoEligibleCandidates
            }
        ));
    }

    #[test]
    fn low_confidence_abstains_after_filtering() {
        let mut input = input(vec![candidate("weak", 4_999, 1_000, true)]);
        input.min_confidence_bps = 5_000;
        let receipt = shadow_intuition_decide(&input).expect("decision");
        assert!(matches!(
            receipt.decision,
            IntuitionDecision::Abstained {
                reason: IntuitionAbstainReason::ConfidenceBelowThreshold
            }
        ));
    }

    #[test]
    fn snapshot_policy_and_schema_bindings_reject_tampering() {
        let input = input(vec![candidate("alpha", 8_000, 1_000, true)]);
        let mut receipt = shadow_intuition_decide(&input).expect("decision");
        receipt.policy_digest = Sha256Digest::for_bytes(b"other-policy");
        assert!(matches!(
            receipt.validate_against(&input),
            Err(IntuitionShadowError::DigestMismatch) | Err(IntuitionShadowError::BindingMismatch)
        ));
        let mut bad_schema = input;
        bad_schema.schema_digest = Sha256Digest::for_bytes(b"future-schema");
        assert_eq!(
            shadow_intuition_decide(&bad_schema),
            Err(IntuitionShadowError::SchemaMismatch)
        );
    }

    #[test]
    fn recomputation_rejects_a_self_consistent_but_wrong_decision() {
        let input = input(vec![candidate("alpha", 8_000, 1_000, true)]);
        let mut receipt = shadow_intuition_decide(&input).expect("decision");
        receipt.decision = IntuitionDecision::Suggested {
            candidate_id: "not-a-candidate".to_string(),
            confidence_bps: 8_000,
        };
        receipt.receipt_digest = super::receipt_digest(&receipt);
        assert_eq!(
            receipt.validate_against(&input),
            Err(IntuitionShadowError::BindingMismatch)
        );
    }

    #[test]
    fn receipt_negative_authority_flags_are_fail_closed() {
        let input = input(vec![candidate("alpha", 8_000, 1_000, true)]);
        let mut receipt = shadow_intuition_decide(&input).expect("decision");
        receipt.execute_allowed = true;
        assert_eq!(
            receipt.validate(),
            Err(IntuitionShadowError::AuthorityBoundary)
        );
    }

    #[test]
    fn duplicate_candidate_ids_are_rejected() {
        let input = input(vec![
            candidate("same", 8_000, 1_000, true),
            candidate("same", 7_000, 1_000, true),
        ]);
        assert!(matches!(
            shadow_intuition_decide(&input),
            Err(IntuitionShadowError::Invalid(_))
        ));
    }
}
