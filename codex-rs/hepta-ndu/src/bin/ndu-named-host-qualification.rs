#[path = "ndu-named-host-qualification/fixture.rs"]
mod fixture;
use fixture::digest;
use fixture::fixture;

use std::error::Error;
use std::fs;
use std::fs::File;
use std::path::PathBuf;
use std::time::Instant;

use codex_hepta_ndu::AggregationOperator;
use codex_hepta_ndu::AxisAggregationRule;
use codex_hepta_ndu::AxisDirection;
use codex_hepta_ndu::AxisLimit;
use codex_hepta_ndu::AxisValue;
use codex_hepta_ndu::ContributionSet;
use codex_hepta_ndu::EvaluationPolicyV1;
use codex_hepta_ndu::FeasibilityPosture;
use codex_hepta_ndu::NduProjectionJournalError;
use codex_hepta_ndu::NduProjectionJournalV1;
use codex_hepta_ndu::NduProjectionKindV1;
use codex_hepta_ndu::NduProjectionStoreError;
use codex_hepta_ndu::NduProjectionStoreV1;
use codex_hepta_ndu::RequiredOrganSet;
use codex_hepta_ndu::UtilityContribution;
use codex_hepta_ndu::UtilityProfile;
use codex_hepta_ndu::evaluate_candidates_with_policy;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

const HOT_RUNS: usize = 100;
const HOT_CANDIDATES: usize = 32;
const HOT_ORGANS: usize = 8;
const HOT_UTILITY_AXES: usize = 4;
const HOT_RISK_RESOURCE_AXES: usize = 4;
const MAX_CANDIDATES: usize = 128;
const MAX_ORGANS: usize = 32;
const MAX_UTILITY_AXES: usize = 8;
const MAX_RISK_RESOURCE_AXES: usize = 32;
const JOURNAL_RECORD_CAPACITY: usize = 4096;
const LIVE_PROJECTION_CAPACITY: usize = JOURNAL_RECORD_CAPACITY / 2;
const OVERSIZED_IMAGE_BYTES: u64 = 1_u64 << 40;

#[derive(Clone)]
struct EvaluationFixture {
    set: ContributionSet,
    profile: UtilityProfile,
    policy: EvaluationPolicyV1,
}

