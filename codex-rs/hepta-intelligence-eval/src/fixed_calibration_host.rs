//! Fixed no-custody evaluator: only its own key and authenticated readonly cuts.
use crate::CalibrationPreflightDispositionV1;
use crate::SignedCalibrationPreflightRequestV1;
use crate::fixed_calibration_cycle_evaluator::decide_profile;
use crate::fixed_calibration_cycle_evaluator::preflight_payload;
use crate::fixed_calibration_cycle_evaluator::profile_matches;
use crate::fixed_calibration_cycle_evaluator::read_publication;
use crate::fixed_calibration_cycle_evaluator::result_schema;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LedgerAnchor;
use codex_hepta_learning_ledger::ReviewEvidenceWireV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::activate_learning_trust;
use codex_hepta_learning_ledger::decode_review_payload_hex;
use codex_hepta_learning_ledger::inspect_ledger;
use codex_hepta_learning_ledger::open_root_review_input;
use codex_hepta_learning_ledger::read_root_review_input;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde::Deserialize;
use std::fs::File;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;
type HostResult<T> = Result<T, Box<dyn std::error::Error>>;
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    schema: String,
    uid: u32,
    gid: u32,
    program_digest: String,
    private_key_path: PathBuf,
    root_verifying_key_hex: String,
    publication_path: PathBuf,
    ledger_path: PathBuf,
    observer_program_digest: String,
    candidate_weights_digest: String,
    baseline_weights_digest: String,
    objective_digest: String,
    scope_digest: String,
    minimum_primary_improvement_q32: i64,
    inaccessible_paths: Vec<PathBuf>,
    #[serde(default)]
    current_program_approval_digest: Option<String>,
}
pub(crate) fn now_ms() -> HostResult<u64> {
    Ok(u64::try_from(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)?
            .as_millis(),
    )?)
}
fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}
pub(crate) fn boundary(uid: u32, gid: u32) -> HostResult<String> {
    let status = std::fs::read_to_string("/proc/self/status")?;
    let field = |n: &str| {
        status
            .lines()
            .find_map(|s| s.strip_prefix(n))
            .unwrap_or("")
            .trim()
    };
    if uid == 0
        || field("Uid:").split_whitespace().count() != 4
        || field("Gid:").split_whitespace().count() != 4
        || field("Uid:")
            .split_whitespace()
            .any(|s| s != uid.to_string())
        || field("Gid:")
            .split_whitespace()
            .any(|s| s != gid.to_string())
        || !field("Groups:").is_empty()
        || field("NoNewPrivs:") != "1"
        || ["CapInh:", "CapPrm:", "CapEff:", "CapBnd:", "CapAmb:"]
            .iter()
            .any(|n| field(n) != "0000000000000000")
    {
        return Err("fixed evaluator requires actual non-root UID/GID, empty groups, zero capabilities and NoNewPrivileges".into());
    }
    let cgroup = std::fs::read_to_string("/proc/self/cgroup")?;
    if !cgroup.contains("hepta-fixed-calibration-eval-") {
        return Err("fixed evaluator requires its bounded service cgroup".into());
    }
    Ok(cgroup)
}
fn key_directory(path: &Path, uid: u32) -> HostResult<()> {
    if !path.is_absolute()
        || path
            .components()
            .any(|c| matches!(c, Component::CurDir | Component::ParentDir))
    {
        return Err("canonical evaluator key location required".into());
    }
    for ancestor in path.ancestors() {
        let m = std::fs::symlink_metadata(ancestor)?;
        if !m.is_dir() || (m.uid() != 0 && m.uid() != uid) || m.mode() & 0o022 != 0 {
            return Err("unprotected evaluator key ancestor".into());
        }
    }
    let m = path.metadata()?;
    if m.uid() != uid || m.mode() & 0o077 != 0 {
        return Err("evaluator key directory must be private to its UID".into());
    }
    Ok(())
}
pub(crate) fn key(path: &Path, uid: u32) -> HostResult<SigningKey> {
    key_directory(path.parent().ok_or("key parent")?, uid)?;
    let before = std::fs::symlink_metadata(path)?;
    if !before.is_file()
        || before.uid() != uid
        || before.nlink() != 1
        || before.len() != 32
        || before.mode() & 0o077 != 0
    {
        return Err("evaluator key owner/mode/width".into());
    }
    let mut file = File::open(path)?;
    let after = file.metadata()?;
    if after.dev() != before.dev() || after.ino() != before.ino() {
        return Err("evaluator key changed while opening".into());
    }
    let mut seed = [0; 32];
    file.read_exact(&mut seed)?;
    Ok(SigningKey::from_bytes(&seed))
}
pub fn initialize_fixed_evaluator_key(path: &Path, uid: u32, gid: u32) -> HostResult<()> {
    boundary(uid, gid)?;
    key_directory(path.parent().ok_or("key parent")?, uid)?;
    if !path.exists() {
        let mut seed = [0; 32];
        File::open("/dev/urandom")?.read_exact(&mut seed)?;
        let mut f = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(path)?;
        f.write_all(&seed)?;
        f.sync_all()?;
        File::open(path.parent().ok_or("key parent")?)?.sync_all()?;
    }
    println!(
        "{}",
        serde_json::json!({"schema":"hepta.fixed-evaluator-public-key.v1","uid":uid,"gid":gid,"verifying_key_hex":hex(key(path,uid)?.verifying_key().as_bytes()),"qualified":false})
    );
    Ok(())
}
pub fn run_fixed_calibration_evaluator(path: &Path) -> HostResult<()> {
    let config_bytes = read_root_review_input(path, 32 * 1024)?;
    let config: Config = serde_json::from_slice(&config_bytes)?;
    let cgroup = boundary(config.uid, config.gid)?;
    let program = Digest32::of_bytes(&read_root_review_input(
        &std::env::current_exe()?,
        128 * 1024 * 1024,
    )?);
    if !profile_matches(&config.schema, None)
        || program != config.program_digest.parse::<Digest32>()?
        || config.inaccessible_paths.len() != 5
    {
        return Err("fixed evaluator program/custody profile".into());
    }
    for inaccessible in &config.inaccessible_paths {
        match File::open(inaccessible){Err(e) if e.kind()==std::io::ErrorKind::PermissionDenied=>(),_=>return Err("fixed evaluator can access gold/another key or the denial is not permission-enforced".into())}
    }
    let (publication, cycle) = read_publication(&read_root_review_input(
        &config.publication_path,
        4 * 1024 * 1024,
    )?)?;
    if !profile_matches(&config.schema, Some(cycle.is_some())) {
        return Err("evaluator config/publication profile mismatch".into());
    }
    if cycle
        .as_ref()
        .map(|v| v.current_program_approval_digest.to_string())
        != config.current_program_approval_digest
    {
        return Err("current evaluator frozen original program approval mismatch".into());
    }
    let cut = &publication.cut;
    if cut.schema != "hepta.signed-calibration-cut.v1"
        || cut.observer_program_digest != config.observer_program_digest
        || cut.candidate_weights_digest != config.candidate_weights_digest
        || cut.baseline_weights_digest != config.baseline_weights_digest
        || publication.trust.root_verifying_key_hex != config.root_verifying_key_hex
        || publication.trust.objective_digest != config.objective_digest
        || publication.trust.scope_digest != config.scope_digest
    {
        return Err("frozen evaluator policy/protected observer identity".into());
    }
    let (root, distribution) = publication.trust.native()?;
    let now = now_ms()?;
    let reviewer = distribution
        .distribution
        .trust
        .signers
        .iter()
        .find(|s| s.principal.principal_id.as_str() == "fixed-no-custody-reviewer")
        .ok_or("no fixed reviewer admitted")?
        .clone();
    let trust = activate_learning_trust(&root, distribution, None, now)?;
    crate::fixed_calibration_cycle_evaluator::verify_actual_reviewer(
        &reviewer,
        program,
        &root.verifying_key,
        config.uid,
        config.gid,
        cycle.as_ref(),
    )?;
    let reviewer = reviewer.principal;
    let signing = key(&config.private_key_path, config.uid)?;
    if Digest32::of_bytes(signing.verifying_key().as_bytes()) != reviewer.signing_key_digest {
        return Err("evaluator owns a different key than the root-admitted reviewer".into());
    }
    let ledger_bytes = read_root_review_input(&config.ledger_path, 8 * 1024 * 1024)?;
    if Digest32::of_bytes(&ledger_bytes) != cut.ledger_file_digest.parse::<Digest32>()? {
        return Err("readonly anchored ledger changed".into());
    }
    let snapshot = inspect_ledger(
        open_root_review_input(&config.ledger_path)?,
        cut.ledger_binding_digest.parse()?,
        4096,
        LedgerAnchor {
            sequence: cut.acknowledged_sequence,
            chain_digest: cut.acknowledged_head.parse()?,
        },
    )?;
    let dataset = cut.dataset.native()?;
    let cut_binding = cut.binding()?;
    let cut_payload = cycle.as_ref().map_or_else(
        || cut.signing_payload(),
        |c| {
            Ok(
                codex_hepta_learning_ledger::calibration_cycle_cut_signing_payload_v2(
                    &cut_binding,
                    c,
                ),
            )
        },
    )?;
    let margin = FixedQ32::from_raw(config.minimum_primary_improvement_q32);
    let payload = preflight_payload(&cut_payload, margin, cycle.is_some())?;
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: StableId::new(format!("fixed.calibration.review.{}", cut.audit_digest))?,
        principal_id: reviewer.principal_id.clone(),
        role: LearningEvidenceRoleV1::Evaluator,
        trust_digest: trust.verifier().trust_digest(),
        scope_digest: reviewer.scope_digest,
        objective_digest: config.objective_digest.parse()?,
        authority_epoch: reviewer.authority_epoch,
        issued_at: now,
        expires_at: now
            .checked_add(3600000)
            .ok_or("expiry overflow")?
            .min(reviewer.expires_at),
        payload_digest: Digest32::of_bytes(&payload),
        signature: [0; 64],
    };
    evidence.signature = signing.sign(&evidence.signing_bytes()).to_bytes();
    let generator = cut.generator_evidence.native()?;
    let observer = publication.observer_evidence.native()?;
    let producer = cut.freeze_evidence.native()?;
    let decision = decide_profile(
        SignedCalibrationPreflightRequestV1 {
            snapshot: &snapshot,
            dataset: &dataset,
            cut_binding: &cut_binding,
            generator_payload: &decode_review_payload_hex(&cut.generator_payload_hex)?,
            minimum_primary_improvement: margin,
            generator: &generator,
            observer: &observer,
            producer: &producer,
            evaluator: &evidence,
        },
        cycle.as_ref(),
        trust.verifier(),
        now,
    )?;
    // These cannot be synthesized from this calibration cut. The existing product
    // qualification runner remains the required ingress for a future passing model.
    let missing = [
        "frozen_cross_fold_plan_before_final_holdout",
        "fenced_final_holdout_use",
        "genuine_deployed_reference_outputs_and_costs",
        "registered_confidence_support_retention_unlearning_evidence",
        "product_runner_signed_qualification_receipt",
        "independent_selector_exact_tuple_acceptance",
    ];
    let output = serde_json::json!({"schema":result_schema(cycle.is_some()),"calibration_cycle":cycle.as_ref().map(codex_hepta_learning_ledger::CalibrationCycleScopeWireV2::from_native),"disposition":match decision.disposition{CalibrationPreflightDispositionV1::Rejected=>"rejected",CalibrationPreflightDispositionV1::RequiresFinalQualification=>"requires_final_qualification"},"candidate_correct":decision.candidate_correct,"baseline_correct":decision.baseline_correct,"labeled_pairs":decision.labeled_pairs,"observed_improvement_q32":decision.observed_improvement.raw(),"minimum_primary_improvement_q32":margin.raw(),"dataset_digest":decision.dataset_digest.to_string(),"evaluation_evidence_digest":decision.evidence_digest.to_string(),"evaluator_signed_evidence":ReviewEvidenceWireV1::from_native(&evidence),"evaluator_uid":config.uid,"evaluator_gid":config.gid,"evaluator_cgroup":cgroup,"evaluator_groups_empty":true,"evaluator_capabilities_zero":true,"evaluator_no_new_privileges":true,"denied_gold_and_other_keys":config.inaccessible_paths.len(),"pairwise_generator_observer_evaluator_verified":true,"producer_evaluator_separation_verified":true,"ledger_and_dataset_verified":true,"policy_config_digest":Digest32::of_bytes(&config_bytes).to_string(),"qualification_missing":missing,"qualified":false,"authority_grants_any":false,"holdout_consumed":false,"production_activation":false});
    if Digest32::of_bytes(&read_root_review_input(
        &config.ledger_path,
        8 * 1024 * 1024,
    )?) != cut.ledger_file_digest.parse::<Digest32>()?
    {
        return Err("readonly ledger changed during independent evaluation".into());
    }
    println!("{}", serde_json::to_string(&output)?);
    Ok(())
}

