use super::*;
use crate::AutomationError;
use crate::effect_dispatch_ledger::EffectDispatchObservationKind;
use crate::effect_dispatch_ledger::EffectDispatchStart;
use crate::effect_dispatch_ledger::tests::prepared_store;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;
#[derive(Debug)]
struct Clock;
impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(21)
    }
}

struct Setup {
    _temp: tempfile::TempDir,
    _authority_dir: tempfile::TempDir,
    layout: codex_hepta_paths::HeptaAgentLayout,
    store: AutomationStore,
    fence: TaskFlowFence,
    durable: EffectDispatchAttempt,
    authority: FinalUseAuthority,
    signed: SignedFinalUseGrant,
}

impl Setup {
    async fn new() -> TestResult<Self> {
        let (temp, layout, store, fence) = prepared_store().await;
        let intent = Sha256Digest::for_bytes(b"effect-intent");
        let payload = Sha256Digest::for_bytes(b"effect-payload");
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "preparation-issuer".into(),
            authority_epoch: 7,
            grant_id: "preparation-grant".into(),
            nonce: [8; 32],
            binding: FinalUseBinding {
                subject_id: "agent:fixture".into(),
                destination_id: "provider:fixture".into(),
                request_sha256: crate::authorized_effect::digest_bytes(&intent)?,
                payload_sha256: crate::authorized_effect::digest_bytes(&payload)?,
                scope_sha256: [4; 32],
            },
            not_before_unix_ms: 0,
            expires_at_unix_ms: 10_000,
        };
        let issuer = SigningKey::from_bytes(&[41; 32]);
        let signature = issuer.sign(&grant.signing_bytes()?).to_bytes().to_vec();
        let directory = tempfile::tempdir()?;
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
        let authority = FinalUseAuthority::open_state_dir_with_clock(
            directory.path(),
            grant.signer_id.clone(),
            issuer.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 7,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
            Arc::new(Clock),
        )?;
        let start = store
            .begin_effect_dispatch_attempt(
                "effect-run",
                "work",
                /*attempt*/ 1,
                &intent,
                &payload,
                &Sha256Digest::for_bytes(&serde_json::to_vec(&grant.binding)?),
                &grant.binding.destination_id,
                grant.authority_epoch,
                &grant.grant_id,
                &Sha256Digest::for_bytes(&grant.nonce),
                "record-effect",
                || Ok(21),
                &fence,
                Some(&Sha256Digest::for_bytes(b"provider-contract")),
            )
            .await?;
        let EffectDispatchStart::Inserted(durable) = start else {
            return Err("expected new attempt".into());
        };
        Ok(Self {
            _temp: temp,
            _authority_dir: directory,
            layout,
            store,
            fence,
            durable,
            authority,
            signed: SignedFinalUseGrant { grant, signature },
        })
    }

    async fn append(&self) -> TestResult<VerifiedPreparationEvidence> {
        let expected = &self.signed.grant.binding;
        let token = self.authority.claim(&self.signed, expected)?;
        Ok(self
            .authority
            .with_prepared_verified_use_async(
                token,
                expected,
                |evidence| async move {
                    let (a, b) = tokio::join!(
                        self.store.record_effect_preparation_witness(
                            &self.durable,
                            &self.fence,
                            &evidence
                        ),
                        self.store.record_effect_preparation_witness(
                            &self.durable,
                            &self.fence,
                            &evidence
                        ),
                    );
                    a?;
                    b?;
                    Ok::<_, TaskFlowError>(evidence)
                },
                |evidence| async { Ok(evidence) },
            )
            .await??)
    }

    async fn read(&self) -> Result<Option<VerifiedUseTokenWitnessV1>, TaskFlowError> {
        self.store
            .authorized_taskflow_effect_preparation_witness(
                "effect-run",
                "work",
                /*attempt*/ 1,
            )
            .await
    }
}