fn main() -> Result<(), Box<dyn Error>> {
    let host_id = env_required("HEPTA_NDU_HOST_ID")?;
    let fs_profile = env_required("HEPTA_NDU_FS_PROFILE")?;
    let rustc = env_required("HEPTA_NDU_RUSTC")?;
    let receipt_path = PathBuf::from(env_required("HEPTA_NDU_RECEIPT_PATH")?);
    let clk_tck: u64 = env_required("HEPTA_NDU_CLK_TCK")?.parse()?;

    let cpu_before = process_cpu_ticks()?;
    let hot = fixture(
        HOT_CANDIDATES,
        HOT_ORGANS,
        HOT_UTILITY_AXES,
        HOT_RISK_RESOURCE_AXES,
    )?;
    let mut latencies = Vec::with_capacity(HOT_RUNS);
    for _ in 0..HOT_RUNS {
        let set = hot.set.clone();
        let profile = hot.profile.clone();
        let policy = hot.policy.clone();
        let started = Instant::now();
        let receipt = evaluate_candidates_with_policy(set, profile, None, policy)?;
        let elapsed = started.elapsed().as_micros();
        if receipt.base.evaluated_candidates.len() != HOT_CANDIDATES {
            return Err("hot-path candidate coverage drift".into());
        }
        latencies.push(elapsed);
    }
    latencies.sort_unstable();

    let maximum = fixture(
        MAX_CANDIDATES,
        MAX_ORGANS,
        MAX_UTILITY_AXES,
        MAX_RISK_RESOURCE_AXES,
    )?;
    let max_started = Instant::now();
    let max_receipt =
        evaluate_candidates_with_policy(maximum.set, maximum.profile, None, maximum.policy)?;
    let max_capacity_micros = max_started.elapsed().as_micros();
    if max_receipt.base.evaluated_candidates.len() != MAX_CANDIDATES {
        return Err("maximum candidate coverage drift".into());
    }

    let journal_started = Instant::now();
    let mut journal = NduProjectionJournalV1::new();
    let objective = digest("capacity-objective");
    let subject = digest("capacity-subject");
    for index in 0..LIVE_PROJECTION_CAPACITY {
        journal.append_projection(
            NduProjectionKindV1::Preference,
            digest(&format!("capacity-identity-{index}")),
            objective,
            subject,
            digest(&format!("capacity-payload-{index}")),
        )?;
    }
    if journal.entries().len() != LIVE_PROJECTION_CAPACITY {
        return Err("journal live-projection envelope underfilled".into());
    }
    let overflow = match journal.append_projection(
        NduProjectionKindV1::Preference,
        digest("capacity-overflow-identity"),
        objective,
        subject,
        digest("capacity-overflow-payload"),
    ) {
        Ok(_) => return Err("ordinary history consumed reserved revocation capacity".into()),
        Err(error) => error,
    };
    if overflow != NduProjectionJournalError::RevocationCapacityExhausted {
        return Err("journal revocation-reserve boundary mismatch".into());
    }
    let mut capacity_prefix = Vec::new();
    for index in 0..LIVE_PROJECTION_CAPACITY {
        if index + 1 == LIVE_PROJECTION_CAPACITY {
            capacity_prefix = journal.export_bytes();
        }
        journal.revoke_projection(
            digest(&format!("capacity-revocation-{index}")),
            objective,
            subject,
            digest(&format!("capacity-payload-{index}")),
        )?;
    }
    if journal.entries().len() != JOURNAL_RECORD_CAPACITY {
        return Err("full-capacity revocation envelope not exercised".into());
    }
    let reopened_capacity = NduProjectionJournalV1::reopen(&journal.export_bytes())?;
    if reopened_capacity.entries() != journal.entries() {
        return Err("full-envelope journal recovery drift".into());
    }
    let journal_capacity_micros = journal_started.elapsed().as_micros();

    let root_nonce = format!("{}", std::process::id());
    let store_root = std::env::temp_dir().join(format!("hepta-ndu-named-host-{root_nonce}"));
    let restore_root =
        std::env::temp_dir().join(format!("hepta-ndu-named-host-restore-{root_nonce}"));
    let oversized_root =
        std::env::temp_dir().join(format!("hepta-ndu-named-host-oversized-{root_nonce}"));
    let capacity_root =
        std::env::temp_dir().join(format!("hepta-ndu-named-host-capacity-{root_nonce}"));
    for root in [&store_root, &restore_root, &oversized_root, &capacity_root] {
        let _ = fs::remove_dir_all(root);
        fs::create_dir(root)?;
    }

    let durability_started = Instant::now();
    let durable_objective = digest("durable-objective");
    let durable_subject = digest("durable-subject");
    let projection = digest("durable-projection");
    {
        let mut store = NduProjectionStoreV1::open(&store_root)?;
        store.append_projection(
            NduProjectionKindV1::Preference,
            digest("durable-projection-id"),
            durable_objective,
            durable_subject,
            projection,
        )?;
        store.select_projection_if_current(
            digest("durable-select-id"),
            durable_objective,
            durable_subject,
            None,
            projection,
        )?;
    }
    let backup;
    {
        let mut reopened = NduProjectionStoreV1::open(&store_root)?;
        if reopened.selected_projection_digest(durable_objective, durable_subject)?
            != Some(projection)
        {
            return Err("durable reopen lost selection".into());
        }
        reopened.revoke_projection(
            digest("durable-revoke-id"),
            durable_objective,
            durable_subject,
            projection,
        )?;
        if reopened
            .selected_projection_digest(durable_objective, durable_subject)?
            .is_some()
        {
            return Err("durable revocation did not clear selection".into());
        }
        backup = reopened.backup_bytes()?;
    }
    {
        let mut restored = NduProjectionStoreV1::open(&restore_root)?;
        restored.restore_backup(&backup)?;
        if restored
            .selected_projection_digest(durable_objective, durable_subject)?
            .is_some()
        {
            return Err("backup restore resurrected revoked projection".into());
        }
        if restored.entries()?.len() != 3 {
            return Err("backup restore record count mismatch".into());
        }
    }

    {
        let mut store = NduProjectionStoreV1::open(&capacity_root)?;
        store.restore_backup(&capacity_prefix)?;
        let last = LIVE_PROJECTION_CAPACITY - 1;
        store.revoke_projection(
            digest(&format!("capacity-revocation-{last}")),
            objective,
            subject,
            digest(&format!("capacity-payload-{last}")),
        )?;
    }
    {
        let reopened = NduProjectionStoreV1::open(&capacity_root)?;
        if reopened.entries()? != journal.entries() {
            return Err("full-capacity disk revocation/reopen drift".into());
        }
    }

    let oversized = File::create(oversized_root.join("projection.journal"))?;
    oversized.set_len(OVERSIZED_IMAGE_BYTES)?;
    oversized.sync_all()?;
    drop(oversized);
    if NduProjectionStoreV1::open(&oversized_root)
        .err()
        .ok_or("oversized image unexpectedly opened")?
        != NduProjectionStoreError::BackupTooLarge
    {
        return Err("oversized image did not fail at bounded-read admission".into());
    }
    let durability_micros = durability_started.elapsed().as_micros();

    for root in [&store_root, &restore_root, &oversized_root, &capacity_root] {
        let _ = fs::remove_dir_all(root);
    }

    let cpu_after = process_cpu_ticks()?;
    let cpu_ticks = cpu_after.saturating_sub(cpu_before);
    let cpu_micros = u128::from(cpu_ticks) * 1_000_000 / u128::from(clk_tck);
    let max_rss_kib = process_hwm_kib()?;

    let p50 = percentile(&latencies, 50);
    let p95 = percentile(&latencies, 95);
    let p99 = percentile(&latencies, 99);
    let hot_target_pass = p95 <= 2_000 && p99 <= 5_000;

    let source_sha = env_required("HEPTA_NDU_SOURCE_SHA")?;
    let source_tree = env_required("HEPTA_NDU_SOURCE_TREE")?;
    let lane = env_required("HEPTA_NDU_QUALIFICATION_LANE")?;
    if [&source_sha, &source_tree]
        .iter()
        .any(|value| value.len() != 40 || !value.bytes().all(|b| b.is_ascii_hexdigit()))
    {
        return Err("exact source commit and tree are required".into());
    }

    let json = format!(
        concat!(
            "{{\n",
            "  \"schema\": \"hepta.ndu.named-host-qualification.v3\",\n",
            "  \"hostId\": \"{}\",\n",
            "  \"lane\": \"{}\",\n",
            "  \"sourceSha\": \"{}\",\n",
            "  \"sourceTree\": \"{}\",\n",
            "  \"os\": \"{}\",\n",
            "  \"arch\": \"{}\",\n",
            "  \"filesystem\": \"{}\",\n",
            "  \"rustc\": \"{}\",\n",
            "  \"hotPath\": {{\"runs\": {}, \"candidates\": {}, \"organs\": {}, ",
            "\"p50Micros\": {}, \"p95Micros\": {}, \"p99Micros\": {}, ",
            "\"targetP95Micros\": 2000, \"targetP99Micros\": 5000, \"targetPass\": {}}},\n",
            "  \"maxCapacity\": {{\"candidates\": {}, \"contributions\": {}, ",
            "\"utilityAxes\": {}, \"riskResourceAxes\": {}, \"elapsedMicros\": {}}},\n",
            "  \"journal\": {{\"recordCapacity\": {}, \"liveProjectionCapacity\": {}, ",
            "\"reservedRevocationSlots\": {}, \"ordinaryOverflowRejected\": true, ",
            "\"fullEnvelopeRevocation\": true, \"restartRecovery\": true, ",
            "\"elapsedMicros\": {}}},\n",
            "  \"durability\": {{\"restartReopen\": true, ",
            "\"revocationNonResurrection\": true, \"backupRestore\": true, \"fullCapacityDiskRecovery\": true, ",
            "\"oversizedImageBoundedReject\": true, \"faultCuts\": \"separate_test_receipt_required\", \"oversizedSparseBytes\": 1099511627776, ",
            "\"elapsedMicros\": {}}},\n",
            "  \"process\": {{\"cpuMicros\": {}, \"maxRssKiB\": {}}}\n",
            "}}\n"
        ),
        escape(&host_id),
        escape(&lane),
        escape(&source_sha),
        escape(&source_tree),
        std::env::consts::OS,
        std::env::consts::ARCH,
        escape(&fs_profile),
        escape(&rustc),
        HOT_RUNS,
        HOT_CANDIDATES,
        HOT_ORGANS,
        p50,
        p95,
        p99,
        hot_target_pass,
        MAX_CANDIDATES,
        MAX_CANDIDATES * MAX_ORGANS,
        MAX_UTILITY_AXES,
        MAX_RISK_RESOURCE_AXES,
        max_capacity_micros,
        JOURNAL_RECORD_CAPACITY,
        LIVE_PROJECTION_CAPACITY,
        LIVE_PROJECTION_CAPACITY,
        journal_capacity_micros,
        durability_micros,
        cpu_micros,
        max_rss_kib
    );
    fs::write(&receipt_path, json)?;

    if !hot_target_pass {
        return Err(format!("named-host latency target failed: p95={p95}us p99={p99}us").into());
    }
    Ok(())
}

