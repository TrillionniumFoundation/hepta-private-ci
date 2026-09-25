//! Target-host measurement harness for the authenticated production learning ledger.
//!
//! This executable produces measurements, not acceptance. It deliberately
//! reports power-loss and longitudinal-efficacy qualification as false because
//! ordinary process/file tests cannot establish either claim.

use std::env;
use std::error::Error;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::time::Instant;

use codex_hepta_learning_ledger::AppendDisposition;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningTrustDistributionV1;
use codex_hepta_learning_ledger::LearningTrustRootV1;
use codex_hepta_learning_ledger::LedgerSegmentLimits;
use codex_hepta_learning_ledger::LedgerWitnessStore;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::ProductionDecisionV2;
use codex_hepta_learning_ledger::SegmentedLedger;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::SignedLearningTrustDistributionV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_learning_ledger::activate_learning_trust;
use codex_hepta_learning_ledger::candidate_ids_digest_v2;
use codex_hepta_learning_ledger::candidate_order_digest_v2;
use codex_hepta_learning_ledger::decision_signing_payload_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde::Serialize;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct LatencySummary {
    count: usize,
    p50_micros: u64,
    p95_micros: u64,
    p99_micros: u64,
    max_micros: u64,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct TargetHostReceipt {
    schema: &'static str,
    target_host_id: String,
    os: &'static str,
    arch: &'static str,
    source_commit: String,
    source_tree: String,
    binary_digest: String,
    record_count: usize,
    segment_record_limit: usize,
    segment_count: usize,
    append_latency: LatencySummary,
    rotation_latency: LatencySummary,
    lookup_latency: LatencySummary,
    retry_latency: LatencySummary,
    recovered_retry_preserves_identity: bool,
    substituted_retry_rejected: bool,
    source_identity_attested: bool,
    reopen_micros: u64,
    sustained_appends_per_second: f64,
    storage_bytes: u64,
    rss_before_kib: Option<u64>,
    rss_after_kib: Option<u64>,
    rss_growth_kib: Option<i64>,
    final_sequence: u64,
    final_chain_digest: String,
    exact_reopen_record_count: usize,
    power_loss_qualified: bool,
    longitudinal_efficacy_qualified: bool,
    production_activation_authorized: bool,
}

fn main() -> Result<(), Box<dyn Error>> {
    let target_host_id = env::var("HEPTA_TARGET_HOST_ID")
        .map_err(|_| "HEPTA_TARGET_HOST_ID must name the measured target host")?;
    let record_count = env_usize("HEPTA_LEDGER_RECORDS", 2_048)?;
    let segment_record_limit = env_usize("HEPTA_LEDGER_SEGMENT_RECORDS", 128)?;
    if record_count == 0
        || record_count > 1_000_000
        || !(1..=8_192).contains(&segment_record_limit)
        || record_count.div_ceil(segment_record_limit) > 1_024
    {
        return Err("measurement bounds exceed the supported ledger profile".into());
    }

    let source_commit = git_rev_parse("HEAD")?;
    let source_tree = git_rev_parse("HEAD^{tree}")?;
    let binary_digest = Digest32::of_bytes(&fs::read(env::current_exe()?)?).to_string();

    let root = measurement_root()?;
    fs::create_dir(&root)?;
    create_empty(&root.join("owner"))?;
    create_empty(&root.join("0"))?;
    create_empty(&root.join("witness"))?;

    let binding = digest("target-host-production-ledger");
    let limits = LedgerSegmentLimits {
        records: segment_record_limit,
        bytes: 8 * 1024 * 1024,
    };
    let journal = SegmentedLedger::create(
        read_write(&root.join("owner"))?,
        read_write(&root.join("0"))?,
        binding,
        limits,
    )?;
    let witness = LedgerWitnessStore::create(read_write(&root.join("witness"))?, binding)?;
    let segment_directory = File::open(&root)?;
    let witness_directory = File::open(&root)?;
    let trust = activated_trust()?;
    let mut writer = LedgerWriter::from_segmented(
        journal,
        witness,
        trust,
        &segment_directory,
        &witness_directory,
    )?;

    let rss_before_kib = rss_kib();
    let mut append_micros = Vec::with_capacity(record_count);
    let mut rotation_micros = Vec::new();
    let total_start = Instant::now();
    let mut segment_count = 1_usize;
    let mut first_chain_digest = None;

    for index in 0..record_count {
        if index != 0 && index % segment_record_limit == 0 {
            let anchor = writer.witness_frontier()?.anchor;
            let next_path = root.join(segment_count.to_string());
            create_empty(&next_path)?;
            let directory = File::open(&root)?;
            let started = Instant::now();
            writer.rotate_segment(read_write(&next_path)?, anchor, &directory)?;
            rotation_micros.push(elapsed_micros(started));
            segment_count += 1;
        }

        let request = decision(index)?;
        let payload = decision_signing_payload_v2(&request)?;
        let evidence = sign(writer.verifier(), index, &payload)?;
        let predecessor = writer.witness_frontier()?.anchor.chain_digest;
        let started = Instant::now();
        let appended = writer.append_decision(predecessor, request, &evidence, NOW)?;
        if index == 0 {
            first_chain_digest = Some(appended.chain_digest);
        }
        append_micros.push(elapsed_micros(started));
    }

    let total_elapsed = total_start.elapsed();
    let checkpoint = writer
        .segmented_checkpoint()?
        .ok_or("segmented checkpoint unavailable")?;
    let frontier = writer.witness_frontier()?;
    let rss_after_kib = rss_kib();
    drop(writer);

    let storage_bytes = directory_bytes(&root)?;
    let reopen_start = Instant::now();
    let recovered = SegmentedLedger::recover_with_opener(
        read_write(&root.join("owner"))?,
        segment_count,
        |index| read_write(&root.join(index.to_string())).map_err(Into::into),
        binding,
        limits,
        checkpoint,
    )?;
    let witness = LedgerWitnessStore::recover(read_write(&root.join("witness"))?, binding)?;
    let segment_directory = File::open(&root)?;
    let witness_directory = File::open(&root)?;
    let mut reopened = LedgerWriter::from_segmented(
        recovered,
        witness,
        activated_trust()?,
        &segment_directory,
        &witness_directory,
    )?;
    let reopen_micros = elapsed_micros(reopen_start);
    let exact_reopen_record_count = reopened.records()?.len();
    let reopened_frontier = reopened.witness_frontier()?;
    if reopened_frontier != frontier || exact_reopen_record_count != record_count {
        return Err("reopen did not reproduce the exact witnessed history".into());
    }
    // Exercise oldest and newest identities in the same recovered, signed
    // history. Neither a retry nor a rejected substitution may grow either
    // the data files or the separately retained witness.
    let first = decision(0)?;
    let last = decision(record_count - 1)?;
    let first_chain_digest = first_chain_digest.ok_or("first receipt missing")?;
    let mut lookup_micros = Vec::with_capacity(100);
    for index in 0..100 {
        let request = if index % 2 == 0 { &first } else { &last };
        let started = Instant::now();
        reopened.verify_active_decision_binding(&request.record_id, &request.episode_id)?;
        lookup_micros.push(elapsed_micros(started));
    }
    let evidence = sign(
        reopened.verifier(),
        0,
        &decision_signing_payload_v2(&first)?,
    )?;
    let mut retry_micros = Vec::with_capacity(32);
    for _ in 0..32 {
        let started = Instant::now();
        let replay = reopened.append_decision(Digest32::ZERO, first.clone(), &evidence, NOW)?;
        retry_micros.push(elapsed_micros(started));
        if replay.disposition != AppendDisposition::IdempotentReplay
            || replay.chain_digest != first_chain_digest
        {
            return Err("recovered retry changed original operation identity".into());
        }
    }
    let mut substituted = first;
    substituted.support_digest = digest("substituted-after-recovery");
    let evidence = sign(
        reopened.verifier(),
        0,
        &decision_signing_payload_v2(&substituted)?,
    )?;
    if reopened
        .append_decision(Digest32::ZERO, substituted, &evidence, NOW)
        .is_ok()
    {
        return Err("same-ID different-body retry was accepted".into());
    }
    if reopened.witness_frontier()? != frontier || directory_bytes(&root)? != storage_bytes {
        return Err("retry or substitution changed persisted history".into());
    }
    drop(reopened);

    let receipt = TargetHostReceipt {
        schema: "hepta.learning-ledger.target-host.v1",
        target_host_id,
        os: env::consts::OS,
        arch: env::consts::ARCH,
        source_commit,
        source_tree,
        binary_digest,
        record_count,
        segment_record_limit,
        segment_count,
        append_latency: summarize(&mut append_micros),
        rotation_latency: summarize(&mut rotation_micros),
        lookup_latency: summarize(&mut lookup_micros),
        retry_latency: summarize(&mut retry_micros),
        recovered_retry_preserves_identity: true,
        substituted_retry_rejected: true,
        // Git checkout identity plus a binary hash is not a build attestation.
        source_identity_attested: false,
        reopen_micros,
        sustained_appends_per_second: record_count as f64 / total_elapsed.as_secs_f64(),
        storage_bytes,
        rss_before_kib,
        rss_after_kib,
        rss_growth_kib: rss_delta(rss_before_kib, rss_after_kib),
        final_sequence: frontier.anchor.sequence,
        final_chain_digest: frontier.anchor.chain_digest.to_string(),
        exact_reopen_record_count,
        power_loss_qualified: false,
        longitudinal_efficacy_qualified: false,
        production_activation_authorized: false,
    };
    println!("{}", serde_json::to_string_pretty(&receipt)?);

    if env::var_os("HEPTA_KEEP_ARTIFACTS").is_none() {
        fs::remove_dir_all(root)?;
    }
    Ok(())
}

const NOW: u64 = 1_000_000;

fn activated_trust() -> Result<codex_hepta_learning_ledger::ActivatedLearningTrustV1, Box<dyn Error>>
{
    let generator_key = SigningKey::from_bytes(&[1_u8; 32]);
    let root_key = SigningKey::from_bytes(&[99_u8; 32]);
    let scope = digest("target-host-scope");
    let objective = digest("target-host-objective");
    let root = LearningTrustRootV1 {
        root_id: id("target-host-learning-root")?,
        scope_digest: scope,
        verifying_key: root_key.verifying_key().to_bytes(),
        valid_from: 1,
        expires_at: NOW + 1_000_000,
        revoked_at: None,
    };
    let trust = LearningEvidenceTrustV1 {
        scope_digest: scope,
        objective_digest: objective,
        authority_epoch: 1,
        signers: vec![TrustedLearningSignerV1 {
            principal: AuthenticatedPrincipalV1 {
                principal_id: id("target-host-generator")?,
                credential_chain_digest: digest("target-host-generator-credential"),
                signing_key_digest: Digest32::of_bytes(&generator_key.verifying_key().to_bytes()),
                scope_digest: scope,
                authority_epoch: 1,
                authenticated_at: 1,
                expires_at: NOW + 1_000_000,
            },
            controller_id: id("target-host-generator-controller")?,
            verifying_key: generator_key.verifying_key().to_bytes(),
            roles: vec![LearningEvidenceRoleV1::Generator],
            revoked_at: None,
        }],
    };
    let mut signed = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("target-host-distribution")?,
            generation: 1,
            effective_at: 10,
            trust,
        },
        root_id: root.root_id.clone(),
        issued_at: 5,
        expires_at: NOW + 500_000,
        signature: [0_u8; 64],
    };
    signed.signature = root_key.sign(&signed.signing_bytes()?).to_bytes();
    Ok(activate_learning_trust(&root, signed, None, NOW)?)
}

