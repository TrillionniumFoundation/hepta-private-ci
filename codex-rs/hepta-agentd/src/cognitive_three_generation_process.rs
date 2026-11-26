//! Raw host-pinned process installation; every opaque owner proof is rebuilt.
use super::*;
use crate::cognitive_process_materials::*;
use codex_hepta_learning_artifacts as artifacts;

pub(super) fn descriptor(
    root: &std::path::Path,
    published: &publication::Published,
    fitted: &support::Fitted,
    view: &publication::StudyView,
    launch: u64,
    anchor: codex_hepta_intelligence_eval::FinalHoldoutCasAnchorV1,
) -> (PathBuf, Digest32) {
    let config = view.config();
    let trust = &config.trust;
    let signer = |signer: &artifacts::TrustedArtifactSignerV1| {
        json!({
        "signer_id":signer.signer_id.as_str(), "verifying_key_hex":support::hex(&signer.verifying_key),
        "minimum_authority_epoch":signer.minimum_authority_epoch,"maximum_authority_epoch":signer.maximum_authority_epoch,
        "valid_from":signer.valid_from,"expires_at":signer.expires_at,"revoked_at":signer.revoked_at})
    };
    let signed = config.required_current_head.as_ref().unwrap();
    let witness = &signed.witness;
    let mut value: Value = serde_json::from_slice(
        &std::fs::read(root.join("generation-3/evaluation-materials.json")).unwrap(),
    )
    .unwrap();
    let object = value.as_object_mut().unwrap();
    object.remove("evaluation_bundle");
    object.insert(
        "schema".into(),
        json!("hepta.agentd.cognitive-bootstrap.v2"),
    );
    object.insert(
        "profile".into(),
        json!("published_product_qualification_v1"),
    );
    object.insert("agent_id".into(), json!(owner().as_str()));
    object.insert("spawn_generation".into(), json!(launch));
    object.insert("snapshot_path".into(), json!(published.snapshot));
    object.insert("payload_path".into(), json!(published.payload));
    object.insert(
        "selected".into(),
        serde_json::to_value(PinnedCandidateSpecRaw::from(published.selected.clone())).unwrap(),
    );
    object.insert(
        "model_pin".into(),
        serde_json::to_value(TabularPayloadPinV1Raw::from(fitted.pin.clone())).unwrap(),
    );
    object.insert(
        "source_manifest".into(),
        serde_json::to_value(LearningArtifactManifestV2Raw::from(
            published.source.clone(),
        ))
        .unwrap(),
    );
    object.insert("current".into(), json!({"root":config.root,
        "trust":{"registry_id":trust.registry_id.as_str(),"withdrawal_scope_digest":trust.withdrawal_scope_digest.to_string(),
            "minimum_registry_generation":trust.minimum_registry_generation.get(),"genesis_predecessor_head_digest":trust.genesis_predecessor_head_digest.to_string(),
            "minimum_authority_epoch":trust.minimum_authority_epoch,"writer_signers":trust.writer_signers.iter().map(signer).collect::<Vec<_>>(),
            "head_signers":trust.head_signers.iter().map(signer).collect::<Vec<_>>()},
        "required_current_head":{"withdrawal_scope_digest":signed.withdrawal_scope_digest.to_string(),"binding":signed.binding.to_string(),
            "registry_id":witness.registry_id.as_str(),"generation":witness.generation.get(),"head_digest":witness.head_digest.to_string(),
            "predecessor_head_digest":witness.predecessor_head_digest.to_string(),"authority_epoch":witness.authority_epoch,
            "signer_id":witness.signer_id.as_str(),"signing_key_digest":witness.signing_key_digest.to_string(),"issued_at":witness.issued_at,"expires_at":witness.expires_at,
            "signature_hex":support::hex(&signed.signature)}}));
    object.insert(
        "holdout".into(),
        json!({"path":root.join("holdouts"),"binding":hash("three-generation-holdouts").to_string(),
        "fence":crate::cognitive_process_product_wire::HoldoutWriterFenceV1Raw::from(holdout_fence()),
        "anchor":crate::cognitive_process_product_wire::FinalHoldoutCasAnchorV1Raw::from(anchor)}),
    );
    let path = root.join(format!("process-{launch}-bootstrap.json"));
    save(&path, &value);
    let digest = Digest32::of_bytes(&std::fs::read(&path).unwrap());
    (path, digest)
}
