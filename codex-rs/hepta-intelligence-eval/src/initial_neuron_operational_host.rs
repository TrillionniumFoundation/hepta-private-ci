//! Independent fixed first-install profile. No-change CPU observations cannot
//! become a paired superiority receipt or authorize activation through this API.
use crate::fixed_calibration_host::boundary;
use crate::fixed_calibration_host::key;
use crate::fixed_calibration_host::now_ms;
use crate::initial_neuron_operational_metrics::Gates;
use crate::initial_neuron_operational_metrics::measure;
use crate::initial_neuron_operational_source::Cut;
use crate::initial_neuron_operational_source::HostResult;
use crate::initial_neuron_operational_source::Source;
use crate::initial_neuron_operational_source::inspect_cut;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::ReviewEvidenceWireV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::read_root_review_input;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use serde::Deserialize;
use serde_json::Value;
use serde_json::json;
use std::fs::File;
use std::path::Path;
use std::path::PathBuf;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    schema: String,
    uid: u32,
    gid: u32,
    program_digest: String,
    private_key_path: PathBuf,
    root_verifying_key_hex: String,
    policy: Source,
    baseline_manifest: Source,
    baseline_weights: Source,
    preregistration: Source,
    calibration: Cut,
    ood: Cut,
    inaccessible_paths: Vec<PathBuf>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Policy {
    schema: String,
    generation: u64,
    qualified_predecessor: Option<String>,
    scope_digest: String,
    objective_digest: String,
    baseline_manifest_digest: String,
    baseline_weights_digest: String,
    source_training_digest: String,
    preregistration_digest: String,
    frozen_at_ms: u64,
    expires_at_ms: u64,
    calibration_rows: usize,
    ood_rows: usize,
    claim_scope: String,
    gates: Gates,
}
impl Policy {
    fn validate(&self, now: u64) -> HostResult<()> {
        if self.schema != "hepta.cpu-neuron.initial-operational-policy.v1"
            || self.generation != 1
            || self.qualified_predecessor.is_some()
            || self.frozen_at_ms == 0
            || self.frozen_at_ms > now
            || self.expires_at_ms <= now
            || self.expires_at_ms.saturating_sub(self.frozen_at_ms) > 86_400_000
            || self.claim_scope
                != "initial-operational;training-source-reused;no-unseen-holdout;no-primary-superiority"
            || !(20..=2048).contains(&self.calibration_rows)
            || !(20..=2048).contains(&self.ood_rows)
        {
            return Err("fixed generation-one no-predecessor operational policy".into());
        }
        for digest in [
            &self.scope_digest,
            &self.objective_digest,
            &self.baseline_manifest_digest,
            &self.baseline_weights_digest,
            &self.source_training_digest,
            &self.preregistration_digest,
        ] {
            if digest.parse::<Digest32>()?.is_zero() {
                return Err(
                    "initial operational policy requires all original identity pins".into(),
                );
            }
        }
        self.gates.validate()
    }
}
fn payload(body: &Value) -> HostResult<Vec<u8>> {
    let bytes = serde_json::to_vec(body)?;
    if bytes.len() > 64 * 1024 {
        return Err("bounded initial operational report".into());
    }
    let mut payload = b"hepta.intelligence-eval.initial-operational-anchor.v1".to_vec();
    payload.extend_from_slice(Digest32::of_bytes(&bytes).as_array());
    Ok(payload)
}
/// Run only the protected fixed initial-install policy under the independent
/// evaluator UID. Its evidence attests measurements; S and the durable artifact
/// Owner must separately admit generation one through the existing initial API.
pub fn run_initial_neuron_operational_evaluator(path: &Path) -> HostResult<()> {
    let bytes = read_root_review_input(path, 32 * 1024)?;
    let config: Config = serde_json::from_slice(&bytes)?;
    let cgroup = boundary(config.uid, config.gid)?;
    let program = Digest32::of_bytes(&read_root_review_input(
        &std::env::current_exe()?,
        128 * 1024 * 1024,
    )?);
    if config.schema != "hepta.fixed-initial-neuron-evaluator-config.v1"
        || program != config.program_digest.parse::<Digest32>()?
        || config.inaccessible_paths.len() != 5
    {
        return Err("initial fixed evaluator actual program/custody binding".into());
    }
    for inaccessible in &config.inaccessible_paths {
        match File::open(inaccessible) {
            Err(error) if error.kind() == std::io::ErrorKind::PermissionDenied => (),
            _ => {
                return Err(
                    "independent initial evaluator can read source gold or another key".into(),
                );
            }
        }
    }
    let now = now_ms()?;
    let policy: Policy = serde_json::from_slice(&config.policy.read(32 * 1024)?)?;
    policy.validate(now)?;
    let manifest = config.baseline_manifest.read(16 * 1024)?;
    let weights = config.baseline_weights.read(8 * 1024 * 1024)?;
    let manifest_digest = Digest32::of_bytes(&manifest);
    let weights_digest = Digest32::of_bytes(&weights);
    let manifest: Value = serde_json::from_slice(&manifest)?;
    let registration: Value = serde_json::from_slice(&config.preregistration.read(16 * 1024)?)?;
    if manifest_digest.to_string() != policy.baseline_manifest_digest
        || weights_digest.to_string() != policy.baseline_weights_digest
        || manifest["weights_digest"] != policy.baseline_weights_digest
        || registration["schema"]
            != "hepta.scifact.public-training.initial-anchor-preregistration.v1"
        || registration["original_calibration_read"] != false
        || registration["original_holdout_read"] != false
        || registration["no_historical_unseen_holdout_claim"] != true
        || registration["source_sha256"] != policy.source_training_digest
        || config.preregistration.digest != policy.preregistration_digest
        || config.calibration.expected_rows != policy.calibration_rows
        || config.ood.expected_rows != policy.ood_rows
    {
        return Err("initial baseline or preregistered public training cut changed".into());
    }
    let scope = policy.scope_digest.parse()?;
    let objective = policy.objective_digest.parse()?;
    let calibration = inspect_cut(
        &config.calibration,
        manifest_digest,
        weights_digest,
        scope,
        objective,
        policy.frozen_at_ms,
        now,
    )?;
    let ood = inspect_cut(
        &config.ood,
        manifest_digest,
        weights_digest,
        scope,
        objective,
        policy.frozen_at_ms,
        now,
    )?;
    if calibration.root_key != ood.root_key
        || calibration.publication.trust.root_verifying_key_hex != config.root_verifying_key_hex
        || ood.publication.trust.root_verifying_key_hex != config.root_verifying_key_hex
        || calibration.trust.distribution_digest() != ood.trust.distribution_digest()
    {
        return Err("initial source current root/trust differs between frozen cuts".into());
    }
    let calibration_dataset = calibration.publication.cut.dataset.native()?;
    let ood_dataset = ood.publication.cut.dataset.native()?;
    if calibration_dataset
        .snapshot
        .source_record_digests
        .iter()
        .any(|digest| ood_dataset.snapshot.source_record_digests.contains(digest))
    {
        return Err("initial calibration/OOD source records overlap".into());
    }
    let (_, distribution) = calibration.publication.trust.native()?;
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
        &calibration.root_key,
        config.uid,
        config.gid,
        None,
    )?;
    let signing = key(&config.private_key_path, config.uid)?;
    if Digest32::of_bytes(signing.verifying_key().as_bytes())
        != reviewer.principal.signing_key_digest
    {
        return Err("initial independent evaluator owns a different key".into());
    }
    let calibration_metrics = measure(&calibration, &policy.gates)?;
    let ood_metrics = measure(&ood, &policy.gates)?;
    let body = json!({"schema":"hepta.cpu-neuron.initial-operational-measurements.v1",
        "generation":1,"qualified_predecessor":null,"claim_scope":policy.claim_scope,
        "policy_digest":config.policy.digest,"source_training_digest":policy.source_training_digest,
        "preregistration_digest":policy.preregistration_digest,"model_manifest_digest":manifest_digest.to_string(),
        "weights_digest":weights_digest.to_string(),"calibration_cut_digest":config.calibration.publication.digest,
        "ood_cut_digest":config.ood.publication.digest,"calibration_dataset_digest":calibration_dataset.snapshot.dataset_digest.to_string(),
        "ood_dataset_digest":ood_dataset.snapshot.dataset_digest.to_string(),
        "calibration":calibration_metrics,"ood":ood_metrics,
        "operational_constraints_passed":calibration_metrics.operational_constraints_passed && ood_metrics.operational_constraints_passed,
        "evaluator_uid":config.uid,"evaluator_gid":config.gid,"evaluator_cgroup":cgroup,
        "evaluator_program_digest":program.to_string(),"config_digest":Digest32::of_bytes(&bytes).to_string(),
        "measured_at_ms":now,"original_calibration_read":false,"original_holdout_read":false,
        "historical_unseen_holdout_claim":false,"primary_superiority_claim":false,
        "qualified":false,"authority_grants_any":false,"holdout_consumed":false,"production_activation":false});
    let payload = payload(&body)?;
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: StableId::new(format!(
            "initial.operational.{}",
            Digest32::of_bytes(&payload)
        ))?,
        principal_id: reviewer.principal.principal_id.clone(),
        role: LearningEvidenceRoleV1::Evaluator,
        trust_digest: calibration.trust.verifier().trust_digest(),
        scope_digest: scope,
        objective_digest: objective,
        authority_epoch: reviewer.principal.authority_epoch,
        issued_at: now,
        expires_at: policy.expires_at_ms.min(reviewer.principal.expires_at),
        payload_digest: Digest32::of_bytes(&payload),
        signature: [0; 64],
    };
    evidence.signature = signing.sign(&evidence.signing_bytes()).to_bytes();
    let actual = calibration.trust.verifier().verify(
        LearningEvidenceRoleV1::Evaluator,
        &evidence,
        &payload,
        now,
    )?;
    for source in [&calibration, &ood] {
        for actor in &source.actors {
            verify_signed_actor_separation(actor, &actual, now)?;
        }
    }
    // Revalidate current lifetime and original source pins at the final use.
    let final_now = now_ms()?;
    policy.validate(final_now)?;
    if read_root_review_input(path, 32 * 1024)? != bytes {
        return Err("initial root policy changed before final evaluation use".into());
    }
    config.policy.read(32 * 1024)?;
    config.baseline_manifest.read(16 * 1024)?;
    config.baseline_weights.read(8 * 1024 * 1024)?;
    config.preregistration.read(16 * 1024)?;
    for cut in [&config.calibration, &config.ood] {
        inspect_cut(
            cut,
            manifest_digest,
            weights_digest,
            scope,
            objective,
            policy.frozen_at_ms,
            final_now,
        )?;
    }
    calibration.trust.verifier().verify(
        LearningEvidenceRoleV1::Evaluator,
        &evidence,
        &payload,
        final_now,
    )?;
    println!(
        "{}",
        serde_json::to_string(
            &json!({"body":body,"evaluator_signed_evidence":ReviewEvidenceWireV1::from_native(&evidence)})
        )?
    );
    Ok(())
}

#[cfg(test)]
#[path = "initial_neuron_operational_host_tests.rs"]
mod tests;
