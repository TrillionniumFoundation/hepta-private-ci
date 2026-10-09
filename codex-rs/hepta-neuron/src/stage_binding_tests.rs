use super::*;

fn d(text: &str) -> Digest32 {
    Digest32::of_bytes(text.as_bytes())
}

fn binding() -> NeuronStageBindingV1 {
    NeuronStageBindingV1 {
        run_id: StableId::new("run:1").expect("id"),
        subject_id: StableId::new("subject:1").expect("id"),
        owner_id: StableId::new("neuron:1").expect("id"),
        objective_digest: d("objective"),
        scope_digest: d("scope"),
        generation: Generation::new(3).expect("generation"),
        authority_epoch: 7,
        fence_digest: d("fence"),
        revocation_frontier_digest: d("revocation"),
        model_artifact_digest: d("model"),
        ndu_snapshot_ref_digest: d("ndu-ref"),
        context_snapshot_ref_digest: d("context-ref"),
        feature_vector_digest: d("features"),
        predecessor_checkpoint_digest: d("checkpoint"),
        idempotency_digest: d("nonce"),
        deadline_ms: 100,
    }
}

#[test]
fn stage_ref_binds_fence_epoch_and_immutable_payloads() {
    let base = binding();
    let digest = base.binding_digest().expect("valid binding");
    let mut altered = base.clone();
    altered.fence_digest = d("next-fence");
    assert_ne!(altered.binding_digest().expect("binding"), digest);
    altered = base.clone();
    altered.ndu_snapshot_ref_digest = d("other-ndu");
    assert_ne!(altered.binding_digest().expect("binding"), digest);
    altered = base.clone();
    altered.feature_vector_digest = d("other-features");
    assert_ne!(altered.binding_digest().expect("binding"), digest);
    altered = base.clone();
    altered.generation = Generation::new(4).expect("generation");
    assert_ne!(altered.binding_digest().expect("binding"), digest);
    altered = base.clone();
    altered.authority_epoch += 1;
    assert_ne!(altered.binding_digest().expect("binding"), digest);
}

#[test]
fn stage_ref_requires_revalidated_source_evidence() {
    let mut input = binding();
    input.revocation_frontier_digest = Digest32::ZERO;
    assert_eq!(input.validate(), Err(NeuronStageBindingErrorV1::MissingDigest));
    input = binding();
    input.authority_epoch = 0;
    assert_eq!(input.validate(), Err(NeuronStageBindingErrorV1::MissingAuthorityEpoch));
    input = binding();
    input.deadline_ms = 0;
    assert_eq!(input.validate(), Err(NeuronStageBindingErrorV1::InvalidDeadline));
}
