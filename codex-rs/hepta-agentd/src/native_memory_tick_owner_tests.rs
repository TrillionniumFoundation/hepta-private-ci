//! Controlled source/journal receipts exercise owner identity, not model quality.
use super::*;
use crate::native_memory_shadow_namespace::NativeMemoryShadowStartV1;
use crate::native_memory_shadow_namespace::tests::FixtureModel;
use crate::native_memory_shadow_namespace::tests::files;
use crate::native_memory_shadow_namespace::tests::profile;
use crate::native_memory_test_support::Fixture;
use crate::native_memory_test_support::execution;
use crate::native_memory_test_support::fixture;
use codex_hepta_memory::ProductionCognitiveMutation;
use std::assert_eq;
use std::sync::atomic::Ordering;

#[derive(Clone)]
struct Context(NativeMemoryTickContextV1);
impl NativeMemoryContextAuthorityV1 for Context {
    fn current(&mut self) -> Result<NativeMemoryTickContextV1, NativeMemoryError> {
        Ok(self.0.clone())
    }
}

pub(super) fn binding(f: &Fixture) -> NativeShadowHostBinding {
    NativeShadowHostBinding {
        writer: Arc::clone(&f.writer),
        access: f.access.clone(),
        key: f.admission.query().key.clone(),
        claim: f.claim.clone(),
        model: f.config.clone(),
        dispatches: Arc::new(AtomicU64::new(0)),
        capacity: Arc::new(Semaphore::new(1)),
        cancellation: tokio_util::sync::CancellationToken::new(),
    }
}

#[tokio::test]
async fn shadow_delivery_is_immutable_owner_bound_and_late_withdrawal_closes_owner() {
    enum Withdrawal {
        Authority,
        SourceTombstone,
    }
    for withdrawal in [Withdrawal::Authority, Withdrawal::SourceTombstone] {
        let mut f = fixture().await;
        f.config.output_width = 5;
        let a = tempfile::tempdir().unwrap();
        let b = tempfile::tempdir().unwrap();
        let context = Context(NativeMemoryTickContextV1 {
            subject_id: StableId::new("subject:delivery-fixture").unwrap(),
            objective_digest: Digest32::of_bytes(b"controlled objective fixture"),
            ndu_snapshot_digest: Digest32::of_bytes(b"controlled NDU fixture"),
            monotonic_time_micros: 1,
            body_generation: None,
            modulator_digest: None,
        });
        let owner_a = AgentdNativeMemoryShadowOwner::open(
            binding(&f),
            files(a.path(), NativeMemoryShadowStartV1::Bootstrap),
            profile(&f.config),
            context.clone(),
        )
        .await
        .unwrap();
        let mut other_profile = profile(&f.config);
        other_profile.cell_id = StableId::new("memory:other-cell").unwrap();
        let owner_b = AgentdNativeMemoryShadowOwner::open(
            binding(&f),
            files(b.path(), NativeMemoryShadowStartV1::Bootstrap),
            other_profile,
            context.clone(),
        )
        .await
        .unwrap();
        let features = query_features(&f.admission.query().key.question().unwrap()).unwrap();
        let input = NeuronTickInputV1 {
            tick_id: f.admission.query().request_id.clone(),
            subject_id: context.0.subject_id,
            logical_sequence: 1,
            monotonic_time_micros: 1,
            checkpoint_digest: Digest32::ZERO,
            input_feature_digest: canonical_feature_vector_digest_v1(&features),
            feature_vector_q24: features,
            objective_digest: context.0.objective_digest,
            ndu_snapshot_digest: context.0.ndu_snapshot_digest,
            body_generation: None,
            modulator_digest: None,
        };
        let observation = owner_a
            .state
            .lock()
            .unwrap()
            .runtime
            .tick_shadow(&mut FixtureModel(f.config.clone()), input.clone())
            .unwrap();
        let execution = execution(&f);
        let source = f
            .writer
            .finish_memory_cell(
                &f.admission,
                Digest32::of_bytes(&serde_json::to_vec(&execution).unwrap()),
            )
            .await
            .unwrap();
        let result = NativeMemoryShadowReadV1 {
            observation,
            execution,
            source,
            namespace: owner_a.namespace,
            admission: Arc::clone(&f.admission),
            input,
            context_binding: owner_a.context_binding.clone(),
        };
        owner_a.revalidate_delivery(&result).await.unwrap();
        assert_eq!(result.execution().text, "fixture-only");
        assert!(result.observation().abstain);
        assert!(!result.observation().authority.grants_any());
        assert_eq!(result.source().binding, *f.admission.binding());
        assert!(owner_b.revalidate_delivery(&result).await.is_err());
        assert!(owner_b.host.cancellation.is_cancelled());
        assert!(owner_b.state.lock().unwrap().failed);
        assert_eq!(owner_a.host.dispatches.load(Ordering::SeqCst), 0);
        assert!(f.writer.revalidate_memory_cell(&f.admission).await.is_err());
        match withdrawal {
            Withdrawal::Authority => f.verifier.0.store(true, Ordering::SeqCst),
            Withdrawal::SourceTombstone => {
                use codex_hepta_memory::CognitiveScope;
                use codex_hepta_memory::ForgetMemoryDraft;
                use codex_hepta_memory::LedgerSourceKind;
                use codex_hepta_memory::SourceDraft;
                let now = std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap()
                    .as_secs() as i64;
                let reason = "late controlled source withdrawal";
                let source = SourceDraft {
                    scope: CognitiveScope::AgentPrivate,
                    kind: LedgerSourceKind::ExplicitMemoryDirective,
                    event_key: "late-shadow-forget".to_string(),
                    content: reason.as_bytes().to_vec(),
                    observed_at_unix_seconds: now,
                };
                f.writer
                    .cognitive_mutation_capability()
                    .unwrap()
                    .forget_with_kg(
                        &f.access,
                        &f.claim.production.write.memory.id.memory_id,
                        /*expected_revision*/ 1,
                        &source,
                        &ForgetMemoryDraft {
                            scope: CognitiveScope::AgentPrivate,
                            reason: reason.to_string(),
                            valid_from_unix_seconds: now,
                            citations: vec![],
                        },
                    )
                    .await
                    .unwrap();
                assert!(!f.verifier.0.load(Ordering::SeqCst));
                assert!(matches!(
                    f.writer.revalidate_memory_cell(&f.admission).await,
                    Err(codex_hepta_memory::MemoryCellSourceError::Replay)
                ));
            }
        }
        let denied = owner_a
            .revalidate_delivery(&result)
            .await
            .expect_err("withdrawn source escaped delivery fence");
        match withdrawal {
            Withdrawal::Authority => assert!(matches!(
                denied,
                NativeMemoryError::Source(codex_hepta_memory::MemoryCellSourceError::Authority(_))
            )),
            Withdrawal::SourceTombstone => assert!(matches!(
                denied,
                NativeMemoryError::Source(codex_hepta_memory::MemoryCellSourceError::Invalid(
                    "current source revision or typed identity"
                ))
            )),
        }
        assert!(owner_a.host.cancellation.is_cancelled());
        assert!(owner_a.state.lock().unwrap().failed);
    }
}
