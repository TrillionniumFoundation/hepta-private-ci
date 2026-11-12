use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn altered_append_default_fails_reopen_with_triggers_and_migration_checksums_intact() {
    for (table, column) in [
        (
            "taskflow_effect_dispatch_attempts",
            "append_profile_version",
        ),
        (
            "taskflow_effect_provider_bindings",
            "append_profile_version",
        ),
        (
            "taskflow_effect_dispatch_observations",
            "append_profile_version",
        ),
        (
            "taskflow_effect_dispatch_reconciliations",
            "append_profile_version",
        ),
        (
            "taskflow_effect_dispatch_attempts",
            "provider_context_profile",
        ),
        (
            "taskflow_effect_provider_bindings",
            "provider_context_profile",
        ),
        (
            "taskflow_effect_dispatch_observations",
            "provider_context_profile",
        ),
        (
            "taskflow_effect_dispatch_reconciliations",
            "provider_context_profile",
        ),
    ] {
        let mut original = legacy_effect(LegacyReceipt::LostAcceptedV20).await;
        original.reopen().await;
        let preserved = "SELECT name,sql FROM main.sqlite_schema WHERE type='trigger'
                         UNION ALL SELECT CAST(version AS TEXT),hex(checksum)
                         FROM main._sqlx_migrations ORDER BY 1";
        let before: Vec<(String, String)> = sqlx::query_as(preserved)
            .fetch_all(&original.store.pool)
            .await
            .expect("original guards and migration history");
        let mut connection = original
            .store
            .pool
            .acquire()
            .await
            .expect("catalog fault injection");
        sqlx::query("PRAGMA writable_schema=ON")
            .execute(&mut *connection)
            .await
            .expect("enable catalog injection");
        let changed = sqlx::query(
            "UPDATE main.sqlite_schema SET sql=replace(sql,?,?)
             WHERE type='table' AND name=?",
        )
        .bind(format!("{column} INTEGER NOT NULL DEFAULT 0"))
        .bind(format!("{column} INTEGER NOT NULL DEFAULT 1"))
        .bind(table)
        .execute(&mut *connection)
        .await
        .expect("alter one persisted column default");
        assert_eq!(changed.rows_affected(), 1);
        sqlx::query("PRAGMA writable_schema=OFF")
            .execute(&mut *connection)
            .await
            .expect("end catalog injection");
        let after: Vec<(String, String)> = sqlx::query_as(preserved)
            .fetch_all(&mut *connection)
            .await
            .expect("unchanged guards and checksums");
        assert_eq!(after, before);
        drop(connection);
        original.store.close().await;
        let result =
            AutomationStore::open_root(original.root, original.store.owner_agent_id.clone()).await;
        match result {
            Err(AutomationError::Corrupt) => {}
            Ok(reopened) => {
                reopened.close().await;
                panic!("changed append default was accepted on reopen for {table}");
            }
            Err(error) => panic!("unexpected reopen failure for {table}: {error}"),
        }
    }
}

