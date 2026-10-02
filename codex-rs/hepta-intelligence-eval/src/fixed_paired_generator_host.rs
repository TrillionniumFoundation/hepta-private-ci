//! Actual unprivileged G freezes source memberships and measured input hashes.
//! Numeric execution and gold access belong to the original after-CAS custody.
use crate::paired_development_transport::Encoder;
use crate::paired_development_transport::Source;
use crate::paired_development_transport::measure;
use crate::*;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::ReviewEvidenceWireV1;
use codex_hepta_learning_ledger::ReviewTrustWireV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::activate_learning_trust;
use codex_hepta_learning_ledger::decode_review_payload_hex;
use codex_hepta_learning_ledger::read_root_review_input;
use codex_hepta_types::Digest32;
use ed25519_dalek::Signer;
use serde::Deserialize;
use std::collections::BTreeMap;
use std::fs::File;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;
use std::time::Instant;
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    schema: String,
    uid: u32,
    gid: u32,
    program_digest: String,
    private_key_path: PathBuf,
    root_verifying_key_hex: String,
    source: Source,
    scope_digest: String,
    objective_digest: String,
    distribution_generation: u64,
    authority_epoch: u64,
    inaccessible_paths: Vec<PathBuf>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Pair {
    source_record_digest: String,
    pair_id: String,
    source_row_sha256: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Inputs {
    schema: String,
    plan_inputs_hex: String,
    trust: ReviewTrustWireV1,
    encoder: Encoder,
    batch_id: String,
    pairs: Vec<Pair>,
    timeout_ms: u64,
    expected_output_width: usize,
}
fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}
fn sample(
    trust: &codex_hepta_learning_ledger::ActivatedLearningTrustV1,
    last: &mut Option<u64>,
) -> Result<u64> {
    let now = crate::fixed_calibration_host::now_ms()?;
    if last.is_some_and(|old| now < old) || !trust.is_current_at(now) {
        return Err("original G clock/distribution expired or rolled back".into());
    }
    *last = Some(now);
    Ok(now)
}
fn actual_generator(
    signer: &codex_hepta_learning_ledger::TrustedLearningSignerV1,
    program: Digest32,
    uid: u32,
    root: &[u8; 32],
) -> Result<()> {
    let launcher = Digest32::of_bytes(&read_root_review_input(
        Path::new("/usr/bin/setpriv"),
        16 * 1024 * 1024,
    )?);
    let manager = Digest32::of_bytes(&read_root_review_input(
        Path::new("/usr/bin/systemd-run"),
        16 * 1024 * 1024,
    )?);
    // Reuse the original Generator controller/credential convention.
    let controller = format!("bounded-generator.{}", Digest32::of_bytes(&[
        program.as_array().as_slice(), uid.to_be_bytes().as_slice(), launcher.as_array(), manager.as_array(),
        b"clear-groups;all-caps-zero;no-new-privileges;cgroup-memory-256MiB-pids16-cpu100;protected-eval-custody"
    ].concat()));
    let credential = Digest32::of_bytes(
        &[
            root.as_slice(),
            signer.verifying_key.as_slice(),
            controller.as_bytes(),
        ]
        .concat(),
    );
    if signer.controller_id.as_str() != controller
        || signer.principal.credential_chain_digest != credential
        || signer.roles != [LearningEvidenceRoleV1::Generator]
        || signer.principal.signing_key_digest != Digest32::of_bytes(&signer.verifying_key)
    {
        return Err("admitted G is not actual immutable Generator program/UID/key".into());
    }
    Ok(())
}
fn actual_limits(cgroup: &str) -> Result<()> {
    let group = cgroup
        .strip_prefix("0::/system.slice/")
        .and_then(|value| value.strip_suffix('\n'))
        .filter(|value| !value.contains('/') && value.starts_with("hepta-native-generator-"))
        .ok_or("actual sole Root-managed unified G cgroup required")?;
    let path = Path::new("/sys/fs/cgroup/system.slice").join(group);
    let memory = std::fs::read_to_string(path.join("memory.max"))?;
    let pids = std::fs::read_to_string(path.join("pids.max"))?;
    let cpu = std::fs::read_to_string(path.join("cpu.max"))?;
    let parts: Vec<_> = cpu.split_whitespace().collect();
    if memory.trim() != "268435456" || pids.trim() != "16" || parts.len() != 2 {
        return Err("original admitted G finite memory/pids/CPU ceiling lost".into());
    }
    let quota: u64 = parts[0].parse()?;
    let period: u64 = parts[1].parse()?;
    if quota == 0 || period == 0 || quota != period {
        return Err("original admitted G one-CPU ceiling lost".into());
    }
    Ok(())
}
fn native_input(
    request: &codex_hepta_types::StableId,
    features: &[i64],
    width: usize,
) -> Result<Vec<u8>> {
    let mut bytes = serde_json::to_vec(&serde_json::json!({
        "request_id":request.to_string(),"feature_vector_q24":features,"expected_output_width":width,
    }))?;
    bytes.push(b'\n');
    if bytes.len() > 16 * 1024 {
        return Err("actual paired numeric input bound".into());
    }
    Ok(bytes)
}
/// Execute the Root-predeclared public batch as the actual G MainPID. This is
/// source preregistration only; no final holdout use or qualification occurs.
pub fn run_fixed_paired_generator(path: &Path) -> Result<()> {
    let config_bytes = read_root_review_input(path, 32 * 1024)?;
    let config: Config = serde_json::from_slice(&config_bytes)?;
    if config.schema != "hepta.fixed-paired-generator-config.v1"
        || config.uid == 0
        || config.uid != config.gid
        || config.inaccessible_paths.len() != 5
        || config.distribution_generation == 0
        || config.authority_epoch == 0
    {
        return Err("fixed paired G Root policy".into());
    }
    let cgroup = crate::fixed_calibration_host::boundary_in_service(
        config.uid,
        config.gid,
        "hepta-native-generator-",
    )?;
    actual_limits(&cgroup)?;
    let program = Digest32::of_bytes(&read_root_review_input(
        &std::env::current_exe()?,
        128 * 1024 * 1024,
    )?);
    if program != config.program_digest.parse::<Digest32>()? {
        return Err("immutable actual G program pin".into());
    }
    for inaccessible in &config.inaccessible_paths {
        match File::open(inaccessible) {
            Err(e) if e.kind() == std::io::ErrorKind::PermissionDenied => (),
            _ => return Err("G has custody/another role access or no physical denial".into()),
        }
    }
    let source_bytes = config.source.read(128 * 1024 * 1024)?;
    let inputs: Inputs = serde_json::from_slice(&source_bytes)?;
    if inputs.schema != "hepta.eval.paired-supervised.public-generator-inputs.v1"
        || inputs.batch_id.is_empty()
        || inputs.batch_id.len() > 256
        || !(1..=120_000).contains(&inputs.timeout_ms)
        || !(1..=128).contains(&inputs.expected_output_width)
        || inputs.trust.root_verifying_key_hex != config.root_verifying_key_hex
        || inputs.trust.scope_digest != config.scope_digest
        || inputs.trust.objective_digest != config.objective_digest
        || inputs.trust.generation != config.distribution_generation
        || inputs.trust.authority_epoch != config.authority_epoch
    {
        return Err("original Root G scope/epoch/batch policy".into());
    }
    let (root, distribution) = inputs.trust.native()?;
    let signer = distribution
        .distribution
        .trust
        .signers
        .iter()
        .find(|signer| signer.principal.principal_id.as_str() == "native-unprivileged-generator")
        .ok_or("original G admission missing")?
        .clone();
    actual_generator(&signer, program, config.uid, &root.verifying_key)?;
    let trust = activate_learning_trust(
        &root,
        distribution,
        None,
        crate::fixed_calibration_host::now_ms()?,
    )?;
    let mut last = None;
    sample(&trust, &mut last)?;
    let mut source =
        PairedReviewSourcePlanV1::decode(&decode_review_payload_hex(&inputs.plan_inputs_hex)?)?;
    if source.source_scope.objective_digest != config.objective_digest.parse::<Digest32>()?
        || source.tasks.is_empty()
        || source.tasks.len() > 1024
        || inputs.pairs.len() != source.tasks.len()
        || source.runtime.task_input_contract_digest.is_zero()
        || source.tasks.iter().any(|task| {
            !task.candidate_input_digest.is_zero() || !task.baseline_input_digest.is_zero()
        })
    {
        return Err("fresh unmeasured source template required, no original input replay".into());
    }
    let mut pairs = BTreeMap::new();
    let mut pair_ids = std::collections::BTreeSet::new();
    for pair in &inputs.pairs {
        if pair.pair_id.is_empty()
            || pair.pair_id.len() > 256
            || pair.source_row_sha256.parse::<Digest32>()?.is_zero()
            || pair.source_row_sha256.parse::<Digest32>()?
                != pair.source_record_digest.parse::<Digest32>()?
            || !pair_ids.insert(&pair.pair_id)
            || pairs
                .insert(pair.source_record_digest.parse::<Digest32>()?, pair)
                .is_some()
        {
            return Err("complete distinct Root paired rows required".into());
        }
    }
    // Validate the complete graph, folds, gates, roles and original request IDs
    // before any physical encoder request. These row-identity placeholders
    // check shape only; they are never returned, signed or used as inputs.
    let mut structural = source.clone();
    for task in &mut structural.tasks {
        task.candidate_input_digest = task.source_record_digest;
        task.baseline_input_digest = task.source_record_digest;
    }
    structural.freeze()?;
    // The input contract binds the actual complete physical responses, including
    // conservative whole-service accounting, under the original G plan signature.
    let original_contract = source.runtime.task_input_contract_digest;
    let deadline = Instant::now()
        .checked_add(Duration::from_millis(inputs.timeout_ms))
        .ok_or("G batch deadline overflow")?;
    let mut measurements = Vec::new();
    for task in &mut source.tasks {
        sample(&trust, &mut last)?;
        let pair = pairs
            .get(&task.source_record_digest)
            .ok_or("source row absent from Root batch")?;
        let response = measure(
            &inputs.encoder,
            &inputs.batch_id,
            &pair.pair_id,
            &pair.source_row_sha256,
            config.uid,
            deadline,
        )?;
        let candidate = native_input(
            &task.candidate_request_id,
            &response.features_q24,
            inputs.expected_output_width,
        )?;
        let baseline = native_input(
            &task.baseline_request_id,
            &response.features_q24,
            inputs.expected_output_width,
        )?;
        task.candidate_input_digest = Digest32::of_bytes(&candidate);
        task.baseline_input_digest = Digest32::of_bytes(&baseline);
        measurements.push(serde_json::json!({"source_record_digest":task.source_record_digest.to_string(),
            "candidate_input_hex":hex(&candidate),"baseline_input_hex":hex(&baseline),"physical_response":response}));
        sample(&trust, &mut last)?;
    }
    let measurement_bytes = serde_json::to_vec(&measurements)?;
    if measurement_bytes.len() > 32 * 1024 * 1024 {
        return Err("complete original G measurements exceed publication bound".into());
    }
    source.runtime.task_input_contract_digest =
        measured_contract(original_contract, &measurement_bytes);
    let plan = source.freeze()?;
    if config_bytes != read_root_review_input(path, 32 * 1024)?
        || source_bytes != config.source.read(128 * 1024 * 1024)?
    {
        return Err("Root G publication changed before original signature".into());
    }
    let now = sample(&trust, &mut last)?;
    signer.principal.validate(now)?;
    let signing = crate::fixed_calibration_host::key(&config.private_key_path, config.uid)?;
    if signing.verifying_key().to_bytes() != signer.verifying_key {
        return Err("actual G private key is not admitted key".into());
    }
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: codex_hepta_types::StableId::new(format!(
            "paired-g.{}",
            plan.frozen_plan().plan_digest
        ))?,
        principal_id: signer.principal.principal_id.clone(),
        trust_digest: trust.verifier().trust_digest(),
        scope_digest: signer.principal.scope_digest,
        objective_digest: plan.frozen_plan().objective_digest,
        authority_epoch: signer.principal.authority_epoch,
        role: LearningEvidenceRoleV1::Generator,
        issued_at: now,
        expires_at: signer.principal.expires_at.min(inputs.trust.expires_at),
        payload_digest: Digest32::of_bytes(plan.frozen_plan().plan_digest.as_array()),
        signature: [0; 64],
    };
    if evidence.expires_at <= now {
        return Err("original G authority expired".into());
    }
    evidence.signature = signing.sign(&evidence.signing_bytes()).to_bytes();
    trust.verifier().verify(
        LearningEvidenceRoleV1::Generator,
        &evidence,
        plan.frozen_plan().plan_digest.as_array(),
        sample(&trust, &mut last)?,
    )?;
    println!(
        "{}",
        serde_json::json!({"schema":"hepta.eval.paired-supervised.public-generator-source.v1",
        "original_source_digest":config.source.digest,"original_input_contract_digest":original_contract.to_string(),
        "plan_inputs_hex":hex(&source.encode()?),"measurements":measurements,
        "generator_evidence":ReviewEvidenceWireV1::from_native(&evidence),"generator_uid":config.uid,"generator_gid":config.gid,
        "generator_cgroup":cgroup,"trust":inputs.trust,"qualified":false,"final_holdout_consumed":false,
        "authority_grants_any":false,"production_activation":false})
    );
    Ok(())
}
pub(super) fn measured_contract(original: Digest32, bytes: &[u8]) -> Digest32 {
    Digest32::of_bytes(
        &[
            b"hepta.eval.paired-supervised.measured-public-inputs.v1".as_slice(),
            original.as_array(),
            bytes,
        ]
        .concat(),
    )
}
