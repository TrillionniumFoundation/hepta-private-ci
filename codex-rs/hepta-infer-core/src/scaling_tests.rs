//! Opt-in source workload for 64/256/1024/4096 scope/cell configurations.
//! It does not measure a real provider, CAS, signatures, CNS or GPU/NPU.

use std::sync::Arc;
use std::time::Instant;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::SharedFeatureBufferV1;
use crate::microbatch::BoundedMicrobatchSchedulerV1;
use crate::microbatch::InferenceIntentV1;
use crate::microbatch::MicrobatchKeyV1;
use crate::microbatch::MicrobatchLimitsV1;
use crate::scoped_cache::FenceCacheBindingV1;
use crate::scoped_cache::ScopedCachesV1;

fn id(value: impl Into<String>) -> StableId {
    StableId::new(value).unwrap()
}

fn digest(seed: &str) -> Digest32 {
    Digest32::of_bytes(seed.as_bytes())
}

fn percentile_ns(samples: &mut [u128], percentile: usize) -> u128 {
    samples.sort_unstable();
    let index = ((samples.len() - 1) * percentile).div_ceil(100);
    samples[index]
}

fn linux_rss_kib() -> Option<u64> {
    let status = std::fs::read_to_string("/proc/self/status").ok()?;
    let line = status.lines().find(|line| line.starts_with("VmRSS:"))?;
    line.split_whitespace().nth(1)?.parse().ok()
}

#[test]
#[ignore = "opt-in, run with --ignored --nocapture on intended deployment hardware"]
fn workload_64_256_1024_4096_scope_cells() {
    // Use one independently named cell per scope, two requests per cell.
    // Both paths use the exact same immutable input and identity bindings.
    for scopes in [64_usize, 256, 1024, 4096] {
        let shared = SharedFeatureBufferV1::from_vec(vec![1 << 24; 128]).unwrap();
        let mut intents = Vec::with_capacity(scopes * 2);
        let mut bindings = Vec::with_capacity(scopes);
        for scope_index in 0..scopes {
            let scope = id(format!("scope-{scope_index}"));
            let key = MicrobatchKeyV1 {
                scope_id: scope.clone(),
                model_digest: digest("fixed-model"),
                generation: Generation::new(1).unwrap(),
                route_fence: 1,
                authority_epoch: 1,
            };
            let binding = FenceCacheBindingV1 {
                scope,
                generation: key.generation,
                route_fence: key.route_fence,
                revocation_epoch: key.authority_epoch,
                binding_digest: digest("admitted-owner-binding"),
            };
            bindings.push(binding);
            for local in 0..2 {
                intents.push(InferenceIntentV1 {
                    request_id: id(format!("req-{scope_index}-{local}")),
                    key: key.clone(),
                    feature_digest: shared.digest(),
                    shared_features: Some(shared.clone()),
                    deadline_ms: 100_000,
                });
            }
        }

        // No-change baseline: independent single-request planner without
        // batch grouping. Not an apples-to-apples deployed baseline.
        let baseline_started = Instant::now();
        let mut baseline_ns = Vec::with_capacity(intents.len());
        let mut baseline_count = 0_usize;
        for intent in &intents {
            let started = Instant::now();
            assert_eq!(
                intent.shared_features.as_ref().unwrap().digest(),
                intent.feature_digest
            );
            assert_eq!(intent.key.model_digest, digest("fixed-model"));
            baseline_count += 1;
            baseline_ns.push(started.elapsed().as_nanos());
        }
        let baseline_total_ns = baseline_started.elapsed().as_nanos();
        assert_eq!(baseline_count, scopes * 2);

        let config = MicrobatchLimitsV1 {
            max_pending: 16_384,
            max_batch_size: 4,
            max_lanes_per_poll: 64,
            max_wait_ms: 5,
        };
        let mut scheduler = BoundedMicrobatchSchedulerV1::new(config).unwrap();
        let mut enqueue_ns = Vec::with_capacity(intents.len());
        let enqueue_started = Instant::now();
        for intent in intents {
            let started = Instant::now();
            scheduler.enqueue(1, intent).unwrap();
            enqueue_ns.push(started.elapsed().as_nanos());
        }
        let enqueue_total_ns = enqueue_started.elapsed().as_nanos();
        assert_eq!(scheduler.pending(), scopes * 2);
        assert_eq!(scheduler.active_lanes(), scopes);

        let mut batches = 0;
        let mut seen = 0;
        let mut polls_ns = Vec::with_capacity(scopes);
        let drain_started = Instant::now();
        while scheduler.pending() != 0 {
            let started = Instant::now();
            let poll = scheduler.poll(10).unwrap();
            polls_ns.push(started.elapsed().as_nanos());
            assert!(poll.scanned_lanes <= 64);
            assert!(poll.expired_request_ids.is_empty());
            let batch = poll.batch.expect("every cell must drain at max-wait");
            assert_eq!(batch.requests.len(), 2);
            assert!(
                batch
                    .requests
                    .iter()
                    .all(|request| request.key == batch.key)
            );
            assert!(batch.requests.iter().all(|request| {
                request
                    .shared_features
                    .as_ref()
                    .unwrap()
                    .shares_allocation_with(&shared)
            }));
            seen += batch.requests.len();
            batches += 1;
        }
        let drain_total_ns = drain_started.elapsed().as_nanos();
        assert_eq!(seen, scopes * 2);
        assert_eq!(batches, scopes);

        // Four independent facade fields, one generation/fence backend.
        let mut caches = ScopedCachesV1::<u64, u64, u64, u64>::new(4096).unwrap();
        let cache_started = Instant::now();
        let mut cache_ns = Vec::with_capacity(scopes);
        for (i, binding) in bindings.iter().enumerate() {
            let started = Instant::now();
            for cache in [
                &mut caches.authority,
                &mut caches.ndu,
                &mut caches.worker,
                &mut caches.retrieval,
            ] {
                cache.observe_binding(binding.clone()).unwrap();
                cache.put(10, binding, Arc::new(i as u64), 100).unwrap();
                assert_eq!(*cache.get(11, binding).unwrap(), i as u64);
            }
            cache_ns.push(started.elapsed().as_nanos());
        }
        let cache_total_ns = cache_started.elapsed().as_nanos();

        eprintln!(
            "HEPTA_SOURCE_SCALE_V1 scopes={scopes} cells={scopes} intents={seen} batches={batches} \
             base_individual_total_ns={baseline_total_ns} base_p50_ns={} base_p95_ns={} base_p99_ns={} \
             enqueue_total_ns={enqueue_total_ns} enqueue_p50_ns={} enqueue_p95_ns={} enqueue_p99_ns={} \
             drain_total_ns={drain_total_ns} poll_p50_ns={} poll_p95_ns={} poll_p99_ns={} \
             cache_total_ns={cache_total_ns} cache_p50_ns={} cache_p95_ns={} cache_p99_ns={} \
             rss_kib={:?}",
            percentile_ns(&mut baseline_ns, 50),
            percentile_ns(&mut baseline_ns, 95),
            percentile_ns(&mut baseline_ns, 99),
            percentile_ns(&mut enqueue_ns, 50),
            percentile_ns(&mut enqueue_ns, 95),
            percentile_ns(&mut enqueue_ns, 99),
            percentile_ns(&mut polls_ns, 50),
            percentile_ns(&mut polls_ns, 95),
            percentile_ns(&mut polls_ns, 99),
            percentile_ns(&mut cache_ns, 50),
            percentile_ns(&mut cache_ns, 95),
            percentile_ns(&mut cache_ns, 99),
            linux_rss_kib(),
        );
    }
}