fn decision(index: usize) -> Result<ProductionDecisionV2, Box<dyn Error>> {
    let candidates = vec![id("abstain")?, id("action")?];
    Ok(ProductionDecisionV2 {
        record_id: id(&format!("target-host-record-{index}"))?,
        episode_id: id(&format!("target-host-episode-{index}"))?,
        run_snapshot_digest: digest(&format!("run-snapshot-{index}")),
        objective_digest: digest("target-host-objective"),
        policy_digest: digest("target-host-policy"),
        candidate_ids: candidates.clone(),
        selected_candidate_id: id("action")?,
        selected_propensity: ProbabilityQ32::ONE,
        completeness: CandidateSetCompletenessReceiptV1 {
            set_id: id(&format!("target-host-candidates-{index}"))?,
            state_digest: digest(&format!("state-{index}")),
            generator_id: id("target-host-generator")?,
            generator_code_digest: digest("target-host-generator-code"),
            grammar_digest: digest("target-host-grammar"),
            hard_filter_digest: digest("target-host-hard-filter"),
            truncation_digest: digest("target-host-truncation"),
            candidates_digest: candidate_ids_digest_v2(&candidates),
            candidate_count: 2,
            omitted_count_bound: 0,
            canonical_order_digest: candidate_order_digest_v2(&candidates),
            complete_for_generator: true,
        },
        support_digest: digest(&format!("target-host-support-{index}")),
    })
}

