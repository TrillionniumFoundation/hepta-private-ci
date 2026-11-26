//! Qualification-only latency and recovery measurements for kernel.authority.
//!
//! The test is inert during ordinary unit-test runs. Set
//! `HEPTA_KERNEL_AUTHORITY_BENCH_OUTPUT` to emit one machine-readable receipt.
//! The receipt is source evidence only and grants no production SLO.

#![cfg(unix)]

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_contracts::authority_lease::AuthorityLeaseFrontier;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;
use serde_json::json;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Barrier;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::thread;
use std::time::Instant;

const DEFAULT_SAMPLES: usize = 128;
const MAX_SAMPLES: usize = 2_048;
const CONTENTION_THREADS: usize = 4;
const CONTENTION_ITERATIONS: usize = 64;

#[derive(Debug)]
struct BenchClock(AtomicU64);

impl BenchClock {
    fn new(now_unix_ms: u64) -> Self {
        Self(AtomicU64::new(now_unix_ms))
    }
}

impl AuthorityClock for BenchClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(self.0.load(Ordering::Acquire))
    }
}

fn binding(index: usize) -> AuthorityLeaseBinding {
    let marker = (index % 250) as u8 + 1;
    AuthorityLeaseBinding {
        principal_id: format!("benchmark-principal-{index}"),
        operation_class: "benchmark.dispatch".into(),
        destination_id: "kernel.authority.benchmark".into(),
        scope_sha256: [marker; 32],
        payload_sha256: [marker.saturating_add(1); 32],
    }
}

fn micros(started: Instant) -> u64 {
    u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX)
}

fn percentile(samples: &[u64], numerator: usize) -> u64 {
    assert!(!samples.is_empty());
    let index = ((samples.len() - 1) * numerator) / 100;
    samples[index]
}

fn distribution(mut samples: Vec<u64>) -> serde_json::Value {
    samples.sort_unstable();
    let sum: u128 = samples.iter().copied().map(u128::from).sum();
    let mean = u64::try_from(sum / samples.len() as u128).unwrap_or(u64::MAX);
    json!({
        "count": samples.len(),
        "minUs": samples[0],
        "meanUs": mean,
        "p50Us": percentile(&samples, 50),
        "p95Us": percentile(&samples, 95),
        "p99Us": percentile(&samples, 99),
        "maxUs": samples[samples.len() - 1]
    })
}

fn configured_samples() -> usize {
    std::env::var("HEPTA_KERNEL_AUTHORITY_BENCH_SAMPLES")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(DEFAULT_SAMPLES)
        .clamp(16, MAX_SAMPLES)
}