#[tokio::test]
async fn preopened_v22_writer_cannot_append_barrier_or_bind_accepted_without_context_profile() {
    let mut original = legacy_effect(LegacyReceipt::UnobservedV21).await;
    MIGRATOR
        .run_to(22, &original.store.pool)
        .await
        .expect("v22 schema");
    let old_pool = SqliteConfig::from_sqlite_home(
        AbsolutePathBuf::try_from(original.root.clone()).expect("root"),
    )
    .open_durable_evidence_pool(original.store.path())
    .await
    .expect("old writer pool");
    let mut connection = old_pool.acquire().await.expect("preopened v22 writer");
    sqlx::query("PRAGMA recursive_triggers=OFF")
        .execute(&mut *connection)
        .await
        .expect("replacement must not rely on delete triggers");
    let old_insert = "INSERT INTO taskflow_effect_dispatch_attempts
        (owner_agent_id,run_id,step_id,attempt,intent_digest,payload_digest,provider_effect_key,
         wire_payload,binding_digest,destination_id,authority_epoch,grant_id,grant_nonce_digest,
         record_command_id,started_at_ms,append_profile_version)
        SELECT owner_agent_id,run_id,step_id,2,intent_digest,payload_digest,provider_effect_key,
         wire_payload,binding_digest,destination_id,authority_epoch,'v22-writer',payload_digest,
         'v22-writer',26,1 FROM taskflow_effect_dispatch_attempts WHERE attempt=1";
    let old_observation = "INSERT INTO taskflow_effect_dispatch_observations
        (owner_agent_id,run_id,step_id,attempt,observation,evidence_digest,observed_at_ms,append_profile_version)
        SELECT owner_agent_id,run_id,step_id,attempt,'indeterminate',payload_digest,26,1
        FROM taskflow_effect_dispatch_attempts WHERE attempt=2";
    let old_binding = "INSERT INTO taskflow_effect_provider_bindings
        (owner_agent_id,run_id,step_id,attempt,receipt_json,receipt_digest,observed_at_ms,append_profile_version)
        SELECT owner_agent_id,run_id,step_id,attempt,?,?,27,1
        FROM taskflow_effect_dispatch_attempts WHERE attempt=2";
    let ack = original.ack.clone();
    let json = format!(
        "{{\"schema_version\":1,\"source\":\"status_lookup\",\"ack\":{}}}",
        serde_json::to_string(&ack).expect("actual accepted receipt"),
    );
    let digest = AuthorizedEffectProviderReceipt::from_provider_ack(
        ack,
        ProviderEffectAckSource::StatusLookup,
    )
    .receipt_digest;
    let mut transaction = connection.begin().await.expect("v22 transaction");
    sqlx::query(old_insert)
        .execute(&mut *transaction)
        .await
        .expect("v22 statement really works");
    sqlx::query(old_observation)
        .execute(&mut *transaction)
        .await
        .expect("v22 original Unknown");
    sqlx::query(old_binding)
        .bind(&json)
        .bind(digest.as_str())
        .execute(&mut *transaction)
        .await
        .expect("v22 Accepted-only binding really works");
    transaction.rollback().await.expect("rollback v22 probe");
    original.reopen().await;
    let before = original
        .store
        .pending_authorized_taskflow_effects(8)
        .await
        .expect("historical uncertainty");
    assert_eq!(before.len(), 1);
    assert_eq!(before[0].provider_context_digest, None);
    let error = sqlx::query(old_insert)
        .execute(&mut *connection)
        .await
        .expect_err("preopened writer fenced");
    assert!(error.to_string().contains("provider context writer"));
    // Accepted lookup commits a first binding without a new observation row.
    // Prove that its old INSERT is fenced even for a current-profile attempt.
    let current_insert = "INSERT INTO taskflow_effect_dispatch_attempts
        (owner_agent_id,run_id,step_id,attempt,intent_digest,payload_digest,provider_effect_key,
         wire_payload,binding_digest,destination_id,authority_epoch,grant_id,grant_nonce_digest,
         record_command_id,started_at_ms,append_profile_version,provider_context_profile)
        SELECT owner_agent_id,run_id,step_id,2,intent_digest,payload_digest,provider_effect_key,
         wire_payload,binding_digest,destination_id,authority_epoch,'v22-writer',payload_digest,
         'v22-writer',26,1,1 FROM taskflow_effect_dispatch_attempts WHERE attempt=1";
    let mut transaction = connection.begin().await.expect("current barrier fixture");
    sqlx::query(current_insert)
        .execute(&mut *transaction)
        .await
        .expect("current writer admitted");
    // No observation or binding exists yet: the reused nonce is the only
    // conflicting key, and REPLACE must not erase the MayHaveBeenSent row.
    let reused_nonce = "INSERT OR REPLACE INTO taskflow_effect_dispatch_attempts
        (owner_agent_id,run_id,step_id,attempt,intent_digest,payload_digest,provider_effect_key,
         wire_payload,binding_digest,destination_id,authority_epoch,grant_id,grant_nonce_digest,
         record_command_id,started_at_ms,append_profile_version,provider_context_profile)
        SELECT owner_agent_id,run_id,step_id,3,intent_digest,payload_digest,provider_effect_key,
         wire_payload,binding_digest,destination_id,authority_epoch,'v22-writer',payload_digest,
         'v22-writer',26,1,1 FROM taskflow_effect_dispatch_attempts WHERE attempt=1";
    let error = sqlx::query(reused_nonce)
        .execute(&mut *transaction)
        .await
        .expect_err("nonce replacement refused");
    assert!(error.to_string().contains("provider context writer"));
    let rowid_replace = "INSERT OR REPLACE INTO taskflow_effect_dispatch_attempts
        (rowid,owner_agent_id,run_id,step_id,attempt,intent_digest,payload_digest,provider_effect_key,
         wire_payload,binding_digest,destination_id,authority_epoch,grant_id,grant_nonce_digest,
         record_command_id,started_at_ms,append_profile_version,provider_context_profile)
        SELECT rowid,owner_agent_id,run_id,'rowid-target',3,intent_digest,payload_digest,provider_effect_key,
         wire_payload,binding_digest,destination_id,authority_epoch,'rowid-writer',?,
         'v22-writer',26,1,1 FROM taskflow_effect_dispatch_attempts WHERE attempt=1";
    let error = sqlx::query(rowid_replace)
        .bind(Sha256Digest::for_bytes(b"fresh-rowid-nonce").as_str())
        .execute(&mut *transaction)
        .await
        .expect_err("rowid-only replacement before child rows refused");
    assert!(error.to_string().contains("provider context writer"));
    let current_observation = "INSERT INTO taskflow_effect_dispatch_observations
        (owner_agent_id,run_id,step_id,attempt,observation,evidence_digest,observed_at_ms,
         append_profile_version,provider_context_profile)
        SELECT owner_agent_id,run_id,step_id,attempt,'indeterminate',payload_digest,26,1,1
        FROM taskflow_effect_dispatch_attempts WHERE attempt=2";
    sqlx::query(current_observation)
        .execute(&mut *transaction)
        .await
        .expect("current original Unknown");
    let error = sqlx::query(old_binding)
        .bind(&json)
        .bind(digest.as_str())
        .execute(&mut *transaction)
        .await
        .expect_err("old Accepted-only commit fenced");
    assert!(error.to_string().contains("provider context writer"));
    let current_binding = "INSERT INTO taskflow_effect_provider_bindings
        (owner_agent_id,run_id,step_id,attempt,receipt_json,receipt_digest,observed_at_ms,
         append_profile_version,provider_context_profile)
        SELECT owner_agent_id,run_id,step_id,attempt,?,?,27,1,1
        FROM taskflow_effect_dispatch_attempts WHERE attempt=2";
    sqlx::query(current_binding)
        .bind(&json)
        .bind(digest.as_str())
        .execute(&mut *transaction)
        .await
        .expect("current receipt writer admitted");
    sqlx::query("INSERT INTO taskflow_effect_dispatch_reconciliations
        (owner_agent_id,run_id,step_id,attempt,observation,evidence_digest,observed_at_ms,append_profile_version,provider_context_profile)
        SELECT owner_agent_id,run_id,step_id,attempt,'succeeded',payload_digest,28,1,1
        FROM taskflow_effect_dispatch_attempts WHERE attempt=2")
        .execute(&mut *transaction).await.expect("current reconciliation schema fixture");
    for statement in [
        "INSERT OR REPLACE INTO taskflow_effect_dispatch_attempts
         SELECT * FROM taskflow_effect_dispatch_attempts WHERE attempt=2",
        "INSERT OR REPLACE INTO taskflow_effect_provider_bindings
         SELECT * FROM taskflow_effect_provider_bindings WHERE attempt=2",
        "INSERT OR REPLACE INTO taskflow_effect_dispatch_observations
         SELECT * FROM taskflow_effect_dispatch_observations WHERE attempt=2",
        "INSERT OR REPLACE INTO taskflow_effect_dispatch_reconciliations
         SELECT * FROM taskflow_effect_dispatch_reconciliations WHERE attempt=2",
    ] {
        let error = sqlx::query(statement)
            .execute(&mut *transaction)
            .await
            .expect_err("replacement refused");
        assert!(error.to_string().contains("provider context writer"));
    }
    // The alternate child key has a valid current-profile parent. Without the
    // context gate, rowid replacement would therefore pass the foreign key and
    // v22 append checks; the earlier attempt probe has no child-row conflicts.
    sqlx::query("INSERT INTO taskflow_effect_dispatch_attempts
        (owner_agent_id,run_id,step_id,attempt,intent_digest,payload_digest,provider_effect_key,
         wire_payload,binding_digest,destination_id,authority_epoch,grant_id,grant_nonce_digest,
         record_command_id,started_at_ms,append_profile_version,provider_context_profile)
        SELECT owner_agent_id,run_id,'rowid-child-target',3,intent_digest,payload_digest,provider_effect_key,
         wire_payload,binding_digest,destination_id,authority_epoch,'rowid-child-parent',?,
         'rowid-child-parent',29,1,1 FROM taskflow_effect_dispatch_attempts WHERE attempt=2")
        .bind(Sha256Digest::for_bytes(b"fresh-rowid-child-parent-nonce").as_str())
        .execute(&mut *transaction).await.expect("valid alternate parent for child rowid probes");
    for statement in [
        "INSERT OR REPLACE INTO taskflow_effect_provider_bindings
         (rowid,owner_agent_id,run_id,step_id,attempt,receipt_json,receipt_digest,
          observed_at_ms,append_profile_version,provider_context_profile)
         SELECT rowid,owner_agent_id,run_id,'rowid-child-target',3,receipt_json,receipt_digest,
          observed_at_ms,append_profile_version,provider_context_profile
         FROM taskflow_effect_provider_bindings WHERE attempt=2",
        "INSERT OR REPLACE INTO taskflow_effect_dispatch_observations
         (rowid,owner_agent_id,run_id,step_id,attempt,observation,evidence_digest,
          observed_at_ms,provider_receipt_json,append_profile_version,provider_context_profile)
         SELECT rowid,owner_agent_id,run_id,'rowid-child-target',3,observation,evidence_digest,
          observed_at_ms,provider_receipt_json,append_profile_version,provider_context_profile
         FROM taskflow_effect_dispatch_observations WHERE attempt=2",
        "INSERT OR REPLACE INTO taskflow_effect_dispatch_reconciliations
         (rowid,owner_agent_id,run_id,step_id,attempt,observation,evidence_digest,
          observed_at_ms,provider_receipt_json,append_profile_version,provider_context_profile)
         SELECT rowid,owner_agent_id,run_id,'rowid-child-target',3,observation,evidence_digest,
          observed_at_ms,provider_receipt_json,append_profile_version,provider_context_profile
         FROM taskflow_effect_dispatch_reconciliations WHERE attempt=2",
    ] {
        let error = sqlx::query(statement)
            .execute(&mut *transaction)
            .await
            .expect_err("explicit child rowid collision refused");
        assert!(error.to_string().contains("provider context writer"));
    }
    transaction
        .rollback()
        .await
        .expect("preserve original history");
    assert_eq!(
        original
            .store
            .pending_authorized_taskflow_effects(8)
            .await
            .expect("preserved uncertainty"),
        before
    );
    drop(connection);
    old_pool.close().await;
    original.store.close().await;
}
