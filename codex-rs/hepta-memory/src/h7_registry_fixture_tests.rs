//! Produce the persisted Agentd quarantine fixture through the real writers.
//!
//! Only this memory unit-test build has the task-local clock below. Normal
//! dependencies, including Agentd's tests and all-features product builds, use
//! the production clock. The fixture consumer reopens and verifies the database
//! with that clock; it neither changes expiry nor disables a fence check.
//!
//! Regenerate with HEPTA_H7_REGISTRY_FIXTURE_OUTPUT set to an explicit output path
//! and `just test --locked -p codex-hepta-memory --lib -E
//! 'test(h7_registry_fixture_tests::expired_registry_fixture_matches_real_writers)'`.
//! Export never skips the golden comparison: review a real mismatch before
//! replacing the fixture, then rerun the same test without the output variable.

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use pretty_assertions::assert_eq;

use crate::CognitiveStore;
use crate::CompactFence;
use crate::H7TrajectoryAppend;
use crate::H7TrajectoryEventKind;
use crate::H7TrajectoryRecord;
use crate::LocalAdmission;
use crate::LocalLeaseHeadDisposition;
use crate::LocalLeaseOutboxError;
use crate::LocalTurnLifecycleBinding;
use crate::LogicalTurnAttemptRequest;
use crate::LogicalTurnEvidence;
use crate::LogicalTurnInspectionDisposition;
use crate::LogicalTurnRequest;
use crate::LogicalTurnReservation;
use crate::append_h7_trajectory_event_bound;
use crate::cognitive_test_support::layout;
use crate::h7_trajectory_local_receipt_digest;

tokio::task_local! {
    static FIXTURE_UNIX_SECONDS: u64;
}

pub(crate) fn fixture_unix_seconds() -> Option<u64> {
    FIXTURE_UNIX_SECONDS.try_with(|seconds| *seconds).ok()
}

