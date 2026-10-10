use super::*;
use std::fs;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

fn p_ns(samples: &mut [u128], pct: usize) -> u128 {
    samples.sort_unstable();
    samples[(samples.len() - 1) * pct / 100]
}

fn rss_kib() -> Option<u64> {
    std::fs::read_to_string("/proc/self/status").ok()?
        .lines().find(|line| line.starts_with("VmRSS:"))?
        .split_whitespace().nth(1)?.parse().ok()
}

fn process_cpu_ticks() -> Option<u64> {
    let stat = std::fs::read_to_string("/proc/self/stat").ok()?;
    let after_comm = stat.rsplit_once(") ")?.1;
    let fields = after_comm.split_whitespace().collect::<Vec<_>>();
    Some(fields.get(11)?.parse::<u64>().ok()?
        .saturating_add(fields.get(12)?.parse::<u64>().ok()?))
}

#[test]
#[ignore = "qualified source workload, needs actual target-host storage measurements"]
fn durable_writer_reopen_64_256_1024_4096_scope_history() {
    for scopes in [64_usize, 256, 1024, 4096] {
        let nonce = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let path = std::env::temp_dir().join(format!(
            "hepta-durable-scale-{}-{scopes}-{nonce}", std::process::id()
        ));
        let baseline_rss = rss_kib();
        let start_cpu = process_cpu_ticks();
        let mut writer = DurableInferenceControl::open(&path, scopes + 1).unwrap();
        let mut append_ns = Vec::with_capacity(scopes);
        let start = Instant::now();
        for index in 0..scopes {
            let request = InferenceRequest {
                request_id: format!("scope-{index}"),
                principal_id: "baseline-principal".to_string(),
                model_digest: "1".repeat(64),
                payload_digest: "2".repeat(64),
                semantic_digest: "3".repeat(64),
                maximum_tokens: 16,
                deadline_ms: 100_000,
            };
            let begun = Instant::now();
            let receipt = writer.submit(1, request).unwrap();
            assert_eq!(receipt.revision, 1);
            append_ns.push(begun.elapsed().as_nanos());
        }
        let append_total = start.elapsed().as_nanos();
        drop(writer);

        let started = Instant::now();
        let reopened = DurableInferenceControl::open(&path, scopes + 1).unwrap();
        let reopen_ns = started.elapsed().as_nanos();
        let mut read_ns = Vec::with_capacity(scopes);
        for index in 0..scopes {
            let id = format!("scope-{index}");
            let started = Instant::now();
            let record = reopened.get(&id).unwrap();
            assert_eq!(record.state, RequestState::Pending);
            assert_eq!(record.revision, 1);
            read_ns.push(started.elapsed().as_nanos());
        }
        let disk_bytes = fs::metadata(&path).unwrap().len();
        let after_rss = rss_kib();
        let cpu_ticks = process_cpu_ticks()
            .zip(start_cpu).map(|(after, before)| after.saturating_sub(before));
        eprintln!(
            "HEPTA_DURABLE_SCALE_V1 scopes={scopes} writes={scopes} \
             append_total_ns={append_total} append_p50_ns={} append_p95_ns={} append_p99_ns={} \
             reopen_ns={reopen_ns} read_p50_ns={} read_p95_ns={} read_p99_ns={} \
             journal_bytes={disk_bytes} rss_before_kib={baseline_rss:?} \
             rss_after_kib={after_rss:?} cpu_process_ticks={cpu_ticks:?}",
            p_ns(&mut append_ns, 50), p_ns(&mut append_ns, 95), p_ns(&mut append_ns, 99),
            p_ns(&mut read_ns, 50), p_ns(&mut read_ns, 95), p_ns(&mut read_ns, 99),
        );
        drop(reopened);
        fs::remove_file(path).unwrap();
    }
}
