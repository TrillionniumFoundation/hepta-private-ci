//! Real SQLite and independent-file custody tests. The verifier/host below are
//! explicit test issuers; this does not install or qualify a production issuer.

use std::fs::File;
use std::io::Write;
use std::path::Path;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::*;
use crate::CognitiveAccess;
use crate::CognitiveRecoveryRequirement;
use crate::CognitiveScope;
use crate::ProductionAuthorityToken;
use crate::cognitive_store::create_private_directory;
use crate::cognitive_store::protect_database_file;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::source;

struct TestVerifier {
    revoked: AtomicBool,
}

impl ProductionAuthorityVerifier for TestVerifier {
    fn verify(
        &self,
        authority: &ProductionAuthorityLease,
        expected: &AgentId,
    ) -> Result<(), String> {
        if !self.revoked.load(Ordering::SeqCst)
            && authority.agent_id == *expected
            && authority.grant_digest == Sha256Digest::for_bytes(b"schema-upgrade-test-only-grant")
        {
            Ok(())
        } else {
            Err("test-only authority is not current".into())
        }
    }
}

struct TestHost {
    path: PathBuf,
    retention: Mutex<()>,
    fail_before: AtomicBool,
    fail_after: AtomicBool,
    false_ack: AtomicBool,
}

impl TestHost {
    fn write(&self, witness: &CognitiveSchemaUpgradeWitnessV1) {
        let temporary = self.path.with_extension("pending");
        let mut file = File::create(&temporary).unwrap();
        file.write_all(&serde_json::to_vec(witness).unwrap())
            .unwrap();
        file.sync_all().unwrap();
        std::fs::rename(temporary, &self.path).unwrap();
        File::open(self.path.parent().unwrap())
            .unwrap()
            .sync_all()
            .unwrap();
    }
}

impl CognitiveSchemaUpgradeHostV1 for TestHost {
    fn current_witness(&self, owner: &AgentId) -> Result<CognitiveSchemaUpgradeWitnessV1, String> {
        let witness: CognitiveSchemaUpgradeWitnessV1 =
            serde_json::from_slice(&std::fs::read(&self.path).map_err(|error| error.to_string())?)
                .map_err(|error| error.to_string())?;
        let actual = match &witness {
            CognitiveSchemaUpgradeWitnessV1::CurrentAnchor(anchor) => &anchor.owner_agent_id,
            CognitiveSchemaUpgradeWitnessV1::RetainedTransition(t) => &t.old_anchor.owner_agent_id,
            CognitiveSchemaUpgradeWitnessV1::Revoked => owner,
        };
        if actual != owner {
            return Err("test host owner mismatch".into());
        }
        Ok(witness)
    }

    fn retain_transition(&self, t: &CognitiveSchemaUpgradeTransitionV1) -> Result<(), String> {
        let _guard = self.retention.lock().unwrap();
        if self.fail_before.load(Ordering::SeqCst) {
            return Err("injected failure before durable retention".into());
        }
        if self.false_ack.load(Ordering::SeqCst) {
            return Ok(());
        }
        let current = self.current_witness(&t.old_anchor.owner_agent_id)?;
        if current != CognitiveSchemaUpgradeWitnessV1::CurrentAnchor(t.old_anchor.clone())
            && current != CognitiveSchemaUpgradeWitnessV1::RetainedTransition(t.clone())
        {
            return Err("independent witness compare-and-swap conflict".into());
        }
        self.write(&CognitiveSchemaUpgradeWitnessV1::RetainedTransition(
            t.clone(),
        ));
        if self.fail_after.load(Ordering::SeqCst) {
            return Err("injected process failure after durable retention".into());
        }
        Ok(())
    }
}

struct Fixture {
    _temp: TempDir,
    layout: HeptaAgentLayout,
    owner: AgentId,
    old: CognitiveRecoveryAnchor,
    source_path: PathBuf,
    source_bytes: Vec<u8>,
    authority: ProductionAuthorityLease,
    verifier: TestVerifier,
    host: TestHost,
}

