//! A distinct entry to the same existing holdout owner.
//! No OPE ingress, evidence role, signature or qualification rule is relaxed.
use crate::FencedFinalHoldoutOwnerV1;
use crate::FencedHoldoutError;
use crate::FinalHoldoutCasStoreV1;
use crate::ProductEvidenceSinkErrorV1;
use crate::ProductProviderErrorV1;
use crate::holdout_envelope::PairedHoldoutJournalReceiptV1;
use crate::paired_data::PairedBoundedIntervalV1;
use crate::paired_data::PairedDataV1;
use crate::paired_data::PairedManifestV1;
use crate::paired_data::PairedStatisticsV1;
use crate::paired_plan::FrozenPairedPlanV1;
use crate::paired_plan::PairedProfileError;
use crate::paired_plan::seal;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_independent_roles_v1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PairedEvaluationError {
    Profile(PairedProfileError),
    Holdout(FencedHoldoutError),
    Provider(ProductProviderErrorV1),
    Signed(SignedEvidenceError),
    Publication(ProductEvidenceSinkErrorV1),
}
impl std::fmt::Display for PairedEvaluationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for PairedEvaluationError {}
fn invalid(s: &'static str) -> PairedEvaluationError {
    PairedEvaluationError::Profile(PairedProfileError(s))
}

