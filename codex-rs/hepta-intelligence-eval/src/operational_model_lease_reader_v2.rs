//! Opaque, current V2 E evidence. Legacy V1 signatures cannot mint this value.
use crate::ConservativeCpuRuntimeProfileV2;
use crate::OperationalModelLeaseBindingV2;
use crate::fixed_calibration_host::now_ms;
use crate::initial_neuron_operational_host::Config;
use crate::initial_neuron_operational_source::HostResult;
use crate::initial_neuron_operational_source::Source;
use crate::operational_model_lease_host_v2::body;
use crate::operational_model_lease_host_v2::expires_at;
use crate::operational_model_lease_host_v2::payload;
use crate::operational_model_lease_material_v2::VerifiedMaterial;
use crate::operational_model_lease_policy_v2::inspect_inputs;
use crate::operational_model_lease_policy_v2::reinspect_inputs;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::ReviewEvidenceWireV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde_json::Value;
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Report {
    body: Value,
    evaluator_signed_evidence: ReviewEvidenceWireV1,
}

/// A separately signed stable-model lease for abstention-only CPU execution.
/// It grants no Goal, answer acceptance, promotion, holdout or activation rights.
/// Consumers must also validate each current Goal and its seven Owner final use.
pub struct VerifiedOperationalModelLeaseV2 {
    config: Source,
    report: Source,
    body: Value,
    evaluator: VerifiedLearningEvidenceV1,
    authentication_digest: Digest32,
    binding: OperationalModelLeaseBindingV2,
    profile: ConservativeCpuRuntimeProfileV2,
    scope: Digest32,
    expires_at: u64,
    // This is a retained-value clock floor, not a cross-boot authority frontier.
    // FinalUse still supplies the independently protected execution clock.
    clock_floor: AtomicU64,
    material: Arc<VerifiedMaterial>,
}
impl VerifiedOperationalModelLeaseV2 {
    #[must_use]
    pub fn binding(&self) -> &OperationalModelLeaseBindingV2 {
        &self.binding
    }
    #[must_use]
    pub fn runtime_profile(&self) -> &ConservativeCpuRuntimeProfileV2 {
        &self.profile
    }
    #[must_use]
    pub fn measurements(&self) -> &Value {
        &self.body
    }
    #[must_use]
    pub fn evaluator(&self) -> &VerifiedLearningEvidenceV1 {
        &self.evaluator
    }
    #[must_use]
    pub fn authentication_digest(&self) -> Digest32 {
        self.authentication_digest
    }
    #[must_use]
    pub fn scope_digest(&self) -> Digest32 {
        self.scope
    }
    #[must_use]
    pub fn expires_at(&self) -> u64 {
        self.expires_at
    }
    /// Recompute original native measurements and current independent role
    /// signatures before use. Neither stale files nor wall-clock rollback renew
    /// this retained value; no signing key or holdout owner is opened here.
    pub fn revalidate_current(&self) -> HostResult<()> {
        let now = now_ms()?;
        observe_clock(&self.clock_floor, now)?;
        let current = inspect(
            &self.config,
            &self.report,
            now,
            MaterialAdmission::Retained(&self.material),
        )?;
        observe_clock(
            &self.clock_floor,
            current.clock_floor.load(Ordering::Acquire),
        )?;
        if current.authentication_digest != self.authentication_digest
            || current.body != self.body
            || current.binding != self.binding
            || current.profile != self.profile
        {
            return Err("stable model evidence changed at final use".into());
        }
        Ok(())
    }
}
fn observe_clock(floor: &AtomicU64, now: u64) -> HostResult<()> {
    if now < floor.fetch_max(now, Ordering::AcqRel) {
        return Err("stable model current clock rolled backwards".into());
    }
    Ok(())
}

