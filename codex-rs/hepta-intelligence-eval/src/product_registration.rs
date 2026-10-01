//! Verify the registered generator plan before any holdout consumption/release.
//! The custody host owns the immutable registration and trusted event clock.

use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_independent_roles_v1;
use codex_hepta_types::Digest32;

use crate::EvaluationClaimScopeV1;
use crate::FinalHoldoutCasStoreV1;
use crate::FinalHoldoutProviderV1;
use crate::ProductEvaluationError;
use crate::ProductFrozenEvaluationPlanV1;
use crate::ProductTemporalEvaluationReceiptV1;
use crate::SignedEvaluationError;
use crate::TemporalEvaluationPlan;
use crate::product_runner::ProductEvaluationRunnerV1;

/// Values from the custody owner's durable, immutable plan registration.
/// These are neither filesystem timestamps nor caller-selected future dates.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductRegistrationBindingV1 {
    pub registration_digest: Digest32,
    pub source_graph_digest: Digest32,
    pub deployed_baseline_digest: Digest32,
    pub objective_digest: Digest32,
    pub dataset_digest: Digest32,
    pub plan_digest: Digest32,
    pub final_holdout_digest: Digest32,
    pub registered_at_unix_micros: u64,
}

impl<S: FinalHoldoutCasStoreV1> ProductEvaluationRunnerV1<S> {
    /// Host ingress: reauthenticate both the Generator's exact frozen plan and
    /// the independent custody registration before even consulting a provider.
    /// The lower-level estimator remains reusable; external hosts use this path.
    #[allow(clippy::too_many_arguments)]
    pub fn evaluate_registered_temporal_comparison<P: FinalHoldoutProviderV1>(
        &mut self,
        registration: &AuthenticatedProductRegistrationV1,
        candidate_plan: &TemporalEvaluationPlan,
        baseline_plan: &TemporalEvaluationPlan,
        provider: &mut P,
        verifier: &LearningEvidenceVerifierV1,
        now_unix_millis: u64,
    ) -> Result<ProductTemporalEvaluationReceiptV1, ProductEvaluationError> {
        registration.verify_current(verifier, now_unix_millis)?;
        self.evaluate_temporal_comparison(
            registration.plan(),
            candidate_plan,
            baseline_plan,
            provider,
        )
    }
}

/// Opaque pre-consumption authorization. It does not qualify a candidate and
/// cannot replace the independent evaluator's exact post-execution signature.
pub struct AuthenticatedProductRegistrationV1 {
    plan: ProductFrozenEvaluationPlanV1,
    binding: ProductRegistrationBindingV1,
    generator: AuthenticatedPrincipalV1,
    trust_digest: Digest32,
    generator_evidence: SignedLearningEvidenceV1,
    custody_evidence: SignedLearningEvidenceV1,
}

/// The existing custody Observer attests the exact durable registration,
/// including its source graph and actual deployed comparator. This attestation
/// does not establish scientific support or authorize release by itself.
pub fn product_registration_signing_payload_v1(binding: &ProductRegistrationBindingV1) -> Vec<u8> {
    let mut bytes = b"hepta.intelligence-eval.registered-product-plan.v1".to_vec();
    for digest in [
        binding.registration_digest,
        binding.source_graph_digest,
        binding.deployed_baseline_digest,
        binding.objective_digest,
        binding.dataset_digest,
        binding.plan_digest,
        binding.final_holdout_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&binding.registered_at_unix_micros.to_be_bytes());
    bytes
}

