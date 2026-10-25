use super::*;
use crate::HOS2_CPU_PERIOD_NS;
use crate::HOS2_DESTINATION_V1;
use crate::HOS2_INSTALL_TOPIC_V1;
use crate::Hos2DeliveryId;
use crate::Hos2InstallBudgetV1;
use crate::LocalOutcomeState;
use crate::ProductionDurableWriter;
use codex_hepta_operations::OperationIntentV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use std::sync::Arc;

const LEASE: &str = "historical-original-lease";
const OPERATION: &str = "historical-hos2-operation";

struct HistoricalFixture {
    temp: TempDir,
    owner: AgentId,
    old: CognitiveRecoveryAnchor,
    current: CognitiveRecoveryAnchor,
    path: PathBuf,
    request: Hos2InstallBudgetV1,
    operation: OperationIntentV1,
}

impl HistoricalFixture {
    async fn new() -> Self {
        let temp = TempDir::new().expect("temp");
        let owner = agent_id(93);
        let (store, _, _) = seeded(&temp, &owner).await;
        let old = store
            .recovery_anchor()
            .await
            .expect("original independent cut");
        store.close().await;
        let mut authority = recovery_authority(&owner);
        authority.lease_expires_at_unix_seconds = i64::MAX as u64;
        let recovered = CognitiveStore::open_with_recovery(
            &layout(&temp, &owner),
            CognitiveRecoveryRequirement::ExactCurrentCut(&old),
            &authority,
            &RecoveryVerifier,
        )
        .await
        .expect("original active-generation recovery");
        let path = recovered.path().to_path_buf();
        let writer = ProductionDurableWriter::open_with_live_verifier(
            recovered,
            authority,
            Arc::new(RecoveryVerifier),
            LEASE,
            /*generation*/ 1,
        )
        .await
        .expect("original writer");
        let request = Hos2InstallBudgetV1 {
            schema_version: 1,
            delivery: Hos2DeliveryId::new([1; 16], [2; 16], /*sequence*/ 1).expect("old boot D"),
            manage_slot: 2,
            manage_generation: 1,
            expected_revision: 1,
            period_ns: HOS2_CPU_PERIOD_NS,
            cap_ns: 1_001,
        };
        let payload = request.to_json().expect("exact payload");
        let operation = OperationIntentV1::new(
            StableId::new(OPERATION).expect("op"),
            StableId::new(owner.as_str()).expect("subject"),
            StableId::new(HOS2_DESTINATION_V1).expect("destination"),
            Digest32::of_bytes(payload.as_bytes()),
            request.scope_digest(),
            Generation::new(1).expect("generation"),
            /*expected_predecessor*/ None,
        )
        .expect("operation");
        writer
            .prepare_operation(operation.clone(), HOS2_INSTALL_TOPIC_V1, payload)
            .await
            .expect("original operation admission");
        writer
            .mark_indeterminate(OPERATION, "effect response unavailable")
            .await
            .expect("original indeterminate state");
        let current = writer
            .recovery_anchor()
            .await
            .expect("independently retained current");
        writer
            .close()
            .await
            .expect("close original writer before cold observation");
        Self {
            temp,
            owner,
            old,
            current,
            path,
            request,
            operation,
        }
    }

    fn layout(&self) -> HeptaAgentLayout {
        layout(&self.temp, &self.owner)
    }
}

#[tokio::test]
async fn active_cold_history_retains_original_delivery_payload_and_indeterminate() {
    let fixture = HistoricalFixture::new().await;
    let root = fixture.path.parent().expect("root");
    let before = capture_recovery_tree(root);
    for _ in 0..2 {
        let history = CognitiveStore::open_active_read_only_recovery(
            &fixture.layout(),
            CognitiveRecoveryRequirement::ExactCurrentCut(&fixture.current),
        )
        .await
        .expect("active historical observation");
        assert_eq!(history.anchor(), &fixture.current);
        let retained = history
            .retained_operation(LEASE, OPERATION)
            .await
            .expect("original checks")
            .expect("original operation");
        assert_eq!(
            (
                retained.operation,
                retained.topic,
                retained.payload_json,
                retained.state
            ),
            (
                fixture.operation.clone(),
                HOS2_INSTALL_TOPIC_V1.to_owned(),
                fixture.request.to_json().expect("exact old D bytes"),
                LocalOutcomeState::Indeterminate
            ),
        );
        assert!(
            history
                .retained_operation("other-lease", OPERATION)
                .await
                .expect("no foreign lease")
                .is_none()
        );
        assert!(
            history
                .retained_operation(LEASE, "missing-operation")
                .await
                .expect("unknown")
                .is_none()
        );
        assert!(history.retained_operation("", OPERATION).await.is_err());
        assert!(history.retained_operation(LEASE, "\0").await.is_err());
        history.close().await;
        assert_eq!(capture_recovery_tree(root), before);
    }
    // The original fixed-file API retains its identity and never accidentally
    // substitutes the selected active generation for the old source file.
    let original = CognitiveStore::open_read_only_recovery(
        &fixture.layout(),
        CognitiveRecoveryRequirement::ExactCurrentCut(&fixture.old),
    )
    .await
    .expect("original cold API still reads original source");
    assert!(
        original
            .retained_operation(LEASE, OPERATION)
            .await
            .expect("old cut")
            .is_none()
    );
    original.close().await;
    assert!(matches!(
        CognitiveStore::open_read_only_recovery(
            &fixture.layout(),
            CognitiveRecoveryRequirement::ExactCurrentCut(&fixture.current),
        )
        .await,
        Err(CognitiveRecoveryError::AccessDenied(_))
    ));
    assert_eq!(capture_recovery_tree(root), before);
}

