//! Retained owner-verified authentication for current receipt consumption.
//!
//! Immutable trust digests do not change when a scheduled revocation becomes
//! effective. Keep the verifier's sealed evidence values, including their
//! lifetime and scheduled revocation, rather than only asserted principals.

use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use codex_hepta_learning_ledger::verify_signed_role_separation;

use crate::IndependentEvaluationBundleV1;
use crate::MetricRoleContractV2;
use crate::ProductTimingEvidenceV1;
use crate::SignedEvaluationError;
use crate::SignedEvaluationEvidenceV1;
use crate::evaluation_signing_payload_v2;
use crate::future_window_signing_payload_v1;
use crate::longitudinal_evaluation_signing_payload_v3;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) struct ProductQualificationAuthenticationV1 {
    generator: VerifiedLearningEvidenceV1,
    evaluator: VerifiedLearningEvidenceV1,
    observer: Option<VerifiedLearningEvidenceV1>,
}

impl ProductQualificationAuthenticationV1 {
    pub(super) fn capture(
        bundle: &IndependentEvaluationBundleV1,
        roles: &[MetricRoleContractV2],
        evidence: &SignedEvaluationEvidenceV1,
        timing: &ProductTimingEvidenceV1<'_>,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
    ) -> Result<Self, SignedEvaluationError> {
        let generator = verifier.verify(
            LearningEvidenceRoleV1::Generator,
            &evidence.generator_plan,
            bundle.frozen_plan.plan_digest.as_array(),
            now,
        )?;
        let (payload, observer) = match timing {
            ProductTimingEvidenceV1::Qualification => {
                (evaluation_signing_payload_v2(bundle, roles)?, None)
            }
            ProductTimingEvidenceV1::SystemLongitudinal {
                timing,
                minimum_window_micros,
            } => {
                let observer = verifier.verify(
                    LearningEvidenceRoleV1::Observer,
                    &timing.observer,
                    &future_window_signing_payload_v1(bundle, timing, *minimum_window_micros)?,
                    now,
                )?;
                (
                    longitudinal_evaluation_signing_payload_v3(
                        bundle,
                        roles,
                        timing,
                        *minimum_window_micros,
                    )?,
                    Some(observer),
                )
            }
        };
        let evaluator = verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            &evidence.evaluator_bundle,
            &payload,
            now,
        )?;
        let authentication = Self {
            generator,
            evaluator,
            observer,
        };
        authentication.validate_current(verifier, now)?;
        Ok(authentication)
    }

    pub(super) fn validate_current(
        &self,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
    ) -> Result<(), SignedEvaluationError> {
        for evidence in [&self.generator, &self.evaluator]
            .into_iter()
            .chain(self.observer.iter())
        {
            if evidence.trust_digest() != verifier.trust_digest() {
                return Err(SignedEvidenceError::ContextMismatch.into());
            }
        }
        verify_signed_role_separation(&self.generator, &self.evaluator, now)?;
        if let Some(observer) = &self.observer {
            verify_signed_role_separation(&self.generator, observer, now)?;
            verify_signed_actor_separation(&self.evaluator, observer, now)?;
        }
        Ok(())
    }
}