async fn fixture(version: i64) -> Fixture {
    let temp = TempDir::new().unwrap();
    let owner = agent_id(201);
    let layout = layout(&temp, &owner);
    let root = create_private_directory(layout.cognitive_root()).unwrap();
    let guard = CognitiveStoreOpenGuard::acquire_shared(&root).unwrap();
    let config = SqliteConfig::from_sqlite_home(AbsolutePathBuf::try_from(root.clone()).unwrap());
    let source_path = root.join(COGNITIVE_DB_FILENAME);
    let pool = config
        .open_durable_evidence_pool(&source_path)
        .await
        .unwrap();
    MIGRATOR.run_to(version, &pool).await.unwrap();
    sqlx::query(
        "INSERT INTO cognitive_meta (singleton, schema_version, owner_agent_id) VALUES (1, 1, ?)",
    )
    .bind(owner.as_str())
    .execute(&pool)
    .await
    .unwrap();
    protect_database_file(&source_path).unwrap();
    let store = CognitiveStore {
        pool,
        owner_agent_id: owner.clone(),
        path: source_path.clone(),
        _open_guard: Some(guard),
    };
    store
        .append_source(
            &CognitiveAccess::agent_private(owner.clone()),
            &source(
                CognitiveScope::AgentPrivate,
                "old-evidence",
                "retained old bytes\0including a NUL",
            ),
        )
        .await
        .unwrap();
    let oracle = match version {
        15 => "046f23bab5d4c779735c762159c79e61cfe3a6a8a35e18ff8ec4f40e5c4e2be2",
        16 => "58b210d8065a05856a1e18ad37342a7b65b0f542909b85b1a7683c78e72db1e5",
        _ => panic!("historical fixture version"),
    };
    let hint = CognitiveRecoveryAnchor {
        profile: PROFILE.into(),
        owner_agent_id: owner.clone(),
        schema_digest: Sha256Digest::parse(oracle).unwrap(),
        state_digest: Sha256Digest::for_bytes(b"unused fixture lookup"),
    };
    let old = profile::capture_verified(&store.pool, &owner, &profile::historical(&hint).unwrap())
        .await
        .unwrap();
    store.close().await;
    let source_bytes = std::fs::read(&source_path).unwrap();
    let host = TestHost {
        path: temp.path().join("independent-upgrade-witness.json"),
        retention: Mutex::new(()),
        fail_before: AtomicBool::new(false),
        fail_after: AtomicBool::new(false),
        false_ack: AtomicBool::new(false),
    };
    host.write(&CognitiveSchemaUpgradeWitnessV1::CurrentAnchor(old.clone()));
    let authority = ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(b"schema-upgrade-test-only-grant"),
        /*authority_epoch*/ 1,
        /*owner_epoch*/ 1,
        u64::MAX,
        ProductionAuthorityToken::from_verified_bytes(b"schema-upgrade-test-only-fence".to_vec())
            .unwrap(),
    )
    .unwrap();
    Fixture {
        _temp: temp,
        layout,
        owner,
        old,
        source_path,
        source_bytes,
        authority,
        verifier: TestVerifier {
            revoked: AtomicBool::new(false),
        },
        host,
    }
}

async fn prepare(f: &Fixture) -> PreparedCognitiveSchemaUpgradeV1 {
    CognitiveStore::prepare_schema_upgrade(&f.layout, &f.host, &f.authority, &f.verifier)
        .await
        .unwrap()
}

async fn pool_for(path: &Path) -> sqlx::SqlitePool {
    SqliteConfig::from_sqlite_home(
        AbsolutePathBuf::try_from(path.parent().unwrap().to_path_buf()).unwrap(),
    )
    .open_durable_evidence_pool(path)
    .await
    .unwrap()
}

#[tokio::test]
async fn approved_0015_and_0016_upgrade_preserve_source_and_new_cut_after_restart() {
    for version in [15, 16] {
        let f = fixture(version).await;
        // Ordinary exact reopen remains deliberately incompatible with old schemas.
        assert!(
            CognitiveStore::open_with_recovery(
                &f.layout,
                CognitiveRecoveryRequirement::ExactCurrentCut(&f.old),
                &f.authority,
                &f.verifier
            )
            .await
            .is_err()
        );
        let mut prepared = prepare(&f).await;
        let t = prepared.transition().clone();
        assert_eq!(t.old_anchor(), &f.old);
        assert_ne!(t.new_anchor().schema_digest, f.old.schema_digest);
        assert_eq!(std::fs::read(&f.source_path).unwrap(), f.source_bytes);
        assert!(CognitiveStore::open(&f.layout).await.is_err());
        let store = prepared
            .activate(&f.host, &f.authority, &f.verifier)
            .await
            .unwrap();
        assert_eq!(store.recovery_anchor().await.unwrap(), *t.new_anchor());
        let bytes: Vec<u8> = sqlx::query_scalar("SELECT content FROM source_ledger")
            .fetch_one(&store.pool)
            .await
            .unwrap();
        assert_eq!(bytes, b"retained old bytes\0including a NUL");
        let tables: i64 = sqlx::query_scalar("SELECT count(*) FROM sqlite_schema WHERE type = 'table' AND name IN ('cognitive_memory_cell_checkpoints', 'cognitive_memory_cell_heads')").fetch_one(&store.pool).await.unwrap();
        assert_eq!(tables, 2);
        assert_eq!(
            f.host.current_witness(&f.owner).unwrap(),
            CognitiveSchemaUpgradeWitnessV1::RetainedTransition(t.clone())
        );
        store.close().await;
        assert_eq!(std::fs::read(&f.source_path).unwrap(), f.source_bytes);
        let reopened = CognitiveStore::open_with_recovery(
            &f.layout,
            CognitiveRecoveryRequirement::ExactCurrentCut(t.new_anchor()),
            &f.authority,
            &f.verifier,
        )
        .await
        .unwrap();
        assert_eq!(reopened.recovery_anchor().await.unwrap(), *t.new_anchor());
        reopened.close().await;
    }
}

