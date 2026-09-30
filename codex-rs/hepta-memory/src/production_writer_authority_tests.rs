use super::*;
use crate::CognitiveScope;
use crate::LedgerSourceKind;
use crate::MemoryLifecycleState;
use crate::MemoryVerification;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use tempfile::TempDir;

#[tokio::test]
async fn revoked_semantic_authority_rolls_back_remember_correct_and_forget() {
    for mutation in ["remember", "correct", "forget"] {
        for rejected_check in [2, 3] {
            let temp = TempDir::new().unwrap();
            let owner = agent_id(93);
            let store = CognitiveStore::open(&layout(&temp, &owner)).await.unwrap();
            let authority = ProductionAuthorityLease::from_verified_parts(
                owner.clone(),
                Sha256Digest::for_bytes(b"semantic-currentness-grant"),
                /*authority_epoch*/ 9,
                /*owner_epoch*/ 4,
                now_unix_seconds().unwrap() + 3_600,
                ProductionAuthorityToken::from_verified_bytes(
                    b"semantic-currentness-token".to_vec(),
                )
                .unwrap(),
            )
            .unwrap();
            let calls = Arc::new(AtomicUsize::new(0));
            let reject_at = Arc::new(AtomicUsize::new(0));
            let verifier_calls = Arc::clone(&calls);
            let verifier_reject_at = Arc::clone(&reject_at);
            let verifier: Arc<dyn ProductionAuthorityVerifier> =
                Arc::new(move |_: &ProductionAuthorityLease, _: &AgentId| {
                    let current = verifier_calls.fetch_add(1, Ordering::SeqCst) + 1;
                    let rejected = verifier_reject_at.load(Ordering::SeqCst);
                    if rejected != 0 && current >= rejected {
                        Err("semantic authority revoked before commit".to_string())
                    } else {
                        Ok(())
                    }
                });
            let writer = Arc::new(
                ProductionDurableWriter::open_with_live_verifier(
                    store,
                    authority,
                    verifier,
                    "production:semantic-currentness",
                    /*generation*/ 1,
                )
                .await
                .unwrap(),
            );
            let capability = writer.cognitive_mutation_capability().unwrap();
            let access = CognitiveAccess::agent_private(owner);
            let mut source = SourceDraft {
                scope: CognitiveScope::AgentPrivate,
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "semantic-currentness:seed".to_string(),
                content: b"seed memory".to_vec(),
                observed_at_unix_seconds: 100,
            };
            let mut draft = MemoryDraft {
                stable_key: "semantic-currentness-memory".to_string(),
                revision: MemoryRevisionDraft {
                    scope: CognitiveScope::AgentPrivate,
                    content: "seed memory".to_string(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: 100,
                    valid_to_unix_seconds: None,
                    citations: Vec::new(),
                },
            };
            let facts = KgFactSetDraft::default();
            let original = capability
                .remember_with_kg(&access, &source, &draft, &facts)
                .await
                .unwrap();
            let before = writer.recovery_anchor().await.unwrap();
            source.event_key = format!("semantic-currentness:{mutation}");
            source.content = if mutation == "forget" {
                b"explicit_forget".to_vec()
            } else {
                b"changed memory".to_vec()
            };
            source.observed_at_unix_seconds = 200;
            draft.stable_key = "semantic-currentness-second-memory".to_string();
            draft.revision.content = "changed memory".to_string();
            draft.revision.valid_from_unix_seconds = 200;
            calls.store(0, Ordering::SeqCst);
            reject_at.store(rejected_check, Ordering::SeqCst);

            let result = match mutation {
                "remember" => {
                    capability
                        .remember_with_kg(&access, &source, &draft, &facts)
                        .await
                }
                "correct" => {
                    capability
                        .correct_with_kg(
                            &access,
                            &original.write.memory.id.memory_id,
                            /*expected_revision*/ 1,
                            &source,
                            &draft.revision,
                            &facts,
                        )
                        .await
                }
                "forget" => {
                    capability
                        .forget_with_kg(
                            &access,
                            &original.write.memory.id.memory_id,
                            /*expected_revision*/ 1,
                            &source,
                            &ForgetMemoryDraft {
                                scope: CognitiveScope::AgentPrivate,
                                reason: "explicit_forget".to_string(),
                                valid_from_unix_seconds: 200,
                                citations: Vec::new(),
                            },
                        )
                        .await
                }
                _ => unreachable!(),
            };
            assert!(matches!(
                result,
                Err(ProductionCognitiveMutationError::Authority(
                    ProductionWriterError::AuthorityRejected(_)
                ))
            ));
            assert_eq!(calls.load(Ordering::SeqCst), rejected_check);
            assert_eq!(writer.recovery_anchor().await.unwrap(), before);
        }
    }
}
