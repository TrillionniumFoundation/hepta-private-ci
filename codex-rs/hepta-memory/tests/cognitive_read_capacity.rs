use std::error::Error;
use std::fs;
use std::time::Instant;

use codex_hepta_cognitive_read::MAX_ENCODED_READ_RESULT_BYTES_V2;
use codex_hepta_cognitive_read::PreparedReadSnapshotV1;
use codex_hepta_cognitive_read::ReadFieldV1;
use codex_hepta_cognitive_read::ReadIdsRequestV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryDraft;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryRevisionDraft;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::SourceDraft;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::StableId;
use serde_json::json;

const RECORDS: usize = 512;
const REQUESTED_IDS: usize = 512;
const ITERATIONS: usize = 32;
const OBSERVED_AT: i64 = 200;

fn micros(started: Instant) -> u64 {
    u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX)
}

fn distribution(mut values: Vec<u64>) -> serde_json::Value {
    values.sort_unstable();
    let pick = |percent: usize| {
        let index = ((values.len() - 1) * percent).div_ceil(100);
        values[index.min(values.len() - 1)]
    };
    json!({
        "p50_us": pick(50),
        "p95_us": pick(95),
        "p99_us": pick(99),
    })
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cognitive_read_sqlite_capacity_report() -> Result<(), Box<dyn Error + Send + Sync>> {
    let Ok(output_path) = std::env::var("COGNITIVE_READ_SQLITE_CAPACITY_OUTPUT") else {
        return Ok(());
    };

    let temp = tempfile::tempdir()?;
    let fleet_path = temp.path().join("fleet");
    fs::create_dir_all(&fleet_path)?;
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000512")?;
    let layout = HeptaFleetRoot::parse(fleet_path)?.layout().agent(&owner);
    let store = CognitiveStore::open(&layout).await?;
    let access = CognitiveAccess::agent_private(owner);
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(
            &access,
            &SourceDraft {
                scope: scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "cognitive-read-capacity-source".to_string(),
                content: b"capacity evidence".to_vec(),
                observed_at_unix_seconds: 100,
            },
        )
        .await?;

    let mut record_ids = Vec::with_capacity(RECORDS);
    for index in 0..RECORDS {
        let record = store
            .remember_memory(
                &access,
                &MemoryDraft {
                    stable_key: format!("capacity-{index:04}"),
                    revision: MemoryRevisionDraft {
                        scope: scope.clone(),
                        content: format!("bounded cognitive capacity record {index:04}"),
                        verification: MemoryVerification::Verified,
                        lifecycle: MemoryLifecycleState::Active,
                        valid_from_unix_seconds: 100,
                        valid_to_unix_seconds: None,
                        citations: vec![citation.clone()],
                    },
                },
            )
            .await?;
        record_ids.push(StableId::new(record.id.memory_id.as_str())?);
    }
    record_ids.sort();

    let mut acquire_snapshot_us = Vec::with_capacity(ITERATIONS);
    let mut prepare_index_us = Vec::with_capacity(ITERATIONS);
    let mut read_ids_us = Vec::with_capacity(ITERATIONS);
    let mut revalidate_us = Vec::with_capacity(ITERATIONS);
    let mut final_cut_digest = None;

    for _ in 0..ITERATIONS {
        let started = Instant::now();
        let cut = store.lane_c_snapshot(&access, &scope, OBSERVED_AT).await?;
        acquire_snapshot_us.push(micros(started));

        let started = Instant::now();
        let prepared = PreparedReadSnapshotV1::new(cut.snapshot())?;
        prepare_index_us.push(micros(started));

        let started = Instant::now();
        let result = prepared.read_ids(ReadIdsRequestV1 {
            snapshot_digest: cut.snapshot().snapshot_digest,
            record_ids: record_ids.clone(),
            fields: vec![ReadFieldV1::ContentDigest],
            maximum_encoded_bytes: MAX_ENCODED_READ_RESULT_BYTES_V2,
        })?;
        read_ids_us.push(micros(started));
        assert_eq!(result.records().len(), REQUESTED_IDS);
        assert!(result.missing_ids().is_empty());
        assert_eq!(result.authority(), AuthorityPosture::DENY_ALL);

        let started = Instant::now();
        let current = store
            .revalidate_lane_c_snapshot(&access, &scope, &cut, OBSERVED_AT)
            .await?;
        revalidate_us.push(micros(started));
        assert_eq!(current.cut_digest(), cut.cut_digest());
        final_cut_digest = Some(cut.cut_digest().to_string());
    }

    let sqlite_path = layout.cognitive_root().join("cognitive_1.sqlite3");
    let sqlite_file_bytes = fs::metadata(&sqlite_path)?.len();
    let measurement_config = codex_state::SqliteConfig::from_sqlite_home(
        codex_utils_absolute_path::AbsolutePathBuf::from_absolute_path(layout.cognitive_root())?,
    );
    let measurement_pool = measurement_config.open_read_only_pool(&sqlite_path).await?;
    let sqlite_page_count: i64 = sqlx::query_scalar("PRAGMA page_count")
        .fetch_one(&measurement_pool)
        .await?;
    let sqlite_page_size_bytes: i64 = sqlx::query_scalar("PRAGMA page_size")
        .fetch_one(&measurement_pool)
        .await?;
    let sqlite_memory_revision_rows: i64 =
        sqlx::query_scalar("SELECT count(*) FROM memory_revisions")
            .fetch_one(&measurement_pool)
            .await?;
    let sqlite_source_rows: i64 = sqlx::query_scalar("SELECT count(*) FROM source_ledger")
        .fetch_one(&measurement_pool)
        .await?;
    let sqlite_citation_rows: i64 = sqlx::query_scalar("SELECT count(*) FROM memory_citations")
        .fetch_one(&measurement_pool)
        .await?;
    measurement_pool.close().await;
    let report = json!({
        "schema": "hepta.cognitive.read.sqlite-capacity.v1",
        "records": RECORDS,
        "requested_ids": REQUESTED_IDS,
        "iterations": ITERATIONS,
        "sqlite_file_bytes": sqlite_file_bytes,
        "sqlite_page_count": sqlite_page_count,
        "sqlite_page_size_bytes": sqlite_page_size_bytes,
        "sqlite_memory_revision_rows": sqlite_memory_revision_rows,
        "sqlite_source_rows": sqlite_source_rows,
        "sqlite_citation_rows": sqlite_citation_rows,
        "seeded_source_rows": 1,
        "seeded_memory_revision_rows": RECORDS,
        "authority": "deny_all",
        "cut_digest": final_cut_digest.expect("measured cut"),
        "acquire_snapshot": distribution(acquire_snapshot_us),
        "prepare_index": distribution(prepare_index_us),
        "read_ids": distribution(read_ids_us),
        "revalidate": distribution(revalidate_us),
    });
    fs::write(output_path, serde_json::to_vec_pretty(&report)?)?;
    Ok(())
}
