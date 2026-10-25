//! Real journal/recovery boundaries with controlled owner-proof identities.
use super::tests::binding;
use super::*;
use crate::NativeMemoryContextBindingV1;
use crate::native_memory_shadow_namespace::NativeMemoryShadowStartV1;
use crate::native_memory_shadow_namespace::tests::FixtureModel;
use crate::native_memory_shadow_namespace::tests::files;
use crate::native_memory_shadow_namespace::tests::profile;
use crate::native_memory_test_support::fixture;

fn proof(run: &str, version: &[u8]) -> NativeMemoryContextBindingV1 {
    NativeMemoryContextBindingV1::from_checked_owners(
        StableId::new(run).unwrap(),
        Digest32::of_bytes(version),
        Digest32::of_bytes(b"controlled NDU proof"),
        Digest32::of_bytes(b"controlled clock domain"),
    )
    .unwrap()
}

#[tokio::test]
async fn recovery_requires_same_run_and_checked_owner_version() {
    let mut f = fixture().await;
    f.config.output_width = 5;
    let enrolled = proof("run:one", b"version one");
    let subject = StableId::new("subject:proof-fixture").unwrap();
    let objective = Digest32::of_bytes(b"same objective content");
    let context = NativeMemoryJournalContext {
        subject: &subject,
        objective,
        binding: Some(&enrolled),
    };
    let (mut runtime, namespace) = open_runtime(
        files(f.temp.path(), NativeMemoryShadowStartV1::Bootstrap),
        profile(&f.config),
        &f.config,
        f.admission.binding(),
        f.writer.owner_agent_id().as_str(),
        context,
    )
    .unwrap();
    let features = query_features(&f.admission.query().key.question().unwrap()).unwrap();
    runtime
        .tick_shadow(
            &mut FixtureModel(f.config.clone()),
            NeuronTickInputV1 {
                tick_id: f.admission.query().request_id.clone(),
                subject_id: subject.clone(),
                logical_sequence: 1,
                monotonic_time_micros: 1,
                checkpoint_digest: Digest32::ZERO,
                input_feature_digest: canonical_feature_vector_digest_v1(&features),
                feature_vector_q24: features,
                objective_digest: objective,
                ndu_snapshot_digest: Digest32::of_bytes(b"controlled NDU snapshot"),
                body_generation: None,
                modulator_digest: None,
            },
        )
        .unwrap();
    let anchor = runtime.current_anchor().unwrap();
    drop(runtime);
    let journal = std::fs::read(f.temp.path().join("shadow-journal")).unwrap();
    let witness = std::fs::read(f.temp.path().join("shadow-witness")).unwrap();
    for changed in [
        proof("run:two", b"version one"),
        proof("run:one", b"version two"),
    ] {
        assert!(
            open_runtime(
                files(f.temp.path(), NativeMemoryShadowStartV1::Recover),
                profile(&f.config),
                &f.config,
                f.admission.binding(),
                f.writer.owner_agent_id().as_str(),
                NativeMemoryJournalContext {
                    binding: Some(&changed),
                    ..context
                },
            )
            .is_err()
        );
        assert_eq!(
            std::fs::read(f.temp.path().join("shadow-journal")).unwrap(),
            journal
        );
        assert_eq!(
            std::fs::read(f.temp.path().join("shadow-witness")).unwrap(),
            witness
        );
    }
    let (recovered, recovered_namespace) = open_runtime(
        files(f.temp.path(), NativeMemoryShadowStartV1::Recover),
        profile(&f.config),
        &f.config,
        f.admission.binding(),
        f.writer.owner_agent_id().as_str(),
        context,
    )
    .unwrap();
    assert_eq!(recovered_namespace, namespace);
    assert_eq!(recovered.current_anchor().unwrap(), anchor);
}

struct Context {
    current: NativeMemoryTickContextV1,
    proof: NativeMemoryContextBindingV1,
}
impl NativeMemoryContextAuthorityV1 for Context {
    fn current(&mut self) -> Result<NativeMemoryTickContextV1, NativeMemoryError> {
        Ok(self.current.clone())
    }
    fn binding(&self) -> Option<&NativeMemoryContextBindingV1> {
        Some(&self.proof)
    }
}

#[tokio::test]
async fn proof_replacement_refuses_before_source_admission_and_decoder() {
    let mut f = fixture().await;
    f.config.output_width = 5;
    let context = Context {
        current: NativeMemoryTickContextV1 {
            subject_id: StableId::new("subject:proof-fixture").unwrap(),
            objective_digest: Digest32::of_bytes(b"same objective"),
            ndu_snapshot_digest: Digest32::of_bytes(b"same NDU"),
            monotonic_time_micros: 1,
            body_generation: None,
            modulator_digest: None,
        },
        proof: proof("run:one", b"incarnation one"),
    };
    let owner = AgentdNativeMemoryShadowOwner::open(
        binding(&f),
        files(f.temp.path(), NativeMemoryShadowStartV1::Bootstrap),
        profile(&f.config),
        context,
    )
    .await
    .unwrap();
    owner.state.lock().unwrap().context.proof = proof("run:one", b"incarnation two");
    let mut query = f.admission.query().clone();
    query.request_id = StableId::new("request:proof-replaced").unwrap();
    assert!(owner.read(query.clone()).await.is_err());
    assert_eq!(
        owner
            .host
            .dispatches
            .load(std::sync::atomic::Ordering::SeqCst),
        0
    );
    assert!(owner.state.lock().unwrap().failed);
    f.writer
        .admit_memory_cell(&f.access, &query, &f.claim)
        .await
        .unwrap();
}
