//! Opaque E1 result under the live original baseline. Historical publication
//! is a separate original Artifact-owner purpose, never a claimed live baseline.
use crate::fixed_calibration_host::now_ms;
use crate::fixed_parameter_generator_v3::ParameterRoleSourceV3;
use crate::initial_neuron_operational_source::HostResult;
use crate::parameter_pre_registration_host_v1::Output;
use crate::parameter_pre_registration_host_v1::measure_body;
use crate::parameter_pre_registration_host_v1::payload;
use crate::parameter_pre_registration_host_v1::preparation_facts;
use crate::parameter_pre_registration_policy_v1::BaselineUseV1;
use crate::parameter_pre_registration_policy_v1::inspect_frontier;
use crate::parameter_pre_registration_policy_v1::validate_reviewer;
use crate::parameter_pre_registration_v1::*;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use codex_hepta_neuron::NeuronGenerationMaterialV2;
use codex_hepta_neuron::decode_neuron_generation_material_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use std::path::Path;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

pub struct VerifiedParameterPreRegistrationEvaluationV1 {
    config: ParameterRoleSourceV3,
    report: ParameterRoleSourceV3,
    round: ParameterPreRegistrationRoundV1,
    purpose: ParameterPreRegistrationPurposeV1,
    subject: StableId,
    candidate: StableId,
    baseline_artifact: StableId,
    baseline_head_artifact: StableId,
    baseline_head_manifest: Digest32,
    baseline_head: Digest32,
    baseline_operation: StableId,
    evaluator: VerifiedLearningEvidenceV1,
    generator: VerifiedLearningEvidenceV1,
    observer: VerifiedLearningEvidenceV1,
    material: Option<NeuronGenerationMaterialV2>,
    authentication_digest: Digest32,
    publication_digest: Digest32,
    expires_at: u64,
    clock_floor: AtomicU64,
    evaluator_uid: u32,
    evaluator_gid: u32,
    selectors: Vec<TrustedLearningSignerV1>,
    source_dataset_digests: [Digest32; 2],
    preparation_terminal: Option<Vec<u8>>,
    historical: bool,
}
impl VerifiedParameterPreRegistrationEvaluationV1 {
    pub fn round(&self) -> &ParameterPreRegistrationRoundV1 {
        &self.round
    }
    pub fn purpose(&self) -> ParameterPreRegistrationPurposeV1 {
        self.purpose
    }
    pub fn subject(&self) -> &StableId {
        &self.subject
    }
    pub fn candidate_id(&self) -> &StableId {
        &self.candidate
    }
    pub fn baseline_artifact_id(&self) -> &StableId {
        &self.baseline_artifact
    }
    pub fn baseline_head_artifact_id(&self) -> &StableId {
        &self.baseline_head_artifact
    }
    pub fn baseline_head_manifest_digest(&self) -> Digest32 {
        self.baseline_head_manifest
    }
    pub fn baseline_registry_head(&self) -> Digest32 {
        self.baseline_head
    }
    pub fn baseline_publication_operation(&self) -> &StableId {
        &self.baseline_operation
    }
    pub fn evaluator(&self) -> &VerifiedLearningEvidenceV1 {
        &self.evaluator
    }
    pub fn generator(&self) -> &VerifiedLearningEvidenceV1 {
        &self.generator
    }
    pub fn observer(&self) -> &VerifiedLearningEvidenceV1 {
        &self.observer
    }
    pub fn material(&self) -> Option<&NeuronGenerationMaterialV2> {
        self.material.as_ref()
    }
    pub fn authentication_digest(&self) -> Digest32 {
        self.authentication_digest
    }
    pub fn evaluation_publication_digest(&self) -> Digest32 {
        self.publication_digest
    }
    pub fn evaluator_uid(&self) -> u32 {
        self.evaluator_uid
    }
    pub fn evaluator_gid(&self) -> u32 {
        self.evaluator_gid
    }
    pub fn expires_at(&self) -> u64 {
        self.expires_at
    }
    pub fn source_dataset_digests(&self) -> &[Digest32; 2] {
        &self.source_dataset_digests
    }
    pub fn trusted_selector(&self, id: &StableId) -> Option<&TrustedLearningSignerV1> {
        self.selectors
            .iter()
            .find(|s| &s.principal.principal_id == id)
    }
    pub fn preparation_terminal_bytes(&self) -> Option<&[u8]> {
        self.preparation_terminal.as_deref()
    }
    pub fn revalidate_after_registration(&self) -> HostResult<()> {
        if !self.historical {
            return Err(
                "live E1 must be freshly inspected under completed publication history".into(),
            );
        }
        let now = now_ms()?;
        if now < self.clock_floor.fetch_max(now, Ordering::AcqRel) {
            return Err("E1 historical clock rollback".into());
        }
        let actual = inspect_at(&self.config, &self.report, now, E1ObservationV1::Historical)?;
        if actual.authentication_digest != self.authentication_digest
            || actual.evaluator != self.evaluator
            || actual.round != self.round
            || now >= self.expires_at
        {
            return Err("completed E1 original history/current eligibility changed".into());
        }
        self.clock_floor
            .fetch_max(actual.clock_floor.load(Ordering::Acquire), Ordering::AcqRel);
        Ok(())
    }
    pub fn revalidate_before_registration(&self) -> HostResult<()> {
        let now = now_ms()?;
        if now < self.clock_floor.fetch_max(now, Ordering::AcqRel) {
            return Err("E1 retained clock rollback".into());
        }
        if self.historical {
            return Err("historical E1 is not a live before-registration baseline".into());
        }
        let actual = inspect_at(
            &self.config,
            &self.report,
            now,
            E1ObservationV1::BeforeRegistration,
        )?;
        if actual.authentication_digest != self.authentication_digest
            || actual.evaluator != self.evaluator
            || actual.round != self.round
            || now >= self.expires_at
        {
            return Err("E1 original current evidence changed/expired before publication".into());
        }
        self.clock_floor
            .fetch_max(actual.clock_floor.load(Ordering::Acquire), Ordering::AcqRel);
        Ok(())
    }
}
pub fn inspect_parameter_pre_registration_evaluation_v1(
    config: &Path,
    config_digest: Digest32,
    report: &Path,
    report_digest: Digest32,
) -> HostResult<VerifiedParameterPreRegistrationEvaluationV1> {
    inspect_at(
        &ParameterRoleSourceV3 {
            path: config.to_owned(),
            digest: config_digest.to_string(),
        },
        &ParameterRoleSourceV3 {
            path: report.to_owned(),
            digest: report_digest.to_string(),
        },
        now_ms()?,
        E1ObservationV1::BeforeRegistration,
    )
}
fn unhex(value: &str, maximum: usize) -> HostResult<Vec<u8>> {
    if value.len() > maximum.checked_mul(2).ok_or("hex bound")?
        || value.len() % 2 != 0
        || !value
            .bytes()
            .all(|v| v.is_ascii_digit() || (b'a'..=b'f').contains(&v))
    {
        return Err("bounded complete canonical E1 material hex".into());
    }
    value
        .as_bytes()
        .chunks_exact(2)
        .map(|pair| Ok(u8::from_str_radix(std::str::from_utf8(pair)?, 16)?))
        .collect()
}
#[derive(Clone, Copy)]
enum E1ObservationV1 {
    BeforeRegistration,
    Historical,
}
/// Completed E1 evidence is verified under the original protected ancestor ACK
/// and current dataset eligibility. This never calls the old baseline live.
pub fn inspect_parameter_pre_registration_history_v1(
    config: &Path,
    config_digest: Digest32,
    report: &Path,
    report_digest: Digest32,
) -> HostResult<VerifiedParameterPreRegistrationEvaluationV1> {
    inspect_at(
        &ParameterRoleSourceV3 {
            path: config.to_owned(),
            digest: config_digest.to_string(),
        },
        &ParameterRoleSourceV3 {
            path: report.to_owned(),
            digest: report_digest.to_string(),
        },
        now_ms()?,
        E1ObservationV1::Historical,
    )
}
fn inspect_at(
    config_source: &ParameterRoleSourceV3,
    report_source: &ParameterRoleSourceV3,
    now: u64,
    purpose: E1ObservationV1,
) -> HostResult<VerifiedParameterPreRegistrationEvaluationV1> {
    let config_bytes = config_source.read(64 * 1024)?;
    let report_bytes = report_source.read(MAX_PARAMETER_PRE_REGISTRATION_REPORT_BYTES_V1 as u64)?;
    let config: FixedParameterPreRegistrationConfigV1 = serde_json::from_slice(&config_bytes)?;
    let output: Output = serde_json::from_slice(&report_bytes)?;
    let body = &output.publication.body;
    let original_head = codex_hepta_learning_artifacts::decode_untrusted_signed_artifact_head_v1(
        &unhex(&body.baseline_signed_head_hex, 4096)?,
    )?;
    let inputs = inspect_frontier(
        &config,
        now,
        match purpose {
            E1ObservationV1::BeforeRegistration => BaselineUseV1::BeforeRegistration,
            E1ObservationV1::Historical => BaselineUseV1::Historical(&original_head),
        },
    )?;
    validate_reviewer(&config, &inputs)?;
    if body.schema != "hepta.parameter-pre-registration-evaluation.v1"
        || body.claim_scope != PARAMETER_PRE_REGISTRATION_CLAIM_V1
        || body.configuration_digest != config_source.digest
        || body.measured_at_ms < config.round.admitted_at_ms
        || body.measured_at_ms > now
        || body.measured_at_ms >= inputs.expiry
        || body.evaluator_uid != config.uid
        || body.evaluator_gid != config.gid
        || body.evaluator_program_digest != config.program_digest
        || body.evaluator_cgroup.len() > 4096
        || !body
            .evaluator_cgroup
            .contains("hepta-fixed-calibration-eval-")
        || body.cpu_answer_acceptance_permitted
    {
        return Err("E1 complete report purpose/identity/time/original process".into());
    }
    let bytes = payload(body)?;
    let signed = output.publication.evaluator_signed_evidence.native()?;
    if signed.principal_id != inputs.reviewer.principal.principal_id
        || signed.issued_at != body.measured_at_ms
        || signed.expires_at > inputs.expiry
    {
        return Err("E1 actual E original measurement instant/expiry".into());
    }
    let evaluator =
        inputs
            .trust
            .verifier()
            .verify(LearningEvidenceRoleV1::Evaluator, &signed, &bytes, now)?;
    for actor in [&inputs.generator, &inputs.observer] {
        verify_signed_actor_separation(actor, &evaluator, now)?;
    }
    for cut in [&inputs.source.native.calibration, &inputs.source.native.ood] {
        for actor in &cut.actors {
            verify_signed_actor_separation(actor, &evaluator, now)?;
        }
    }
    // Actual replay transcript and head metrics must match. E's signed physical
    // execution observations are bounded; a consumer's latency is not E's.
    let expected = measure_body(
        &config,
        &inputs,
        config_source.digest.parse()?,
        body.measured_at_ms,
        body.evaluator_cgroup.clone(),
        Some((&body.calibration_execution, &body.ood_execution)),
    )?;
    if expected != *body {
        return Err("E1 whole final material differs from original replay/measurement".into());
    }
    let material = match (&body.final_material_hex, &body.final_material_digest) {
        (Some(hex), Some(pin)) if body.operational_constraints_passed => {
            let bytes = unhex(
                hex,
                codex_hepta_neuron::MAX_NEURON_GENERATION_MATERIAL_BYTES_V2,
            )?;
            if Digest32::of_bytes(&bytes).to_string() != *pin {
                return Err("E1 full material pin".into());
            }
            Some(decode_neuron_generation_material_v2(&bytes)?)
        }
        (None, None) if !body.operational_constraints_passed => None,
        _ => return Err("E1 honest qualified/rejected material shape".into()),
    };
    let preparation_terminal = match &output.preparation_terminal_hex {
        Some(hex) if material.is_none() => {
            let bytes = unhex(hex, crate::MAX_SELF_ITERATION_PREPARATION_TERMINAL_BYTES_V1)?;
            let (facts, evidence) = crate::decode_self_iteration_preparation_terminal_v1(&bytes)?;
            if facts
                != preparation_facts(&config, config_source.digest.parse()?, &output.publication)?
                || evidence.principal_id != signed.principal_id
                || evidence.issued_at != signed.issued_at
            {
                return Err("E1 actual rejection differs from original preparation facts".into());
            }
            inputs.trust.verifier().verify(
                LearningEvidenceRoleV1::Evaluator,
                &evidence,
                &crate::self_iteration_preparation_terminal_signing_payload_v1(&facts)?,
                now,
            )?;
            Some(bytes)
        }
        None if material.is_some() => None,
        _ => return Err("E1 rejection must retain actual terminal evidence".into()),
    };
    inputs.baseline.revalidate(now)?;
    if config_source.read(64 * 1024)? != config_bytes
        || report_source.read(MAX_PARAMETER_PRE_REGISTRATION_REPORT_BYTES_V1 as u64)?
            != report_bytes
    {
        return Err("E1 current protected Source changed at use".into());
    }
    let settled_now = now_ms()?;
    if settled_now < now {
        return Err("E1 final observation clock rollback".into());
    }
    config.round.validate(settled_now)?;
    inputs.baseline.revalidate(settled_now)?;
    let baseline_material = codex_hepta_neuron::decode_neuron_generation_material_v2(
        &config
            .baseline_material
            .read(codex_hepta_neuron::MAX_NEURON_GENERATION_MATERIAL_BYTES_V2 as u64)?,
    )?;
    let current_head = super::parameter_pre_registration_head_v1::inspect_head(
        &config,
        &inputs.baseline,
        &baseline_material,
        &inputs.admission,
        settled_now,
    )?;
    if current_head != inputs.head_manifest {
        return Err("E1 original parameter head changed during measurement".into());
    }
    inputs.trust.revalidate_at(settled_now)?;
    inputs.trust.verifier().verify(
        LearningEvidenceRoleV1::Evaluator,
        &signed,
        &bytes,
        settled_now,
    )?;
    for actor in [&inputs.generator, &inputs.observer] {
        verify_signed_actor_separation(actor, &evaluator, settled_now)?;
    }
    if settled_now >= inputs.expiry {
        return Err("E1 expired during actual observation".into());
    }
    Ok(VerifiedParameterPreRegistrationEvaluationV1 {
        config: config_source.clone(),
        report: report_source.clone(),
        round: config.round,
        purpose: config.purpose,
        subject: StableId::new(config.subject)?,
        candidate: StableId::new(config.candidate_id)?,
        baseline_artifact: StableId::new(body.baseline_model_artifact_id.clone())?,
        baseline_head_artifact: StableId::new(body.baseline_head_artifact_id.clone())?,
        baseline_head_manifest: body.baseline_head_manifest_digest.parse()?,
        baseline_head: body.baseline_registry_head.parse()?,
        baseline_operation: StableId::new(body.baseline_publication_operation.clone())?,
        evaluator,
        generator: inputs.generator,
        observer: inputs.observer,
        material,
        authentication_digest: Digest32::of_bytes(&report_bytes),
        publication_digest: Digest32::of_bytes(&serde_json::to_vec(&output.publication)?),
        expires_at: signed.expires_at,
        clock_floor: AtomicU64::new(settled_now),
        evaluator_uid: config.uid,
        evaluator_gid: config.gid,
        selectors: inputs.selectors,
        source_dataset_digests: [
            inputs
                .source
                .native
                .calibration
                .publication
                .cut
                .dataset
                .native()?
                .snapshot
                .dataset_digest,
            inputs
                .source
                .native
                .ood
                .publication
                .cut
                .dataset
                .native()?
                .snapshot
                .dataset_digest,
        ],
        preparation_terminal,
        historical: matches!(purpose, E1ObservationV1::Historical),
    })
}
