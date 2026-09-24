use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::DispatchEffect;
use crate::DurableOperationError;
use crate::DurableOperationIntentV1 as OperationIntentV1;
use crate::DurableOperationState;
use crate::DurableOperationStore;
use crate::DurableOutboxState;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("generation")
}

fn intent(index: usize) -> OperationIntentV1 {
    let operation_id = format!("operation:disk-full:{index:05}");
    OperationIntentV1 {
        scope_id: id("scope:disk-full"),
        operation_id: id(&operation_id),
        expected_predecessor: None,
        destination: id("automation.taskflow"),
        payload_digest: Digest32::of_bytes(operation_id.as_bytes()),
        owner_generation: generation(1),
    }
}

#[tokio::test]
async fn sqlite_full_never_leaves_half_of_the_ledger_outbox_transaction() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let store = DurableOperationStore::open(&path).await.expect("open");

    sqlx::query("VACUUM")
        .execute(&store.pool)
        .await
        .expect("vacuum");
    let pages: i64 = sqlx::query_scalar("PRAGMA page_count")
        .fetch_one(&store.pool)
        .await
        .expect("page count");
    assert!(pages > 0);
    // The cap belongs to a connection. Force the repository SQLite shim's
    // complete five-connection pool open, arm every connection, then release
    // them for the owner test. This preserves the production connection policy
    // instead of rebuilding a policy-bypassing raw pool.
    let mut held = Vec::new();
    for _ in 0..5 {
        let mut connection = store.pool.acquire().await.expect("fault connection");
        sqlx::query(sqlx::AssertSqlSafe(format!(
            "PRAGMA max_page_count = {pages}"
        )))
        .execute(&mut *connection)
        .await
        .expect("arm disk-full fault");
        let capped: i64 = sqlx::query_scalar("PRAGMA max_page_count")
            .fetch_one(&mut *connection)
            .await
            .expect("read back page cap");
        assert_eq!(
            capped, pages,
            "every writer must have the disk-full fault armed"
        );
        held.push(connection);
    }
    drop(held);

    let mut saw_full = false;
    for index in 0..20_000 {
        let before: (i64, i64) = sqlx::query_as(
            "SELECT (SELECT COUNT(*) FROM operation_ledger),
                    (SELECT COUNT(*) FROM cross_owner_outbox)",
        )
        .fetch_one(&store.pool)
        .await
        .expect("before counts");
        match store.prepare_intent(&intent(index)).await {
            Ok(_) => {
                let after: (i64, i64) = sqlx::query_as(
                    "SELECT (SELECT COUNT(*) FROM operation_ledger),
                            (SELECT COUNT(*) FROM cross_owner_outbox)",
                )
                .fetch_one(&store.pool)
                .await
                .expect("after counts");
                assert_eq!(after.0, before.0 + 1);
                assert_eq!(after.1, before.1 + 1);
            }
            Err(DurableOperationError::Unavailable(message))
                if message.to_ascii_lowercase().contains("full") =>
            {
                let after: (i64, i64) = sqlx::query_as(
                    "SELECT (SELECT COUNT(*) FROM operation_ledger),
                            (SELECT COUNT(*) FROM cross_owner_outbox)",
                )
                .fetch_one(&store.pool)
                .await
                .expect("failure counts");
                assert_eq!(after, before, "SQLITE_FULL exposed a partial transaction");
                saw_full = true;
                break;
            }
            Err(error) => panic!("unexpected fault result: {error}"),
        }
    }
    assert!(saw_full, "fault fixture never reached SQLITE_FULL");
}

#[cfg(unix)]
const CRASH_SCENARIO_ENV: &str = "HEPTA_KERNEL_OPERATIONS_CRASH_SCENARIO";
#[cfg(unix)]
const CRASH_PATH_ENV: &str = "HEPTA_KERNEL_OPERATIONS_CRASH_PATH";
#[cfg(unix)]
const CRASH_EFFECT_MARKER_ENV: &str = "HEPTA_KERNEL_OPERATIONS_EFFECT_MARKER";

#[cfg(unix)]
fn crash_intent() -> OperationIntentV1 {
    OperationIntentV1 {
        scope_id: id("scope:child-process-crash"),
        operation_id: id("operation:child-process-crash"),
        expected_predecessor: None,
        destination: id("automation.taskflow"),
        payload_digest: Digest32::of_bytes(b"child-process-crash-payload"),
        owner_generation: generation(1),
    }
}

#[cfg(unix)]
fn crash_authority(
    operation: &OperationIntentV1,
    root: &std::path::Path,
    nonce: u8,
) -> (
    codex_hepta_contracts::FinalUseAuthority,
    codex_hepta_contracts::SignedFinalUseGrant,
) {
    use std::collections::BTreeSet;
    use std::os::unix::fs::PermissionsExt;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    use codex_hepta_contracts::FinalUseGrant;
    use codex_hepta_contracts::FinalUseRevocations;
    use ed25519_dalek::Signer as _;
    use ed25519_dalek::SigningKey;

    let signing = SigningKey::from_bytes(&[61; 32]);
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_millis() as u64;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "crash-fault-security-owner".to_owned(),
        authority_epoch: 19,
        grant_id: format!("crash-fault-grant-{nonce}"),
        nonce: [nonce; 32],
        binding: operation.final_use_binding(),
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now.saturating_add(30_000),
    };
    let signature = signing
        .sign(&grant.signing_bytes().expect("signing bytes"))
        .to_bytes()
        .to_vec();
    let authority_dir = root.join("final-use");
    std::fs::create_dir_all(&authority_dir).expect("authority directory");
    std::fs::set_permissions(&authority_dir, std::fs::Permissions::from_mode(0o700))
        .expect("authority permissions");
    let authority = codex_hepta_contracts::FinalUseAuthority::open_state_dir(
        &authority_dir,
        "crash-fault-security-owner".to_owned(),
        signing.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 19,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("authority");
    (
        authority,
        codex_hepta_contracts::SignedFinalUseGrant { grant, signature },
    )
}