/// Inspect pinned Root files, using only genuine current E evidence. This does
/// not select or mutate a model and never opens a custody/key/holdout store.
pub fn inspect_operational_model_lease_v2(
    config: &Path,
    config_digest: Digest32,
    report: &Path,
    report_digest: Digest32,
) -> HostResult<VerifiedOperationalModelLeaseV2> {
    inspect(
        &Source {
            path: config.to_owned(),
            digest: config_digest.to_string(),
        },
        &Source {
            path: report.to_owned(),
            digest: report_digest.to_string(),
        },
        now_ms()?,
        MaterialAdmission::Original,
    )
}
enum MaterialAdmission<'a> {
    Original,
    Retained(&'a Arc<VerifiedMaterial>),
}
fn inspect(
    config_source: &Source,
    report_source: &Source,
    now: u64,
    material: MaterialAdmission<'_>,
) -> HostResult<VerifiedOperationalModelLeaseV2> {
    let config_bytes = config_source.read(32 * 1024)?;
    let config: Config = serde_json::from_slice(&config_bytes)?;
    let report_bytes = report_source.read(64 * 1024)?;
    let report: Report = serde_json::from_slice(&report_bytes)?;
    let inputs = match material {
        MaterialAdmission::Original => inspect_inputs(&config, now)?,
        MaterialAdmission::Retained(material) => reinspect_inputs(&config, now, material)?,
    };
    let at = report.body["measured_at_ms"]
        .as_u64()
        .ok_or("stable model actual measured instant")?;
    let cgroup = report.body["evaluator_cgroup"]
        .as_str()
        .ok_or("stable model actual E cgroup")?;
    let program: Digest32 = config.program_digest.parse()?;
    if at < inputs.policy.frozen_at_ms
        || at > now
        || program.is_zero()
        || cgroup.len() > 4096
        || !cgroup.contains("hepta-fixed-calibration-eval-")
    {
        return Err("stable model actual E execution identity/clock".into());
    }
    let expected = body(
        &config,
        &inputs,
        Digest32::of_bytes(&config_bytes),
        at,
        program,
        cgroup,
    )?;
    if report.body != expected || report.body["operational_constraints_passed"] != true {
        return Err("stable model report differs from original native evidence/ceilings".into());
    }
    let (_, distribution) = inputs.native.calibration.publication.trust.native()?;
    let reviewer = distribution
        .distribution
        .trust
        .signers
        .iter()
        .find(|s| s.principal.principal_id.as_str() == "fixed-no-custody-reviewer")
        .ok_or("stable model independent reviewer not Root admitted")?;
    crate::fixed_calibration_cycle_evaluator::verify_actual_reviewer(
        reviewer,
        program,
        &inputs.native.calibration.root_key,
        config.uid,
        config.gid,
        None,
    )?;
    let signed = report.evaluator_signed_evidence.native()?;
    let payload = payload(&report.body)?;
    if signed.issued_at != at
        || signed.expires_at > expires_at(&inputs, reviewer.principal.expires_at)?
        || signed.principal_id != reviewer.principal.principal_id
        || signed.evidence_id.as_str()
            != format!("operational.model.v2.{}", Digest32::of_bytes(&payload))
    {
        return Err("stable model signature differs from V2 E identity/current lifetime".into());
    }
    let evaluator = inputs.native.calibration.trust.verifier().verify(
        LearningEvidenceRoleV1::Evaluator,
        &signed,
        &payload,
        now,
    )?;
    for cut in [&inputs.native.calibration, &inputs.native.ood] {
        for actor in &cut.actors {
            verify_signed_actor_separation(actor, &evaluator, now)?;
        }
    }
    let mut authenticated = signed.signing_bytes();
    authenticated.extend_from_slice(&signed.signature);
    let final_now = now_ms()?;
    if final_now < now {
        return Err("stable model clock rolled backwards during admission".into());
    }
    reinspect_inputs(&config, final_now, &inputs.material)?;
    inputs.native.calibration.trust.verifier().verify(
        LearningEvidenceRoleV1::Evaluator,
        &signed,
        &payload,
        final_now,
    )?;
    if config_source.read(32 * 1024)? != config_bytes
        || report_source.read(64 * 1024)? != report_bytes
    {
        return Err("protected stable model inputs changed during admission".into());
    }
    Ok(VerifiedOperationalModelLeaseV2 {
        config: config_source.clone(),
        report: report_source.clone(),
        body: report.body,
        evaluator,
        authentication_digest: Digest32::of_bytes(&authenticated),
        binding: inputs.binding,
        profile: inputs.policy.runtime_profile,
        scope: inputs.policy.scope_digest.parse()?,
        expires_at: signed.expires_at,
        clock_floor: AtomicU64::new(final_now),
        material: inputs.material,
    })
}

#[cfg(test)]
#[path = "operational_model_lease_reader_v2_tests.rs"]
mod tests;