fn percentile(values: &[u128], percentile: usize) -> u128 {
    let index = ((values.len() - 1) * percentile).div_ceil(100);
    values[index.min(values.len() - 1)]
}

fn env_required(name: &str) -> Result<String, Box<dyn Error>> {
    std::env::var(name).map_err(|_| format!("missing environment variable {name}").into())
}

fn process_cpu_ticks() -> Result<u64, Box<dyn Error>> {
    let stat = fs::read_to_string("/proc/self/stat")?;
    let end = stat.rfind(')').ok_or("malformed /proc/self/stat")?;
    let fields = stat
        .get(end + 2..)
        .ok_or("malformed /proc/self/stat tail")?
        .split_whitespace()
        .collect::<Vec<_>>();
    let user: u64 = fields.get(11).ok_or("missing utime")?.parse()?;
    let system: u64 = fields.get(12).ok_or("missing stime")?.parse()?;
    Ok(user.saturating_add(system))
}

fn process_hwm_kib() -> Result<u64, Box<dyn Error>> {
    let status = fs::read_to_string("/proc/self/status")?;
    for line in status.lines() {
        if let Some(rest) = line.strip_prefix("VmHWM:") {
            let value = rest
                .split_whitespace()
                .next()
                .ok_or("malformed VmHWM")?
                .parse()?;
            return Ok(value);
        }
    }
    Err("VmHWM not available".into())
}

fn escape(value: &str) -> String {
    value.replace('\\', "\\\\").replace('"', "\\\"")
}
