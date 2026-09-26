//! Local storage probe using synthetic frozen plans; not longitudinal efficacy.
//! Usage: cargo run --release -p codex-hepta-intelligence-eval --example
//! fenced_holdout_probe -- <new-directory> [number-of-plans:1..=2048]
use std::error::Error;
#[cfg(unix)]
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::{self};
use std::path::PathBuf;
use std::time::Instant;

use codex_hepta_intelligence_eval::CrossFoldPartitionV1;
use codex_hepta_intelligence_eval::CrossFoldPlanV1;
use codex_hepta_intelligence_eval::EvaluationClaimScopeV1;
use codex_hepta_intelligence_eval::EvaluationDirectionV1;
use codex_hepta_intelligence_eval::FencedFinalHoldoutOwnerV1;
use codex_hepta_intelligence_eval::HoldoutFenceIssuerV1;
use codex_hepta_intelligence_eval::HoldoutUseDispositionV1;
use codex_hepta_intelligence_eval::LockedFileFinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::MetricContractV1;
use codex_hepta_intelligence_eval::freeze_cross_fold_plan;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

type ProbeResult<T> = Result<T, Box<dyn Error>>;
fn id(value: &str) -> ProbeResult<StableId> {
    Ok(StableId::new(value)?)
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn plan(index: usize) -> ProbeResult<codex_hepta_intelligence_eval::CrossFoldPlanReceiptV1> {
    let final_window = id(&format!("final-{index}"))?;
    Ok(freeze_cross_fold_plan(CrossFoldPlanV1 {
        plan_id: id(&format!("storage-plan-{index}"))?,
        claim_scope: EvaluationClaimScopeV1::Qualification,
        candidate_id: id("synthetic-candidate")?,
        baseline_id: id("synthetic-baseline")?,
        objective_digest: digest("storage-probe-only"),
        dataset_digest: digest("synthetic-dataset"),
        estimand_digest: digest("storage-probe-estimand"),
        metric_contracts: vec![MetricContractV1 {
            metric_id: id("utility")?,
            direction: EvaluationDirectionV1::Maximize,
            safety_floor: Some(FixedQ32::ZERO),
        }],
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 1,
        folds: vec![
            CrossFoldPartitionV1 {
                fold_id: id("fold-a")?,
                training_principals: vec![id("train-a")?],
                training_episodes: vec![id("episode-train-a")?],
                training_windows: vec![id("window-train-a")?],
                holdout_principals: vec![id("heldout-a")?],
                holdout_episodes: vec![id("episode-heldout-a")?],
                holdout_windows: vec![id("window-heldout-a")?],
                model_digest: digest("model-a"),
                predictions_digest: digest("prediction-a"),
            },
            CrossFoldPartitionV1 {
                fold_id: id("fold-b")?,
                training_principals: vec![id("train-b")?],
                training_episodes: vec![id("episode-train-b")?],
                training_windows: vec![id("window-train-b")?],
                holdout_principals: vec![id("heldout-b")?],
                holdout_episodes: vec![id("episode-heldout-b")?],
                holdout_windows: vec![final_window.clone()],
                model_digest: digest("model-b"),
                predictions_digest: digest("prediction-b"),
            },
        ],
        final_holdout_window_id: final_window,
        final_holdout_digest: digest(&format!("holdout-{index}")),
    })?)
}

fn percentile(values: &[u128], percent: usize) -> u128 {
    values[(values.len() * percent).div_ceil(100).saturating_sub(1)]
}

fn main() -> ProbeResult<()> {
    let mut args = std::env::args().skip(1);
    let root = PathBuf::from(args.next().ok_or("missing new probe directory")?);
    let count: usize = args.next().map_or_else(|| Ok(128), |value| value.parse())?;
    if !(1..=2048).contains(&count) || args.next().is_some() {
        return Err("expected a new directory and 1..=2048 plans".into());
    }
    let source = std::env::var("HEPTA_SOURCE_SHA").unwrap_or_else(|_| "unrecorded".to_string());
    if source != "unrecorded"
        && (source.len() != 40 || !source.bytes().all(|b| b.is_ascii_hexdigit()))
    {
        return Err("HEPTA_SOURCE_SHA must identify the tested commit".into());
    }
    fs::create_dir(&root)?; // Never clobber an existing owner namespace.
    let path = root.join("holdout.journal");
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(&path)?;
    let binding = digest("hepta.local-storage-probe.v1");
    let store = LockedFileFinalHoldoutCasStoreV1::create(file, binding)?;
    #[cfg(unix)]
    File::open(&root)?.sync_all()?;
    let mut fences =
        HoldoutFenceIssuerV1::resume(id("storage-probe")?, digest("synthetic-authority"), None)?;
    let mut owner =
        FencedFinalHoldoutOwnerV1::initialize(store, binding, fences.issue(digest("lease-1"))?)?;
    let mut micros = Vec::with_capacity(count);
    for index in 0..count {
        let frozen = plan(index)?;
        let start = Instant::now();
        let receipt = owner.consume(&frozen)?;
        micros.push(start.elapsed().as_micros());
        if receipt.disposition != HoldoutUseDispositionV1::Recorded {
            return Err("new plan was not recorded".into());
        }
    }
    let anchor = owner.anchor();
    drop(owner.into_store());
    let start = Instant::now();
    let file = OpenOptions::new().read(true).write(true).open(&path)?;
    let store = LockedFileFinalHoldoutCasStoreV1::recover(file, binding, Some(anchor))?;
    let mut fences = HoldoutFenceIssuerV1::resume(
        id("storage-probe")?,
        digest("synthetic-authority"),
        Some(anchor),
    )?;
    let mut owner =
        FencedFinalHoldoutOwnerV1::recover(store, binding, fences.issue(digest("lease-2"))?)?;
    let recovery_micros = start.elapsed().as_micros();
    let replay = owner.consume(&plan(count - 1)?)?;
    if replay.disposition != HoldoutUseDispositionV1::IdempotentReplay
        || owner.anchor().record_count != count as u64
    {
        return Err("recovery changed the original holdout history".into());
    }
    let bytes = fs::metadata(&path)?.len();
    let peak_kib = fs::read_to_string("/proc/self/status")
        .ok()
        .and_then(|status| {
            status
                .lines()
                .find(|line| line.starts_with("VmHWM:"))
                .and_then(|line| line.split_whitespace().nth(1))
                .and_then(|value| value.parse::<u64>().ok())
        })
        .unwrap_or(0);
    micros.sort_unstable();
    println!(
        "{{\"schema\":\"hepta.learning-eval.storage-probe.v1\",\"source\":\"{source}\",\"qualificationOnly\":true,\"syntheticPlans\":true,\"plans\":{count},\"journalBytes\":{bytes},\"appendP50Micros\":{},\"appendP95Micros\":{},\"appendP99Micros\":{},\"appendMaxMicros\":{},\"recoveryMicros\":{recovery_micros},\"peakResidentKiB\":{peak_kib},\"replayRecordCount\":{}}}",
        percentile(&micros, 50),
        percentile(&micros, 95),
        percentile(&micros, 99),
        percentile(&micros, 100),
        owner.anchor().record_count
    );
    Ok(())
}
