use super::*;
use crate::AuthorizedEffectOutcome;
use crate::AuthorizedEffectProviderReceipt;
use crate::AuthorizedEffectRecovery;
use crate::AuthorizedEffectRecoveryResult;
use crate::TaskFlowCommand;
use crate::TaskFlowDefinition;
use crate::TaskFlowEdgeSpec;
use crate::TaskFlowFence;
use crate::TaskFlowNodeKind;
use crate::TaskFlowNodeSpec;
use crate::TaskFlowReconcileOutcome;
use crate::TaskFlowTransition;
use codex_hepta_contracts::ProviderEffectAck;
use codex_hepta_contracts::ProviderEffectAckSource;
use codex_hepta_contracts::ProviderEffectAckStatus;
use codex_hepta_contracts::ProviderEffectKey;
use pretty_assertions::assert_eq;
use sqlx::Connection;
use sqlx::Executor;

enum LegacyReceipt {
    LostAcceptedV20,
    CompletedV20,
    UnobservedV21,
    AcceptedV21,
}

struct LegacyEffect {
    _directory: tempfile::TempDir,
    root: PathBuf,
    store: AutomationStore,
    fence: TaskFlowFence,
    ack: ProviderEffectAck,
    evidence: Sha256Digest,
}

impl LegacyEffect {
    async fn reopen(&mut self) {
        self.store.close().await;
        self.store =
            AutomationStore::open_root(self.root.clone(), self.store.owner_agent_id.clone())
                .await
                .expect("migrate and verify original owner");
    }

    async fn recover(
        &self,
        recovery: AuthorizedEffectRecovery,
    ) -> Result<AuthorizedEffectRecoveryResult, crate::AuthorizedEffectError> {
        self.store
            .recover_authorized_taskflow_effect("legacy-run", "work", 1, &self.fence, recovery, 30)
            .await
    }
}

