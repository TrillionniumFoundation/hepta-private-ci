//! Versioned full-information execution on the existing fenced custody owner.
//! No behavior propensity is fabricated and no OpeRow is reinterpreted.

use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::AuthenticatedPairedRegistrationV1;
use crate::FinalHoldoutCasStoreV1;
use crate::FinalHoldoutJournalReceiptV1;
use crate::HoldoutUseDispositionV1;
use crate::PairedObservationCutV1;
use crate::PairedSupervisedErrorV1;
use crate::PairedSupervisedEstimateV1;
use crate::ProductEvaluationError;
use crate::ProductProviderErrorV1;
use crate::SignedEvaluationError;
use crate::paired_observation_cut_signing_payload_v1;
use crate::paired_supervised_estimate::estimate_paired_cut;
use crate::paired_supervised_host_clock::PairedHostClockV1;
use crate::product_runner::ProductEvaluationRunnerV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedPairedObservationCutV1 {
    pub cut: PairedObservationCutV1,
    pub observer_evidence: SignedLearningEvidenceV1,
}

/// Implemented by the original custody service. It releases exactly its
/// registered cohort after the existing owner has committed consumption.
pub trait PairedFinalHoldoutProviderV1 {
    fn manifest_digest(&mut self) -> Result<Digest32, ProductProviderErrorV1>;
    fn release_after_consumption(
        &mut self,
        receipt: &FinalHoldoutJournalReceiptV1,
    ) -> Result<SignedPairedObservationCutV1, ProductProviderErrorV1>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductPairedEvaluationReceiptV1 {
    pub(crate) registration: AuthenticatedPairedRegistrationV1,
    pub(crate) holdout: FinalHoldoutJournalReceiptV1,
    pub(crate) observations: SignedPairedObservationCutV1,
    pub(crate) estimate: PairedSupervisedEstimateV1,
    pub(crate) execution_digest: Digest32,
    pub(crate) support_digest: Digest32,
    pub(crate) confidence_digest: Digest32,
    receipt_seal: Digest32,
}

impl ProductPairedEvaluationReceiptV1 {
    #[must_use]
    pub fn estimate(&self) -> &PairedSupervisedEstimateV1 {
        &self.estimate
    }
    #[must_use]
    pub fn execution_digest(&self) -> Digest32 {
        self.execution_digest
    }
    #[must_use]
    pub fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }

    pub(crate) fn validate(&self) -> Result<(), PairedSupervisedErrorV1> {
        self.estimate.validate(&self.registration.plan)?;
        if self.estimate.original_cut != self.observations.cut
            || self.execution_digest != self.seal()
            || self.receipt_seal != self.execution_digest
        {
            return Err(PairedSupervisedErrorV1::Binding(
                "paired execution integrity",
            ));
        }
        let (support, confidence) = evidence_digests(&self.registration, &self.estimate);
        if support != self.support_digest || confidence != self.confidence_digest {
            return Err(PairedSupervisedErrorV1::Binding(
                "paired confidence/support integrity",
            ));
        }
        Ok(())
    }

    pub(crate) fn verify_current(
        &self,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
    ) -> Result<(), PairedSupervisedErrorV1> {
        self.validate()?;
        self.registration.verify_current(verifier, now)?;
        verify_cut(&self.registration, &self.observations, verifier, now)
    }

    fn seal(&self) -> Digest32 {
        let mut bytes = b"hepta.eval.paired-supervised.product-execution.v1".to_vec();
        for digest in [
            self.registration.plan.frozen.plan_digest,
            self.registration.binding.registration_digest,
            self.holdout.record_digest,
            self.holdout.head_digest,
            self.holdout.use_receipt.use_digest,
            self.estimate.evidence_digest,
            self.support_digest,
            self.confidence_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        for evidence in [
            &self.registration.generator_evidence,
            &self.registration.observer_evidence,
            &self.observations.observer_evidence,
        ] {
            bytes.extend_from_slice(Digest32::of_bytes(&evidence.signing_bytes()).as_array());
            bytes.extend_from_slice(&evidence.signature);
        }
        Digest32::of_bytes(&bytes)
    }
}

impl<S: FinalHoldoutCasStoreV1> ProductEvaluationRunnerV1<S> {
    pub fn evaluate_registered_paired_supervised<P: PairedFinalHoldoutProviderV1>(
        &mut self,
        registration: &AuthenticatedPairedRegistrationV1,
        provider: &mut P,
        trust: &ActivatedLearningTrustV1,
    ) -> Result<ProductPairedEvaluationReceiptV1, PairedSupervisedErrorV1> {
        self.evaluate_paired_with_clock(
            registration,
            provider,
            trust,
            &mut PairedHostClockV1::system(),
        )
    }