#[tokio::test]
async fn retention_failure_keeps_receipt_and_lock_without_activating_or_scanning_candidates() {
    let f = fixture(15).await;
    let mut prepared = prepare(&f).await;
    let t = prepared.transition().clone();
    f.host.fail_before.store(true, Ordering::SeqCst);
    assert!(
        prepared
            .activate(&f.host, &f.authority, &f.verifier)
            .await
            .is_err()
    );
    assert_eq!(prepared.transition(), &t);
    assert_eq!(
        resolve_active_database_path(f.layout.cognitive_root()).unwrap(),
        f.source_path
    );
    assert!(
        f.layout
            .cognitive_root()
            .join(&t.prepared_database_filename)
            .exists()
    );
    assert!(CognitiveStore::open(&f.layout).await.is_err());
    assert!(
        CognitiveStore::resume_schema_upgrade(&f.layout, &f.host, &f.authority, &f.verifier)
            .await
            .is_err()
    );
    f.host.fail_before.store(false, Ordering::SeqCst);
    let store = prepared
        .activate(&f.host, &f.authority, &f.verifier)
        .await
        .unwrap();
    assert_eq!(store.recovery_anchor().await.unwrap(), *t.new_anchor());
    store.close().await;
}

#[tokio::test]
async fn crash_after_host_retention_resumes_before_and_after_pointer_publication() {
    let f = fixture(16).await;
    let mut prepared = prepare(&f).await;
    let t = prepared.transition().clone();
    f.host.fail_after.store(true, Ordering::SeqCst);
    assert!(
        prepared
            .activate(&f.host, &f.authority, &f.verifier)
            .await
            .is_err()
    );
    assert_eq!(
        resolve_active_database_path(f.layout.cognitive_root()).unwrap(),
        f.source_path
    );
    drop(prepared); // Simulate process loss; only the independent witness survives.
    let resumed =
        CognitiveStore::resume_schema_upgrade(&f.layout, &f.host, &f.authority, &f.verifier)
            .await
            .unwrap();
    assert_eq!(resumed.recovery_anchor().await.unwrap(), *t.new_anchor());
    resumed.close().await;
    // Once new is active, recovery uses that exact active cut even if the old
    // prepared filename disappears; it must not seek another local candidate.
    std::fs::remove_file(
        f.layout
            .cognitive_root()
            .join(&t.prepared_database_filename),
    )
    .unwrap();
    let resumed_again =
        CognitiveStore::resume_schema_upgrade(&f.layout, &f.host, &f.authority, &f.verifier)
            .await
            .unwrap();
    assert_eq!(
        resumed_again.recovery_anchor().await.unwrap(),
        *t.new_anchor()
    );
    resumed_again.close().await;
}

#[tokio::test]
async fn acknowledgement_without_independent_readback_and_revocation_cannot_activate() {
    let f = fixture(15).await;
    let mut prepared = prepare(&f).await;
    f.host.false_ack.store(true, Ordering::SeqCst);
    assert!(
        prepared
            .activate(&f.host, &f.authority, &f.verifier)
            .await
            .is_err()
    );
    f.host.false_ack.store(false, Ordering::SeqCst);
    f.verifier.revoked.store(true, Ordering::SeqCst);
    assert!(
        prepared
            .activate(&f.host, &f.authority, &f.verifier)
            .await
            .is_err()
    );
    f.verifier.revoked.store(false, Ordering::SeqCst);
    f.host.write(&CognitiveSchemaUpgradeWitnessV1::Revoked);
    assert!(
        prepared
            .activate(&f.host, &f.authority, &f.verifier)
            .await
            .is_err()
    );
    assert_eq!(
        resolve_active_database_path(f.layout.cognitive_root()).unwrap(),
        f.source_path
    );
    assert_eq!(std::fs::read(&f.source_path).unwrap(), f.source_bytes);
}