#[test]
fn qualification_benchmark_emits_machine_receipt() {
    let Some(output) = std::env::var_os("HEPTA_KERNEL_AUTHORITY_BENCH_OUTPUT") else {
        return;
    };
    let output = PathBuf::from(output);
    let samples = configured_samples();
    let directory = tempfile::tempdir().expect("benchmark state directory");
    fs::set_permissions(directory.path(), fs::Permissions::from_mode(0o700))
        .expect("private benchmark directory");
    let clock = Arc::new(BenchClock::new(2_000));
    let registry = AuthorityLeaseRegistry::open_state_dir_with_clock(
        directory.path(),
        "benchmark-authority".into(),
        AuthorityLeaseFrontier::for_empty_epoch(7).expect("initial frontier"),
        clock,
    )
    .expect("open benchmark authority");
    let verifier = registry.verifier();

    let total_started = Instant::now();
    let mut put_us = Vec::with_capacity(samples);
    let mut dispatch_us = Vec::with_capacity(samples);
    let mut revoke_us = Vec::with_capacity(samples);

    for index in 0..samples {
        let lease_id = format!("benchmark-lease-{index}");
        let expected = binding(index);
        let started = Instant::now();
        registry
            .put_lease(
                AuthorityLease {
                    schema_version: 1,
                    lease_id: lease_id.clone(),
                    authority_epoch: 7,
                    revision: 1,
                    binding: expected.clone(),
                    issued_at_unix_ms: 1_000,
                    expires_at_unix_ms: 60_000,
                },
                0,
            )
            .expect("durable lease put");
        put_us.push(micros(started));

        let started = Instant::now();
        let dispatch = verifier
            .bind_dispatch(&lease_id, 1, &expected)
            .expect("bind benchmark dispatch");
        let (value, witness) = dispatch
            .dispatch(|_| index)
            .expect("enter benchmark dispatch");
        assert_eq!(value, index);
        witness.validate().expect("benchmark witness");
        dispatch_us.push(micros(started));

        let started = Instant::now();
        registry
            .revoke(&lease_id, 1, [17; 32])
            .expect("durable lease revoke");
        revoke_us.push(micros(started));
    }

    let contention_binding = binding(samples + 1);
    let contention_lease_id = "benchmark-contention";
    registry
        .put_lease(
            AuthorityLease {
                schema_version: 1,
                lease_id: contention_lease_id.into(),
                authority_epoch: 7,
                revision: 1,
                binding: contention_binding.clone(),
                issued_at_unix_ms: 1_000,
                expires_at_unix_ms: 60_000,
            },
            0,
        )
        .expect("contention lease");

    let barrier = Arc::new(Barrier::new(CONTENTION_THREADS));
    let contention_results = Arc::new(Mutex::new(Vec::with_capacity(
        CONTENTION_THREADS * CONTENTION_ITERATIONS,
    )));
    let mut workers = Vec::with_capacity(CONTENTION_THREADS);
    for _ in 0..CONTENTION_THREADS {
        let verifier = verifier.clone();
        let barrier = Arc::clone(&barrier);
        let results = Arc::clone(&contention_results);
        let expected = contention_binding.clone();
        workers.push(thread::spawn(move || {
            barrier.wait();
            let mut local = Vec::with_capacity(CONTENTION_ITERATIONS);
            for _ in 0..CONTENTION_ITERATIONS {
                let started = Instant::now();
                verifier
                    .bind_dispatch(contention_lease_id, 1, &expected)
                    .expect("contention bind")
                    .dispatch(|_| ())
                    .expect("contention dispatch");
                local.push(micros(started));
            }
            results.lock().expect("contention results").extend(local);
        }));
    }
    for worker in workers {
        worker.join().expect("contention worker");
    }
    let contention_us = Arc::try_unwrap(contention_results)
        .expect("all contention workers completed")
        .into_inner()
        .expect("contention results mutex");

    let total_us = micros(total_started).max(1);
    let operation_count = samples.saturating_mul(3).saturating_add(
        CONTENTION_THREADS
            .saturating_mul(CONTENTION_ITERATIONS)
            .saturating_add(1),
    );
    let throughput_milli = u64::try_from(
        (operation_count as u128)
            .saturating_mul(1_000_000_000)
            .saturating_div(u128::from(total_us)),
    )
    .unwrap_or(u64::MAX);

    let frontier = registry.frontier().expect("benchmark frontier");
    drop(verifier);
    drop(registry);
    let reopen_started = Instant::now();
    let reopened = AuthorityLeaseRegistry::open_state_dir_with_clock(
        directory.path(),
        "benchmark-authority".into(),
        frontier,
        Arc::new(BenchClock::new(2_000)),
    )
    .expect("reopen benchmark authority");
    let reopen_us = micros(reopen_started);
    let capacity = reopened.capacity().expect("benchmark capacity");
    drop(reopened);
    let snapshot_bytes = fs::metadata(directory.path().join("authority-leases.json"))
        .expect("benchmark snapshot")
        .len();

    let receipt = json!({
        "schema": "hepta.kernel-authority-benchmark.v1",
        "schemaVersion": 1,
        "qualificationOnly": true,
        "productionSloGranted": false,
        "samples": samples,
        "state": {
            "snapshotBytes": snapshot_bytes,
            "leases": capacity.leases,
            "revocations": capacity.revocations,
            "retiredLeaseIds": capacity.retired_lease_ids,
            "reopenUs": reopen_us
        },
        "operations": {
            "durableLeasePut": distribution(put_us),
            "dispatchEntry": distribution(dispatch_us),
            "durableLeaseRevoke": distribution(revoke_us),
            "contendedDispatchEntry": distribution(contention_us)
        },
        "contention": {
            "threads": CONTENTION_THREADS,
            "iterationsPerThread": CONTENTION_ITERATIONS
        },
        "throughputMilliOperationsPerSecond": throughput_milli,
        "totalMeasuredUs": total_us
    });
    if let Some(parent) = output.parent() {
        fs::create_dir_all(parent).expect("benchmark receipt directory");
    }
    fs::write(
        output,
        serde_json::to_vec(&receipt).expect("benchmark receipt JSON"),
    )
    .expect("write benchmark receipt");
}
