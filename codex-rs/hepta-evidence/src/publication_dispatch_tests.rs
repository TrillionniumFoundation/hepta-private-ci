use std::cell::Cell;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use std::time::Duration;

use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use sqlx::Connection;
use tempfile::TempDir;

use super::*;
use crate::EvidenceAcceptedFrontierV1;
use crate::EvidenceCandidateV1;
use crate::EvidenceClaimClassV1;
use crate::EvidenceId;
use crate::EvidenceIssuerRoleV1;
use crate::EvidencePublicationBatchStateV1;
use crate::EvidenceReceiptKindV1;
use crate::EvidenceRecoveryFrontierSignatureV2;
use crate::EvidenceTrustGenerationAcceptanceV1;
use crate::QualificationEvidenceEnvelopeV1;
use crate::evidence_recovery_ledger_root_v2;
use crate::qualification_append_scope_digest;
use crate::qualification_envelope_bytes;
use crate::qualification_subject;

struct Fixture {
    _temp: TempDir,
    store: HeptaEvidenceStore,
    trust: VerifiedEvidenceTrustSnapshot,
    registry: PathBuf,
    lease: EvidencePublicationOwnerLeaseV1,
    batch_id: String,
    proposed: EvidenceRecoveryFrontierV2,
    ack: EvidenceFrontierDurableAckV1,
}