#[cfg(unix)]
#[tokio::test]
async fn child_process_crash_boundary_helper() {
    let Ok(scenario) = std::env::var(CRASH_SCENARIO_ENV) else {
        return;
    };
    let path =
        std::path::PathBuf::from(std::env::var_os(CRASH_PATH_ENV).expect("crash database path"));
    let effect_marker = std::path::PathBuf::from(
        std::env::var_os(CRASH_EFFECT_MARKER_ENV).expect("effect marker path"),
    );
    let store = DurableOperationStore::open(&path)
        .await
        .expect("child open");
    let operation = crash_intent();
    store
        .prepare_intent(&operation)
        .await
        .expect("child prepare");
    if scenario == "after-prepare" {
        std::process::exit(81);
    }

    let claim = store
        .claim_next(
            &operation.destination,
            &id("worker:child-crash"),
            generation(1),
            std::time::Duration::from_secs(30),
        )
        .await
        .expect("child claim")
        .expect("child claim row");
    let nonce = if scenario == "during-effect" { 21 } else { 22 };
    let (authority, signed) = crash_authority(
        &claim.intent,
        path.parent().expect("crash database parent"),
        nonce,
    );
    let authorized = store
        .authorize_dispatch(&authority, &signed, &claim)
        .await
        .expect("child authorize");

    if scenario == "during-effect" {
        let _never = store
            .execute_authorized::<()>(authorized, |_| {
                std::fs::write(&effect_marker, b"effect-entered").expect("physical effect marker");
                std::process::exit(82);
            })
            .await;
        unreachable!("child exits from inside the final-use effect boundary");
    }

    assert_eq!(scenario, "after-ack");
    store
        .execute_authorized(authorized, |_| DispatchEffect::Dispatched {
            value: (),
            dispatch_digest: Digest32::of_bytes(b"crash-transport-dispatched"),
            acknowledgement_digest: Some(Digest32::of_bytes(b"crash-transport-ack")),
        })
        .await
        .expect("child acknowledged dispatch");
    std::process::exit(83);
}

#[cfg(unix)]
#[tokio::test]
async fn child_process_kill_matrix_preserves_durable_effect_semantics() {
    use std::process::Command;
    use std::time::Duration;

    let executable = std::env::current_exe().expect("current test executable");
    for (scenario, expected_code) in [
        ("after-prepare", 81),
        ("during-effect", 82),
        ("after-ack", 83),
    ] {
        let directory = tempfile::tempdir().expect("tempdir");
        let path = directory.path().join("operations.sqlite3");
        let marker = directory.path().join("external-effect.marker");
        let status = Command::new(&executable)
            .arg("--exact")
            .arg("fault_tests::child_process_crash_boundary_helper")
            .arg("--nocapture")
            .env(CRASH_SCENARIO_ENV, scenario)
            .env(CRASH_PATH_ENV, &path)
            .env(CRASH_EFFECT_MARKER_ENV, &marker)
            .status()
            .expect("spawn crash child");
        assert_eq!(
            status.code(),
            Some(expected_code),
            "unexpected child exit at {scenario}"
        );

        let store = DurableOperationStore::open(&path)
            .await
            .expect("parent reopen");
        let operation = crash_intent();
        let record = store
            .operation(&operation.scope_id, &operation.operation_id)
            .await
            .expect("lookup")
            .expect("durable row");
        let outbox = store
            .outbox_status(
                &operation.destination,
                &operation.scope_id,
                &operation.operation_id,
            )
            .await
            .expect("outbox")
            .expect("durable outbox row");

        match scenario {
            "after-prepare" => {
                assert_eq!(record.state, DurableOperationState::Prepared);
                assert_eq!(outbox.state, DurableOutboxState::Queued);
                assert!(!marker.exists());
            }
            "during-effect" => {
                assert!(
                    marker.exists(),
                    "the physical effect marker proves callback entry before process death"
                );
                assert_eq!(record.state, DurableOperationState::Dispatching);
                assert_eq!(outbox.state, DurableOutboxState::Leased);
                let adopted = store
                    .adopt_unsettled_generation(
                        &operation.scope_id,
                        &operation.operation_id,
                        generation(2),
                    )
                    .await
                    .expect("adopt unknown effect");
                assert_eq!(adopted.state, DurableOperationState::Indeterminate);
                assert!(
                    store
                        .claim_next(
                            &operation.destination,
                            &id("worker:successor"),
                            generation(2),
                            Duration::from_secs(1),
                        )
                        .await
                        .expect("successor claim query")
                        .is_none(),
                    "an effect that may have crossed the boundary must never blind-retry"
                );
            }
            "after-ack" => {
                assert_eq!(record.state, DurableOperationState::Dispatched);
                assert_eq!(outbox.state, DurableOutboxState::Acknowledged);
                let adopted = store
                    .adopt_unsettled_generation(
                        &operation.scope_id,
                        &operation.operation_id,
                        generation(2),
                    )
                    .await
                    .expect("adopt acknowledged unresolved effect");
                assert_eq!(adopted.state, DurableOperationState::Indeterminate);
                assert!(
                    store
                        .claim_next(
                            &operation.destination,
                            &id("worker:successor"),
                            generation(2),
                            Duration::from_secs(1),
                        )
                        .await
                        .expect("successor claim query")
                        .is_none(),
                    "transport acknowledgement is not permission to replay the effect"
                );
            }
            _ => unreachable!("bounded crash scenario"),
        }
        store.close().await;
    }
}