async fn legacy_effect(profile: LegacyReceipt) -> LegacyEffect {
    let directory = tempfile::tempdir().expect("legacy owner");
    let root = directory.path().canonicalize().expect("canonical owner");
    let path = root.join(AUTOMATION_DB_FILENAME);
    let pool =
        SqliteConfig::from_sqlite_home(AbsolutePathBuf::try_from(root.clone()).expect("root"))
            .open_durable_evidence_pool(&path)
            .await
            .expect("legacy database");
    let version = match profile {
        LegacyReceipt::LostAcceptedV20 | LegacyReceipt::CompletedV20 => 20,
        LegacyReceipt::UnobservedV21 | LegacyReceipt::AcceptedV21 => 21,
    };
    MIGRATOR
        .run_to(version, &pool)
        .await
        .expect("original migration prefix");
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("owner");
    sqlx::query("INSERT INTO automation_meta VALUES (1, ?, ?)")
        .bind(version)
        .bind(owner.as_str())
        .execute(&pool)
        .await
        .expect("legacy owner metadata");
    let timer_epoch = sqlx::query_scalar("SELECT writer_epoch FROM automation_timer_lifecycle")
        .fetch_one(&pool)
        .await
        .expect("legacy timer epoch");
    let store = AutomationStore {
        pool,
        owner_agent_id: owner.clone(),
        path,
        timer_epoch,
    };
    let fence =
        TaskFlowFence::new(owner.clone(), "legacy-owner", 1, 1, "legacy-fence").expect("fence");
    let digest = Sha256Digest::for_bytes(b"legacy-intent");
    let wire = b"legacy-wire";
    let payload = Sha256Digest::for_bytes(wire);
    let definition = TaskFlowDefinition::new(
        "legacy",
        1,
        "work",
        vec![
            TaskFlowNodeSpec::new("work", TaskFlowNodeKind::Activity),
            TaskFlowNodeSpec::new("done", TaskFlowNodeKind::TerminalSuccess),
            TaskFlowNodeSpec::new("failed", TaskFlowNodeKind::TerminalFailure),
        ],
        vec![
            TaskFlowEdgeSpec::new("work", "done"),
            TaskFlowEdgeSpec::new("work", "failed"),
        ],
        Vec::new(),
        digest.clone(),
    )
    .expect("definition");
    store
        .register_taskflow_definition(&definition, &fence, 10)
        .await
        .expect("definition");
    store
        .create_taskflow_run(
            "legacy-run",
            "legacy",
            1,
            definition.definition_digest(),
            "thread",
            10,
        )
        .await
        .expect("run");
    let claimed = store
        .claim_taskflow_run("legacy-run", &fence, 20, 1_000)
        .await
        .expect("claim");
    store
        .apply_taskflow_command(
            &TaskFlowCommand::new(
                "legacy-run",
                "start",
                fence.clone(),
                claimed.revision,
                TaskFlowTransition::Start,
                21,
            )
            .expect("start command"),
        )
        .await
        .expect("start");
    store
        .prepare_taskflow_step(
            "legacy-run",
            "work",
            1,
            &fence,
            &digest,
            &payload,
            "prepare",
            22,
        )
        .await
        .expect("prepare");
    store
        .claim_taskflow_step(
            "legacy-run",
            "work",
            1,
            &fence,
            &digest,
            &payload,
            "claim",
            23,
        )
        .await
        .expect("step claim");
    let key =
        ProviderEffectKey::for_operation("provider:legacy", "legacy-run", "work").expect("key");
    let status = match profile {
        LegacyReceipt::CompletedV20 => ProviderEffectAckStatus::Completed,
        LegacyReceipt::LostAcceptedV20
        | LegacyReceipt::UnobservedV21
        | LegacyReceipt::AcceptedV21 => ProviderEffectAckStatus::Accepted,
    };
    let ack = ProviderEffectAck::new(
        key.clone(),
        payload.clone(),
        Sha256Digest::for_bytes(b"original-A"),
        status,
    );
    sqlx::query(
        "INSERT INTO taskflow_effect_dispatch_attempts (
            owner_agent_id,run_id,step_id,attempt,intent_digest,payload_digest,
            provider_effect_key,wire_payload,binding_digest,destination_id,authority_epoch,
            grant_id,grant_nonce_digest,record_command_id,started_at_ms
         ) VALUES (?,'legacy-run','work',1,?,?,?,?,?,'provider:legacy',1,'grant',?,'record',24)",
    )
    .bind(owner.as_str())
    .bind(digest.as_str())
    .bind(payload.as_str())
    .bind(key.as_str())
    .bind(wire.as_slice())
    .bind(digest.as_str())
    .bind(digest.as_str())
    .execute(&store.pool)
    .await
    .expect("original legacy attempt");
    let evidence = match profile {
        LegacyReceipt::LostAcceptedV20 | LegacyReceipt::CompletedV20 => {
            // The original v20 receipt encoding retained only this digest,
            // losing Accepted(A) before the TaskFlow projection was written.
            let mut bytes = b"hepta.automation.provider-effect.ack.v1\0".to_vec();
            for field in [ack.key.as_str(), ack.payload_sha256.as_str()] {
                bytes.extend_from_slice(field.as_bytes());
                bytes.push(0);
            }
            bytes.extend_from_slice(ack.provider_operation_id_sha256.as_str().as_bytes());
            bytes.push(match status {
                ProviderEffectAckStatus::Accepted => 1,
                ProviderEffectAckStatus::Completed => 2,
                ProviderEffectAckStatus::Rejected => 3,
            });
            let kind = match profile {
                LegacyReceipt::CompletedV20 => "succeeded",
                LegacyReceipt::LostAcceptedV20
                | LegacyReceipt::UnobservedV21
                | LegacyReceipt::AcceptedV21 => "indeterminate",
            };
            let evidence = Sha256Digest::for_bytes(&bytes);
            sqlx::query("INSERT INTO taskflow_effect_dispatch_observations VALUES (?,'legacy-run','work',1,?,?,25)")
                .bind(owner.as_str()).bind(kind).bind(evidence.as_str()).execute(&store.pool).await.expect("v20 digest-only ACK");
            evidence
        }
        LegacyReceipt::AcceptedV21 => {
            let evidence = AuthorizedEffectProviderReceipt::from_provider_ack(
                ack.clone(),
                ProviderEffectAckSource::DispatchResponse,
            )
            .receipt_digest;
            let json = format!(
                "{{\"schema_version\":1,\"source\":\"dispatch_response\",\"ack\":{}}}",
                serde_json::to_string(&ack).expect("canonical ACK"),
            );
            sqlx::query("INSERT INTO taskflow_effect_provider_bindings VALUES (?,'legacy-run','work',1,?,?,25)")
                .bind(owner.as_str()).bind(&json).bind(evidence.as_str()).execute(&store.pool).await.expect("v21 complete binding");
            sqlx::query("INSERT INTO taskflow_effect_dispatch_observations VALUES (?,'legacy-run','work',1,'indeterminate',?,25,?)")
                .bind(owner.as_str()).bind(evidence.as_str()).bind(json).execute(&store.pool).await.expect("v21 full original ACK");
            evidence
        }
        LegacyReceipt::UnobservedV21 => Sha256Digest::for_bytes(b"no-observation"),
    };
    if matches!(profile, LegacyReceipt::AcceptedV21) {
        store
            .record_taskflow_step(
                "legacy-run",
                "work",
                1,
                &fence,
                &digest,
                &payload,
                "record",
                &evidence,
                crate::TaskFlowStepObservation::Indeterminate,
                25,
            )
            .await
            .expect("original v21 Unknown projection");
    }
    LegacyEffect {
        _directory: directory,
        root,
        store,
        fence,
        ack,
        evidence,
    }
}

