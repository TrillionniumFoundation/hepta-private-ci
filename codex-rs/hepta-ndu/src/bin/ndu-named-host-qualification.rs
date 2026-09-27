use std::error::Error;
use std::fs;
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
const JOURNAL_CAPACITY: usize = 4096;

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
    for index in 0..JOURNAL_CAPACITY {
        journal.append_projection(
            NduProjectionKindV1::Preference,
            digest(&format!("capacity-identity-{index}")),
            objective,
            subject,
            digest(&format!("capacity-payload-{index}")),
        )?;
    }
    let journal_capacity_micros = journal_started.elapsed().as_micros();
    if journal.entries().len() != JOURNAL_CAPACITY {
        return Err("journal capacity underfilled".into());
    }
    let overflow = journal
        .append_projection(
            NduProjectionKindV1::Preference,
            digest("capacity-overflow-identity"),
            objective,
            subject,
            digest("capacity-overflow-payload"),
        )
        .err()
        .ok_or("4097th record must reject")?;
    if overflow != NduProjectionJournalError::RecordLimitExceeded {
        return Err("journal capacity boundary mismatch".into());
    }

    let store_root =
        std::env::temp_dir().join(format!("hepta-ndu-named-host-{}", std::process::id()));
    let restore_root = std::env::temp_dir().join(format!(
        "hepta-ndu-named-host-restore-{}",
        std::process::id()
    ));
    let _ = fs::remove_dir_all(&store_root);
    let _ = fs::remove_dir_all(&restore_root);
    fs::create_dir(&store_root)?;
    fs::create_dir(&restore_root)?;
    let projection = digest("durable-projection");
    {
        let mut store = NduProjectionStoreV1::open(&store_root)?;
        store.append_projection(
            NduProjectionKindV1::Preference,
            digest("durable-projection-id"),
            objective,
            subject,
            projection,
        )?;
        store.select_projection(digest("durable-select-id"), objective, subject, projection)?;
    }
    let backup;
    {
        let mut reopened = NduProjectionStoreV1::open(&store_root)?;
        if reopened.selected_projection_digest(objective, subject)? != Some(projection) {
            return Err("durable reopen lost selection".into());
        }
        reopened.revoke_projection(digest("durable-revoke-id"), objective, subject, projection)?;
        if reopened
            .selected_projection_digest(objective, subject)?
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
            .selected_projection_digest(objective, subject)?
            .is_some()
        {
            return Err("backup restore resurrected revoked projection".into());
        }
        if restored.entries()?.len() != 3 {
            return Err("backup restore record count mismatch".into());
        }
    }
    let _ = fs::remove_dir_all(&store_root);
    let _ = fs::remove_dir_all(&restore_root);

    let cpu_after = process_cpu_ticks()?;
    let cpu_ticks = cpu_after.saturating_sub(cpu_before);
    let cpu_micros = u128::from(cpu_ticks) * 1_000_000 / u128::from(clk_tck);
    let max_rss_kib = process_hwm_kib()?;

    let p50 = percentile(&latencies, 50);
    let p95 = percentile(&latencies, 95);
    let p99 = percentile(&latencies, 99);
    let hot_target_pass = p95 <= 2_000 && p99 <= 5_000;

    let source_sha = std::env::var("HEPTA_NDU_SOURCE_SHA").unwrap_or_default();
    let source_tree = std::env::var("HEPTA_NDU_SOURCE_TREE").unwrap_or_default();
    let lane = std::env::var("HEPTA_NDU_QUALIFICATION_LANE").unwrap_or_default();

    let json = format!(
        concat!(
            "{{\n",
            "  \"schema\": \"hepta.ndu.named-host-qualification.v1\",\n",
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
            "  \"journal\": {{\"records\": 4096, \"overflowRejected\": true, ",
            "\"elapsedMicros\": {}}},\n",
            "  \"durability\": {{\"restartReopen\": true, \"revocationNonResurrection\": true, ",
            "\"backupRestore\": true}},\n",
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
        journal_capacity_micros,
        cpu_micros,
        max_rss_kib
    );
    fs::write(&receipt_path, json)?;

    if !hot_target_pass {
        return Err(format!("named-host latency target failed: p95={p95}us p99={p99}us").into());
    }
    Ok(())
}