    pub(crate) fn evaluate_paired_with_clock<P: PairedFinalHoldoutProviderV1>(
        &mut self,
        registration: &AuthenticatedPairedRegistrationV1,
        provider: &mut P,
        trust: &ActivatedLearningTrustV1,
        clock: &mut PairedHostClockV1,
    ) -> Result<ProductPairedEvaluationReceiptV1, PairedSupervisedErrorV1> {
        // No provider metadata access or CAS mutation precedes original G/O
        // signature, controller, epoch, revocation and expiration checks.
        clock.sample_registered(trust, registration)?;
        let manifest = provider
            .manifest_digest()
            .map_err(ProductEvaluationError::from)?;
        if manifest != registration.plan.frozen.final_holdout_digest {
            return Err(PairedSupervisedErrorV1::Binding(
                "paired final holdout manifest",
            ));
        }
        // Provider metadata I/O cannot carry a formerly valid root across the
        // actual CAS invocation. Recheck the original registration and clock.
        clock.sample_registered(trust, registration)?;
        let holdout = self.consume_profile_holdout(&registration.plan.frozen)?;
        // The consumed obligation survives every later error. A failed attempt
        // cannot reopen gold or substitute a new observation on replay.
        if holdout.disposition == HoldoutUseDispositionV1::IdempotentReplay {
            return Err(PairedSupervisedErrorV1::Binding(
                "consumed paired holdout requires original receipt",
            ));
        }
        clock.sample_registered(trust, registration)?;
        let observations = provider
            .release_after_consumption(&holdout)
            .map_err(ProductEvaluationError::from)?;
        let now = clock.sample_registered(trust, registration)?;
        verify_cut(registration, &observations, trust.verifier(), now)?;
        let estimate = estimate_paired_cut(&registration.plan, &observations.cut)?;
        let (support_digest, confidence_digest) = evidence_digests(registration, &estimate);
        let mut receipt = ProductPairedEvaluationReceiptV1 {
            registration: registration.clone(),
            holdout,
            observations,
            estimate,
            execution_digest: Digest32::ZERO,
            support_digest,
            confidence_digest,
            receipt_seal: Digest32::ZERO,
        };
        receipt.execution_digest = receipt.seal();
        receipt.receipt_seal = receipt.execution_digest;
        receipt.validate()?;
        Ok(receipt)
    }
}

fn verify_cut(
    registration: &AuthenticatedPairedRegistrationV1,
    observations: &SignedPairedObservationCutV1,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<(), PairedSupervisedErrorV1> {
    let cut = &observations.cut;
    let now_micros = now
        .checked_mul(1_000)
        .and_then(|v| v.checked_add(999))
        .ok_or(PairedSupervisedErrorV1::Arithmetic)?;
    if cut.started_at_unix_micros <= registration.binding.registered_at_unix_micros
        || cut.finished_at_unix_micros > now_micros
        || observations.observer_evidence.issued_at < cut.finished_at_unix_micros / 1_000
        || observations.observer_evidence.objective_digest
            != registration.plan.frozen.objective_digest
    {
        return Err(PairedSupervisedErrorV1::Binding(
            "paired actual execution clock/objective",
        ));
    }
    let observer = verifier
        .verify(
            LearningEvidenceRoleV1::Observer,
            &observations.observer_evidence,
            &paired_observation_cut_signing_payload_v1(cut)?,
            now,
        )
        .map_err(SignedEvaluationError::from)?;
    if observer.principal() != &registration.observer {
        return Err(PairedSupervisedErrorV1::Binding(
            "paired cut custody changed",
        ));
    }
    Ok(())
}

fn evidence_digests(
    registration: &AuthenticatedPairedRegistrationV1,
    estimate: &PairedSupervisedEstimateV1,
) -> (Digest32, Digest32) {
    let mut support = b"hepta.eval.paired-supervised.support-audit.v1".to_vec();
    support.extend_from_slice(registration.plan.profile_digest().as_array());
    support.extend_from_slice(estimate.evidence_digest.as_array());
    support.extend_from_slice(&(estimate.cluster_count as u64).to_be_bytes());
    support.extend_from_slice(&(estimate.largest_cluster_tasks as u64).to_be_bytes());
    let mut confidence = b"hepta.eval.paired-supervised.cluster-hoeffding.v1".to_vec();
    confidence.extend_from_slice(&registration.plan.frozen.family_alpha_ppm.to_be_bytes());
    confidence.extend_from_slice(
        &registration
            .plan
            .frozen
            .simultaneous_comparisons
            .to_be_bytes(),
    );
    confidence.extend_from_slice(Digest32::of_bytes(&support).as_array());
    (
        Digest32::of_bytes(&support),
        Digest32::of_bytes(&confidence),
    )
}