#[tokio::test]
async fn exact_preparation_handles_concurrent_append_replay_and_reopen() -> TestResult {
    let setup = Setup::new().await?;
    assert_eq!(setup.read().await?, None);
    let before = setup.store.taskflow_run("effect-run").await?;
    let evidence = setup.append().await?;
    for _ in 0..2 {
        setup
            .store
            .record_effect_preparation_witness(&setup.durable, &setup.fence, &evidence)
            .await?;
        assert_eq!(setup.read().await?, Some(evidence.observation().clone()));
    }
    assert_eq!(setup.store.taskflow_run("effect-run").await?, before);
    assert_eq!(
        setup
            .store
            .scan_authorized_taskflow_effects(/*cursor*/ None, /*limit*/ 10)
            .await?
            .effects
            .len(),
        1
    );
    for sql in [
        "UPDATE taskflow_effect_preparation_evidence SET record_json = record_json",
        "DELETE FROM taskflow_effect_preparation_evidence",
    ] {
        assert!(
            sqlx::query(sql)
                .execute(setup.store.taskflow_pool())
                .await
                .is_err()
        );
    }
    setup.store.close().await;
    let reopened = AutomationStore::open(&setup.layout).await?;
    assert_eq!(
        reopened
            .authorized_taskflow_effect_preparation_witness(
                "effect-run",
                "work",
                /*attempt*/ 1
            )
            .await?,
        Some(evidence.observation().clone())
    );
    assert_eq!(
        reopened
            .scan_authorized_taskflow_effects(/*cursor*/ None, /*limit*/ 10)
            .await?
            .effects
            .len(),
        1
    );
    reopened.close().await;
    Ok(())
}

#[tokio::test]
async fn preparation_read_rejects_invalid_identity_before_querying_a_closed_store() -> TestResult {
    let setup = Setup::new().await?;
    setup.store.close().await;
    let oversized = "r".repeat(257);
    for (run, step, attempt) in [
        ("", "work", 1),
        ("effect-run", "", 1),
        ("effect-run", "work", 0),
        ("effect-run", "work", 1_000_001),
        (oversized.as_str(), "work", 1),
        ("effect-run", "bad\nstep", 1),
    ] {
        assert!(matches!(
            setup
                .store
                .authorized_taskflow_effect_preparation_witness(run, step, attempt)
                .await,
            Err(TaskFlowError::Invalid(_))
        ));
    }
    Ok(())
}

#[tokio::test]
async fn preparation_audit_read_works_with_every_connection_query_only() -> TestResult {
    let setup = Setup::new().await?;
    let evidence = setup.append().await?;
    let mut held = Vec::new();
    for _ in 0..setup.store.taskflow_pool().options().get_max_connections() {
        let mut connection = setup.store.taskflow_pool().acquire().await?;
        sqlx::query("PRAGMA query_only = ON")
            .execute(&mut *connection)
            .await?;
        held.push(connection);
    }
    drop(held);
    assert_eq!(setup.read().await?, Some(evidence.observation().clone()));
    setup.store.close().await;
    Ok(())
}

