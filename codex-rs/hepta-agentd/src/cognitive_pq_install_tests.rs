//! Complete native PQ installation through the ordinary process descriptor,
//! original CURRENT/selector and cognitive read. The tiny tabular observations
//! and authority fixture prove composition only, not measured learning quality.
use super::*;
use crate::cognitive_process_evidence::SignedLearningEvidenceV1Raw;
use crate::cognitive_process_wire::LearningKey;
use crate::cognitive_process_wire::LearningSignature;
use codex_hepta_intelligence_eval as eval;
use codex_hepta_learning_ledger as ledger;
use std::path::Path;
use std::sync::atomic::Ordering;

#[path = "cognitive_pq_install_support.rs"]
mod fixture;
#[path = "cognitive_pq_install_materials.rs"]
mod materials;

const PQ: LearningAuthenticationProfile = LearningAuthenticationProfile::MlDsa65V2;

fn pinned(root: &Path, name: &str, value: &Value) -> (PathBuf, Digest32) {
    let path = root.join(name);
    save(&path, value);
    let digest = Digest32::of_bytes(&std::fs::read(&path).unwrap());
    (path, digest)
}

fn install(
    host: &Host,
    path: &Path,
    digest: Digest32,
) -> Result<crate::AgentdConfig, crate::AgentdError> {
    let config = host.config();
    let input = crate::load_cognitive_process_bootstrap_v1(path, digest, config.identity())?;
    assert_eq!(input.verifier.authentication_profile(), PQ);
    assert_eq!(input.ledger_snapshot.authentication_profile(), PQ);
    assert_eq!(
        input.current.current().unwrap().authentication_profile(),
        PQ
    );
    config.with_evaluated_cognitive_bootstrap(input)
}

