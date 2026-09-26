use std::ops::Deref;

use codex_hepta_prompt_registry::PromptModelTupleV2;
use codex_hepta_prompt_registry::PromptRegistry;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use super::raw;
use super::selection::VerifiedSelectedPromptPortfolioV1;
use super::types::CanonicalPromptError;
use super::types::PromptStaleReasonV1;
use super::types::ensure_digest;
use super::types::push_id;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExercisePolicyV1 {
    pub policy_id: StableId,
    pub objective_digest: Digest32,
    pub scope_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub allowed_boundaries: Vec<raw::PromptDecisionBoundaryV1>,
    pub minimum_exercise_margin_q32: FixedQ32,
    pub valid_from_unix_ms: u64,
    pub valid_until_unix_ms: u64,
}

impl PromptExercisePolicyV1 {
    pub fn digest(&self) -> Result<Digest32, CanonicalPromptError> {
        ensure_digest("exercise policy objective", self.objective_digest)?;
        ensure_digest("exercise policy scope", self.scope_digest)?;
        ensure_digest("exercise policy model tuple", self.model_tuple_digest)?;
        if self.allowed_boundaries.is_empty()
            || self.minimum_exercise_margin_q32 < FixedQ32::ZERO
            || self.valid_from_unix_ms == 0
            || self.valid_until_unix_ms <= self.valid_from_unix_ms
        {
            return Err(CanonicalPromptError::InvalidPolicy);
        }
        let mut previous = None;
        for boundary in &self.allowed_boundaries {
            let code = boundary_code(*boundary);
            if previous.is_some_and(|value| value >= code) {
                return Err(CanonicalPromptError::InvalidPolicy);
            }
            previous = Some(code);
        }
        let mut bytes = b"hepta.prompt-optimizer.exercise-policy.v2".to_vec();
        push_id(&mut bytes, &self.policy_id);
        for digest in [
            self.objective_digest,
            self.scope_digest,
            self.model_tuple_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(
            &u64::try_from(self.allowed_boundaries.len())
                .unwrap_or(u64::MAX)
                .to_be_bytes(),
        );
        for boundary in &self.allowed_boundaries {
            bytes.push(boundary_code(*boundary));
        }
        bytes.extend_from_slice(&self.minimum_exercise_margin_q32.raw().to_be_bytes());
        bytes.extend_from_slice(&self.valid_from_unix_ms.to_be_bytes());
        bytes.extend_from_slice(&self.valid_until_unix_ms.to_be_bytes());
        Ok(Digest32::of_bytes(&bytes))
    }

    fn permits(&self, boundary: raw::PromptDecisionBoundaryV1) -> bool {
        self.allowed_boundaries.contains(&boundary)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExerciseRequestV1 {
    pub decision_boundary: raw::PromptDecisionBoundaryV1,
    pub current_state_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub model_tuple: PromptModelTupleV2,
    pub current_graph_generation_digest: Digest32,
    pub current_graph_source_snapshot_digest: Digest32,
    pub current_graph_profile_digest: Digest32,
    pub current_trust_digest: Digest32,
    pub current_authority_epoch: u64,
    pub now_unix_ms: u64,
    pub wait_value_q32: FixedQ32,
    pub wait_value_evidence_digest: Digest32,
    pub policy: PromptExercisePolicyV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExerciseAuditV2 {
    pub portfolio_verification_digest: Digest32,
    pub policy_digest: Digest32,
    pub trust_digest: Digest32,
    pub authority_epoch: u64,
    pub graph_generation_digest: Digest32,
    pub graph_source_snapshot_digest: Digest32,
    pub graph_profile_digest: Digest32,
    pub wait_value_evidence_digest: Digest32,
    pub checked_at_unix_ms: u64,
    pub audit_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedPromptExerciseDecisionV1 {
    raw: raw::PromptExerciseDecisionV1,
    audit: PromptExerciseAuditV2,
    verification_digest: Digest32,
}

impl Deref for VerifiedPromptExerciseDecisionV1 {
    type Target = raw::PromptExerciseDecisionV1;

    fn deref(&self) -> &Self::Target {
        &self.raw
    }
}

impl VerifiedPromptExerciseDecisionV1 {
    pub fn audit(&self) -> &PromptExerciseAuditV2 {
        &self.audit
    }

    pub fn verification_digest(&self) -> Digest32 {
        self.verification_digest
    }

    pub(crate) fn as_raw(&self) -> &raw::PromptExerciseDecisionV1 {
        &self.raw
    }

    pub(crate) fn validate_seal(&self) -> Result<(), CanonicalPromptError> {
        if self.raw.authority.grants_any()
            || self.raw.receipt_digest
                != digest_exercise_receipt(
                    &self.raw.factor_or_portfolio_id,
                    self.raw.decision_boundary,
                    self.raw.exercise_now_value_q32,
                    self.raw.wait_value_q32,
                    self.raw.decision,
                    self.raw.policy_digest,
                    self.audit.portfolio_verification_digest,
                )
            || self.audit.audit_digest != exercise_audit_digest(&self.audit)
            || self.verification_digest
                != exercise_verification_digest(
                    self.raw.receipt_digest,
                    self.audit.audit_digest,
                )
        {
            return Err(CanonicalPromptError::Corrupt(
                "exercise decision seal".to_owned(),
            ));
        }
        Ok(())
    }
}

pub fn exercise_v1(
    registry: &PromptRegistry,
    portfolio: &VerifiedSelectedPromptPortfolioV1,
    request: PromptExerciseRequestV1,
) -> Result<VerifiedPromptExerciseDecisionV1, CanonicalPromptError> {
    portfolio.validate_seal()?;
    ensure_digest("exercise state", request.current_state_digest)?;
    ensure_digest("exercise generation vector", request.generation_vector_digest)?;
    ensure_digest(
        "exercise graph generation",
        request.current_graph_generation_digest,
    )?;
    ensure_digest(
        "exercise graph source snapshot",
        request.current_graph_source_snapshot_digest,
    )?;
    ensure_digest("exercise graph profile", request.current_graph_profile_digest)?;
    ensure_digest("exercise trust", request.current_trust_digest)?;
    ensure_digest("wait-value evidence", request.wait_value_evidence_digest)?;
    if request.now_unix_ms == 0 || request.current_authority_epoch == 0 {
        return Err(CanonicalPromptError::InvalidTime);
    }

    let policy_digest = request.policy.digest()?;
    if request.now_unix_ms < request.policy.valid_from_unix_ms
        || request.now_unix_ms >= request.policy.valid_until_unix_ms
        || !request.policy.permits(request.decision_boundary)
        || request.policy.objective_digest != portfolio.objective_digest
        || request.policy.scope_digest != portfolio.provenance().scope_digest
        || request.policy.model_tuple_digest != portfolio.model_tuple_digest
    {
        return Err(CanonicalPromptError::Stale(PromptStaleReasonV1::Policy));
    }
    if request.current_state_digest != portfolio.state_digest {
        return Err(CanonicalPromptError::Stale(PromptStaleReasonV1::State));
    }
    if request.generation_vector_digest != portfolio.generation_vector_digest {
        return Err(CanonicalPromptError::Stale(
            PromptStaleReasonV1::GenerationVector,
        ));
    }
    if request.model_tuple != portfolio.model_tuple
        || request.model_tuple.digest() != portfolio.model_tuple_digest
    {
        return Err(CanonicalPromptError::Stale(
            PromptStaleReasonV1::ModelTuple,
        ));
    }
    if request.current_graph_generation_digest != portfolio.graph_generation_digest
        || request.current_graph_source_snapshot_digest
            != portfolio.graph_source_snapshot_digest()
        || request.current_graph_profile_digest != portfolio.graph_profile_digest()
    {
        return Err(CanonicalPromptError::Stale(
            PromptStaleReasonV1::GraphGeneration,
        ));
    }
    if request.current_trust_digest != portfolio.provenance().trust_digest
        || request.current_authority_epoch != portfolio.provenance().authority_epoch
    {
        return Err(CanonicalPromptError::Stale(
            PromptStaleReasonV1::TrustSnapshot,
        ));
    }
    if request.now_unix_ms > portfolio.provenance().valid_until_unix_ms
        || request.now_unix_ms > portfolio.audit().evidence_valid_until_unix_ms
        || request.now_unix_ms > portfolio.graph_valid_until_unix_ms()
    {
        return Err(CanonicalPromptError::Stale(
            PromptStaleReasonV1::EvidenceExpired,
        ));
    }
    if request.now_unix_ms >= portfolio.receipt.valid_until_unix_ms {
        return Err(CanonicalPromptError::Stale(
            PromptStaleReasonV1::PortfolioExpired,
        ));
    }

    let mut raw_decision = raw::exercise_v1(
        registry,
        portfolio.as_raw(),
        raw::PromptExerciseRequestV1 {
            decision_boundary: request.decision_boundary,
            current_state_digest: request.current_state_digest,
            generation_vector_digest: request.generation_vector_digest,
            model_tuple: request.model_tuple,
            now_unix_ms: request.now_unix_ms,
            wait_value_q32: request.wait_value_q32,
            policy_digest,
        },
    )
    .map_err(CanonicalPromptError::from)?;
    if raw_decision.decision == raw::PromptExerciseActionV1::RejectStale {
        return Err(CanonicalPromptError::Stale(
            PromptStaleReasonV1::RegistryOrRealization,
        ));
    }
    let exercise_threshold = request
        .wait_value_q32
        .checked_add(request.policy.minimum_exercise_margin_q32)
        .map_err(|_| CanonicalPromptError::Arithmetic)?;
    if raw_decision.decision == raw::PromptExerciseActionV1::Exercise
        && raw_decision.exercise_now_value_q32 <= exercise_threshold
    {
        raw_decision.decision = raw::PromptExerciseActionV1::Wait;
        raw_decision.receipt_digest = digest_exercise_receipt(
            &raw_decision.factor_or_portfolio_id,
            raw_decision.decision_boundary,
            raw_decision.exercise_now_value_q32,
            raw_decision.wait_value_q32,
            raw_decision.decision,
            raw_decision.policy_digest,
            portfolio.receipt.receipt_digest,
        );
    }

    let mut audit = PromptExerciseAuditV2 {
        portfolio_verification_digest: portfolio.verification_digest(),
        policy_digest,
        trust_digest: request.current_trust_digest,
        authority_epoch: request.current_authority_epoch,
        graph_generation_digest: request.current_graph_generation_digest,
        graph_source_snapshot_digest: request.current_graph_source_snapshot_digest,
        graph_profile_digest: request.current_graph_profile_digest,
        wait_value_evidence_digest: request.wait_value_evidence_digest,
        checked_at_unix_ms: request.now_unix_ms,
        audit_digest: Digest32::ZERO,
    };
    audit.audit_digest = exercise_audit_digest(&audit);
    raw_decision.receipt_digest = digest_exercise_receipt(
        &raw_decision.factor_or_portfolio_id,
        raw_decision.decision_boundary,
        raw_decision.exercise_now_value_q32,
        raw_decision.wait_value_q32,
        raw_decision.decision,
        raw_decision.policy_digest,
        audit.portfolio_verification_digest,
    );
    let verification_digest =
        exercise_verification_digest(raw_decision.receipt_digest, audit.audit_digest);
    let result = VerifiedPromptExerciseDecisionV1 {
        raw: raw_decision,
        audit,
        verification_digest,
    };
    result.validate_seal()?;
    Ok(result)
}

fn exercise_audit_digest(audit: &PromptExerciseAuditV2) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.exercise-audit.v2".to_vec();
    for digest in [
        audit.portfolio_verification_digest,
        audit.policy_digest,
        audit.trust_digest,
        audit.graph_generation_digest,
        audit.graph_source_snapshot_digest,
        audit.graph_profile_digest,
        audit.wait_value_evidence_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&audit.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&audit.checked_at_unix_ms.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn exercise_verification_digest(receipt_digest: Digest32, audit_digest: Digest32) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.verified-exercise.v2".to_vec();
    bytes.extend_from_slice(receipt_digest.as_array());
    bytes.extend_from_slice(audit_digest.as_array());
    Digest32::of_bytes(&bytes)
}

#[allow(clippy::too_many_arguments)]
fn digest_exercise_receipt(
    portfolio_id: &StableId,
    boundary: raw::PromptDecisionBoundaryV1,
    exercise_now: FixedQ32,
    wait: FixedQ32,
    decision: raw::PromptExerciseActionV1,
    policy_digest: Digest32,
    portfolio_verification_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.exercise-receipt.v2".to_vec();
    push_id(&mut bytes, portfolio_id);
    bytes.push(boundary_code(boundary));
    bytes.extend_from_slice(&exercise_now.raw().to_be_bytes());
    bytes.extend_from_slice(&wait.raw().to_be_bytes());
    bytes.push(exercise_action_code(decision));
    bytes.extend_from_slice(policy_digest.as_array());
    bytes.extend_from_slice(portfolio_verification_digest.as_array());
    Digest32::of_bytes(&bytes)
}

pub(crate) const fn boundary_code(value: raw::PromptDecisionBoundaryV1) -> u8 {
    match value {
        raw::PromptDecisionBoundaryV1::RequestAccepted => 0,
        raw::PromptDecisionBoundaryV1::ObjectiveCompiled => 1,
        raw::PromptDecisionBoundaryV1::BeforePlanning => 2,
        raw::PromptDecisionBoundaryV1::BeforeCandidateGeneration => 3,
        raw::PromptDecisionBoundaryV1::BeforeModelOrToolDispatch => 4,
        raw::PromptDecisionBoundaryV1::AfterObservation => 5,
        raw::PromptDecisionBoundaryV1::AfterFailureOrUncertaintySpike => 6,
        raw::PromptDecisionBoundaryV1::BeforeIrreversibleMutation => 7,
        raw::PromptDecisionBoundaryV1::BeforeVerification => 8,
        raw::PromptDecisionBoundaryV1::BeforeFinalResponse => 9,
        raw::PromptDecisionBoundaryV1::BeforeCompactOrHandoff => 10,
    }
}

pub(crate) const fn exercise_action_code(value: raw::PromptExerciseActionV1) -> u8 {
    match value {
        raw::PromptExerciseActionV1::Exercise => 0,
        raw::PromptExerciseActionV1::Wait => 1,
        raw::PromptExerciseActionV1::RejectStale => 2,
        raw::PromptExerciseActionV1::NoIntervention => 3,
    }
}