#[tokio::test]
async fn preparation_survives_terminal_crash_cuts_and_later_absence_owner() -> TestResult {
    for kind in [
        EffectDispatchObservationKind::Succeeded,
        EffectDispatchObservationKind::Failed,
        EffectDispatchObservationKind::ProvenAbsent,
    ] {
        let setup = Setup::new().await?;
        let evidence = setup.append().await?;
        setup
            .store
            .record_effect_dispatch_observation(
                "effect-run",
                "work",
                /*attempt*/ 1,
                kind,
                &Sha256Digest::for_bytes(b"terminal"),
                /*observed_at_ms*/ 22,
                /*provider*/ None,
            )
            .await?;
        assert_eq!(setup.read().await?, Some(evidence.observation().clone()));
        assert_eq!(
            setup
                .store
                .scan_authorized_taskflow_effects(/*cursor*/ None, /*limit*/ 10)
                .await?
                .effects
                .len(),
            1
        );
        setup
            .store
            .settle_authorized_taskflow_effect_observation(
                "effect-run",
                "work",
                /*attempt*/ 1,
                &setup.fence,
            )
            .await?;
        if kind == EffectDispatchObservationKind::ProvenAbsent {
            let successor = TaskFlowFence::new(
                setup.fence.owner_agent_id.clone(),
                "successor-owner",
                /*owner_epoch*/ 2,
                /*generation*/ 2,
                "successor-fence",
            )?;
            setup
                .store
                .claim_taskflow_run(
                    "effect-run",
                    &successor,
                    /*now_ms*/ 30,
                    /*lease_duration_ms*/ 10_000,
                )
                .await?;
        }
        let before = setup.store.taskflow_run("effect-run").await?;
        assert_eq!(setup.read().await?, Some(evidence.observation().clone()));
        assert_eq!(setup.store.taskflow_run("effect-run").await?, before);
        assert!(
            setup
                .store
                .scan_authorized_taskflow_effects(/*cursor*/ None, /*limit*/ 10)
                .await?
                .effects
                .is_empty()
        );
        setup.store.close().await;
        let reopened = AutomationStore::open(&setup.layout).await?;
        assert_eq!(
            reopened
                .authorized_taskflow_effect_preparation_witness(
                    "effect-run",
                    "work",
                    /*attempt*/ 1
                )
                .await?,
            Some(evidence.observation().clone())
        );
        reopened.close().await;
    }
    Ok(())
}

#[tokio::test]
async fn append_rejects_wrong_attempt_or_fence_without_poisoning_evidence() -> TestResult {
    let setup = Setup::new().await?;
    let evidence = setup.append().await?;
    let mut wrong = setup.durable.clone();
    wrong.record_command_id = "wrong-command".into();
    assert!(matches!(
        setup
            .store
            .record_effect_preparation_witness(&wrong, &setup.fence, &evidence)
            .await,
        Err(TaskFlowError::Conflict(_))
    ));
    let mut fence = setup.fence.clone();
    fence.fencing_token = "wrong-fence".into();
    assert!(matches!(
        setup
            .store
            .record_effect_preparation_witness(&setup.durable, &fence, &evidence)
            .await,
        Err(TaskFlowError::Conflict(_))
    ));
    assert_eq!(setup.read().await?, Some(evidence.observation().clone()));
    setup.store.close().await;
    Ok(())
}

