//! Original Generator/Observer registration, rechecked before custody access.

use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_independent_roles_v1;
use codex_hepta_types::Digest32;

use crate::PairedSupervisedErrorV1;
use crate::PairedSupervisedPlanV1;
use crate::ProductRegistrationBindingV1;
use crate::SignedEvaluationError;

/// Observer signs a durable registration with the complete graph and installed
/// comparator pins. This is distinct from both OPE registration and final cut.
pub fn paired_registration_signing_payload_v1(
    plan: &PairedSupervisedPlanV1,
    binding: &ProductRegistrationBindingV1,
) -> Result<Vec<u8>, PairedSupervisedErrorV1> {
    plan.validate()?;
    let mut bytes = b"hepta.eval.paired-supervised.registered-plan.v1".to_vec();
    bytes.extend_from_slice(plan.profile_digest().as_array());
    bytes.extend_from_slice(&crate::product_registration_signing_payload_v1(binding));
    Ok(bytes)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedPairedRegistrationV1 {
    pub(crate) plan: PairedSupervisedPlanV1,
    pub(crate) binding: ProductRegistrationBindingV1,
    pub(crate) generator: AuthenticatedPrincipalV1,
    pub(crate) observer: AuthenticatedPrincipalV1,
    pub(crate) generator_evidence: SignedLearningEvidenceV1,
    pub(crate) observer_evidence: SignedLearningEvidenceV1,
    trust_digest: Digest32,
}

impl AuthenticatedPairedRegistrationV1 {
    pub fn verify(
        plan: &PairedSupervisedPlanV1,
        binding: ProductRegistrationBindingV1,
        generator_evidence: &SignedLearningEvidenceV1,
        observer_evidence: &SignedLearningEvidenceV1,
        verifier: &LearningEvidenceVerifierV1,
        now_unix_millis: u64,
    ) -> Result<Self, PairedSupervisedErrorV1> {
        plan.validate()?;
        let now_micros = now_unix_millis
            .checked_mul(1_000)
            .and_then(|value| value.checked_add(999))
            .ok_or(PairedSupervisedErrorV1::Arithmetic)?;
        let frozen = plan.frozen_plan();
        if binding.registration_digest.is_zero()
            || binding.source_graph_digest != plan.source_graph_digest()
            || binding.deployed_baseline_digest != plan.runtime.deployed_baseline_digest
            || binding.objective_digest != frozen.objective_digest
            || binding.dataset_digest != frozen.dataset_digest
            || binding.plan_digest != frozen.plan_digest
            || binding.final_holdout_digest != frozen.final_holdout_digest
            || binding.registered_at_unix_micros == 0
            || binding.registered_at_unix_micros > now_micros
            || generator_evidence.objective_digest != frozen.objective_digest
            || observer_evidence.objective_digest != frozen.objective_digest
            || generator_evidence
                .issued_at
                .checked_mul(1_000)
                .is_none_or(|issued| issued > binding.registered_at_unix_micros)
            || observer_evidence.issued_at < binding.registered_at_unix_micros / 1_000
        {
            return Err(PairedSupervisedErrorV1::Binding(
                "paired original registration",
            ));
        }
        let generator = verifier
            .verify(
                LearningEvidenceRoleV1::Generator,
                generator_evidence,
                frozen.plan_digest.as_array(),
                now_unix_millis,
            )
            .map_err(SignedEvaluationError::from)?;
        let observer = verifier
            .verify(
                LearningEvidenceRoleV1::Observer,
                observer_evidence,
                &paired_registration_signing_payload_v1(plan, &binding)?,
                now_unix_millis,
            )
            .map_err(SignedEvaluationError::from)?;
        verify_signed_independent_roles_v1(&generator, &observer, now_unix_millis)
            .map_err(SignedEvaluationError::from)?;
        Ok(Self {
            plan: plan.clone(),
            binding,
            generator: generator.principal().clone(),
            observer: observer.principal().clone(),
            generator_evidence: generator_evidence.clone(),
            observer_evidence: observer_evidence.clone(),
            trust_digest: verifier.trust_digest(),
        })
    }

    pub(crate) fn verify_current(
        &self,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
    ) -> Result<(), PairedSupervisedErrorV1> {
        if verifier.trust_digest() != self.trust_digest {
            return Err(PairedSupervisedErrorV1::Binding(
                "paired registration trust changed",
            ));
        }
        let current = Self::verify(
            &self.plan,
            self.binding.clone(),
            &self.generator_evidence,
            &self.observer_evidence,
            verifier,
            now,
        )?;
        if &current != self {
            return Err(PairedSupervisedErrorV1::Binding(
                "paired registration changed",
            ));
        }
        Ok(())
    }

    #[must_use]
    pub fn plan(&self) -> &PairedSupervisedPlanV1 {
        &self.plan
    }
    #[must_use]
    pub fn binding(&self) -> &ProductRegistrationBindingV1 {
        &self.binding
    }
    #[must_use]
    pub fn generator(&self) -> &AuthenticatedPrincipalV1 {
        &self.generator
    }
}