#[tokio::test]
async fn v20_lost_accepted_cannot_acquire_a_replacement_operation_after_migration() {
    let mut original = legacy_effect(LegacyReceipt::LostAcceptedV20).await;
    original.reopen().await;
    let before = original
        .store
        .pending_authorized_taskflow_effects(8)
        .await
        .expect("legacy pending");
    assert_eq!(before.len(), 1);
    assert_eq!(before[0].provider_ack, None);
    assert_eq!(
        before[0].wire_payload.as_deref(),
        Some(b"legacy-wire".as_slice())
    );
    let mut substituted = original.ack.clone();
    substituted.provider_operation_id_sha256 = Sha256Digest::for_bytes(b"replacement-B");
    substituted.status = ProviderEffectAckStatus::Completed;
    for recovery in [
        AuthorizedEffectRecovery::Observed(AuthorizedEffectProviderReceipt::from_provider_ack(
            substituted,
            ProviderEffectAckSource::StatusLookup,
        )),
        AuthorizedEffectRecovery::Observed(AuthorizedEffectProviderReceipt {
            outcome: AuthorizedEffectOutcome::Succeeded,
            receipt_digest: Sha256Digest::for_bytes(b"opaque-completion"),
            provider_ack: None,
        }),
        AuthorizedEffectRecovery::ProvenAbsent {
            proof_digest: Sha256Digest::for_bytes(b"later-absence"),
        },
    ] {
        assert!(
            original.recover(recovery).await.is_err(),
            "later evidence cannot reconstruct lost Accepted(A)"
        );
    }
    original.reopen().await;
    assert_eq!(
        original
            .store
            .pending_authorized_taskflow_effects(8)
            .await
            .expect("retained Unknown"),
        before
    );
    let retained: String =
        sqlx::query_scalar("SELECT evidence_digest FROM taskflow_effect_dispatch_observations")
            .fetch_one(&original.store.pool)
            .await
            .expect("original digest");
    assert_eq!(retained, original.evidence.as_str());
    let attachments: i64 =
        sqlx::query_scalar("SELECT count(*) FROM taskflow_effect_provider_bindings")
            .fetch_one(&original.store.pool)
            .await
            .expect("no fabricated binding");
    assert_eq!(attachments, 0);
}

#[tokio::test]
async fn v21_full_typed_binding_continues_after_migration_and_restart() {
    let mut original = legacy_effect(LegacyReceipt::AcceptedV21).await;
    original.reopen().await;
    let before = original
        .store
        .pending_authorized_taskflow_effects(8)
        .await
        .expect("bound legacy pending");
    assert_eq!(before[0].provider_ack, Some(original.ack.clone()));
    original.reopen().await;
    assert_eq!(
        original
            .store
            .pending_authorized_taskflow_effects(8)
            .await
            .expect("retained binding"),
        before
    );
    let mut completed = original.ack.clone();
    completed.status = ProviderEffectAckStatus::Completed;
    let result = original
        .recover(AuthorizedEffectRecovery::Observed(
            AuthorizedEffectProviderReceipt::from_provider_ack(
                completed,
                ProviderEffectAckSource::StatusLookup,
            ),
        ))
        .await
        .expect("same original operation remains live");
    assert!(
        matches!(result, AuthorizedEffectRecoveryResult::Observed(receipt)
        if receipt.final_outcome == Some(TaskFlowReconcileOutcome::Succeeded))
    );
    original.reopen().await;
    assert!(
        original
            .store
            .pending_authorized_taskflow_effects(8)
            .await
            .expect("settled original")
            .is_empty()
    );
}