pub trait PairedFinalHoldoutProviderV1 {
    /// Metadata only: canonical source cohort and exact already escrowed bundle.
    fn identities(&mut self) -> Result<(Digest32, Digest32), ProductProviderErrorV1>;
    /// May release observations only after the existing authoritative CAS succeeds.
    /// Exact idempotent retries must return the same frozen bundle.
    fn release_after_consumption(
        &mut self,
        receipt: &PairedHoldoutJournalReceiptV1,
    ) -> Result<(PairedDataV1, SignedLearningEvidenceV1), ProductProviderErrorV1>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairedEvaluationReceiptV1 {
    pub holdout: PairedHoldoutJournalReceiptV1,
    pub statistics: PairedStatisticsV1,
    pub outcome_bundle_digest: Digest32,
    pub execution_digest: Digest32,
    pub authority: AuthorityPosture,
    receipt_seal: Digest32,
}
impl PairedEvaluationReceiptV1 {
    pub fn validate(&self) -> Result<(), PairedEvaluationError> {
        self.holdout
            .validate(&self.holdout.plan)
            .map_err(|_| invalid("holdout receipt seal"))?;
        if self.authority.grants_any()
            || self.outcome_bundle_digest != self.holdout.plan.spec().outcome_bundle_digest
            || self.execution_digest != Digest32::of_bytes(&receipt_body(self))
            || self.receipt_seal
                != seal(
                    b"hepta.paired-full-information.evaluation-seal.v1",
                    &[self.execution_digest],
                )
        {
            return Err(invalid("derived paired receipt"));
        }
        Ok(())
    }
    pub fn grants_qualification_or_promotion(&self) -> bool {
        false
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedPairedEvaluationV1 {
    pub evaluation: PairedEvaluationReceiptV1,
    pub generator_plan: SignedLearningEvidenceV1,
    pub observer_outcomes: SignedLearningEvidenceV1,
    pub evaluator_receipt: SignedLearningEvidenceV1,
    pub trust_digest: Digest32,
    pub authentication_digest: Digest32,
}
impl SignedPairedEvaluationV1 {
    /// Receivers revalidate against their own immutable host trust snapshot.
    pub fn validate(
        &self,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
    ) -> Result<(), PairedEvaluationError> {
        self.evaluation.validate()?;
        let plan = &self.evaluation.holdout.plan;
        if verifier.objective_digest() != plan.spec().objective_digest
            || self.trust_digest != verifier.trust_digest()
        {
            return Err(invalid("signed objective/trust binding"));
        }
        let specs = [
            (
                LearningEvidenceRoleV1::Generator,
                &self.generator_plan,
                paired_plan_signing_payload_v1(plan).map_err(PairedEvaluationError::Profile)?,
            ),
            (
                LearningEvidenceRoleV1::Observer,
                &self.observer_outcomes,
                paired_observation_signing_payload_v1(plan)
                    .map_err(PairedEvaluationError::Profile)?,
            ),
            (
                LearningEvidenceRoleV1::Evaluator,
                &self.evaluator_receipt,
                paired_evaluation_signing_payload_v1(&self.evaluation)?,
            ),
        ];
        let mut admitted = Vec::new();
        for (role, evidence, payload) in specs {
            admitted.push(
                verifier
                    .verify(role, evidence, &payload, now)
                    .map_err(PairedEvaluationError::Signed)?,
            );
        }
        for (a, b) in [(0, 1), (0, 2), (1, 2)] {
            verify_signed_independent_roles_v1(&admitted[a], &admitted[b], now)
                .map_err(PairedEvaluationError::Signed)?;
        }
        if self.authentication_digest
            != authentication_digest(
                verifier,
                [
                    &self.generator_plan,
                    &self.observer_outcomes,
                    &self.evaluator_receipt,
                ],
            )
        {
            return Err(invalid("authentication receipt"));
        }
        Ok(())
    }
}
pub trait PairedEvaluationEvidenceSinkV1 {
    /// Same host evidence owner, but an explicitly distinct payload profile.
    /// Nonzero digest only after durable publication; reject/uncertain writes fail.
    fn persist_paired(
        &mut self,
        decision: &SignedPairedEvaluationV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1>;
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PublishedPairedEvaluationV1 {
    pub decision: SignedPairedEvaluationV1,
    pub publication_digest: Digest32,
    receipt_seal: Digest32,
}
impl PublishedPairedEvaluationV1 {
    pub fn validate(
        &self,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
    ) -> Result<(), PairedEvaluationError> {
        self.decision.validate(verifier, now)?;
        if self.publication_digest.is_zero()
            || self.receipt_seal != publication_seal(&self.decision, self.publication_digest)
        {
            return Err(invalid("publication receipt seal"));
        }
        Ok(())
    }
}

pub fn paired_plan_signing_payload_v1(
    plan: &FrozenPairedPlanV1,
) -> Result<Vec<u8>, PairedProfileError> {
    plan.validate()?;
    Ok([
        b"hepta.paired-full-information.signed-plan.v1".as_slice(),
        plan.plan_digest().as_array(),
    ]
    .concat())
}
pub fn paired_observation_signing_payload_v1(
    plan: &FrozenPairedPlanV1,
) -> Result<Vec<u8>, PairedProfileError> {
    plan.validate()?;
    Ok([
        b"hepta.paired-full-information.signed-observations.v1".as_slice(),
        plan.plan_digest().as_array(),
        plan.spec().outcome_bundle_digest.as_array(),
        plan.spec().audit_observer_digest.as_array(),
    ]
    .concat())
}
pub fn paired_evaluation_signing_payload_v1(
    receipt: &PairedEvaluationReceiptV1,
) -> Result<Vec<u8>, PairedEvaluationError> {
    receipt.validate()?;
    Ok([
        b"hepta.paired-full-information.signed-evaluation.v1".as_slice(),
        receipt.execution_digest.as_array(),
    ]
    .concat())
}

/// All data-dependent evaluation starts AFTER consume_paired. This is the same
/// FencedFinalHoldoutOwnerV1 instance/binding used by the existing OPE runner.
/// The first profile accepts only previously observed engineering evidence.
#[allow(clippy::too_many_arguments)]
pub fn evaluate_paired_full_information_v1<S, P, E, F>(
    owner: &mut FencedFinalHoldoutOwnerV1<S>,
    plan: &FrozenPairedPlanV1,
    manifest: &PairedManifestV1,
    provider: &mut P,
    generator_plan: &SignedLearningEvidenceV1,
    verifier: &LearningEvidenceVerifierV1,
    evaluator_attest: F,
    sink: &mut E,
    now: u64,
) -> Result<PublishedPairedEvaluationV1, PairedEvaluationError>
where
    S: FinalHoldoutCasStoreV1,
    P: PairedFinalHoldoutProviderV1,
    E: PairedEvaluationEvidenceSinkV1,
    F: FnOnce(&PairedEvaluationReceiptV1) -> Result<SignedLearningEvidenceV1, SignedEvidenceError>,
{
    manifest
        .validate(plan)
        .map_err(PairedEvaluationError::Profile)?;
    let spec = plan.spec();
    if provider
        .identities()
        .map_err(PairedEvaluationError::Provider)?
        != (spec.holdout_digest, spec.outcome_bundle_digest)
        || generator_plan.objective_digest != spec.objective_digest
    {
        return Err(invalid("escrow or objective identity"));
    }
    let generator = verifier
        .verify(
            LearningEvidenceRoleV1::Generator,
            generator_plan,
            &paired_plan_signing_payload_v1(plan).map_err(PairedEvaluationError::Profile)?,
            now,
        )
        .map_err(PairedEvaluationError::Signed)?;

    // Existing CAS/journal commits first. Rejection, conflict or indeterminate
    // commits return before the provider is invoked; no parallel release path.
    let holdout = owner
        .consume_paired(plan)
        .map_err(PairedEvaluationError::Holdout)?;
    let (data, observer_outcomes) = provider
        .release_after_consumption(&holdout)
        .map_err(PairedEvaluationError::Provider)?;
    if &data.manifest != manifest {
        return Err(invalid("released manifest changed"));
    }
    let statistics = data.derive(plan).map_err(PairedEvaluationError::Profile)?;
    let observer = verifier
        .verify(
            LearningEvidenceRoleV1::Observer,
            &observer_outcomes,
            &paired_observation_signing_payload_v1(plan).map_err(PairedEvaluationError::Profile)?,
            now,
        )
        .map_err(PairedEvaluationError::Signed)?;
    verify_signed_independent_roles_v1(&generator, &observer, now)
        .map_err(PairedEvaluationError::Signed)?;
    let mut evaluation = PairedEvaluationReceiptV1 {
        holdout,
        statistics,
        outcome_bundle_digest: spec.outcome_bundle_digest,
        execution_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
        receipt_seal: Digest32::ZERO,
    };
    evaluation.execution_digest = Digest32::of_bytes(&receipt_body(&evaluation));
    evaluation.receipt_seal = seal(
        b"hepta.paired-full-information.evaluation-seal.v1",
        &[evaluation.execution_digest],
    );
    let evaluator_receipt = evaluator_attest(&evaluation).map_err(PairedEvaluationError::Signed)?;
    let evaluator = verifier
        .verify(
            LearningEvidenceRoleV1::Evaluator,
            &evaluator_receipt,
            &paired_evaluation_signing_payload_v1(&evaluation)?,
            now,
        )
        .map_err(PairedEvaluationError::Signed)?;
    for other in [&generator, &observer] {
        verify_signed_independent_roles_v1(other, &evaluator, now)
            .map_err(PairedEvaluationError::Signed)?;
    }
    let authentication_digest = authentication_digest(
        verifier,
        [generator_plan, &observer_outcomes, &evaluator_receipt],
    );
    let decision = SignedPairedEvaluationV1 {
        evaluation,
        generator_plan: generator_plan.clone(),
        observer_outcomes,
        evaluator_receipt,
        trust_digest: verifier.trust_digest(),
        authentication_digest,
    };
    decision.validate(verifier, now)?;
    let publication_digest = sink
        .persist_paired(&decision)
        .map_err(PairedEvaluationError::Publication)?;
    if publication_digest.is_zero() {
        return Err(invalid("noncommitted publication"));
    }
    let receipt_seal = publication_seal(&decision, publication_digest);
    Ok(PublishedPairedEvaluationV1 {
        decision,
        publication_digest,
        receipt_seal,
    })
}

fn authentication_digest(
    verifier: &LearningEvidenceVerifierV1,
    evidence: [&SignedLearningEvidenceV1; 3],
) -> Digest32 {
    let mut bytes = b"hepta.paired-full-information.authentication.v1".to_vec();
    bytes.extend_from_slice(verifier.trust_digest().as_array());
    for signed in evidence {
        bytes.extend_from_slice(Digest32::of_bytes(&signed.signing_bytes()).as_array());
        bytes.extend_from_slice(&signed.signature);
    }
    Digest32::of_bytes(&bytes)
}
fn publication_seal(decision: &SignedPairedEvaluationV1, publication: Digest32) -> Digest32 {
    seal(
        b"hepta.paired-full-information.publication-seal.v1",
        &[
            decision.evaluation.execution_digest,
            decision.authentication_digest,
            publication,
        ],
    )
}

fn receipt_body(r: &PairedEvaluationReceiptV1) -> Vec<u8> {
    let mut bytes = b"hepta.paired-full-information.derived-statistics.v1".to_vec();
    for digest in [
        r.holdout.plan.plan_digest(),
        r.holdout.record_digest,
        r.outcome_bundle_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&r.holdout.sequence.to_be_bytes());
    // Current head and idempotent status are transport context; they may change
    // after later unrelated consumption. Original record/sequence stay stable.
    let s = &r.statistics;
    for count in [
        s.source_cases,
        s.fixed_seeds,
        s.candidate_complete,
        s.baseline_complete,
    ] {
        bytes.extend_from_slice(&count.to_be_bytes());
    }
    for interval in [&s.loss_difference, &s.factual_error_difference] {
        push_interval(&mut bytes, interval);
    }
    bytes.push(u8::from(s.observed_thresholds_pass));
    bytes
}
fn push_interval(bytes: &mut Vec<u8>, value: &Option<PairedBoundedIntervalV1>) {
    bytes.push(u8::from(value.is_some()));
    if let Some(value) = value {
        for q in [
            value.mean_floor,
            value.mean_ceiling,
            value.lower,
            value.upper,
            value.conservative_radius,
        ] {
            bytes.extend_from_slice(&q.raw().to_be_bytes());
        }
    }
}

#[cfg(test)]
#[path = "paired_runner_tests.rs"]
mod tests;