fn sign(
    verifier: &codex_hepta_learning_ledger::LearningEvidenceVerifierV1,
    index: usize,
    payload: &[u8],
) -> Result<SignedLearningEvidenceV1, Box<dyn Error>> {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(&format!("target-host-evidence-{index}"))?,
        principal_id: id("target-host-generator")?,
        role: LearningEvidenceRoleV1::Generator,
        trust_digest: verifier.trust_digest(),
        scope_digest: digest("target-host-scope"),
        objective_digest: digest("target-host-objective"),
        authority_epoch: 1,
        issued_at: 20,
        expires_at: NOW + 100_000,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0_u8; 64],
    };
    evidence.signature = SigningKey::from_bytes(&[1_u8; 32])
        .sign(&evidence.signing_bytes())
        .to_bytes();
    Ok(evidence)
}

fn measurement_root() -> Result<PathBuf, Box<dyn Error>> {
    let base = env::var_os("HEPTA_LEDGER_QUAL_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(env::temp_dir);
    Ok(base.join(format!(
        "hepta-learning-ledger-target-host-{}",
        std::process::id()
    )))
}

fn create_empty(path: &Path) -> Result<(), Box<dyn Error>> {
    OpenOptions::new().create_new(true).write(true).open(path)?;
    Ok(())
}

fn read_write(path: &Path) -> std::io::Result<File> {
    OpenOptions::new().read(true).write(true).open(path)
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn id(value: &str) -> Result<StableId, Box<dyn Error>> {
    Ok(StableId::new(value.to_owned())?)
}

fn env_usize(name: &str, default: usize) -> Result<usize, Box<dyn Error>> {
    match env::var(name) {
        Ok(value) => Ok(value.parse()?),
        Err(env::VarError::NotPresent) => Ok(default),
        Err(error) => Err(error.into()),
    }
}

fn elapsed_micros(started: Instant) -> u64 {
    u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX)
}

fn summarize(values: &mut [u64]) -> LatencySummary {
    if values.is_empty() {
        return LatencySummary {
            count: 0,
            p50_micros: 0,
            p95_micros: 0,
            p99_micros: 0,
            max_micros: 0,
        };
    }
    values.sort_unstable();
    LatencySummary {
        count: values.len(),
        p50_micros: percentile(values, 50),
        p95_micros: percentile(values, 95),
        p99_micros: percentile(values, 99),
        max_micros: values[values.len() - 1],
    }
}

fn percentile(values: &[u64], percentile: usize) -> u64 {
    let index = (values.len() - 1) * percentile / 100;
    values[index]
}

fn directory_bytes(root: &Path) -> Result<u64, Box<dyn Error>> {
    let mut total = 0_u64;
    for entry in fs::read_dir(root)? {
        let metadata = entry?.metadata()?;
        if metadata.is_file() {
            total = total.saturating_add(metadata.len());
        }
    }
    Ok(total)
}

fn rss_kib() -> Option<u64> {
    let text = fs::read_to_string("/proc/self/status").ok()?;
    text.lines().find_map(|line| {
        let value = line.strip_prefix("VmRSS:")?.trim();
        value.split_whitespace().next()?.parse().ok()
    })
}

fn rss_delta(before: Option<u64>, after: Option<u64>) -> Option<i64> {
    let before = i64::try_from(before?).ok()?;
    let after = i64::try_from(after?).ok()?;
    Some(after - before)
}

fn git_rev_parse(value: &str) -> Result<String, Box<dyn Error>> {
    let output = Command::new("git").args(["rev-parse", value]).output()?;
    if !output.status.success() {
        return Err(format!("git rev-parse {value} failed").into());
    }
    Ok(String::from_utf8(output.stdout)?.trim().to_owned())
}