/// Revalidate an existing independent result without reading any private key.
/// The Root product provider supplies protected bytes and an independently
/// pinned evaluator executable. Expiry remains pending, never qualification.
pub(crate) fn read_fixed_calibration_result(
    config_bytes: &[u8],
    evaluator_program: Digest32,
    result_bytes: &[u8],
    now: u64,
) -> HostResult<serde_json::Value> {
    if config_bytes.len() > 32 * 1024 || result_bytes.len() > 64 * 1024 {
        return Err("bounded evaluator policy/result".into());
    }
    let config: Config = serde_json::from_slice(config_bytes)?;
    let output: serde_json::Value = serde_json::from_slice(result_bytes)?;
    if !profile_matches(&config.schema, None)
        || config.program_digest.parse::<Digest32>()? != evaluator_program
        || config.uid == 0
        || config.gid == 0
        || config.inaccessible_paths.len() != 5
        || output["schema"] != result_schema(config.schema.ends_with(".v2"))
        || output["policy_config_digest"] != Digest32::of_bytes(config_bytes).to_string()
        || output["evaluator_uid"] != config.uid
        || output["evaluator_gid"] != config.gid
        || output["qualified"] != false
        || output["production_activation"] != false
        || output["holdout_consumed"] != false
        || output["authority_grants_any"] != false
    {
        return Err("independent result/pinned policy/program binding".into());
    }
    let evidence: ReviewEvidenceWireV1 =
        serde_json::from_value(output["evaluator_signed_evidence"].clone())?;
    let evidence = evidence.native()?;
    if evidence.principal_id.as_str() != "fixed-no-custody-reviewer" {
        return Err("fixed reviewer identity".into());
    }
    let publication_bytes = read_root_review_input(&config.publication_path, 4 * 1024 * 1024)?;
    let (publication, cycle) = read_publication(&publication_bytes)?;
    if !profile_matches(&config.schema, Some(cycle.is_some())) {
        return Err("evaluator config/publication profile mismatch".into());
    }
    let expected_cycle = cycle
        .as_ref()
        .map(codex_hepta_learning_ledger::CalibrationCycleScopeWireV2::from_native)
        .map(serde_json::to_value)
        .transpose()?
        .unwrap_or(serde_json::Value::Null);
    if output
        .get("calibration_cycle")
        .unwrap_or(&serde_json::Value::Null)
        != &expected_cycle
    {
        return Err("original evaluator signed cycle scope mismatch".into());
    }
    if cycle
        .as_ref()
        .map(|v| v.current_program_approval_digest.to_string())
        != config.current_program_approval_digest
    {
        return Err("current evaluator frozen original program approval mismatch".into());
    }
    let cut = &publication.cut;
    if cut.schema != "hepta.signed-calibration-cut.v1"
        || cut.observer_program_digest != config.observer_program_digest
        || cut.candidate_weights_digest != config.candidate_weights_digest
        || cut.baseline_weights_digest != config.baseline_weights_digest
        || publication.trust.root_verifying_key_hex != config.root_verifying_key_hex
        || publication.trust.objective_digest != config.objective_digest
        || publication.trust.scope_digest != config.scope_digest
    {
        return Err("protected custody cut/evaluator policy".into());
    }
    // Expired artifacts remain original evidence, but cannot authorize a new
    // execution. Do not move the verification clock backwards to accept them.
    if now > evidence.expires_at {
        return Ok(
            serde_json::json!({"state":"pending_fresh_independent_evaluation","current_authentication":false,
            "original_result_digest":Digest32::of_bytes(result_bytes).to_string(),"original_signed_result":output,
            "qualification":false,"original_custody_publication":serde_json::from_slice::<serde_json::Value>(&publication_bytes)?}),
        );
    }
    let (root, distribution) = publication.trust.native()?;
    let reviewer = distribution
        .distribution
        .trust
        .signers
        .iter()
        .find(|s| s.principal.principal_id.as_str() == "fixed-no-custody-reviewer")
        .ok_or("current reviewer missing")?;
    crate::fixed_calibration_cycle_evaluator::verify_actual_reviewer(
        reviewer,
        evaluator_program,
        &root.verifying_key,
        config.uid,
        config.gid,
        cycle.as_ref(),
    )?;
    let trust = activate_learning_trust(&root, distribution, None, now)?;
    let before = read_root_review_input(&config.ledger_path, 8 * 1024 * 1024)?;
    if Digest32::of_bytes(&before) != cut.ledger_file_digest.parse::<Digest32>()? {
        return Err("readonly ledger cut changed".into());
    }
    let snapshot = inspect_ledger(
        open_root_review_input(&config.ledger_path)?,
        cut.ledger_binding_digest.parse()?,
        4096,
        LedgerAnchor {
            sequence: cut.acknowledged_sequence,
            chain_digest: cut.acknowledged_head.parse()?,
        },
    )?;
    let dataset = cut.dataset.native()?;
    let binding = cut.binding()?;
    let generator = cut.generator_evidence.native()?;
    let observer = publication.observer_evidence.native()?;
    let producer = cut.freeze_evidence.native()?;
    let generator_payload = decode_review_payload_hex(&cut.generator_payload_hex)?;
    let margin = FixedQ32::from_raw(config.minimum_primary_improvement_q32);
    let decision = decide_profile(
        SignedCalibrationPreflightRequestV1 {
            snapshot: &snapshot,
            dataset: &dataset,
            cut_binding: &binding,
            generator_payload: &generator_payload,
            minimum_primary_improvement: margin,
            generator: &generator,
            observer: &observer,
            producer: &producer,
            evaluator: &evidence,
        },
        cycle.as_ref(),
        trust.verifier(),
        now,
    )?;
    let disposition = match decision.disposition {
        CalibrationPreflightDispositionV1::Rejected => "rejected",
        CalibrationPreflightDispositionV1::RequiresFinalQualification => {
            "requires_final_qualification"
        }
    };
    if output["disposition"] != disposition
        || output["candidate_correct"] != decision.candidate_correct
        || output["baseline_correct"] != decision.baseline_correct
        || output["labeled_pairs"] != decision.labeled_pairs
        || output["dataset_digest"] != decision.dataset_digest.to_string()
        || output["evaluation_evidence_digest"] != decision.evidence_digest.to_string()
        || before != read_root_review_input(&config.ledger_path, 8 * 1024 * 1024)?
    {
        return Err("independent output/native decision mismatch".into());
    }
    Ok(
        serde_json::json!({"state":disposition,"current_authentication":true,
        "original_result_digest":Digest32::of_bytes(result_bytes).to_string(),"original_signed_result":output,
        "qualification":false,"original_custody_publication":serde_json::from_slice::<serde_json::Value>(&publication_bytes)?}),
    )
}