#[tokio::test]
async fn pre_upgrade_open_connection_cannot_append_through_old_insert_statements() {
    let mut original = legacy_effect(LegacyReceipt::UnobservedV21).await;
    let old_pool = SqliteConfig::from_sqlite_home(
        AbsolutePathBuf::try_from(original.root.clone()).expect("root"),
    )
    .open_durable_evidence_pool(original.store.path())
    .await
    .expect("old writer pool");
    let mut old_connection = old_pool.acquire().await.expect("pre-upgrade connection");
    let statements = [
        "INSERT INTO taskflow_effect_dispatch_attempts
         (owner_agent_id,run_id,step_id,attempt,intent_digest,payload_digest,provider_effect_key,
          wire_payload,binding_digest,destination_id,authority_epoch,grant_id,grant_nonce_digest,record_command_id,started_at_ms)
         SELECT owner_agent_id,run_id,step_id,2,intent_digest,payload_digest,provider_effect_key,
                wire_payload,binding_digest,destination_id,authority_epoch,'old-writer',payload_digest,'old-writer',26
         FROM taskflow_effect_dispatch_attempts WHERE attempt=1",
        "INSERT INTO taskflow_effect_dispatch_observations
         (owner_agent_id,run_id,step_id,attempt,observation,evidence_digest,observed_at_ms)
         SELECT owner_agent_id,run_id,step_id,attempt,'succeeded',payload_digest,26
         FROM taskflow_effect_dispatch_attempts WHERE attempt=1",
        "INSERT INTO taskflow_effect_dispatch_reconciliations
         (owner_agent_id,run_id,step_id,attempt,observation,evidence_digest,observed_at_ms)
         SELECT owner_agent_id,run_id,step_id,attempt,'proven_absent',payload_digest,26
         FROM taskflow_effect_dispatch_attempts WHERE attempt=1",
        "INSERT INTO taskflow_effect_provider_bindings
         (owner_agent_id,run_id,step_id,attempt,receipt_json,receipt_digest,observed_at_ms)
         SELECT owner_agent_id,run_id,step_id,attempt,?,?,26
         FROM taskflow_effect_dispatch_attempts WHERE attempt=1",
    ];
    for statement in statements {
        (&mut *old_connection)
            .prepare(sqlx::SqlStr::from_static(statement))
            .await
            .expect("prepare on original schema");
    }
    original.reopen().await;
    let before = original
        .store
        .pending_authorized_taskflow_effects(8)
        .await
        .expect("migrated pending");
    let json = format!(
        "{{\"schema_version\":1,\"source\":\"status_lookup\",\"ack\":{}}}",
        serde_json::to_string(&original.ack).expect("actual provider ACK"),
    );
    let digest = AuthorizedEffectProviderReceipt::from_provider_ack(
        original.ack.clone(),
        ProviderEffectAckSource::StatusLookup,
    )
    .receipt_digest;
    let mut accepted = Vec::new();
    for statement in statements {
        let mut transaction = old_connection
            .begin()
            .await
            .expect("old writer transaction");
        let mut query = sqlx::query(statement);
        if statement.starts_with("INSERT INTO taskflow_effect_provider_bindings") {
            query = query.bind(&json).bind(digest.as_str());
        }
        accepted.push(query.execute(&mut *transaction).await.is_ok());
        transaction
            .rollback()
            .await
            .expect("retain failed-control fixture");
    }
    assert_eq!(
        accepted,
        vec![false; statements.len()],
        "every old append is refused on the existing connection"
    );
    drop(old_connection);
    old_pool.close().await;
    original.reopen().await;
    assert_eq!(
        original
            .store
            .pending_authorized_taskflow_effects(8)
            .await
            .expect("unchanged pending"),
        before
    );
}

#[tokio::test]
async fn v20_existing_terminal_evidence_survives_migration_without_new_binding() {
    let mut original = legacy_effect(LegacyReceipt::CompletedV20).await;
    original.reopen().await;
    let result = original
        .store
        .settle_authorized_taskflow_effect_observation("legacy-run", "work", 1, &original.fence)
        .await
        .expect("read original terminal evidence")
        .expect("existing terminal result");
    assert!(
        matches!(result, AuthorizedEffectRecoveryResult::Observed(receipt)
        if receipt.observation == Some(crate::TaskFlowStepObservation::Succeeded))
    );
    original.reopen().await;
    let retained: String =
        sqlx::query_scalar("SELECT evidence_digest FROM taskflow_effect_dispatch_observations")
            .fetch_one(&original.store.pool)
            .await
            .expect("original terminal digest");
    assert_eq!(retained, original.evidence.as_str());
    let bindings: i64 =
        sqlx::query_scalar("SELECT count(*) FROM taskflow_effect_provider_bindings")
            .fetch_one(&original.store.pool)
            .await
            .expect("no invented binding");
    assert_eq!(bindings, 0);
}
