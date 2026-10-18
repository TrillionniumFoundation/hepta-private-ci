use super::*;
use crate::CognitiveScope;
use crate::MemoryLifecycleState;
use crate::MemoryVerification;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::task::Poll;
use tempfile::TempDir;

struct CurrentMutationVerifier {
    revoked: AtomicBool,
    calls: AtomicUsize,
}

impl ProductionAuthorityVerifier for CurrentMutationVerifier {
    fn verify(
        &self,
        authority: &ProductionAuthorityLease,
        expected_agent: &AgentId,
    ) -> Result<(), String> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        if authority.agent_id != *expected_agent || self.revoked.load(Ordering::SeqCst) {
            return Err("semantic authority withdrawn during SQL wait".to_string());
        }
        Ok(())
    }
}

#[tokio::test]
async fn semantic_revocation_during_sql_wait_rolls_back_every_mutation() {
    for kind in [
        "remember",
        "correct",
        "remember_assertions",
        "correct_assertions",
        "forget",
    ] {
        let temp = TempDir::new().expect("temp");
        let owner = agent_id(93);
        let store = CognitiveStore::open(&layout(&temp, &owner))
            .await
            .expect("store");
        let authority = ProductionAuthorityLease::from_verified_parts(
            owner.clone(),
            Sha256Digest::for_bytes(b"semantic-current-grant"),
            7,
            11,
            now_unix_seconds().expect("clock") + 3_600,
            ProductionAuthorityToken::from_verified_bytes(b"semantic-current-token".to_vec())
                .expect("token"),
        )
        .expect("authority");
        let verifier = Arc::new(CurrentMutationVerifier {
            revoked: AtomicBool::new(false),
            calls: AtomicUsize::new(0),
        });
        let writer = Arc::new(
            ProductionDurableWriter::open_with_live_verifier(
                store.clone(),
                authority,
                verifier.clone(),
                "lease:semantic-final-use",
                1,
            )
            .await
            .expect("writer"),
        );
        let capability = writer.cognitive_mutation_capability().expect("capability");
        let access = CognitiveAccess::agent_private(owner);
        let now = i64::try_from(now_unix_seconds().expect("clock")).expect("clock fits");
        let revision = |content: &str| MemoryRevisionDraft {
            scope: CognitiveScope::AgentPrivate,
            content: content.to_string(),
            verification: MemoryVerification::Verified,
            lifecycle: MemoryLifecycleState::Active,
            valid_from_unix_seconds: now,
            valid_to_unix_seconds: None,
            citations: Vec::new(),
        };
        let source = |key: &str, content: &str| SourceDraft {
            scope: CognitiveScope::AgentPrivate,
            kind: crate::LedgerSourceKind::ExplicitMemoryDirective,
            event_key: key.to_string(),
            content: content.as_bytes().to_vec(),
            observed_at_unix_seconds: now,
        };
        let facts = KgFactSetDraft::default();
        let seeded = capability
            .remember_with_kg(
                &access,
                &source("seed", "Original committed memory."),
                &MemoryDraft {
                    stable_key: "seed".to_string(),
                    revision: revision("Original committed memory."),
                },
                &facts,
            )
            .await
            .expect("original semantic cut");
        let before = store.recovery_anchor().await.expect("original exact cut");
        let before_counts = writer
            .lease
            .snapshot_counts()
            .await
            .expect("original outbox counts");
        let memory_id = &seeded.write.memory.id.memory_id;
        let draft = MemoryDraft {
            stable_key: "next".to_string(),
            revision: revision("Candidate semantic mutation."),
        };
        let change_source = source("next", "Candidate semantic mutation.");
        let forget = ForgetMemoryDraft {
            scope: CognitiveScope::AgentPrivate,
            reason: "Candidate semantic mutation.".to_string(),
            valid_from_unix_seconds: now,
            citations: Vec::new(),
        };
        let mut mutation = match kind {
            "remember" => capability.remember_with_kg(&access, &change_source, &draft, &facts),
            "correct" => capability.correct_with_kg(
                &access,
                memory_id,
                1,
                &change_source,
                &draft.revision,
                &facts,
            ),
            "remember_assertions" => {
                capability.remember_with_assertions(&access, &change_source, &draft, &facts, &[])
            }
            "correct_assertions" => capability.correct_with_assertions(
                &access,
                memory_id,
                1,
                &change_source,
                &draft.revision,
                &facts,
                &[],
            ),
            "forget" => capability.forget_with_kg(&access, memory_id, 1, &change_source, &forget),
            _ => unreachable!(),
        };
        let initial_calls = verifier.calls.load(Ordering::SeqCst);
        // Suspend the actual owner future after its live verification enters
        // SQLite. No fake backend, production test hook or clock substitution.
        std::future::poll_fn(|cx| match mutation.as_mut().poll(cx) {
            Poll::Pending => Poll::Ready(()),
            Poll::Ready(_) => panic!("semantic {kind} did not await SQL"),
        })
        .await;
        assert_eq!(verifier.calls.load(Ordering::SeqCst), initial_calls + 1);
        verifier.revoked.store(true, Ordering::SeqCst);
        let result = mutation.await;
        assert!(
            matches!(
                &result,
                Err(ProductionCognitiveMutationError::Authority(ProductionWriterError::AuthorityRejected(message)))
                    if message == "semantic authority withdrawn during SQL wait"
            ),
            "semantic {kind} must reject revoked authority before commit: {result:?}"
        );
        assert_eq!(
            store.recovery_anchor().await.expect("preserved exact cut"),
            before
        );
        assert_eq!(
            writer
                .lease
                .snapshot_counts()
                .await
                .expect("preserved outbox counts"),
            before_counts
        );
    }
}
