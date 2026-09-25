use super::tests::AllowVerifier;
use super::tests::authority;
use super::tests::store;
use super::*;
use crate::CognitiveScope;
use crate::LedgerSourceKind;
use crate::MemoryLifecycleState;
use crate::MemoryVerification;
use tempfile::TempDir;

fn request() -> (SourceDraft, MemoryDraft, KgFactSetDraft) {
    let now = i64::try_from(now_unix_seconds().unwrap()).unwrap();
    let content = "one immutable memory, one operation result";
    (
        SourceDraft {
            scope: CognitiveScope::AgentPrivate,
            kind: LedgerSourceKind::ExplicitMemoryDirective,
            event_key: "result-port-source".into(),
            content: content.as_bytes().to_vec(),
            observed_at_unix_seconds: now,
        },
        MemoryDraft {
            stable_key: "result-port-memory".into(),
            revision: MemoryRevisionDraft {
                scope: CognitiveScope::AgentPrivate,
                content: content.into(),
                verification: MemoryVerification::Verified,
                lifecycle: MemoryLifecycleState::Active,
                valid_from_unix_seconds: now,
                valid_to_unix_seconds: None,
                citations: Vec::new(),
            },
        },
        KgFactSetDraft::default(),
    )
}

#[tokio::test]
async fn terminal_result_survives_release_and_successor_writer() {
    let temp = TempDir::new().unwrap();
    let store = store(&temp).await;
    let owner = store.owner_agent_id().clone();
    let auth = authority(owner.clone());
    let writer = Arc::new(
        ProductionDurableWriter::open_with_live_verifier(
            store.clone(),
            auth.clone(),
            Arc::new(AllowVerifier),
            "production:result-port",
            1,
        )
        .await
        .unwrap(),
    );
    let access = CognitiveAccess::agent_private(owner);
    let (source, draft, facts) = request();
    let capability = writer.cognitive_mutation_capability().unwrap();
    let receipt = capability
        .remember_with_kg(&access, &source, &draft, &facts)
        .await
        .unwrap();
    let expected = writer
        .cognitive_mutation_result(&receipt.operation_digest)
        .await
        .unwrap()
        .unwrap();
    expected.validate().unwrap();
    writer.release().await.unwrap();
    let after_release = writer
        .cognitive_mutation_result(&receipt.operation_digest)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(expected, after_release);
    assert!(
        writer
            .cognitive_mutation_result(&Sha256Digest::for_bytes(b"absent"))
            .await
            .unwrap()
            .is_none()
    );
    drop(capability);
    drop(writer);
    // Retired fencing material must not authorize a new generation. Keep the
    // negative assertion and use a genuinely fresh verified grant for takeover.
    let reused = ProductionDurableWriter::open_with_live_verifier(
        store.clone(),
        auth.clone(),
        Arc::new(AllowVerifier),
        "production:result-port",
        2,
    )
    .await;
    assert!(matches!(
        reused,
        Err(ProductionWriterError::Local(
            LocalLeaseOutboxError::CasConflict(_)
        ))
    ));
    let successor_authority = ProductionAuthorityLease::from_verified_parts(
        auth.agent_id,
        Sha256Digest::for_bytes(b"signed-successor-grant"),
        auth.authority_epoch + 1,
        auth.owner_epoch + 1,
        auth.lease_expires_at_unix_seconds,
        ProductionAuthorityToken::from_verified_bytes(b"successor-supervisor-token".to_vec())
            .unwrap(),
    )
    .unwrap();
    let successor = ProductionDurableWriter::open_with_live_verifier(
        store,
        successor_authority,
        Arc::new(AllowVerifier),
        "production:result-port",
        2,
    )
    .await
    .unwrap();
    let recovered = successor
        .cognitive_mutation_result(&receipt.operation_digest)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(expected, recovered);
}

#[tokio::test]
async fn concurrent_identical_mutations_observe_one_committed_operation() {
    let temp = TempDir::new().unwrap();
    let store = store(&temp).await;
    let owner = store.owner_agent_id().clone();
    let access = CognitiveAccess::agent_private(owner.clone());
    let writer = Arc::new(
        ProductionDurableWriter::open_with_live_verifier(
            store.clone(),
            authority(owner),
            Arc::new(AllowVerifier),
            "production:concurrent-result",
            1,
        )
        .await
        .unwrap(),
    );
    let capability = writer.cognitive_mutation_capability().unwrap();
    let (source, draft, facts) = request();
    let (first, second) = tokio::join!(
        capability.remember_with_kg(&access, &source, &draft, &facts),
        capability.remember_with_kg(&access, &source, &draft, &facts),
    );
    let (receipt, observed) = match (first, second) {
        (Ok(receipt), Err(ProductionCognitiveMutationError::ObservedResult(result)))
        | (Err(ProductionCognitiveMutationError::ObservedResult(result)), Ok(receipt)) => {
            (receipt, *result)
        }
        other => panic!("one success and one existing result required: {other:?}"),
    };
    assert_eq!(observed.operation_digest, receipt.operation_digest);
    assert_eq!(
        observed.state,
        ProductionCognitiveMutationResultStateV1::Committed
    );
    let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM memory_revisions")
        .fetch_one(&store.pool)
        .await
        .unwrap();
    assert_eq!(count, 1);
    let foreign = CognitiveAccess::agent_private(
        AgentId::parse("00000000-0000-4000-8000-00000000c0ff").unwrap(),
    );
    assert!(matches!(
        capability
            .remember_with_kg(&foreign, &source, &draft, &facts)
            .await,
        Err(ProductionCognitiveMutationError::Store(
            CognitiveStoreError::AccessDenied(_)
        ))
    ));
    let queried = writer
        .cognitive_mutation_result(&receipt.operation_digest)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(queried, observed);
    let mut tampered = observed.clone();
    tampered.state = ProductionCognitiveMutationResultStateV1::Queued;
    tampered.result_sha256 = tampered.compute_result_sha256();
    assert!(tampered.validate().is_err());
    let mut tampered = observed;
    tampered.mutation_kind = "forget".into();
    tampered.result_sha256 = tampered.compute_result_sha256();
    assert!(tampered.validate().is_err());
}

#[tokio::test]
async fn point_in_time_only_verifier_cannot_leave_a_durable_lease_behind() {
    let temp = TempDir::new().unwrap();
    let store = store(&temp).await;
    let before = store.recovery_anchor().await.unwrap();
    let point_check = |_authority: &ProductionAuthorityLease, _owner: &AgentId| Ok(());
    let result = ProductionDurableWriter::open_with_live_verifier(
        store.clone(),
        authority(store.owner_agent_id().clone()),
        Arc::new(point_check),
        "production:guard-required-before-lease",
        1,
    )
    .await;
    assert!(matches!(
        result,
        Err(ProductionWriterError::AuthorityRejected(_))
    ));
    assert_eq!(store.recovery_anchor().await.unwrap(), before);
    let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_local_leases")
        .fetch_one(&store.pool)
        .await
        .unwrap();
    assert_eq!(count, 0);
}