fn fixture(
    candidate_count: usize,
    organ_count: usize,
    utility_axes: usize,
    risk_resource_axes: usize,
) -> Result<EvaluationFixture, Box<dyn Error>> {
    let objective = digest("benchmark-objective");
    let generation = Generation::new(1)?;
    let organs = (0..organ_count)
        .map(|index| stable(&format!("organ-{index:02}")))
        .collect::<Result<Vec<_>, _>>()?;
    let utility_ids = (0..utility_axes)
        .map(|index| stable(&format!("utility-{index:02}")))
        .collect::<Result<Vec<_>, _>>()?;
    let risk_ids = (0..risk_resource_axes)
        .map(|index| stable(&format!("risk-{index:02}")))
        .collect::<Result<Vec<_>, _>>()?;
    let resource_ids = (0..risk_resource_axes)
        .map(|index| stable(&format!("resource-{index:02}")))
        .collect::<Result<Vec<_>, _>>()?;

    let mut contributions = Vec::with_capacity(candidate_count * organ_count);
    for candidate_index in 0..candidate_count {
        let candidate = if candidate_index == 0 {
            stable("abstain")?
        } else {
            stable(&format!("candidate-{candidate_index:03}"))?
        };
        for organ in &organs {
            let score = if candidate_index == 0 {
                FixedQ32::ZERO
            } else {
                q32(candidate_index as i64)
            };
            contributions.push(UtilityContribution {
                candidate_id: candidate.clone(),
                organ_id: organ.clone(),
                objective_digest: objective,
                generation,
                feasibility: FeasibilityPosture::Feasible,
                utility: utility_ids
                    .iter()
                    .cloned()
                    .map(|axis| AxisValue { axis, value: score })
                    .collect(),
                risk: risk_ids
                    .iter()
                    .cloned()
                    .map(|axis| AxisValue {
                        axis,
                        value: FixedQ32::ZERO,
                    })
                    .collect(),
                resource: resource_ids
                    .iter()
                    .cloned()
                    .map(|axis| AxisValue {
                        axis,
                        value: FixedQ32::ZERO,
                    })
                    .collect(),
                uncertainty: utility_ids
                    .iter()
                    .cloned()
                    .map(|axis| AxisValue {
                        axis,
                        value: FixedQ32::ZERO,
                    })
                    .collect(),
                support_digest: digest(&format!("{candidate_index}-{}", organ.as_str())),
            });
        }
    }

    let profile = UtilityProfile {
        profile_id: stable("named-host-benchmark-v1")?,
        axis_registry_digest: digest("named-host-benchmark-axis-registry"),
        normalization_manifest_digest: digest("named-host-benchmark-normalization"),
        dimensions: utility_ids
            .iter()
            .cloned()
            .map(|axis| (axis, AxisDirection::Maximize))
            .collect(),
        risk_ceilings: risk_ids
            .iter()
            .cloned()
            .map(|axis| AxisLimit {
                axis,
                maximum: FixedQ32::ZERO,
            })
            .collect(),
        resource_ceilings: resource_ids
            .iter()
            .cloned()
            .map(|axis| AxisLimit {
                axis,
                maximum: FixedQ32::ZERO,
            })
            .collect(),
        required_organs: RequiredOrganSet { organ_ids: organs },
    };
    let policy = EvaluationPolicyV1 {
        policy_id: stable("named-host-benchmark-policy-v1")?,
        utility_rules: utility_ids
            .iter()
            .cloned()
            .map(|axis| AxisAggregationRule {
                axis,
                operator: AggregationOperator::Sum,
            })
            .collect(),
        risk_rules: risk_ids
            .iter()
            .cloned()
            .map(|axis| AxisAggregationRule {
                axis,
                operator: AggregationOperator::Maximum,
            })
            .collect(),
        resource_rules: resource_ids
            .iter()
            .cloned()
            .map(|axis| AxisAggregationRule {
                axis,
                operator: AggregationOperator::Sum,
            })
            .collect(),
        uncertainty_rules: utility_ids
            .iter()
            .cloned()
            .map(|axis| AxisAggregationRule {
                axis,
                operator: AggregationOperator::Maximum,
            })
            .collect(),
        pareto_absolute_tolerances: utility_ids
            .iter()
            .cloned()
            .map(|axis| AxisValue {
                axis,
                value: FixedQ32::ZERO,
            })
            .collect(),
    };
    Ok(EvaluationFixture {
        set: ContributionSet {
            objective_digest: objective,
            generation,
            contributions,
        },
        profile,
        policy,
    })
}

fn stable(value: &str) -> Result<StableId, Box<dyn Error>> {
    StableId::new(value).map_err(|error| format!("invalid id {value}: {error:?}").into())
}

fn q32(value: i64) -> FixedQ32 {
    FixedQ32::from_raw(value << 32)
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
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
