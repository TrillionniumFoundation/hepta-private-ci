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

    const PROFILE_SAMPLES: usize = 16;

    #[tokio::test]
    #[ignore = "full durable profile; run in compact.engine capacity workflow"]
    async fn full_publication_reopen_profile() {
        let peak_rss_before = peak_rss_kib();
        let mut publish_micros = Vec::with_capacity(PROFILE_SAMPLES);
        let mut reopen_micros = Vec::with_capacity(PROFILE_SAMPLES);
        let mut database_growth_bytes = 0_u64;
        let mut wal_growth_bytes = 0_u64;
        let mut payload_bytes = 0_usize;
        let mut archive_bytes = 0_usize;

        for offset in 0..PROFILE_SAMPLES {
            let owner = id(&format!("agent:full-profile:owner:{offset}"));
            let fixture = ProductTrustFixture::new(&owner);
            let temp = TempDir::new().expect("profile temp dir");
            let url = database_url(&temp);
            let label = format!("full-profile-{offset}");
            let publication = sealed_publication(
                &fixture,
                &["memory:full-profile:a", "memory:full-profile:b"],
                1,
                2,
                None,
                &label,
            );
            payload_bytes = publication.candidate().semantic_payload().payload.len();
            archive_bytes = publication.archive().len();
            let now = NOW + u64::try_from(offset).expect("bounded offset");
            let coordinator = MemoryCheckpointCoordinatorV2::open(
                &url,
                owner.as_str(),
                fixture.root.verifying_key().to_bytes(),
                &fixture.manifest_bytes,
                &format!("lease:full-profile:{offset}"),
                1,
                NOW + 10_000,
                now,
            )
            .await
            .expect("open full profile owner");

            let database_path = temp.path().join("product-e2e.db");
            let wal_path = temp.path().join("product-e2e.db-wal");
            let database_before = file_bytes(&database_path);
            let wal_before = file_bytes(&wal_path);

            let started = Instant::now();
            let receipt = coordinator
                .publish_verified_checkpoint(
                    &format!("operation:full-profile:{offset}"),
                    &publication,
                    NOW + 9_000,
                    now,
                )
                .await
                .expect("full profile publication");
            assert_eq!(receipt.disposition, DurableCompactionDisposition::Inserted);
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

            database_growth_bytes = database_growth_bytes.saturating_add(
                file_bytes(&database_path).saturating_sub(database_before),
            );
            wal_growth_bytes = wal_growth_bytes
                .saturating_add(file_bytes(&wal_path).saturating_sub(wal_before));
        }

        publish_micros.sort_unstable();
        reopen_micros.sort_unstable();
        let peak_rss_after = peak_rss_kib();
        println!(
            "COMPACT_ENGINE_FULL_OPERATION_PROFILE={{\"samples\":{},\"payload_bytes\":{},\"archive_bytes\":{},\"publish_p50_micros\":{},\"publish_p95_micros\":{},\"publish_p99_micros\":{},\"reopen_p50_micros\":{},\"reopen_p95_micros\":{},\"reopen_p99_micros\":{},\"database_growth_bytes\":{},\"wal_growth_bytes\":{},\"peak_rss_kib_before\":{},\"peak_rss_kib_after\":{}}}",
            PROFILE_SAMPLES,
            payload_bytes,
            archive_bytes,
            percentile(&publish_micros, 50),
            percentile(&publish_micros, 95),
            percentile(&publish_micros, 99),
            percentile(&reopen_micros, 50),
            percentile(&reopen_micros, 95),
            percentile(&reopen_micros, 99),
            database_growth_bytes,
            wal_growth_bytes,
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