#[tokio::test]
async fn native_pq_history_product_current_selector_install_replay_and_live_floor() {
    let temporary = tempfile::tempdir().unwrap();
    let root = temporary.path().canonicalize().unwrap();
    let host = Host::new(&root).await;
    let actions = host.seed().await;
    let mut roles = fixture::Roles::new(PQ);
    let service = fixture::Service::start(&root.join("independent-authority"), &roles);
    let directory = root.join("generation-3");
    let parent_directory = root.join("generation-0");
    std::fs::create_dir(&directory).unwrap();
    std::fs::create_dir(&parent_directory).unwrap();
    let [parent, candidate] = materials::fitted(&directory, &roles, &service, &actions);
    let view = publication::StudyView::new(root.join("artifact-owner"), &mut roles);
    let previous = view.publish(
        &parent_directory,
        &parent,
        /*predecessor*/ None,
        &mut roles,
    );
    let published = view.publish(
        &directory,
        &candidate,
        Some(&previous.selected.manifest),
        &mut roles,
    );
    let anchor = materials::qualify(&directory, &candidate, &previous.selected.manifest, &roles);
    let (classic_path, _) =
        process::descriptor(&root, &published, &candidate, &view, host.launch, anchor);
    let mut value: Value = serde_json::from_slice(&std::fs::read(classic_path).unwrap()).unwrap();
    value["schema"] = json!("hepta.agentd.cognitive-bootstrap.pq.v4");
    value["profile"] = json!("published_product_qualification_pq_v2");
    value["authentication_profile"] = json!(PQ);
    value["current"]["authentication_profile"] = json!(PQ);
    let signed = &roles.distribution;
    let endpoint = json!({
        "socket_path": service.config.socket_path,
        "peer_uid": service.config.peer_uid,
        "service_id": service.config.service_id,
        "key_generation": service.config.key_generation,
        "public_key_id": service.config.public_key_id,
        "public_key_spki": service.config.public_key_spki,
        "timeout_ms": service.config.timeout_ms,
    });
    value["pq_learning_activation"] = json!({
        "root_id":roles.root.root_id.as_str(),"root_scope_digest":roles.root.scope_digest.to_string(),"root_verifying_key":LearningKey::from(roles.root.verifying_key.clone()),
        "root_valid_from":roles.root.valid_from,"root_expires_at":roles.root.expires_at,"root_revoked_at":null,
        "distribution_id":signed.distribution.distribution_id.as_str(),"generation":signed.distribution.generation,"effective_at":signed.distribution.effective_at,
        "issued_at":signed.issued_at,"expires_at":signed.expires_at,"signature":LearningSignature::from(signed.signature.clone()),"clock":endpoint,"frontier":endpoint});
    // Set the fixture service beyond completed publication, then hold it fixed.
    // Test duration cannot make the original CURRENT witness appear future-issued.
    service
        .clock
        .fetch_max(support::micros() / 1_000 + 1_000, Ordering::SeqCst);
    let (path, digest) = pinned(&root, "pq-bootstrap.json", &value);
    let history = directory.join("training-owner/ledger");
    let before = [
        std::fs::read(&history).unwrap(),
        std::fs::read(root.join("holdouts")).unwrap(),
    ];
    let mut live = None;
    for _ in 0..2 {
        let configured = install(&host, &path, digest).unwrap();
        let ranker = configured.cognitive_ranker().unwrap();
        assert_eq!(ranker.policy_digest, candidate.pin.payload_digest);
        let RankerEvaluationAdmission::Selected(selection) = &ranker.admission else {
            panic!("original selector must issue admission")
        };
        assert_eq!(selection.authentication_profile(), PQ);
        let (_, _, writer_lock) = configured.into_parts();
        let result = crate::cognitive_context::read(
            &host.store,
            &owner(),
            host.launch,
            "bootstrap",
            /*limit*/ 1,
            Some(&ranker),
        )
        .await
        .unwrap();
        assert_eq!(result.items[0].memory_id, actions[0].0.memory_id);
        drop(writer_lock);
        live = Some(ranker);
        assert_eq!(
            [
                std::fs::read(&history).unwrap(),
                std::fs::read(root.join("holdouts")).unwrap()
            ],
            before,
            "exact product replay must not append history or consume the holdout again"
        );
    }
    // A real classic signature over its own classic domain cannot borrow the
    // PQ selector identity, even after the exact material has been installed.
    let mut selector: ledger::SignedLearningEvidenceV1 =
        serde_json::from_value::<SignedLearningEvidenceV1Raw>(value["selector_evidence"].clone())
            .unwrap()
            .into();
    let classic =
        fixture::TestKey::new(LearningAuthenticationProfile::ClassicalV1, /*seed*/ 74);
    selector.signature = classic.placeholder();
    selector.signature = classic.sign(&selector.signing_bytes());
    classic
        .key()
        .verify(&selector.signing_bytes(), &selector.signature)
        .unwrap();
    let mut changed = value.clone();
    changed["selector_evidence"] = json!(SignedLearningEvidenceV1Raw::from(selector));
    let (bad_path, bad_digest) = pinned(&root, "classic-selector.json", &changed);
    assert!(install(&host, &bad_path, bad_digest).is_err());
    // The protected clock reads this exact bound: PQ expiry is half-open.
    let mut expired: ledger::SignedLearningEvidenceV1 =
        serde_json::from_value::<SignedLearningEvidenceV1Raw>(value["selector_evidence"].clone())
            .unwrap()
            .into();
    expired.expires_at = service.clock.load(Ordering::SeqCst) * 1_000;
    expired.signature = roles.keys[3].sign(&expired.signing_bytes());
    roles.keys[3]
        .key()
        .verify(&expired.signing_bytes(), &expired.signature)
        .unwrap();
    changed = value.clone();
    changed["selector_evidence"] = json!(SignedLearningEvidenceV1Raw::from(expired));
    let (bad_path, bad_digest) = pinned(&root, "expired-selector.json", &changed);
    assert!(install(&host, &bad_path, bad_digest).is_err());
    changed = value;
    changed["current"]["authentication_profile"] =
        json!(LearningAuthenticationProfile::ClassicalV1);
    let (bad_path, bad_digest) = pinned(&root, "classic-current.json", &changed);
    assert!(install(&host, &bad_path, bad_digest).is_err());
    assert_eq!(
        [
            std::fs::read(&history).unwrap(),
            std::fs::read(root.join("holdouts")).unwrap()
        ],
        before
    );
    {
        let mut current = service.frontier.lock().unwrap();
        current.generation += 1;
        current.distribution_digest = *hash("withdrawn-test-distribution").as_array();
    }
    let ranker = live.unwrap();
    assert!(
        crate::cognitive_context::read(
            &host.store,
            &owner(),
            host.launch,
            "bootstrap",
            /*limit*/ 1,
            Some(&ranker)
        )
        .await
        .is_err(),
        "a warm native ranker must revalidate the independent activation floor"
    );
    assert!(
        install(&host, &path, digest).is_err(),
        "cold installation must reject the withdrawn distribution before loading history"
    );
}
