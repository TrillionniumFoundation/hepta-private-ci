use super::*;

use crate::CognitiveScope;
use crate::LedgerSourceKind;
use crate::MemoryLifecycleState;
use crate::MemoryVerification;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tempfile::TempDir;
use tokio::sync::watch;
use tokio::time::timeout;

struct RevocableVerifier {
    revoked: AtomicBool,
    calls: AtomicUsize,
    revoke_on_call: AtomicUsize,
    observed_calls: watch::Sender<usize>,
}

impl ProductionAuthorityVerifier for RevocableVerifier {
    fn verify(
        &self,
        _authority: &ProductionAuthorityLease,
        _expected_agent: &AgentId,
    ) -> Result<(), String> {
        let call = self.calls.fetch_add(1, Ordering::SeqCst) + 1;
        self.observed_calls.send_replace(call);
        if self.revoked.load(Ordering::SeqCst) || call >= self.revoke_on_call.load(Ordering::SeqCst)
        {
            Err("authority revoked during semantic mutation".to_string())
        } else {
            Ok(())
        }
    }
}

#[derive(Clone, Copy)]
enum MutationKind {
    Remember,
    Correct,
    Forget,
}

async fn fixture(
    temp: &TempDir,
) -> (
    Arc<ProductionDurableWriter>,
    ProductionCognitiveMutationCapability,
    Arc<RevocableVerifier>,
    StableMemoryId,
) {
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2db1").unwrap();
    let root = temp.path().join("fleet-authority-recheck");
    std::fs::create_dir(&root).unwrap();
    let fleet = HeptaFleetRoot::parse(root.canonicalize().unwrap()).unwrap();
    let store = CognitiveStore::open(&fleet.layout().agent(&owner))
        .await
        .unwrap();
    let authority = ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(b"independently-verified-mutation-grant"),
        1,
        1,
        now_unix_seconds().unwrap() + 3_600,
        ProductionAuthorityToken::from_verified_bytes(b"opaque-mutation-grant-token".to_vec())
            .unwrap(),
    )
    .unwrap();
    let verifier = Arc::new(RevocableVerifier {
        revoked: AtomicBool::new(false),
        calls: AtomicUsize::new(0),
        revoke_on_call: AtomicUsize::new(usize::MAX),
        observed_calls: watch::channel(0).0,
    });
    let writer = Arc::new(
        ProductionDurableWriter::open_with_live_verifier(
            store,
            authority,
            verifier.clone(),
            "production:semantic-authority-recheck",
            1,
        )
        .await
        .unwrap(),
    );
    let capability = writer.cognitive_mutation_capability().unwrap();
    let access = CognitiveAccess::agent_private(owner);
    let seed = capability
        .remember_with_kg(
            &access,
            &source("seed", "Original memory."),
            &MemoryDraft {
                stable_key: "existing-memory".to_string(),
                revision: revision("Original memory."),
            },
            &KgFactSetDraft::default(),
        )
        .await
        .unwrap();
    (writer, capability, verifier, seed.write.memory.id.memory_id)
}

fn source(event_key: &str, content: &str) -> SourceDraft {
    SourceDraft {
        scope: CognitiveScope::AgentPrivate,
        kind: LedgerSourceKind::ExplicitMemoryDirective,
        event_key: event_key.to_string(),
        content: content.as_bytes().to_vec(),
        observed_at_unix_seconds: 1_900_000_000,
    }
}

fn revision(content: &str) -> MemoryRevisionDraft {
    MemoryRevisionDraft {
        scope: CognitiveScope::AgentPrivate,
        content: content.to_string(),
        verification: MemoryVerification::Verified,
        lifecycle: MemoryLifecycleState::Active,
        valid_from_unix_seconds: 1_900_000_000,
        valid_to_unix_seconds: None,
        citations: Vec::new(),
    }
}

async fn mutate(
    capability: &ProductionCognitiveMutationCapability,
    memory_id: &StableMemoryId,
    kind: MutationKind,
) -> Result<ProductionCognitiveMutationReceiptV1, ProductionCognitiveMutationError> {
    let access = CognitiveAccess::agent_private(capability.owner_agent_id().clone());
    let source = source("mutation", "Requested mutation.");
    let facts = KgFactSetDraft::default();
    match kind {
        MutationKind::Remember => {
            capability
                .remember_with_kg(
                    &access,
                    &source,
                    &MemoryDraft {
                        stable_key: "new-memory".to_string(),
                        revision: revision("Requested mutation."),
                    },
                    &facts,
                )
                .await
        }
        MutationKind::Correct => {
            capability
                .correct_with_kg(
                    &access,
                    memory_id,
                    1,
                    &source,
                    &revision("Requested mutation."),
                    &facts,
                )
                .await
        }
        MutationKind::Forget => {
            capability
                .forget_with_kg(
                    &access,
                    memory_id,
                    1,
                    &source,
                    &ForgetMemoryDraft {
                        scope: CognitiveScope::AgentPrivate,
                        reason: "Requested mutation.".to_string(),
                        valid_from_unix_seconds: 1_900_000_000,
                        citations: Vec::new(),
                    },
                )
                .await
        }
    }
}

#[tokio::test]
async fn revocation_while_waiting_for_write_lock_blocks_all_semantic_mutations() {
    for kind in [
        MutationKind::Remember,
        MutationKind::Correct,
        MutationKind::Forget,
    ] {
        let temp = TempDir::new().unwrap();
        let (writer, capability, verifier, memory_id) = fixture(&temp).await;
        let before = writer.recovery_anchor().await.unwrap();
        let blocking_transaction = writer
            .store()
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .unwrap();
        let mut observed_calls = verifier.observed_calls.subscribe();
        let completed_checks = *observed_calls.borrow();
        let mutation = tokio::spawn(async move { mutate(&capability, &memory_id, kind).await });

        timeout(
            Duration::from_secs(5),
            observed_calls.wait_for(|calls| *calls > completed_checks),
        )
        .await
        .expect("mutation must reach its preflight authority check")
        .unwrap();
        verifier.revoked.store(true, Ordering::SeqCst);
        blocking_transaction.rollback().await.unwrap();

        let result = mutation.await.unwrap();
        assert!(matches!(
            result,
            Err(ProductionCognitiveMutationError::Authority(
                ProductionWriterError::AuthorityRejected(_)
            ))
        ));
        assert_eq!(writer.recovery_anchor().await.unwrap(), before);
    }
}

#[tokio::test]
async fn revocation_before_commit_rolls_back_semantics_and_provenance_together() {
    // Check both the complete semantic/provenance state and the later cut
    // after awaited full-schema and owner-budget admission. Rejecting only
    // at the earlier cut would miss revocation during admission itself.
    for revoke_on_call in [3, 4] {
        for kind in [
            MutationKind::Remember,
            MutationKind::Correct,
            MutationKind::Forget,
        ] {
            let temp = TempDir::new().unwrap();
            let (writer, capability, verifier, memory_id) = fixture(&temp).await;
            let before = writer.recovery_anchor().await.unwrap();
            verifier.revoke_on_call.store(
                verifier.calls.load(Ordering::SeqCst) + revoke_on_call,
                Ordering::SeqCst,
            );
            let result = mutate(&capability, &memory_id, kind).await;
            assert!(matches!(
                result,
                Err(ProductionCognitiveMutationError::Authority(
                    ProductionWriterError::AuthorityRejected(_)
                ))
            ));
            assert_eq!(writer.recovery_anchor().await.unwrap(), before);
        }
    }
}
