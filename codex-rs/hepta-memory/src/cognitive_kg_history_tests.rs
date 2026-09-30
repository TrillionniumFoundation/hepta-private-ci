//! Bounded history, concurrent snapshot reads, reopen and deletion qualification.
use super::*;
use crate::ForgetMemoryDraft;

fn history_source(index: usize, content: &str) -> SourceDraft {
    SourceDraft {
        scope: CognitiveScope::AgentPrivate,
        kind: LedgerSourceKind::ExplicitMemoryDirective,
        event_key: format!("kg-history-event-{index}"),
        content: content.as_bytes().to_vec(),
        observed_at_unix_seconds: 100,
    }
}

fn history_revision(content: String) -> MemoryRevisionDraft {
    MemoryRevisionDraft {
        scope: CognitiveScope::AgentPrivate,
        content,
        verification: MemoryVerification::Verified,
        lifecycle: MemoryLifecycleState::Active,
        valid_from_unix_seconds: 100,
        valid_to_unix_seconds: None,
        citations: Vec::new(),
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "qualification: bounded KG history/concurrent-read/reopen/deletion probe"]
async fn qualification_kg_history_reopen_no_resurrection() {
    let corrections = configured_count("HEPTA_KG_HISTORY_CORRECTIONS", 128, 4096);
    let temp = TempDir::new().expect("history directory");
    let owner = agent_id(186);
    let owner_layout = layout(&temp, &owner);
    let access = CognitiveAccess::agent_private(owner);
    let mut store = CognitiveStore::open(&owner_layout)
        .await
        .expect("history store");
    let initial = "Benchmark history initial";
    let mut receipt = store
        .remember_with_kg(
            &access,
            &history_source(0, initial),
            &MemoryDraft {
                stable_key: "kg-history-memory".to_string(),
                revision: history_revision(initial.to_string()),
            },
            &facts(),
        )
        .await
        .expect("initial history write");
    let mut correction_ns = Vec::new();
    let mut concurrent_reader_ns = Vec::new();
    let mut concurrent_round_ns = Vec::new();
    let mut query_ns = Vec::new();
    let mut reopen_ns = Vec::new();
    for index in 1..=corrections {
        let content = format!("Benchmark history revision {index}");
        let source = history_source(index, &content);
        let revision = history_revision(content);
        let graph_facts = facts();
        let previous_revision = receipt.memory.id.revision;
        let query = RetrievalRequest::new("Benchmark Graph", 10_000);
        let started = Instant::now();
        // A reader may see the complete predecessor or successor. Do not
        // presume which SQLite snapshot wins this scheduling race.
        let ((write_elapsed, written), (read_elapsed, observed)) = tokio::join!(
            async {
                let write_started = Instant::now();
                let result = store
                    .correct_with_kg(
                        &access,
                        &receipt.memory.id.memory_id,
                        previous_revision,
                        &source,
                        &revision,
                        &graph_facts,
                    )
                    .await;
                (elapsed_ns(write_started), result)
            },
            async {
                let read_started = Instant::now();
                let batch = store.retrieve_memory_candidates(&access, &query).await;
                (elapsed_ns(read_started), batch)
            },
        );
        correction_ns.push(write_elapsed);
        concurrent_reader_ns.push(read_elapsed);
        concurrent_round_ns.push(elapsed_ns(started));
        let observed = observed.expect("concurrent history retrieval");
        assert_eq!(observed.candidates.len(), 1);
        let observed_id = &observed.candidates[0].memory.id;
        assert_eq!(observed_id.memory_id, receipt.memory.id.memory_id);
        assert!(
            observed_id.revision == previous_revision
                || observed_id.revision == previous_revision + 1,
            "reader must observe one complete source cut"
        );
        assert_eq!(
            observed.candidates[0]
                .revalidation
                .kg_projection_generation
                .as_ref()
                .map(|generation| generation.get()),
            Some(observed_id.revision),
            "memory and KG bindings must belong to the same snapshot"
        );
        receipt = written.expect("history correction");
        if index.is_power_of_two() || index == corrections {
            store.pool.close().await;
            let started = Instant::now();
            store = CognitiveStore::open(&owner_layout)
                .await
                .expect("history reopen");
            reopen_ns.push(elapsed_ns(started));
            let started = Instant::now();
            let batch = store
                .retrieve_memory_candidates(&access, &query)
                .await
                .expect("history retrieval after writer completion/reopen");
            query_ns.push(elapsed_ns(started));
            assert_eq!(batch.candidates.len(), 1);
            assert_eq!(batch.candidates[0].memory.id, receipt.memory.id);
            let generation: i64 = sqlx::query_scalar(
                "SELECT generation FROM kg_projection WHERE projection_scope = 'agent_private'",
            )
            .fetch_one(&store.pool)
            .await
            .expect("current generation");
            assert_eq!(
                generation,
                i64::try_from(index + 1).expect("bounded history")
            );
            eprintln!("KG_HISTORY_CHECKPOINT corrections={index} generation={generation}");
        }
    }
    let rows: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM kg_projection_generation_semantics")
        .fetch_one(&store.pool)
        .await
        .expect("historical semantics");
    assert_eq!(
        rows,
        i64::try_from(corrections + 1).expect("bounded history")
    );
    let reason = "withdraw bounded history fixture";
    receipt = store
        .forget_with_kg(
            &access,
            &receipt.memory.id.memory_id,
            receipt.memory.id.revision,
            &history_source(corrections + 1, reason),
            &ForgetMemoryDraft {
                scope: CognitiveScope::AgentPrivate,
                reason: reason.to_string(),
                citations: Vec::new(),
                valid_from_unix_seconds: 100,
            },
        )
        .await
        .expect("history tombstone");
    for _ in 0..3 {
        store.pool.close().await;
        store = CognitiveStore::open(&owner_layout)
            .await
            .expect("post-deletion reopen");
        let batch = store
            .retrieve_memory_candidates(&access, &RetrievalRequest::new("Benchmark Graph", 10_000))
            .await
            .expect("post-deletion query");
        assert!(
            batch.candidates.is_empty(),
            "historical facts must not resurrect"
        );
    }
    let attempt = "must not resurrect";
    assert!(
        store
            .correct_with_kg(
                &access,
                &receipt.memory.id.memory_id,
                receipt.memory.id.revision,
                &history_source(corrections + 2, attempt),
                &history_revision(attempt.to_string()),
                &facts(),
            )
            .await
            .is_err()
    );
    let final_generation: i64 = sqlx::query_scalar(
        "SELECT generation FROM kg_projection WHERE projection_scope = 'agent_private'",
    )
    .fetch_one(&store.pool)
    .await
    .expect("final generation");
    assert_eq!(
        final_generation,
        i64::try_from(corrections + 2).expect("bounded history")
    );
    let relation_rows: (i64, i64) = sqlx::query_as(
        "SELECT node_count, edge_count FROM kg_projection_generation_receipts
         WHERE generation = ? AND projection_scope = 'agent_private'",
    )
    .bind(final_generation)
    .fetch_one(&store.pool)
    .await
    .expect("final projection");
    assert_eq!(relation_rows, (0, 0));
    println!(
        "HEPTA_KNOWLEDGE_GRAPH_HISTORY_RECEIPT={}",
        json!({
            "schema": "hepta.knowledge-graph-history.v1",
            "corrections": corrections,
            "finalGeneration": final_generation,
            "reopenSamples": reopen_ns.len(),
            "concurrentReads": concurrent_reader_ns.len(),
            "correctionNs": {
                "p50": percentile_ns(&correction_ns, 50),
                "p95": percentile_ns(&correction_ns, 95),
                "p99": percentile_ns(&correction_ns, 99)
            },
            "concurrentReaderNs": {
                "p50": percentile_ns(&concurrent_reader_ns, 50),
                "p95": percentile_ns(&concurrent_reader_ns, 95),
                "p99": percentile_ns(&concurrent_reader_ns, 99)
            },
            "concurrentRoundNs": {
                "p50": percentile_ns(&concurrent_round_ns, 50),
                "p95": percentile_ns(&concurrent_round_ns, 95),
                "p99": percentile_ns(&concurrent_round_ns, 99)
            },
            "queryNs": {
                "p50": percentile_ns(&query_ns, 50),
                "p95": percentile_ns(&query_ns, 95),
                "p99": percentile_ns(&query_ns, 99)
            },
            "reopenNs": {
                "p50": percentile_ns(&reopen_ns, 50),
                "p95": percentile_ns(&reopen_ns, 95),
                "p99": percentile_ns(&reopen_ns, 99)
            },
            "peakRssKiB": linux_peak_rss_kib(),
            "postDeletionReopens": 3,
            "deletedFactsResurrected": false,
            "activationGranted": false,
            "correctionTimingScope": "product_correction_future_with_concurrent_reader"
        })
    );
    store.pool.close().await;
}
