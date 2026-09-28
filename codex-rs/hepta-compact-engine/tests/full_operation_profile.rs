//! Exact-source, ignored end-to-end publication/reopen profile.
//!
//! The existing product fixture is included so the profile exercises the same
//! signed manifest, candidate, proof, durable owner and cryptographic reopen
//! path as the product regression instead of inventing a benchmark-only API.

pub use codex_hepta_compact_engine::*;

mod profile {
    use std::fs;
    use std::time::Instant;

    include!("../src/product_e2e_tests.rs");

    const PROFILE_SAMPLES: usize = 32;

    #[tokio::test]
    #[ignore = "full durable profile; run in compact.engine capacity workflow"]
    async fn full_publication_reopen_profile() {
        let owner = id("agent:full-profile:owner");
        let fixture = ProductTrustFixture::new(&owner);
        let temp = TempDir::new().expect("profile temp dir");
        let url = database_url(&temp);
        let publication = sealed_publication(
            &fixture,
            &["memory:full-profile:a", "memory:full-profile:b"],
            1,
            2,
            None,
            "full-profile",
        );
        let coordinator = MemoryCheckpointCoordinatorV2::open(
            &url,
            owner.as_str(),
            fixture.root.verifying_key().to_bytes(),
            &fixture.manifest_bytes,
            "lease:full-profile:one",
            1,
            NOW + 10_000,
            NOW,
        )
        .await
        .expect("open full profile owner");

        let database_path = temp.path().join("product-e2e.db");
        let wal_path = temp.path().join("product-e2e.db-wal");
        let database_before = file_bytes(&database_path);
        let wal_before = file_bytes(&wal_path);
        let peak_rss_before = peak_rss_kib();
        let mut publish_micros = Vec::with_capacity(PROFILE_SAMPLES);
        let mut reopen_micros = Vec::with_capacity(PROFILE_SAMPLES);

        for offset in 0..PROFILE_SAMPLES {
            let now = NOW + u64::try_from(offset).expect("bounded offset");
            let started = Instant::now();
            coordinator
                .publish_verified_checkpoint(
                    "operation:full-profile",
                    &publication,
                    NOW + 9_000,
                    now,
                )
                .await
                .expect("full profile publication");
            publish_micros.push(elapsed_micros(started));

            let started = Instant::now();
            let recovered = coordinator
                .recover_current_checkpoint("scope:e2e", "purpose:e2e", now)
                .await
                .expect("full profile reopen")
                .expect("full profile checkpoint");
            assert_eq!(
                recovered.checkpoint_digest(),
                publication.candidate().checkpoint().checkpoint_digest
            );
            reopen_micros.push(elapsed_micros(started));
        }

        publish_micros.sort_unstable();
        reopen_micros.sort_unstable();
        let database_after = file_bytes(&database_path);
        let wal_after = file_bytes(&wal_path);
        let peak_rss_after = peak_rss_kib();
        println!(
            "COMPACT_ENGINE_FULL_OPERATION_PROFILE={{\"samples\":{},\"payload_bytes\":{},\"archive_bytes\":{},\"publish_p50_micros\":{},\"publish_p95_micros\":{},\"publish_p99_micros\":{},\"reopen_p50_micros\":{},\"reopen_p95_micros\":{},\"reopen_p99_micros\":{},\"database_bytes_before\":{},\"database_bytes_after\":{},\"wal_bytes_before\":{},\"wal_bytes_after\":{},\"peak_rss_kib_before\":{},\"peak_rss_kib_after\":{}}}",
            PROFILE_SAMPLES,
            publication.candidate().semantic_payload().payload.len(),
            publication.archive().len(),
            percentile(&publish_micros, 50),
            percentile(&publish_micros, 95),
            percentile(&publish_micros, 99),
            percentile(&reopen_micros, 50),
            percentile(&reopen_micros, 95),
            percentile(&reopen_micros, 99),
            database_before,
            database_after,
            wal_before,
            wal_after,
            peak_rss_before,
            peak_rss_after,
        );
    }

    fn elapsed_micros(started: Instant) -> u64 {
        u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX)
    }

    fn percentile(values: &[u64], percentile: usize) -> u64 {
        let rank = values
            .len()
            .saturating_mul(percentile)
            .saturating_add(99)
            / 100;
        values[rank.saturating_sub(1).min(values.len().saturating_sub(1))]
    }

    fn file_bytes(path: &std::path::Path) -> u64 {
        fs::metadata(path).map(|metadata| metadata.len()).unwrap_or(0)
    }

    fn peak_rss_kib() -> u64 {
        fs::read_to_string("/proc/self/status")
            .ok()
            .and_then(|status| {
                status.lines().find_map(|line| {
                    line.strip_prefix("VmHWM:")?
                        .split_whitespace()
                        .next()?
                        .parse::<u64>()
                        .ok()
                })
            })
            .unwrap_or(0)
    }
}