#[tokio::test]
async fn self_hashed_wrong_records_cannot_attest_another_attempt_or_authority() -> TestResult {
    for mutation in [
        "command",
        "provider",
        "receipt",
        "fence",
        "grant",
        "nonce",
        "subject",
        "scope",
        "witness_grant",
        "witness_signer",
        "authority_family",
        "epoch",
        "boundary",
        "time",
        "unknown",
    ] {
        let setup = Setup::new().await?;
        setup.append().await?;
        let bytes: Vec<u8> =
            sqlx::query_scalar("SELECT record_json FROM taskflow_effect_preparation_evidence")
                .fetch_one(setup.store.taskflow_pool())
                .await?;
        let mut value: serde_json::Value = serde_json::from_slice(&bytes)?;
        match mutation {
            "command" => value["attempt_identity"]["record_command_id"] = json!("wrong"),
            "provider" => value["attempt_identity"]["provider_key_version"] = json!(1),
            "receipt" => value["attempt_identity"]["receipt_digest"] = json!("fabricated"),
            "fence" => value["step_authoring_identity"]["fence"]["fencing_token"] = json!("wrong"),
            "grant" => value["grant"]["grant_id"] = json!("wrong"),
            "nonce" => value["grant"]["nonce"] = json!(vec![9; 32]),
            "subject" => value["grant"]["binding"]["subject_id"] = json!("wrong"),
            "scope" => value["grant"]["binding"]["scope_sha256"] = json!(vec![9; 32]),
            "witness_grant" => {
                value["witness"]["authority_ref"]["authority"]["grant_id"] = json!("wrong")
            }
            "witness_signer" => {
                value["witness"]["authority_ref"]["authority"]["signer_id"] = json!("wrong")
            }
            "authority_family" => {
                value["witness"]["authority_ref"] = json!({
                "authority_family": "authority_lease", "authority": {
                    "owner_id": "wrong", "lease_id": "wrong", "lease_revision": 1,
                    "store_revision": 1, "binding_sha256": vec![9; 32] }})
            }
            "epoch" => value["witness"]["authority_epoch"] = json!(8),
            "boundary" => value["witness"]["boundary"] = json!("dispatch_entry"),
            "time" => value["witness"]["verified_at_unix_ms"] = json!(10_000),
            "unknown" => value["unrecognized"] = json!("wrong"),
            _ => unreachable!(),
        }
        let bytes = match serde_json::from_value::<PreparationRecord>(value.clone()) {
            Ok(record) => serde_json::to_vec(&record)?,
            Err(_) => serde_json::to_vec(&value)?,
        };
        sqlx::query("DROP TRIGGER taskflow_effect_preparation_evidence_no_update")
            .execute(setup.store.taskflow_pool())
            .await?;
        sqlx::query(
            "UPDATE taskflow_effect_preparation_evidence SET record_json = ?, record_sha256 = ?",
        )
        .bind(&bytes)
        .bind(record_digest(&bytes).as_str())
        .execute(setup.store.taskflow_pool())
        .await?;
        assert!(
            matches!(setup.read().await, Err(TaskFlowError::Corrupt(_))),
            "{mutation}"
        );
        setup.store.close().await;
    }
    Ok(())
}

#[tokio::test]
async fn reopen_refuses_missing_or_replaced_immutability_triggers() -> TestResult {
    for replacement in [false, true] {
        let setup = Setup::new().await?;
        setup.append().await?;
        let mut connection = setup.store.taskflow_pool().acquire().await?;
        sqlx::query("DROP TRIGGER taskflow_effect_preparation_evidence_no_update")
            .execute(&mut *connection)
            .await?;
        if replacement {
            sqlx::query(
                "CREATE TRIGGER taskflow_effect_preparation_evidence_no_update
                BEFORE UPDATE ON taskflow_effect_preparation_evidence BEGIN SELECT 1; END",
            )
            .execute(&mut *connection)
            .await?;
        }
        drop(connection);
        setup.store.close().await;
        assert!(matches!(
            AutomationStore::open(&setup.layout).await,
            Err(AutomationError::Corrupt)
        ));
    }
    Ok(())
}

#[tokio::test]
async fn oversized_offline_record_is_rejected_before_materialization() -> TestResult {
    let setup = Setup::new().await?;
    setup.append().await?;
    let mut connection = setup.store.taskflow_pool().acquire().await?;
    sqlx::query("DROP TRIGGER taskflow_effect_preparation_evidence_no_update")
        .execute(&mut *connection)
        .await?;
    sqlx::query("PRAGMA ignore_check_constraints = ON")
        .execute(&mut *connection)
        .await?;
    let bytes = vec![b'x'; MAX_RECORD_BYTES + 1];
    sqlx::query(
        "UPDATE taskflow_effect_preparation_evidence SET record_json = ?, record_sha256 = ?",
    )
    .bind(&bytes)
    .bind(record_digest(&bytes).as_str())
    .execute(&mut *connection)
    .await?;
    sqlx::query("PRAGMA ignore_check_constraints = OFF")
        .execute(&mut *connection)
        .await?;
    drop(connection);
    assert!(matches!(setup.read().await, Err(TaskFlowError::Corrupt(_))));
    setup.store.close().await;
    Ok(())
}
