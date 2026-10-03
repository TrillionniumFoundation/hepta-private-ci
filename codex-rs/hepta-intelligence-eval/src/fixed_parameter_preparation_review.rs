//! A rejected preparation must cover every actual generated Update with original
//! measured E output and the original protected custody completion/ACK.
use crate::fixed_parameter_no_change::{HostResult, hex, unhex};
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
pub(crate) fn replay_rejected_preparation(
    inputs: &[FixedParameterCompletedReviewSourceV1],
    generated: &GeneratedParameterCandidateSetV3,
    admission: &PlasticityAdmissionEvidenceV1,
    generator: &SignedLearningEvidenceV1,
    reviewer: &AuthenticatedPrincipalV1,
    trust: &ActivatedLearningTrustV1,
    now: u64,
) -> HostResult<(Vec<u8>, SelfIterationPreparationDispositionV1)> {
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
    let mut insufficient = false;
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
            measured,
            measured_roles,
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
        match decision.decision.disposition {
            IndependentEvaluationDispositionV1::EligibleForIndependentSelection => {
                return Err(
                    "an eligible measured candidate cannot be preparation-terminal rejected".into(),
                );
            }
            IndependentEvaluationDispositionV1::InsufficientEvidence => insufficient = true,
            IndependentEvaluationDispositionV1::Ineligible => (),
        }
        reports.push(hex(&result));
    }
    if actual != expected {
        return Err("original measured preparation coverage changed".into());
    }
    let disposition = if insufficient {
        SelfIterationPreparationDispositionV1::InsufficientEvidence
    } else {
        SelfIterationPreparationDispositionV1::Ineligible
    };
    let summary = serde_json::to_vec(&serde_json::json!({
        "schema":"hepta.parameter.measured-preparation-disposition.v1",
        "generated_digest":generated.generator_digest.to_string(),
        "admission_digest":Digest32::of_bytes(&plasticity_admission_signing_payload_v1(admission)).to_string(),
        "original_custody_completed_reports_hex":reports,
        "disposition":if insufficient {"insufficient_evidence"}else{"ineligible"},
    }))?;
    if summary.len() > MAX_PARAMETER_ROLE_MATERIAL_BYTES_V1 {
        return Err("whole measured preparation summary bound".into());
    }
    Ok((summary, disposition))
}
