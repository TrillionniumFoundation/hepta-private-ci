//! Raw parameter evaluation reuses the exact original custody-measured bundle.
use crate::fixed_parameter_no_change::{HostResult, unhex};
use crate::fixed_parameter_no_change_host::Inputs;
use crate::*;
use codex_hepta_learning_ledger::*;
use codex_hepta_plasticity::*;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use std::path::PathBuf;
#[cfg(test)]
#[path = "fixed_parameter_review_tests.rs"]
mod tests;

pub(crate) const MAX_PARAMETER_EVALUATION_BYTES: usize = 1024 * 1024;
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ParameterReviewPort {
    path: PathBuf,
    digest: String,
}

/// A final-use check inside the original sink call, without another writer or
/// persistence path. The exact measured raw packet must remain current.
pub(crate) struct CurrentParameterSink<'a, S, F> {
    pub(crate) inner: &'a mut S,
    pub(crate) current: F,
}
impl<S: ProductQualificationEvidenceSinkV1, F: FnMut() -> HostResult<()>>
    ProductQualificationEvidenceSinkV1 for CurrentParameterSink<'_, S, F>
{
    fn persist(
        &mut self,
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1> {
        (self.current)().map_err(|_| ProductEvidenceSinkErrorV1::Indeterminate)?;
        self.inner.persist(execution_digest, decision)
    }
}

pub(crate) struct ParameterReview {
    port: ParameterReviewPort,
    bytes: Vec<u8>,
    profile: ParameterGeneratorProfileV3,
    generated: GeneratedParameterCandidateSetV3,
    admission: PlasticityAdmissionEvidenceV1,
    generator: SignedLearningEvidenceV1,
    observer: SignedLearningEvidenceV1,
    admitted_at_ms: u64,
    deadline_ms: u64,
    candidate_id: String,
}
impl ParameterReview {
    pub(crate) fn open(port: ParameterReviewPort) -> HostResult<Self> {
        let bytes = read_root_review_input(
            &port.path,
            4 * MAX_PARAMETER_ROLE_MATERIAL_BYTES_V1 as u64 + 32 * 1024,
        )?;
        if Digest32::of_bytes(&bytes) != port.digest.parse()? {
            return Err("original parameter evaluation inputs pin".into());
        }
        let inputs: Inputs = serde_json::from_slice(&bytes)?;
        if inputs.schema != "hepta.parameter-review-inputs.v1" {
            return Err("original parameter evaluation input purpose".into());
        }
        let candidate_id = inputs
            .candidate_id
            .ok_or("actual generated update candidate absent")?;
        let profile = decode_untrusted_parameter_generator_profile_v3(&unhex(
            &inputs.profile_hex,
            MAX_PARAMETER_ROLE_MATERIAL_BYTES_V1,
        )?)?;
        let admission = decode_untrusted_plasticity_admission_v1(&unhex(
            &inputs.admission_hex,
            MAX_PARAMETER_ROLE_MATERIAL_BYTES_V1,
        )?)?;
        let generated = generate_parameter_candidates_v3(profile.clone())?;
        validate_parameter_admission_binding_v1(&profile, &generated, &admission)?;
        if !generated.candidates.iter().any(|candidate| {
            candidate.candidate_id.as_str() == candidate_id
                && candidate.kind == ParameterCandidateKindV2::Update
        }) {
            return Err(
                "parameter evaluation requires actual original Update frontier member".into(),
            );
        }
        // Parse every original round identity even though the Root owner still
        // joins these protected facts to its live journal before accepting use.
        for pin in [
            inputs.round_identity_digest,
            inputs.round_payload_digest,
            inputs.canonical_policy_digest,
            inputs.execution_envelope_digest,
        ] {
            if pin.parse::<Digest32>()?.is_zero() {
                return Err("parameter evaluation round pin".into());
            }
        }
        Ok(Self {
            port,
            bytes,
            profile,
            generated,
            admission,
            generator: inputs.generator_evidence.native()?,
            observer: inputs.observer_evidence.native()?,
            admitted_at_ms: inputs.admitted_at_ms,
            deadline_ms: inputs.deadline_ms,
            candidate_id,
        })
    }
    pub(crate) fn revalidate(
        &self,
        bundle: &IndependentEvaluationBundleV1,
        trust: &ActivatedLearningTrustV1,
        now: u64,
    ) -> HostResult<()> {
        if read_root_review_input(
            &self.port.path,
            4 * MAX_PARAMETER_ROLE_MATERIAL_BYTES_V1 as u64 + 32 * 1024,
        )? != self.bytes
            || now < self.admitted_at_ms
            || now >= self.deadline_ms
            || bundle.candidate_id.as_str() != self.candidate_id
            || bundle.baseline_id != self.admission.baseline_id
            || bundle.objective_digest != self.admission.objective_digest
            || bundle.dataset_digest != self.admission.dataset_digest
        {
            return Err("original measured parameter lineage/current source/time".into());
        }
        verify_generated_parameter_candidates_v3(self.profile.clone(), &self.generated)?;
        validate_parameter_admission_binding_v1(&self.profile, &self.generated, &self.admission)?;
        trust.revalidate_at(now)?;
        let g = trust.verifier().verify(
            LearningEvidenceRoleV1::Generator,
            &self.generator,
            &parameter_generator_signing_payload_v3(&self.generated),
            now,
        )?;
        let o = trust.verifier().verify(
            LearningEvidenceRoleV1::Observer,
            &self.observer,
            &plasticity_admission_signing_payload_v1(&self.admission),
            now,
        )?;
        if g.principal() != &bundle.generator {
            return Err("original parameter G and plan G differ".into());
        }
        for actor in [&g, &o] {
            verify_independent_roles(actor.principal(), &bundle.evaluator, now)?;
        }
        Ok(())
    }
    pub(crate) fn expiry(&self) -> u64 {
        self.deadline_ms
            .min(self.generator.expires_at)
            .min(self.observer.expires_at)
    }
    pub(crate) fn encode(
        &self,
        bundle: &IndependentEvaluationBundleV1,
        roles: &[MetricRoleContractV2],
        evidence: &SignedEvaluationEvidenceV1,
        trust: &ActivatedLearningTrustV1,
        now: u64,
    ) -> HostResult<Vec<u8>> {
        self.revalidate(bundle, trust, now)?;
        crate::signed_evaluation::authenticate(
            bundle,
            evidence,
            trust.verifier(),
            &evaluation_signing_payload_v2(bundle, roles)?,
            now,
        )?;
        let o = trust.verifier().verify(
            LearningEvidenceRoleV1::Observer,
            &self.observer,
            &plasticity_admission_signing_payload_v1(&self.admission),
            now,
        )?;
        let e = trust.verifier().verify(
            LearningEvidenceRoleV1::Evaluator,
            &evidence.evaluator_bundle,
            &evaluation_signing_payload_v2(bundle, roles)?,
            now,
        )?;
        verify_signed_independent_roles_v1(&o, &e, now)?;
        let bytes = encode_untrusted_plasticity_evaluation_v1(bundle, roles, evidence)?;
        if bytes.len() > MAX_PARAMETER_EVALUATION_BYTES {
            return Err("whole parameter measured evaluation exceeds fixed purpose bound".into());
        }
        Ok(bytes)
    }
    pub(crate) fn verify_material(
        &self,
        bytes: &[u8],
        expected: &IndependentEvaluationBundleV1,
        expected_roles: &[MetricRoleContractV2],
        expected_generator: &SignedLearningEvidenceV1,
        trust: &ActivatedLearningTrustV1,
        now: u64,
    ) -> HostResult<()> {
        if bytes.len() > MAX_PARAMETER_EVALUATION_BYTES {
            return Err("parameter material bound".into());
        }
        let (bundle, roles, evidence) = decode_untrusted_plasticity_evaluation_v1(bytes)?;
        if &bundle != expected
            || roles != expected_roles
            || &evidence.generator_plan != expected_generator
        {
            return Err(
                "parameter raw output changed original custody measurement/roles/G plan".into(),
            );
        }
        if self.encode(&bundle, &roles, &evidence, trust, now)? != bytes {
            return Err("whole original parameter evaluation codec".into());
        }
        Ok(())
    }
}
