//! A current-use reader for the independent initial operational measurement.
//! Root-protected bytes and a historical signature alone cannot mint this value:
//! every native source, lifetime, role and numeric measurement is revalidated.
use crate::fixed_calibration_host::now_ms;
use crate::initial_neuron_operational_host::Config;
use crate::initial_neuron_operational_host::inspect_inputs;
use crate::initial_neuron_operational_host::measurement_body;
use crate::initial_neuron_operational_host::payload;
use crate::initial_neuron_operational_source::HostResult;
use crate::initial_neuron_operational_source::Source;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::ReviewEvidenceWireV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde_json::Value;
use std::path::Path;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Report {
    body: Value,
    evaluator_signed_evidence: ReviewEvidenceWireV1,
}

/// Genuine initial operational measurements, restricted to generation one and
/// no predecessor. This grants no primary superiority or activation authority.
/// The durable Owner and independently admitted selector remain mandatory.
pub struct VerifiedInitialOperationalEvidenceV1 {
    config: Source,
    report: Source,
    body: Value,
    evaluator: VerifiedLearningEvidenceV1,
    authentication_digest: Digest32,
    manifest: Digest32,
    weights: Digest32,
    scope: Digest32,
    objective: Digest32,
    expires_at: u64,
}
impl VerifiedInitialOperationalEvidenceV1 {
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
    pub fn model_manifest_digest(&self) -> Digest32 {
        self.manifest
    }
    #[must_use]
    pub fn weights_digest(&self) -> Digest32 {
        self.weights
    }
    #[must_use]
    pub fn scope_digest(&self) -> Digest32 {
        self.scope
    }
    #[must_use]
    pub fn objective_digest(&self) -> Digest32 {
        self.objective
    }
    #[must_use]
    pub fn expires_at(&self) -> u64 {
        self.expires_at
    }
    /// Present only for a Root-frozen complete CPU deployment profile that the
    /// independent evaluator included in this exact signed measurement.
    #[must_use]
    pub fn initial_product_profile_digest(&self) -> Option<Digest32> {
        self.body
            .get("initial_product_profile_digest")
            .and_then(Value::as_str)
            .and_then(|pin| pin.parse().ok())
    }
    /// Check the original current sources and protected inputs immediately at
    /// use. Expired source credentials cannot be refreshed by copying a report.
    pub fn revalidate_current(&self) -> HostResult<()> {
        let current = inspect(&self.config, &self.report)?;
        if current.authentication_digest != self.authentication_digest || current.body != self.body
        {
            return Err("initial operational evidence changed at final use".into());
        }
        Ok(())
    }
}

/// Read only pinned Root-owned files. This does not open any role's private key,
/// sign a new claim, repair a store, consume holdout, or select an artifact.
pub fn inspect_initial_neuron_operational_evidence(
    config: &Path,
    config_digest: Digest32,
    report: &Path,
    report_digest: Digest32,
) -> HostResult<VerifiedInitialOperationalEvidenceV1> {
    inspect(
        &Source {
            path: config.to_owned(),
            digest: config_digest.to_string(),
        },
        &Source {
            path: report.to_owned(),
            digest: report_digest.to_string(),
        },
    )
}
fn inspect(
    config_source: &Source,
    report_source: &Source,
) -> HostResult<VerifiedInitialOperationalEvidenceV1> {
    let config_bytes = config_source.read(32 * 1024)?;
    let config: Config = serde_json::from_slice(&config_bytes)?;
    let report_bytes = report_source.read(64 * 1024)?;
    let report: Report = serde_json::from_slice(&report_bytes)?;
    let now = now_ms()?;
    let inputs = inspect_inputs(&config, now)?;
    let at = report.body["measured_at_ms"]
        .as_u64()
        .ok_or("initial measured instant")?;
    let cgroup = report.body["evaluator_cgroup"]
        .as_str()
        .ok_or("initial actual evaluator cgroup")?;
    let program: Digest32 = config.program_digest.parse()?;
    if at < inputs.policy.frozen_at_ms
        || at > now
        || program.is_zero()
        || cgroup.len() > 4096
        || !cgroup.contains("hepta-fixed-calibration-eval-")
    {
        return Err("initial actual evaluator execution identity/clock".into());
    }
    let expected = measurement_body(
        &config,
        &inputs,
        Digest32::of_bytes(&config_bytes),
        at,
        program,
        cgroup,
    )?;
    if report.body != expected || report.body["operational_constraints_passed"] != true {
        return Err(
            "initial operational report differs from original native numeric evidence".into(),
        );
    }
    let (_, distribution) = inputs.calibration.publication.trust.native()?;
    let reviewer = distribution
        .distribution
        .trust
        .signers
        .iter()
        .find(|signer| signer.principal.principal_id.as_str() == "fixed-no-custody-reviewer")
        .ok_or("initial independent reviewer not root admitted")?;
    crate::fixed_calibration_cycle_evaluator::verify_actual_reviewer(
        reviewer,
        program,
        &inputs.calibration.root_key,
        config.uid,
        config.gid,
        None,
    )?;
    let signed = report.evaluator_signed_evidence.native()?;
    let payload = payload(&report.body)?;
    if signed.issued_at != at
        || signed.expires_at > inputs.policy.expires_at_ms
        || signed.principal_id != reviewer.principal.principal_id
        || signed.evidence_id.as_str()
            != format!("initial.operational.{}", Digest32::of_bytes(&payload))
    {
        return Err("initial measurement signature profile mismatch".into());
    }
    let evaluator = inputs.calibration.trust.verifier().verify(
        LearningEvidenceRoleV1::Evaluator,
        &signed,
        &payload,
        now,
    )?;
    for source in [&inputs.calibration, &inputs.ood] {
        for actor in &source.actors {
            verify_signed_actor_separation(actor, &evaluator, now)?;
        }
    }
    let mut authenticated = signed.signing_bytes();
    authenticated.extend_from_slice(&signed.signature);
    // Do not retain a value that crossed a source expiry while reading the cuts.
    let final_now = now_ms()?;
    inputs.policy.validate(final_now)?;
    inspect_inputs(&config, final_now)?;
    inputs.calibration.trust.verifier().verify(
        LearningEvidenceRoleV1::Evaluator,
        &signed,
        &payload,
        final_now,
    )?;
    if config_source.read(32 * 1024)? != config_bytes
        || report_source.read(64 * 1024)? != report_bytes
    {
        return Err("initial protected inputs changed during current admission".into());
    }
    let mut expires_at = signed.expires_at.min(inputs.policy.expires_at_ms);
    for source in [&inputs.calibration, &inputs.ood] {
        for actor in &source.actors {
            expires_at = expires_at.min(actor.principal().expires_at);
        }
        for original in [
            source.publication.cut.generator_evidence.native()?,
            source.publication.cut.freeze_evidence.native()?,
            source.publication.observer_evidence.native()?,
        ] {
            expires_at = expires_at.min(original.expires_at);
        }
    }
    Ok(VerifiedInitialOperationalEvidenceV1 {
        config: config_source.clone(),
        report: report_source.clone(),
        body: report.body,
        evaluator,
        authentication_digest: Digest32::of_bytes(&authenticated),
        manifest: inputs.manifest_digest,
        weights: inputs.weights_digest,
        scope: inputs.policy.scope_digest.parse()?,
        objective: inputs.policy.objective_digest.parse()?,
        expires_at,
    })
}