#[tokio::test]
async fn old_cut_ledger_and_schema_tampering_are_rejected_without_repairing_source() {
    for attack in ["cut", "ledger", "schema"] {
        let f = fixture(15).await;
        let pool = pool_for(&f.source_path).await;
        match attack {
            "cut" => {
                sqlx::query("UPDATE _sqlx_migrations SET execution_time = execution_time + 1 WHERE version = 1").execute(&pool).await.unwrap();
            }
            "ledger" => {
                sqlx::query(
                    "UPDATE _sqlx_migrations SET checksum = zeroblob(48) WHERE version = 1",
                )
                .execute(&pool)
                .await
                .unwrap();
                // Even a retained cut over this bad ledger cannot waive the
                // independently compiled historical checksum requirement.
                let mut tx = pool.begin_with("BEGIN IMMEDIATE").await.unwrap();
                let old_profile = profile::historical(&f.old).unwrap();
                let forged_cut = super::super::capture_profile(
                    &mut tx,
                    &f.owner,
                    &old_profile.objects,
                    old_profile.oracle,
                )
                .await
                .unwrap();
                tx.commit().await.unwrap();
                f.host
                    .write(&CognitiveSchemaUpgradeWitnessV1::CurrentAnchor(forged_cut));
            }
            "schema" => {
                sqlx::query("DROP TRIGGER source_ledger_no_delete")
                    .execute(&pool)
                    .await
                    .unwrap();
            }
            _ => unreachable!(),
        }
        pool.close().await;
        let before = std::fs::read(&f.source_path).unwrap();
        assert!(
            CognitiveStore::prepare_schema_upgrade(&f.layout, &f.host, &f.authority, &f.verifier)
                .await
                .is_err()
        );
        assert_eq!(std::fs::read(&f.source_path).unwrap(), before);
        assert_eq!(
            resolve_active_database_path(f.layout.cognitive_root()).unwrap(),
            f.source_path
        );
    }
}

#[tokio::test]
async fn retained_transition_rejects_wrong_plan_owner_fence_and_candidate_locator() {
    let f = fixture(15).await;
    let prepared = prepare(&f).await;
    let t = prepared.transition().clone();
    drop(prepared);
    for attack in ["plan", "owner", "fence", "locator"] {
        let mut changed = t.clone();
        match attack {
            "plan" => {
                changed.migration_plan_digest = Sha256Digest::for_bytes(b"not the compiled plan")
            }
            "owner" => changed.new_anchor.owner_agent_id = agent_id(202),
            "fence" => changed.authority_fence_digest = Sha256Digest::for_bytes(b"other authority"),
            "locator" => changed.prepared_database_filename = "../outside.sqlite3".into(),
            _ => unreachable!(),
        }
        f.host
            .write(&CognitiveSchemaUpgradeWitnessV1::RetainedTransition(
                changed,
            ));
        assert!(
            CognitiveStore::resume_schema_upgrade(&f.layout, &f.host, &f.authority, &f.verifier)
                .await
                .is_err()
        );
        assert_eq!(std::fs::read(&f.source_path).unwrap(), f.source_bytes);
    }
}

#[tokio::test]
async fn changed_prepared_image_cannot_replace_exact_old_source() {
    let f = fixture(15).await;
    let mut prepared = prepare(&f).await;
    let t = prepared.transition().clone();
    f.host.fail_after.store(true, Ordering::SeqCst);
    assert!(
        prepared
            .activate(&f.host, &f.authority, &f.verifier)
            .await
            .is_err()
    );
    drop(prepared);
    let pool = pool_for(
        &f.layout
            .cognitive_root()
            .join(&t.prepared_database_filename),
    )
    .await;
    sqlx::query(
        "UPDATE _sqlx_migrations SET execution_time = execution_time + 1 WHERE version = 16",
    )
    .execute(&pool)
    .await
    .unwrap();
    pool.close().await;
    assert!(
        CognitiveStore::resume_schema_upgrade(&f.layout, &f.host, &f.authority, &f.verifier)
            .await
            .is_err()
    );
    assert_eq!(
        resolve_active_database_path(f.layout.cognitive_root()).unwrap(),
        f.source_path
    );
    assert_eq!(std::fs::read(&f.source_path).unwrap(), f.source_bytes);
}

#[tokio::test]
async fn stale_retained_transition_never_rolls_back_an_advanced_active_cut() {
    let f = fixture(15).await;
    let mut prepared = prepare(&f).await;
    let store = prepared
        .activate(&f.host, &f.authority, &f.verifier)
        .await
        .unwrap();
    store
        .append_source(
            &CognitiveAccess::agent_private(f.owner.clone()),
            &source(
                CognitiveScope::AgentPrivate,
                "post-upgrade",
                "new evidence after activation",
            ),
        )
        .await
        .unwrap();
    let active = store.path().to_path_buf();
    store.close().await;
    let bytes = std::fs::read(&active).unwrap();
    assert!(
        CognitiveStore::resume_schema_upgrade(&f.layout, &f.host, &f.authority, &f.verifier)
            .await
            .is_err()
    );
    assert_eq!(
        resolve_active_database_path(f.layout.cognitive_root()).unwrap(),
        active
    );
    assert_eq!(std::fs::read(active).unwrap(), bytes);
}
