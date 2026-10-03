//! Opaque original E evidence for the whole registered successor. Every final
//! use recomputes the original CURRENT, full tuple, source replay and signature.
use crate::fixed_calibration_host::now_ms;
use crate::initial_neuron_operational_metrics::measure;
use crate::initial_neuron_operational_source::HostResult;
use crate::initial_neuron_operational_source::Source;
use crate::operational_registered_host_v3::Report;
use crate::operational_registered_host_v3::payload;
use crate::operational_registered_host_v3::replay_constraints;
use crate::operational_registered_host_v3::validate_reviewer;
use crate::operational_registered_measurement_v3::replay;
use crate::operational_registered_model_v3::RegisteredOperationalModelBindingV3;
use crate::operational_registered_policy_v3::Config;
use crate::operational_registered_policy_v3::inspect;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use codex_hepta_neuron::NeuronGenerationMaterialV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use std::path::Path;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

pub struct VerifiedRegisteredOperationalEvaluationV3 {
    config: Source,
    report: Source,
    binding: RegisteredOperationalModelBindingV3,
    evaluator: VerifiedLearningEvidenceV1,
    plan: NeuronGenerationMaterialV2,
    authentication_digest: Digest32,
    expires_at: u64,
    clock_floor: AtomicU64,
    evaluator_uid: u32,
    evaluator_gid: u32,
    selectors: Vec<TrustedLearningSignerV1>,
}
impl VerifiedRegisteredOperationalEvaluationV3 {
    pub fn binding(&self) -> &RegisteredOperationalModelBindingV3 {
        &self.binding
    }
    pub fn evaluator(&self) -> &VerifiedLearningEvidenceV1 {
        &self.evaluator
    }
    pub fn material(&self) -> &NeuronGenerationMaterialV2 {
        &self.plan
    }
    pub fn authentication_digest(&self) -> Digest32 {
        self.authentication_digest
    }
    pub fn evaluator_uid(&self) -> u32 {
        self.evaluator_uid
    }
    pub fn evaluator_gid(&self) -> u32 {
        self.evaluator_gid
    }
    /// Original activated Root roster facts; this does not sign or grant use.
    pub fn trusted_selector(&self, id: &StableId) -> Option<&TrustedLearningSignerV1> {
        self.selectors
            .iter()
            .find(|s| &s.principal.principal_id == id)
    }
    pub fn expires_at(&self) -> u64 {
        self.expires_at
    }
    pub fn revalidate_current(&self) -> HostResult<()> {
        let now = now_ms()?;
        if now < self.clock_floor.fetch_max(now, Ordering::AcqRel) {
            return Err("registered operational retained clock rollback".into());
        }
        let actual = inspect_at(&self.config, &self.report, now)?;
        if actual.binding != self.binding
            || actual.authentication_digest != self.authentication_digest
            || actual.evaluator != self.evaluator
            || now >= self.expires_at
        {
            return Err("registered operational current full evidence changed/expired".into());
        }
        Ok(())
    }
}

/// This validates E evidence only. The actual S purpose, current selected
/// artifacts, complete physical generation and each Goal are separate inputs.
pub fn inspect_registered_operational_evaluation_v3(
    config: &Path,
    config_digest: Digest32,
    report: &Path,
    report_digest: Digest32,
) -> HostResult<VerifiedRegisteredOperationalEvaluationV3> {
    inspect_at(
        &Source {
            path: config.to_owned(),
            digest: config_digest.to_string(),
        },
        &Source {
            path: report.to_owned(),
            digest: report_digest.to_string(),
        },
        now_ms()?,
    )
}
fn inspect_at(
    config_source: &Source,
    report_source: &Source,
    now: u64,
) -> HostResult<VerifiedRegisteredOperationalEvaluationV3> {
    let config_bytes = config_source.read(64 * 1024)?;
    let report_bytes = report_source.read(64 * 1024)?;
    let config: Config = serde_json::from_slice(&config_bytes)?;
    let report: Report = serde_json::from_slice(&report_bytes)?;
    let inputs = inspect(&config, now)?;
    validate_reviewer(&config, &inputs)?;
    let body = &report.body;
    let measured = body.measured_at_ms;
    if body.schema != "hepta.registered-operational-model-evaluation.v3"
        || body.binding != inputs.binding
        || body.configuration_digest != config_source.digest
        || body.original_source_configuration_digest != config.source_configuration.digest
        || body.original_source_binding_digest
            != inputs.source.binding.binding_digest()?.to_string()
        || measured < config.frozen_at_ms
        || measured > now
        || measured >= inputs.expiry
        || body.evaluator_uid != config.uid
        || body.evaluator_gid != config.gid
        || body.evaluator_program_digest != config.program_digest
        || body.evaluator_cgroup.len() > 4096
        || !body
            .evaluator_cgroup
            .contains("hepta-fixed-calibration-eval-")
        || body.cpu_answer_acceptance_permitted
        || !body.operational_constraints_passed
    {
        return Err("registered operational report identity/lifetime/slow-path purpose".into());
    }
    for (cut, expected, execution, head) in [
        (
            &inputs.source.native.calibration,
            &body.calibration,
            &body.calibration_execution,
            &body.original_head_calibration,
        ),
        (
            &inputs.source.native.ood,
            &body.ood,
            &body.ood_execution,
            &body.original_head_ood,
        ),
    ] {
        let (actual, _) = replay(&inputs.plan, cut)?;
        let original_head =
            serde_json::to_value(measure(cut, &inputs.source.native.policy.gates)?)?;
        if actual != *expected
            || original_head != *head
            || head["operational_constraints_passed"] != true
            || !replay_constraints(&inputs, &config, expected, execution)
        {
            return Err(
                "registered operational report differs from actual original sparse replay/source"
                    .into(),
            );
        }
    }
    let payload = payload(body)?;
    let signed = report.evaluator_signed_evidence.native()?;
    if signed.principal_id != inputs.reviewer.principal.principal_id
        || signed.issued_at != measured
        || signed.expires_at > inputs.expiry
    {
        return Err("registered operational evidence actual E/measurement instant".into());
    }
    let evaluator = inputs.current_trust.verifier().verify(
        LearningEvidenceRoleV1::Evaluator,
        &signed,
        &payload,
        now,
    )?;
    for cut in [&inputs.source.native.calibration, &inputs.source.native.ood] {
        for actor in &cut.actors {
            verify_signed_actor_separation(actor, &evaluator, now)?;
        }
    }
    if inspect(&config, now)?.binding != inputs.binding
        || config_source.read(64 * 1024)? != config_bytes
        || report_source.read(64 * 1024)? != report_bytes
    {
        return Err("registered whole current/input/report changed at use".into());
    }
    let authentication_digest = Digest32::of_bytes(
        &[
            b"hepta.registered-operational.current-evidence.v3\0".as_slice(),
            Digest32::of_bytes(&report_bytes).as_array(),
            signed.payload_digest.as_array(),
            signed.trust_digest.as_array(),
        ]
        .concat(),
    );
    Ok(VerifiedRegisteredOperationalEvaluationV3 {
        config: config_source.clone(),
        report: report_source.clone(),
        binding: inputs.binding,
        evaluator,
        plan: inputs.plan,
        authentication_digest,
        expires_at: signed.expires_at,
        clock_floor: AtomicU64::new(now),
        evaluator_uid: config.uid,
        evaluator_gid: config.gid,
        selectors: inputs.selectors,
    })
}