#[tokio::test]
async fn active_cold_history_requires_complete_current_and_revocation_disposition() {
    let fixture = HistoricalFixture::new().await;
    let root = fixture.path.parent().expect("root");
    let before = capture_recovery_tree(root);
    let mut wrong_schema = fixture.current.clone();
    wrong_schema.schema_digest = Sha256Digest::for_bytes(b"wrong schema");
    let mut wrong_owner = fixture.current.clone();
    wrong_owner.owner_agent_id = agent_id(99);
    let mut wrong_profile = fixture.current.clone();
    wrong_profile.profile.push_str(":other");
    for cut in [&fixture.old, &wrong_schema, &wrong_owner, &wrong_profile] {
        assert!(
            CognitiveStore::open_active_read_only_recovery(
                &fixture.layout(),
                CognitiveRecoveryRequirement::ExactCurrentCut(cut),
            )
            .await
            .is_err()
        );
        assert_eq!(capture_recovery_tree(root), before);
    }
    std::fs::remove_dir_all(root).expect("absent source");
    assert!(matches!(
        CognitiveStore::open_active_read_only_recovery(
            &fixture.layout(),
            CognitiveRecoveryRequirement::Revoked,
        )
        .await,
        Err(CognitiveRecoveryError::AccessDenied(_))
    ));
    assert!(!root.exists());
}

#[tokio::test]
async fn active_cold_history_refuses_sidecars_and_redirects_without_source_mutation() {
    let fixture = HistoricalFixture::new().await;
    let root = fixture.path.parent().expect("root");
    for suffix in ["-wal", "-shm", "-journal"] {
        let sidecar = PathBuf::from(format!("{}{suffix}", fixture.path.display()));
        std::fs::write(&sidecar, []).expect("even empty sidecar");
        let before = capture_recovery_tree(root);
        assert!(
            CognitiveStore::open_active_read_only_recovery(
                &fixture.layout(),
                CognitiveRecoveryRequirement::ExactCurrentCut(&fixture.current),
            )
            .await
            .is_err()
        );
        assert_eq!(capture_recovery_tree(root), before);
        std::fs::remove_file(sidecar).expect("remove fixture sidecar");
    }
    let pointer = root.join(super::super::super::COGNITIVE_ACTIVE_DB_POINTER);
    let pointer_bytes = std::fs::read(&pointer).expect("active pointer");
    let pointer_copy = fixture.temp.path().join("pointer-copy");
    std::fs::write(&pointer_copy, &pointer_bytes).expect("pointer target");
    std::fs::remove_file(&pointer).expect("remove pointer");
    symlink(&pointer_copy, &pointer).expect("redirect pointer");
    let before = capture_recovery_tree(root);
    assert!(
        CognitiveStore::open_active_read_only_recovery(
            &fixture.layout(),
            CognitiveRecoveryRequirement::ExactCurrentCut(&fixture.current),
        )
        .await
        .is_err()
    );
    assert_eq!(capture_recovery_tree(root), before);
    std::fs::remove_file(&pointer).expect("remove symlink");
    std::fs::write(&pointer, pointer_bytes).expect("restore pointer");
    std::fs::set_permissions(&pointer, std::fs::Permissions::from_mode(0o600)).expect("private");
    let moved = fixture.temp.path().join("moved-active.sqlite3");
    std::fs::rename(&fixture.path, &moved).expect("move selected database");
    symlink(&moved, &fixture.path).expect("redirect active database");
    let before = capture_recovery_tree(root);
    assert!(
        CognitiveStore::open_active_read_only_recovery(
            &fixture.layout(),
            CognitiveRecoveryRequirement::ExactCurrentCut(&fixture.current),
        )
        .await
        .is_err()
    );
    assert_eq!(capture_recovery_tree(root), before);
}
