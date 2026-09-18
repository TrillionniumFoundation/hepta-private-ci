use std::time::Instant;

use codex_hepta_control_plane::ObservedContextV1;
#[cfg(unix)]
use codex_hepta_control_plane::PlannerJournalStoreV1;
use codex_hepta_control_plane::plan_observed_context;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

const PLAN_ITERATIONS: usize = 256;
const STORE_ITERATIONS: usize = 32;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let owner = StableId::new("profile-owner")?;
    let generation = Generation::new(1)?;
    let encoded_context = vec![b'x'; 8 * 1024];

    let mut planning_micros = Vec::with_capacity(PLAN_ITERATIONS);
    let mut last_plan = None;
    for iteration in 0..PLAN_ITERATIONS {
        let observed_at = 1_000_u64 + u64::try_from(iteration)?;
        let started = Instant::now();
        let plan = plan_observed_context(ObservedContextV1 {
            owner_id: owner.clone(),
            body_generation: generation,
            source_snapshot_digest: Digest32::of_bytes(b"profile-source"),
            read_digest: Digest32::of_bytes(b"profile-read"),
            verified_item_count: 4,
            encoded_context: &encoded_context,
            maximum_context_bytes: 24 * 1024,
            observed_at_micros: observed_at,
            expires_at_micros: observed_at + 1_000_000,
        })?;
        planning_micros.push(micros(started.elapsed()));
        last_plan = Some(plan);
    }
    let last_plan = last_plan.expect("profile loop is non-empty");

    #[cfg(unix)]
    let store_metrics = profile_store(&last_plan.evaluation.plan)?;
    #[cfg(not(unix))]
    let store_metrics = {
        let _ = &last_plan;
        StoreMetrics::default()
    };

    let planning = summarize(&mut planning_micros);
    let sha = std::env::var("GITHUB_SHA").unwrap_or_else(|_| "local".to_string());
    let runner_os = std::env::var("RUNNER_OS").unwrap_or_else(|_| std::env::consts::OS.to_string());
    let runner_arch =
        std::env::var("RUNNER_ARCH").unwrap_or_else(|_| std::env::consts::ARCH.to_string());
    let rust_profile = std::env::var("PROFILE").unwrap_or_else(|_| "dev".to_string());

    println!(
        concat!(
            "{{",
            "\"schema\":\"hepta.control-runtime-profile.v1\",",
            "\"sha\":\"{}\",",
            "\"runner_os\":\"{}\",",
            "\"runner_arch\":\"{}\",",
            "\"build_profile\":\"{}\",",
            "\"planning\":{{\"iterations\":{},\"p50_us\":{},\"p95_us\":{},\"p99_us\":{},\"max_us\":{}}},",
            "\"store\":{{\"iterations\":{},\"persist_p95_us\":{},\"reopen_p95_us\":{},\"persist_max_us\":{},\"reopen_max_us\":{}}}",
            "}}"
        ),
        escape(&sha),
        escape(&runner_os),
        escape(&runner_arch),
        escape(&rust_profile),
        PLAN_ITERATIONS,
        planning.p50,
        planning.p95,
        planning.p99,
        planning.max,
        STORE_ITERATIONS,
        store_metrics.persist.p95,
        store_metrics.reopen.p95,
        store_metrics.persist.max,
        store_metrics.reopen.max,
    );

    Ok(())
}

#[derive(Clone, Copy, Default)]
struct Summary {
    p50: u64,
    p95: u64,
    p99: u64,
    max: u64,
}

#[derive(Clone, Copy, Default)]
struct StoreMetrics {
    persist: Summary,
    reopen: Summary,
}

#[cfg(unix)]
fn profile_store(
    receipt: &codex_hepta_control_plane::FeasiblePlanReceiptV1,
) -> Result<StoreMetrics, Box<dyn std::error::Error>> {
    let root = std::env::temp_dir().join(format!(
        "hepta-control-runtime-profile-{}",
        std::process::id()
    ));
    let _ = std::fs::remove_dir_all(&root);

    let (mut store, mut journal) = PlannerJournalStoreV1::open(&root, &[])?;
    journal.record_decision(receipt)?;
    journal.select_plan(Digest32::of_bytes(b"profile-selection"), receipt)?;
    store.persist(&journal)?;

    let mut persist = Vec::with_capacity(STORE_ITERATIONS);
    for _ in 0..STORE_ITERATIONS {
        let started = Instant::now();
        store.persist(&journal)?;
        persist.push(micros(started.elapsed()));
    }
    drop(store);

    let mut reopen = Vec::with_capacity(STORE_ITERATIONS);
    for _ in 0..STORE_ITERATIONS {
        let started = Instant::now();
        let (store, reopened) = PlannerJournalStoreV1::open(&root, &[])?;
        let elapsed = started.elapsed();
        if reopened.selected_plan_digest() != Some(receipt.receipt_digest()) {
            return Err("reopened planner store lost selected decision".into());
        }
        reopen.push(micros(elapsed));
        drop(store);
    }

    std::fs::remove_dir_all(&root)?;
    Ok(StoreMetrics {
        persist: summarize(&mut persist),
        reopen: summarize(&mut reopen),
    })
}

fn micros(duration: std::time::Duration) -> u64 {
    u64::try_from(duration.as_micros()).unwrap_or(u64::MAX)
}

fn summarize(values: &mut [u64]) -> Summary {
    values.sort_unstable();
    Summary {
        p50: percentile(values, 50),
        p95: percentile(values, 95),
        p99: percentile(values, 99),
        max: values.last().copied().unwrap_or(0),
    }
}

fn percentile(values: &[u64], percentile: usize) -> u64 {
    if values.is_empty() {
        return 0;
    }
    let numerator = percentile.saturating_mul(values.len().saturating_sub(1));
    let index = numerator.div_ceil(100);
    values[index.min(values.len() - 1)]
}

fn escape(value: &str) -> String {
    value.replace('\\', "\\\\").replace('"', "\\\"")
}