impl Fixture {
    async fn new() -> Self {
        let temp = TempDir::new().expect("private home");
        std::fs::set_permissions(temp.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        let config = SqliteConfig::new_for_testing(
            AbsolutePathBuf::try_from(temp.path().to_path_buf()).unwrap(),
        );
        let store = HeptaEvidenceStore::open(&config).await.unwrap();
        store
            .bind_recovery_store_id("store:dispatch")
            .await
            .unwrap();
        let key = SigningKey::from_bytes(&[7_u8; 32]);
        let key_hex = key
            .verifying_key()
            .as_bytes()
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        let registry = temp.path().join("trust.json");
        let bytes = canonical_json(&serde_json::json!({
            "schema_version": 2, "agent_id": "agent:dispatch", "generation": 1,
            "predecessor_sha256": null,
            "issuers": [{"issuer_id": "issuer:dispatch", "key_epoch": 1,
                "public_key_hex": key_hex, "revoked": false, "roles": ["architecture"]}]
        }))
        .unwrap();
        std::fs::write(&registry, &bytes).unwrap();
        std::fs::set_permissions(&registry, std::fs::Permissions::from_mode(0o600)).unwrap();
        let trust = VerifiedEvidenceTrustSnapshot::load_owner_registry(
            &store,
            &registry,
            "agent:dispatch",
            Some(&Sha256Digest::for_bytes(&bytes)),
        )
        .unwrap();
        let now = u64::try_from(now_millis().unwrap()).unwrap();
        let initial = EvidenceAcceptedFrontierV1 {
            store_id: "store:dispatch".to_string(),
            frontier_generation: 1,
            frontier_sha256: Sha256Digest::for_bytes(b"independently accepted fixture"),
            backend_identity_sha256: Sha256Digest::for_bytes(b"backend:dispatch"),
            accepted_at_unix_ms: now,
        };
        let accepted_trust = EvidenceTrustGenerationAcceptanceV1 {
            store_id: initial.store_id.clone(),
            agent_id: trust.agent_id().to_string(),
            registry_generation: 1,
            registry_sha256: trust.registry_sha256().clone(),
            predecessor_sha256: None,
            accepted_frontier_generation: 1,
            accepted_frontier_sha256: initial.frontier_sha256.clone(),
            backend_identity_sha256: initial.backend_identity_sha256.clone(),
            accepted_at_unix_ms: now,
        };
        let initial_snapshot = store.authenticated_recovery_snapshot().await.unwrap();
        store
            .accept_production_generation_at_snapshot(&initial, &initial_snapshot, &accepted_trust)
            .await
            .unwrap();
        let envelope = QualificationEvidenceEnvelopeV1 {
            schema_version: 1,
            evidence_id: EvidenceId::parse("evidence:dispatch").unwrap(),
            candidate: EvidenceCandidateV1 {
                candidate_id: "candidate:dispatch".to_string(),
                source_commit: "a".repeat(40),
                source_tree: "b".repeat(40),
            },
            claim_class: EvidenceClaimClassV1::ExactSource,
            receipt_kind: EvidenceReceiptKindV1::Evidence,
            issuer_role: EvidenceIssuerRoleV1::Architecture,
            payload: serde_json::json!({"test": true}),
            predecessor_evidence_id: None,
            target_evidence_id: None,
            observed_unix_ms: now,
            expires_unix_ms: None,
            asset_digests: Vec::new(),
        };
        let claims = SignedMessageClaims {
            issuer_id: StableId::new("issuer:dispatch").unwrap(),
            key_epoch: Generation::new(1).unwrap(),
            message_id: StableId::new("message:dispatch").unwrap(),
            subject_id: qualification_subject(&envelope.candidate, envelope.issuer_role).unwrap(),
            scope_digest: qualification_append_scope_digest(),
            payload_digest: Digest32::of_bytes(&qualification_envelope_bytes(&envelope).unwrap()),
            sequence: 1,
            expires_at_ms: now + 600_000,
        };
        let message = SignedMessage {
            signature: key.sign(&claims.signing_bytes()).to_bytes(),
            claims,
        };
        let issuer = trust
            .issuer_for("issuer:dispatch", 1, EvidenceIssuerRoleV1::Architecture)
            .unwrap();
        store
            .qualification()
            .append_receipt(&issuer, &message, &envelope)
            .await
            .unwrap();
        let now = u64::try_from(now_millis().unwrap()).unwrap();
        let lease = store
            .claim_publication_owner("owner:dispatch", now, 600_000)
            .await
            .unwrap();
        let batch = store
            .prepare_publication_batch(&lease, now, 8)
            .await
            .unwrap()
            .unwrap();
        let proposed = EvidenceRecoveryFrontierV2 {
            schema_version: 2,
            store_id: initial.store_id,
            frontier_generation: 2,
            ledger_root_sha256: evidence_recovery_ledger_root_v2(&batch.snapshot),
            snapshot: batch.snapshot,
            issuer_trust_registry_sha256: trust.registry_sha256().clone(),
            frontier_signer_registry_sha256: Sha256Digest::for_bytes(b"signers"),
            backend_identity_sha256: initial.backend_identity_sha256,
            build_artifact_sha256: Sha256Digest::for_bytes(b"build"),
            qualification_receipt_sha256: Sha256Digest::for_bytes(b"qualification"),
            backup_publication_sha256: Sha256Digest::for_bytes(b"backup"),
            source_commit: "a".repeat(40),
            source_tree: "b".repeat(40),
            created_at_unix_ms: now,
            signer_policy_generation: 1,
            signatures: vec![EvidenceRecoveryFrontierSignatureV2 {
                signer_principal_id: "signer:fixture".to_string(),
                signer_key_epoch: 1,
                signature_hex: "11".repeat(64),
            }],
        };
        let digest = evidence_recovery_frontier_v2_sha256(&proposed).unwrap();
        store
            .mark_publication_dispatched(
                &lease,
                &batch.batch_id,
                &digest,
                &proposed.backend_identity_sha256,
                now,
            )
            .await
            .unwrap();
        let ack = EvidenceFrontierDurableAckV1 {
            backend_id: "backend:dispatch".to_string(),
            backend_identity_sha256: proposed.backend_identity_sha256.clone(),
            store_id: proposed.store_id.clone(),
            frontier_generation: 2,
            frontier_sha256: digest,
            audit_sequence: 2,
        };
        Self {
            _temp: temp,
            store,
            trust,
            registry,
            lease,
            batch_id: batch.batch_id,
            proposed,
            ack,
        }
    }
}

#[tokio::test]
async fn unknown_external_result_preserves_the_same_durable_dispatch() {
    let fixture = Fixture::new().await;
    let result = fixture
        .store
        .with_publication_dispatch_guard(
            &fixture.lease,
            &fixture.batch_id,
            &fixture.trust,
            &fixture.proposed,
            |_| {
                Err(EvidenceFrontierBackendError::Indeterminate(
                    "lost acknowledgement".to_string(),
                ))
            },
        )
        .await;
    assert!(matches!(
        result,
        Err(EvidenceFrontierBackendError::Indeterminate(_))
    ));
    let unresolved = fixture
        .store
        .prepare_publication_batch(
            &fixture.lease,
            u64::try_from(now_millis().unwrap()).unwrap(),
            8,
        )
        .await
        .unwrap()
        .unwrap();
    assert_eq!(unresolved.batch_id, fixture.batch_id);
    assert_eq!(
        unresolved.state,
        EvidencePublicationBatchStateV1::Dispatching
    );
    fixture.store.close().await;
}

#[tokio::test]
async fn stale_owner_never_enters_the_external_callback() {
    let fixture = Fixture::new().await;
    let mut stale = fixture.lease.clone();
    stale.owner_generation += 1;
    let calls = Cell::new(0);
    let result = fixture
        .store
        .with_publication_dispatch_guard(
            &stale,
            &fixture.batch_id,
            &fixture.trust,
            &fixture.proposed,
            |_| {
                calls.set(calls.get() + 1);
                Ok(fixture.ack.clone())
            },
        )
        .await;
    assert!(result.is_err());
    assert_eq!(calls.get(), 0);
    fixture.store.close().await;
}

#[tokio::test]
async fn substituted_proposal_never_enters_the_external_callback() {
    let fixture = Fixture::new().await;
    let mut proposed = fixture.proposed.clone();
    proposed.source_commit = "c".repeat(40);
    let calls = Cell::new(0);
    let result = fixture
        .store
        .with_publication_dispatch_guard(
            &fixture.lease,
            &fixture.batch_id,
            &fixture.trust,
            &proposed,
            |_| {
                calls.set(calls.get() + 1);
                Ok(fixture.ack.clone())
            },
        )
        .await;
    assert!(result.is_err());
    assert_eq!(calls.get(), 0);
    fixture.store.close().await;
}

#[tokio::test]
async fn policy_replaced_during_io_cannot_become_a_successful_acknowledgement() {
    let fixture = Fixture::new().await;
    let result = fixture
        .store
        .with_publication_dispatch_guard(
            &fixture.lease,
            &fixture.batch_id,
            &fixture.trust,
            &fixture.proposed,
            |_| {
                std::fs::write(&fixture.registry, b"revoked during IO").unwrap();
                Ok(fixture.ack.clone())
            },
        )
        .await;
    assert!(matches!(
        result,
        Err(EvidenceFrontierBackendError::Indeterminate(_))
    ));
    assert_eq!(
        fixture
            .store
            .publication_batch(&fixture.batch_id)
            .await
            .unwrap()
            .unwrap()
            .state,
        EvidencePublicationBatchStateV1::Dispatching
    );
    fixture.store.close().await;
}

#[tokio::test]
async fn acknowledged_batch_is_recovery_only_never_a_new_publication() {
    let fixture = Fixture::new().await;
    fixture
        .store
        .acknowledge_publication_with_trust(
            &fixture.lease,
            &fixture.batch_id,
            &fixture.trust,
            &fixture.proposed,
            &fixture.ack,
        )
        .await
        .unwrap();
    let ack = fixture
        .store
        .with_publication_dispatch_guard(
            &fixture.lease,
            &fixture.batch_id,
            &fixture.trust,
            &fixture.proposed,
            |mode| {
                assert_eq!(mode, EvidencePublicationDispatchModeV1::RecoverOnly);
                Ok(fixture.ack.clone())
            },
        )
        .await
        .unwrap();
    assert_eq!(ack, fixture.ack);
    fixture.store.close().await;
}

fn second_writer_can_enter(path: PathBuf) -> bool {
    std::thread::spawn(move || {
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap()
            .block_on(async move {
                let options = sqlx::sqlite::SqliteConnectOptions::new()
                    .filename(path)
                    .create_if_missing(false)
                    .journal_mode(sqlx::sqlite::SqliteJournalMode::Wal)
                    .busy_timeout(Duration::ZERO);
                let mut connection = sqlx::SqliteConnection::connect_with(&options)
                    .await
                    .unwrap();
                let acquired = sqlx::query("BEGIN IMMEDIATE")
                    .execute(&mut connection)
                    .await
                    .is_ok();
                if acquired {
                    sqlx::query("ROLLBACK")
                        .execute(&mut connection)
                        .await
                        .unwrap();
                }
                connection.close().await.unwrap();
                acquired
            })
    })
    .join()
    .unwrap()
}

#[tokio::test]
async fn another_connection_cannot_rotate_owner_or_trust_during_external_dispatch() {
    let fixture = Fixture::new().await;
    let path = fixture.store.path().to_path_buf();
    fixture
        .store
        .with_publication_dispatch_guard(
            &fixture.lease,
            &fixture.batch_id,
            &fixture.trust,
            &fixture.proposed,
            |mode| {
                assert_eq!(mode, EvidencePublicationDispatchModeV1::PublishOrRecover);
                assert!(!second_writer_can_enter(path.clone()));
                Ok(fixture.ack.clone())
            },
        )
        .await
        .unwrap();
    assert!(second_writer_can_enter(path));
    fixture.store.close().await;
}

#[tokio::test]
async fn changed_trust_cannot_race_into_local_acknowledgement() {
    let fixture = Fixture::new().await;
    std::fs::write(&fixture.registry, b"policy revoked before acknowledgement").unwrap();
    let result = fixture
        .store
        .acknowledge_publication_with_trust(
            &fixture.lease,
            &fixture.batch_id,
            &fixture.trust,
            &fixture.proposed,
            &fixture.ack,
        )
        .await;
    assert!(result.is_err());
    assert_eq!(
        fixture
            .store
            .publication_batch(&fixture.batch_id)
            .await
            .unwrap()
            .unwrap()
            .state,
        EvidencePublicationBatchStateV1::Dispatching
    );
    assert_eq!(
        fixture
            .store
            .latest_accepted_frontier("store:dispatch")
            .await
            .unwrap()
            .unwrap()
            .frontier_generation,
        1
    );
    fixture.store.close().await;
}

#[tokio::test]
async fn restored_old_file_cannot_override_a_new_durable_trust_generation() {
    let fixture = Fixture::new().await;
    let now = u64::try_from(now_millis().unwrap()).unwrap();
    let frontier = EvidenceAcceptedFrontierV1 {
        store_id: fixture.proposed.store_id.clone(),
        frontier_generation: 2,
        frontier_sha256: Sha256Digest::for_bytes(b"independently accepted next generation"),
        backend_identity_sha256: fixture.proposed.backend_identity_sha256.clone(),
        accepted_at_unix_ms: now,
    };
    let accepted = EvidenceTrustGenerationAcceptanceV1 {
        store_id: frontier.store_id.clone(),
        agent_id: fixture.trust.agent_id().to_string(),
        registry_generation: 2,
        registry_sha256: Sha256Digest::for_bytes(b"next trust registry"),
        predecessor_sha256: Some(fixture.trust.registry_sha256().clone()),
        accepted_frontier_generation: 2,
        accepted_frontier_sha256: frontier.frontier_sha256.clone(),
        backend_identity_sha256: frontier.backend_identity_sha256.clone(),
        accepted_at_unix_ms: now,
    };
    let snapshot = fixture
        .store
        .authenticated_recovery_snapshot()
        .await
        .unwrap();
    fixture
        .store
        .accept_production_generation_at_snapshot(&frontier, &snapshot, &accepted)
        .await
        .unwrap();
    assert!(fixture.trust.validate_store(&fixture.store).is_ok());
    let calls = Cell::new(0);
    let result = fixture
        .store
        .with_publication_dispatch_guard(
            &fixture.lease,
            &fixture.batch_id,
            &fixture.trust,
            &fixture.proposed,
            |_| {
                calls.set(1);
                Ok(fixture.ack.clone())
            },
        )
        .await;
    assert!(result.is_err());
    assert_eq!(calls.get(), 0);
    fixture.store.close().await;
}