#[tokio::test]
async fn expired_registry_fixture_matches_real_writers() {
    assert_eq!(fixture_unix_seconds(), None);
    let owner =
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("Agentd fixture owner");
    let fixture = FIXTURE_UNIX_SECONDS.scope(/*value*/ 1, async {
        // A separately scheduled task must retain its own production clock.
        assert_eq!(
            tokio::spawn(async { fixture_unix_seconds() })
                .await
                .expect("independent task"),
            None
        );
        let temp = tempfile::tempdir().expect("temporary store");
        let store = CognitiveStore::open(&layout(&temp, &owner))
            .await
            .expect("open cognitive store");
        let turn_id = "turn:agentd-expired-terminal";
        let logical = LogicalTurnRequest::new(
            format!("qualification:logical:{turn_id}"),
            "qualification:local",
            Sha256Digest::for_bytes(format!("qualification:logical-binding:v1:{turn_id}").as_bytes()),
        )
        .expect("logical request");
        let old = LogicalTurnAttemptRequest::new(
            "seed-terminal-attempt",
            "seed-terminal-lease",
            "seed-terminal-journal",
            "seed-terminal-trajectory",
            "seed-terminal-occurrence",
            /*authority_epoch*/ 1,
            /*owner_epoch*/ 2,
            /*generation*/ 1,
            "seed-terminal-fence",
            /*lease_expires_at_unix_seconds*/ 2,
        )
        .expect("terminal attempt request");
        let LogicalTurnReservation::Acquired { attempt } = store
            .reserve_or_replay_logical_turn(logical.clone(), old)
            .await
            .expect("seed registry attempt")
        else {
            panic!("seed must acquire registry attempt")
        };
        let head = store
            .inspect_local_lease_head(&attempt.lease_id)
            .await
            .expect("inspect seeded head");
        assert_eq!(head.disposition, LocalLeaseHeadDisposition::Active);
        let lease = store
            .reopen_host_bound_lease(
                head.head.clone().expect("seeded head"),
                attempt.authority_epoch,
                attempt.owner_epoch,
                attempt.lease_expires_at_unix_seconds,
            )
            .await
            .expect("reopen seeded lease");
        let fence = CompactFence::new(
            attempt.authority_epoch,
            attempt.owner_epoch,
            attempt.generation,
            attempt.fencing_token.clone(),
        )
        .expect("compact fence");
        let executor = store
            .open_local_compact_executor_bound(attempt.journal_id.clone(), fence, &lease)
            .await
            .expect("open compact executor");
        let binding =
            LocalTurnLifecycleBinding::from_handles(turn_id, &lease, &executor).expect("binding");
        let payload = r#"{"schema_version":1,"external_effect":false,"kg_write_authority":false,"production_caller":false}"#;
        let receipt = match lease
            .admit(
                attempt.occurrence_key.clone(),
                "codex.turn.qualification.start.v1",
                payload,
            )
            .await
            .expect("admit local intent")
        {
            LocalAdmission::Queued(receipt) | LocalAdmission::Replay(receipt) => receipt,
        };
        let trajectory_id = attempt.trajectory_id.clone();
        let start = H7TrajectoryRecord::new(
            trajectory_id.clone(),
            /*event_seq*/ 1,
            format!("{trajectory_id}:event:turn-start"),
            H7TrajectoryEventKind::TurnStart,
            turn_id,
            attempt.occurrence_key.clone(),
            /*causal_parent_seq*/ None,
            /*causal_parent_sha256*/ None,
            Sha256Digest::for_bytes(payload.as_bytes()),
            Sha256Digest::for_bytes(b"qualification:observation-only-policy:v1"),
            Sha256Digest::for_bytes(b"qualification:model-receipt:not-applicable:v1"),
            h7_trajectory_local_receipt_digest(&receipt),
            "turn_started",
            /*reward_bps*/ 0,
            /*safety_ok*/ true,
            r#"{"source":"qualification_turn_writer"}"#,
            "not_applicable",
        )
        .expect("start trajectory");
        let H7TrajectoryAppend::Inserted {
            event_sha256: parent,
            ..
        } = append_h7_trajectory_event_bound(&lease, &executor, &binding, &start)
            .await
            .expect("append H7 start")
        else {
            panic!("start must be inserted")
        };
        let terminal = H7TrajectoryRecord::terminal(
            trajectory_id.clone(),
            /*event_seq*/ 2,
            format!("{trajectory_id}:event:terminal:stop"),
            turn_id,
            format!("{}:terminal", attempt.occurrence_key),
            /*causal_parent_seq*/ 1,
            parent,
            Sha256Digest::for_bytes(b"terminal-state"),
            Sha256Digest::for_bytes(b"qualification:observation-only-policy:v1"),
            Sha256Digest::for_bytes(b"qualification:model-receipt:not-applicable:v1"),
            Sha256Digest::for_bytes(b"terminal-receipt"),
            "turn_stopped",
            "turn_stopped",
            r#"{"source":"qualification_turn_writer","terminal_action":"stop"}"#,
        )
        .expect("terminal trajectory");
        assert!(matches!(
            append_h7_trajectory_event_bound(&lease, &executor, &binding, &terminal)
                .await
                .expect("append H7 terminal"),
            H7TrajectoryAppend::Inserted { .. }
        ));
        assert_eq!(
            store.read_h7_trajectory(&trajectory_id)
                .await
                .expect("verified H7 chain")
                .expect("H7 evidence")
                .events,
            vec![start, terminal]
        );

        // Equality with the deadline still expires the untouched active head.
        // These are the real expiry and stale-fence checks, with no sleeps or
        // terminal transition that would turn ExpiredActive into RolledBack.
        FIXTURE_UNIX_SECONDS.scope(/*value*/ 2, async {
            assert!(matches!(
                lease.admit("after-expiry", "codex.turn.qualification.start.v1", payload)
                    .await,
                Err(LocalLeaseOutboxError::StaleFence(_))
            ));
            let expired = store
                .inspect_local_lease_head(&attempt.lease_id)
                .await
                .expect("expired head");
            assert_eq!(expired.head, head.head);
            assert_eq!(expired.disposition, LocalLeaseHeadDisposition::ExpiredActive);
            let inspection = store.inspect_logical_turn(logical)
                .await
                .expect("expired registry with evidence");
            assert_eq!(inspection.head, Some(attempt));
            assert_eq!(inspection.disposition, LogicalTurnInspectionDisposition::ExpiredWithEvidence);
            assert_eq!(inspection.evidence, LogicalTurnEvidence {
                event_rows: 1,
                outbox_rows: 1,
                compact_rows: 0,
                trajectory_rows: 2,
            });
        }).await;

        // Export the values actually committed by the writers. SQLite quote()
        // preserves text/NULL/integer values; no digest is recreated here and
        // no schema, trigger, owner metadata or path is copied between stores.
        let mut exported = String::from(
            "-- Generated by h7_registry_fixture_tests::expired_registry_fixture_matches_real_writers.\n\
             -- Real writer clock: 1; bound lease expiry: 2. Do not edit persisted rows by hand.\n",
        );
        for (table, order, expected_rows) in [
            ("cognitive_local_leases", "lease_id, lease_sequence", 1),
            ("cognitive_logical_turns", "owner_agent_id, logical_turn_id", 1),
            ("cognitive_logical_turn_attempts", "owner_agent_id, logical_turn_id, registry_sequence", 1),
            ("cognitive_local_events", "lease_id, event_sequence", 1),
            ("cognitive_local_outbox", "lease_id, outbox_sequence", 1),
            ("cognitive_h7_trajectory_events", "owner_agent_id, trajectory_id, event_seq", 2),
        ] {
            let columns = sqlx::query_scalar::<_, String>(
                "SELECT name FROM pragma_table_info(?) ORDER BY cid",
            )
            .bind(table)
            .fetch_all(&store.pool)
            .await
            .expect("fixture table columns")
            .into_iter()
            .map(|name| format!("\"{}\"", name.replace('"', "\"\"")))
            .collect::<Vec<_>>();
            let quoted_values = columns.iter()
                .map(|name| format!("quote({name})"))
                .collect::<Vec<_>>()
                .join(" || ',' || ");
            // Table/order fragments are fixed above; schema column identifiers
            // are double-quoted with embedded quotes escaped before use.
            let rows = sqlx::query_scalar::<_, String>(sqlx::AssertSqlSafe(format!(
                "SELECT {quoted_values} FROM {table} ORDER BY {order}",
            )))
            .fetch_all(&store.pool)
            .await
            .expect("persisted fixture values");
            assert_eq!(rows.len(), expected_rows, "{table}");
            let columns = columns.join(", ");
            for values in rows {
                exported.push_str(&format!(
                    "INSERT INTO {table} ({columns}) VALUES ({values});\n",
                ));
            }
        }
        exported
    }).await;
    assert_eq!(fixture_unix_seconds(), None);

    // Port the actual rows to a different directory, reopen the genuine store
    // and read the complete H7 chain without any clock scope. This also catches
    // accidental path, host or random-identity dependencies in the export.
    let imported_temp = tempfile::tempdir().expect("fresh import directory");
    let imported_layout = layout(&imported_temp, &owner);
    let imported = CognitiveStore::open(&imported_layout)
        .await
        .expect("fresh schema");
    let mut transaction = imported.pool.begin().await.expect("import transaction");
    // Replay only the SQL assembled above from fixed table names, escaped
    // column identifiers and SQLite quote() of the real writers' values.
    sqlx::raw_sql(sqlx::AssertSqlSafe(fixture.as_str()))
        .execute(&mut *transaction)
        .await
        .expect("import writer rows");
    transaction.commit().await.expect("commit imported rows");
    imported.pool.close().await;
    drop(imported);
    let reopened = CognitiveStore::open(&imported_layout)
        .await
        .expect("verify imported journals");
    assert_eq!(
        reopened
            .inspect_local_lease_head("seed-terminal-lease")
            .await
            .expect("imported lease")
            .disposition,
        LocalLeaseHeadDisposition::ExpiredActive
    );
    assert!(
        reopened
            .read_h7_trajectory("seed-terminal-trajectory")
            .await
            .expect("verify imported H7 chain")
            .expect("imported H7 evidence")
            .is_complete_qualification_terminal(
                "turn:agentd-expired-terminal",
                "seed-terminal-occurrence",
                "seed-terminal-occurrence:terminal",
            )
    );
    if let Some(output) = std::env::var_os("HEPTA_H7_REGISTRY_FIXTURE_OUTPUT") {
        std::fs::write(output, &fixture).expect("export actual persisted fixture");
    }
    assert_eq!(
        fixture,
        include_str!("../tests/fixtures/h7-expired-registry.sql")
    );
}
