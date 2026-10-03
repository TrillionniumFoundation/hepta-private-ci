//! A rejected preparation must cover every actual generated Update with original
//! measured E output and the original protected custody completion/ACK.
use crate::fixed_parameter_no_change::HostResult;
use crate::fixed_parameter_no_change::hex;
use crate::fixed_parameter_no_change::unhex;
use crate::paired_review_transport::Publication;
use crate::*;
use codex_hepta_learning_ledger::*;
use codex_hepta_plasticity::*;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use std::collections::BTreeSet;
use std::path::PathBuf;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FixedParameterEvaluationSourceV1 {
    pub path: PathBuf,
    pub digest: String,
}
impl FixedParameterEvaluationSourceV1 {
    fn read(&self, maximum: u64) -> HostResult<Vec<u8>> {
        let bytes = read_root_review_input(&self.path, maximum)?;
        if Digest32::of_bytes(&bytes) != self.digest.parse()? {
            return Err("original completed parameter review source pin".into());
        }
        Ok(bytes)
    }
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FixedParameterCompletedReviewSourceV1 {
    pub publication: FixedParameterEvaluationSourceV1,
    pub result: FixedParameterEvaluationSourceV1,
    pub acknowledgement: FixedParameterEvaluationSourceV1,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Finished {
    schema: String,
    execution_digest: String,
    profile_digest: String,
    decision_digest: String,
    publication_digest: String,
    evidence_digest: String,
    eligible_for_independent_selection: bool,
    original_full_sink_acknowledged: bool,
    authority_grants_any: bool,
    production_activation: bool,
    parameter_evaluation_material_hex: String,
}
type OriginalEvaluation = (
    IndependentEvaluationBundleV1,
    Vec<MetricRoleContractV2>,
    SignedEvaluationEvidenceV1,
);

/// Complete measured parts from the original custody and FULL acknowledgement.
/// This result grants no artifact registration, selection or activation.
pub struct CompletedParameterEvaluationsV1 {
    evaluations: Vec<OriginalEvaluation>,
    dispositions: Vec<IndependentEvaluationDispositionV1>,
    reports: Vec<String>,
}
impl CompletedParameterEvaluationsV1 {
    pub fn evaluations(&self) -> &[OriginalEvaluation] {
        &self.evaluations
    }
    pub fn dispositions(&self) -> &[IndependentEvaluationDispositionV1] {
        &self.dispositions
    }
    pub fn into_original_evaluations(self) -> Vec<OriginalEvaluation> {
        self.evaluations
    }
}

/// Read every completed actual Update through the same original measurement,
/// signed decision and FULL ACK checks used by the rejected-preparation owner.
/// Trust is supplied by the independently installed host, never these Sources.
pub fn inspect_completed_parameter_evaluations_v1(
    inputs: &[FixedParameterCompletedReviewSourceV1],
    round: &ParameterEvaluationRoundBindingV1,
    profile: &ParameterGeneratorProfileV3,
    admission: &PlasticityAdmissionEvidenceV1,
    generator: &SignedLearningEvidenceV1,
    observer: &SignedLearningEvidenceV1,
    reviewer: &AuthenticatedPrincipalV1,
    trust: &ActivatedLearningTrustV1,
    now: u64,
) -> HostResult<CompletedParameterEvaluationsV1> {
    let generated = generate_parameter_candidates_v3(profile.clone())?;
    validate_parameter_admission_binding_v1(profile, &generated, admission)?;
    let validate_actors = |at| -> HostResult<()> {
        if at < round.admitted_at_ms
            || at >= round.deadline_ms
            || [
                round.round_identity_digest,
                round.round_payload_digest,
                round.canonical_policy_digest,
                round.execution_envelope_digest,
            ]
            .iter()
            .any(|pin| pin.is_zero())
        {
            return Err("original completed E Round/window".into());
        }
        trust.revalidate_at(at)?;
        let g = trust.verifier().verify(
            LearningEvidenceRoleV1::Generator,
            generator,
            &parameter_generator_signing_payload_v3(&generated),
            at,
        )?;
        let o = trust.verifier().verify(
            LearningEvidenceRoleV1::Observer,
            observer,
            &plasticity_admission_signing_payload_v1(admission),
            at,
        )?;
        for actor in [&g, &o] {
            verify_independent_roles(actor.principal(), reviewer, at)?;
        }
        Ok(())
    };
    validate_actors(now)?;
    let completed = replay_completed(
        inputs, &generated, admission, generator, reviewer, trust, now,
    )?;
    let final_now = crate::fixed_calibration_host::now_ms()?;
    if final_now < now {
        return Err("original completed review clock rollback".into());
    }
    validate_actors(final_now)?;
    for (bundle, roles, evidence) in &completed.evaluations {
        crate::signed_evaluation::decide_with_signed_evidence_v2(
            bundle.clone(),
            roles.clone(),
            evidence,
            trust.verifier(),
            final_now,
        )?;
        let e = trust.verifier().verify(
            LearningEvidenceRoleV1::Evaluator,
            &evidence.evaluator_bundle,
            &evaluation_signing_payload_v2(bundle, roles)?,
            final_now,
        )?;
        for actor in [
            trust.verifier().verify(
                LearningEvidenceRoleV1::Generator,
                generator,
                &parameter_generator_signing_payload_v3(&generated),
                final_now,
            )?,
            trust.verifier().verify(
                LearningEvidenceRoleV1::Observer,
                observer,
                &plasticity_admission_signing_payload_v1(admission),
                final_now,
            )?,
        ] {
            verify_signed_role_separation(&actor, &e, final_now)?;
        }
    }
    for input in inputs {
        input
            .publication
            .read(crate::paired_review_transport::MAX_REVIEW_PUBLICATION_BYTES)?;
        input.result.read(3 * 1024 * 1024)?;
        input.acknowledgement.read(65)?;
    }
    let settled = crate::fixed_calibration_host::now_ms()?;
    if settled < final_now {
        return Err("completed E final clock rollback".into());
    }
    validate_actors(settled)?;
    for (bundle, roles, evidence) in &completed.evaluations {
        crate::signed_evaluation::decide_with_signed_evidence_v2(
            bundle.clone(),
            roles.clone(),
            evidence,
            trust.verifier(),
            settled,
        )?;
    }
    Ok(completed)
}

fn replay_completed(
    inputs: &[FixedParameterCompletedReviewSourceV1],
    generated: &GeneratedParameterCandidateSetV3,
    admission: &PlasticityAdmissionEvidenceV1,
    generator: &SignedLearningEvidenceV1,
    reviewer: &AuthenticatedPrincipalV1,
    trust: &ActivatedLearningTrustV1,
    now: u64,
) -> HostResult<CompletedParameterEvaluationsV1> {
    let expected: BTreeSet<_> = generated
        .candidates
        .iter()
        .filter(|candidate| candidate.kind == ParameterCandidateKindV2::Update)
        .map(|candidate| candidate.candidate_id.clone())
        .collect();
    if expected.is_empty() || expected.len() > 32 || inputs.len() != expected.len() {
        return Err("preparation requires completed coverage of every generated Update".into());
    }
    let mut actual = BTreeSet::new();
    let mut reports = Vec::new();
    let mut evaluations = Vec::new();
    let mut dispositions = Vec::new();
    for input in inputs {
        let original = input
            .publication
            .read(crate::paired_review_transport::MAX_REVIEW_PUBLICATION_BYTES)?;
        let publication = Publication::read(&original)?;
        let (root, distribution) = publication.trust.native()?;
        let declared = activate_learning_trust(&root, distribution, None, now)?;
        if declared.verifier().trust_digest() != trust.verifier().trust_digest() {
            return Err(
                "preparation original review uses different independent installed trust".into(),
            );
        }
        let execution = publication.recompute(trust, now)?;
        let context = ProductQualificationContextV1 {
            generator: execution.registration.generator.clone(),
            evaluator: reviewer.clone(),
            retention_receipt_digests: execution.observations.cut.retention_receipt_digests.clone(),
            unlearning_receipt_digest: execution.observations.cut.unlearning_receipt_digest,
        };
        let bundle = crate::paired_supervised_qualification::paired_bundle(&execution, &context)?;
        let roles: Vec<_> = execution
            .registration
            .plan
            .metrics
            .iter()
            .map(|m| MetricRoleContractV2 {
                metric_id: m.contract.metric_id.clone(),
                role: m.role,
            })
            .collect();
        if !expected.contains(&bundle.candidate_id)
            || !actual.insert(bundle.candidate_id.clone())
            || bundle.baseline_id != admission.baseline_id
            || bundle.objective_digest != admission.objective_digest
            || bundle.dataset_digest != admission.dataset_digest
            || bundle.generator.principal_id != generator.principal_id
        {
            return Err("measured preparation original candidate/lineage/complete frontier".into());
        }
        let result = input.result.read(3 * 1024 * 1024)?;
        let finished: Finished = serde_json::from_slice(&result)?;
        if finished.schema != "hepta.fixed-paired-original-custody-qualified.v1"
            || finished.execution_digest != execution.execution_digest().to_string()
            || finished.profile_digest != execution.registration.plan.profile_digest().to_string()
            || !finished.original_full_sink_acknowledged
            || finished.authority_grants_any
            || finished.production_activation
            || finished.evidence_digest.parse::<Digest32>()?.is_zero()
            || finished.publication_digest.parse::<Digest32>()?.is_zero()
            || input.acknowledgement.read(65)?
                != format!("{}\n", finished.publication_digest).as_bytes()
        {
            return Err("original custody completed whole receipt/ACK mismatch".into());
        }
        let raw = unhex(
            &finished.parameter_evaluation_material_hex,
            crate::fixed_parameter_review::MAX_PARAMETER_EVALUATION_BYTES,
        )?;
        let (measured, measured_roles, evidence) = decode_untrusted_plasticity_evaluation_v1(&raw)?;
        if measured != bundle
            || measured_roles != roles
            || evidence.generator_plan != execution.registration.generator_evidence
            || evidence.evaluator_bundle.issued_at
                < execution.observations.cut.finished_at_unix_micros / 1000
        {
            return Err(
                "original completed raw E output differs from actual custody measurements".into(),
            );
        }
        let decision = crate::signed_evaluation::decide_with_signed_evidence_v2(
            measured.clone(),
            measured_roles.clone(),
            &evidence,
            trust.verifier(),
            now,
        )?;
        if decision.decision.evidence_digest.to_string() != finished.decision_digest
            || finished.eligible_for_independent_selection
                != (decision.decision.disposition
                    == IndependentEvaluationDispositionV1::EligibleForIndependentSelection)
        {
            return Err("original preparation measured disposition mismatch".into());
        }
        dispositions.push(decision.decision.disposition);
        evaluations.push((measured, measured_roles, evidence));
        reports.push(hex(&result));
    }
    if actual != expected {
        return Err("original measured preparation coverage changed".into());
    }
    Ok(CompletedParameterEvaluationsV1 {
        evaluations,
        dispositions,
        reports,
    })
}

pub(crate) fn replay_rejected_preparation(
    inputs: &[FixedParameterCompletedReviewSourceV1],
    generated: &GeneratedParameterCandidateSetV3,
    admission: &PlasticityAdmissionEvidenceV1,
    generator: &SignedLearningEvidenceV1,
    reviewer: &AuthenticatedPrincipalV1,
    trust: &ActivatedLearningTrustV1,
    now: u64,
) -> HostResult<(Vec<u8>, SelfIterationPreparationDispositionV1)> {
    let completed = replay_completed(
        inputs, generated, admission, generator, reviewer, trust, now,
    )?;
    if completed
        .dispositions
        .contains(&IndependentEvaluationDispositionV1::EligibleForIndependentSelection)
    {
        return Err(
            "an eligible measured candidate cannot be preparation-terminal rejected".into(),
        );
    }
    let insufficient = completed
        .dispositions
        .contains(&IndependentEvaluationDispositionV1::InsufficientEvidence);
    let disposition = if insufficient {
        SelfIterationPreparationDispositionV1::InsufficientEvidence
    } else {
        SelfIterationPreparationDispositionV1::Ineligible
    };
    let summary = serde_json::to_vec(&serde_json::json!({
        "schema":"hepta.parameter.measured-preparation-disposition.v1",
        "generated_digest":generated.generator_digest.to_string(),
        "admission_digest":Digest32::of_bytes(&plasticity_admission_signing_payload_v1(admission)).to_string(),
        "original_custody_completed_reports_hex":completed.reports,
        "disposition":if insufficient {"insufficient_evidence"}else{"ineligible"},
    }))?;
    if summary.len() > MAX_PARAMETER_ROLE_MATERIAL_BYTES_V1 {
        return Err("whole measured preparation summary bound".into());
    }
    Ok((summary, disposition))
}