impl AuthenticatedProductRegistrationV1 {
    pub fn verify(
        plan: &ProductFrozenEvaluationPlanV1,
        binding: ProductRegistrationBindingV1,
        generator_evidence: &SignedLearningEvidenceV1,
        custody_evidence: &SignedLearningEvidenceV1,
        verifier: &LearningEvidenceVerifierV1,
        now_unix_millis: u64,
    ) -> Result<Self, ProductEvaluationError> {
        plan.validate_integrity()?;
        let frozen = &plan.frozen_plan;
        let now_micros = now_unix_millis
            .checked_mul(1_000)
            .and_then(|value| value.checked_add(999))
            .ok_or(ProductEvaluationError::Integrity("registration clock"))?;
        if [
            binding.registration_digest,
            binding.source_graph_digest,
            binding.deployed_baseline_digest,
        ]
        .into_iter()
        .any(Digest32::is_zero)
            || binding.registered_at_unix_micros == 0
            || binding.registered_at_unix_micros > now_micros
            || binding.objective_digest != frozen.objective_digest
            || binding.dataset_digest != frozen.dataset_digest
            || binding.plan_digest != frozen.plan_digest
            || binding.final_holdout_digest != frozen.final_holdout_digest
            || frozen.claim_scope != EvaluationClaimScopeV1::Qualification
            || generator_evidence.objective_digest != frozen.objective_digest
        {
            return Err(ProductEvaluationError::Binding("registered product plan"));
        }
        let generator = verifier
            .verify(
                LearningEvidenceRoleV1::Generator,
                generator_evidence,
                frozen.plan_digest.as_array(),
                now_unix_millis,
            )
            .map_err(SignedEvaluationError::from)?;
        let custody = verifier
            .verify(
                LearningEvidenceRoleV1::Observer,
                custody_evidence,
                &product_registration_signing_payload_v1(&binding),
                now_unix_millis,
            )
            .map_err(SignedEvaluationError::from)?;
        verify_signed_independent_roles_v1(&generator, &custody, now_unix_millis)
            .map_err(SignedEvaluationError::from)?;
        if generator_evidence
            .issued_at
            .checked_mul(1_000)
            .is_none_or(|issued_at| issued_at > binding.registered_at_unix_micros)
        {
            return Err(ProductEvaluationError::Binding(
                "plan signature after registration",
            ));
        }
        if custody_evidence.objective_digest != frozen.objective_digest
            // Evidence clocks have millisecond precision. The Observer signs
            // the exact registration microseconds and actual ordering; do not
            // falsely reject a legitimate signature from the same clock bucket.
            || custody_evidence.issued_at < binding.registered_at_unix_micros / 1_000
        {
            return Err(ProductEvaluationError::Binding(
                "custody registration clock",
            ));
        }
        Ok(Self {
            plan: plan.clone(),
            binding,
            generator: generator.principal().clone(),
            trust_digest: verifier.trust_digest(),
            generator_evidence: generator_evidence.clone(),
            custody_evidence: custody_evidence.clone(),
        })
    }

    pub(crate) fn verify_current(
        &self,
        verifier: &LearningEvidenceVerifierV1,
        now_unix_millis: u64,
    ) -> Result<(), ProductEvaluationError> {
        if verifier.trust_digest() != self.trust_digest {
            return Err(ProductEvaluationError::Binding(
                "registration trust changed",
            ));
        }
        let current = verifier
            .verify(
                LearningEvidenceRoleV1::Generator,
                &self.generator_evidence,
                self.plan.frozen_plan.plan_digest.as_array(),
                now_unix_millis,
            )
            .map_err(SignedEvaluationError::from)?;
        let custody = verifier
            .verify(
                LearningEvidenceRoleV1::Observer,
                &self.custody_evidence,
                &product_registration_signing_payload_v1(&self.binding),
                now_unix_millis,
            )
            .map_err(SignedEvaluationError::from)?;
        verify_signed_independent_roles_v1(&current, &custody, now_unix_millis)
            .map_err(SignedEvaluationError::from)?;
        if current.principal() != &self.generator {
            return Err(ProductEvaluationError::Binding(
                "registered generator changed",
            ));
        }
        Ok(())
    }

    #[must_use]
    pub fn binding(&self) -> &ProductRegistrationBindingV1 {
        &self.binding
    }

    #[must_use]
    pub fn plan(&self) -> &ProductFrozenEvaluationPlanV1 {
        &self.plan
    }
}
