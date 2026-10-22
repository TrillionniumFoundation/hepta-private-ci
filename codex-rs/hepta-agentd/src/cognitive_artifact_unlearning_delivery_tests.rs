use super::*;
use crate::CognitiveArtifactUnlearningOwnerV1;
use crate::CognitiveArtifactUnlearningRequestV1;

fn pins(config: &art::LearningArtifactOwnerServiceConfigV1) -> CognitiveArtifactUnlearningOwnerV1 {
    let trust = activated_trust();
    CognitiveArtifactUnlearningOwnerV1 {
        ledger_binding: digest("agentd-retrieval-learning"),
        learning_root_digest: trust.root_digest(),
        learning_distribution_digest: trust.distribution_digest(),
        artifact_trust_digest: art::ArtifactOwnerVerifierV1::new(config.trust.clone())
            .unwrap()
            .trust_digest(),
        artifact_storage_binding: config.storage_binding,
    }
}

fn request(f: &Case) -> CognitiveArtifactUnlearningRequestV1 {
    CognitiveArtifactUnlearningRequestV1 {
        lineage: f.lineage.clone(),
        dataset: f.dataset.clone(),
        evidence: f.evidence.clone(),
        source_manifest: f.source.clone(),
        revocation: f.revoke.clone(),
        learning_now: 50,
    }
}

#[test]
fn confirmed_bridge_delivers_once_reopens_both_owners_and_expiry_does_not_resurrect() {
    let mut f = case();
    let owner = pins(&f.config);
    f.sink = f.sink.with_artifact_unlearning_owner(owner).unwrap();
    let input = request(&f);
    let first = f
        .sink
        .revoke_artifact_from_unlearning(&mut f.service, input.clone())
        .unwrap();
    assert_eq!(
        f.sink
            .revoke_artifact_from_unlearning(&mut f.service, input.clone())
            .unwrap(),
        first
    );
    assert_eq!(
        f.cached.with_current(
            f.reader.current_registry_view(/*now*/ 20).unwrap(),
            /*now*/ 20,
            |_| ()
        ),
        Err(art::PinnedCandidateLoadError::Ineligible)
    );
    let frontier = f.sink.writer.lock().unwrap().witness_frontier().unwrap();
    drop(f.sink);
    let open = |name| {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(f.temp.path().join(name))
            .unwrap()
    };
    let ledger = DurableLedger::recover(
        open("learning.ledger"),
        owner.ledger_binding,
        /*max_records*/ 128,
        led::LedgerRecovery::Acknowledged(frontier.anchor),
    )
    .unwrap();
    let witness =
        LedgerWitnessStore::recover(open("learning.witness"), owner.ledger_binding).unwrap();
    let directory = File::open(f.temp.path()).unwrap();
    let writer =
        LedgerWriter::from_durable(ledger, witness, activated_trust(), &directory, &directory)
            .unwrap();
    let sink = CognitiveRetrievalLearningSink::new(writer)
        .with_artifact_unlearning_owner(owner)
        .unwrap();
    f.config.required_current_head = Some(f.revoke.signed_current_head.clone());
    drop(f.service);
    // Deterministic durable-prefix fault: restore the real WitnessDurable cut
    // without its final ACK. This is a disk-prefix simulation, not a claim of
    // measured power-loss durability or an injected production success.
    let operation_digest = Digest32::of_bytes(f.lineage.record_id.as_str().as_bytes());
    fs::remove_file(
        f.config
            .root
            .join("transactions")
            .join(format!("{operation_digest}-4.checkpoint")),
    )
    .unwrap();
    let mut service = art::LearningArtifactOwnerService::open(f.config.clone()).unwrap();
    assert_eq!(service.recovery_required(), Some(&f.lineage.record_id));
    assert!(f.reader.current_registry_view(/*now*/ 20).is_err());
    assert_eq!(
        sink.revoke_artifact_from_unlearning(&mut service, input.clone())
            .unwrap(),
        first
    );
    let mut expired = input;
    expired.learning_now = 91;
    expired.revocation.now = 91;
    assert!(
        sink.revoke_artifact_from_unlearning(&mut service, expired.clone())
            .is_err()
    );
    // Source expiry blocks new bridge delivery; the original acknowledged
    // artifact operation remains readable through its own owner and authority.
    assert_eq!(service.revoke(expired.revocation).unwrap(), first);
    let reader = art::ArtifactOwnerCurrentReaderV1::open(
        &f.config.root,
        f.config.trust.clone(),
        f.revoke.signed_current_head.clone(),
    )
    .unwrap();
    assert_eq!(
        reader
            .current_registry_view(/*now*/ 91)
            .unwrap()
            .receipt()
            .head_digest,
        first.registry_head_digest
    );
    assert!(!service.registry().is_eligible(&f.source.artifact_id));
    assert_eq!(service.registry().records().len(), 2);
    drop(service);
    fs::remove_dir_all(&f.config.root).unwrap();
    fs::rename(f.temp.path().join("before-revoke"), &f.config.root).unwrap();
    let reader = art::ArtifactOwnerCurrentReaderV1::open(
        &f.config.root,
        f.config.trust,
        f.revoke.signed_current_head,
    )
    .unwrap();
    assert!(matches!(
        reader.current_registry_view(/*now*/ 91),
        Err(art::ArtifactOwnerHostError::CurrentHeadRollback)
    ));
}

#[test]
fn confirmed_bridge_is_default_off_and_rejects_valid_wrong_dataset_or_target_owner() {
    let mut f = case();
    let input = request(&f);
    assert!(matches!(
        f.sink
            .revoke_artifact_from_unlearning(&mut f.service, input),
        Err(crate::CognitiveArtifactUnlearningError::Unconfigured)
    ));
    f.sink = f
        .sink
        .with_artifact_unlearning_owner(pins(&f.config))
        .unwrap();
    for profile in [
        Target::OtherDataset,
        Target::OtherBinding,
        Target::OtherTrust,
    ] {
        let mut other = case_with(profile);
        let before = other.service.registry().snapshot();
        let input = request(&other);
        assert!(other.reader.current_registry_view(/*now*/ 20).is_ok());
        assert!(
            f.sink
                .writer
                .lock()
                .unwrap()
                .verify_committed_unlearning(
                    &input.lineage,
                    &input.dataset,
                    &input.evidence,
                    input.learning_now
                )
                .is_ok()
        );
        assert!(
            art::validate_published_artifact_manifest_v2(
                other
                    .service
                    .registry()
                    .manifest(&other.source.artifact_id)
                    .unwrap(),
                other.source.clone(),
                /*now*/ 20
            )
            .is_ok()
        );
        assert!(
            f.sink
                .revoke_artifact_from_unlearning(&mut other.service, input)
                .is_err()
        );
        assert_eq!(other.service.registry().snapshot(), before);
        assert!(other.service.recovery_required().is_none());
    }
}

#[test]
fn confirmed_bridge_refuses_changed_signed_inputs_and_operation_without_mutation() {
    let mut f = case();
    f.sink = f
        .sink
        .with_artifact_unlearning_owner(pins(&f.config))
        .unwrap();
    let before = f.service.registry().snapshot();
    let original = request(&f);
    let mut variants = vec![];
    let mut bad = original.clone();
    bad.evidence.signature[0] ^= 1;
    variants.push(bad);
    let mut bad = original.clone();
    bad.revocation.signed_current_head.signature[0] ^= 1;
    variants.push(bad);
    let mut bad = original.clone();
    bad.revocation.operation_id = id("other-operation");
    variants.push(bad);
    let mut bad = original.clone();
    bad.revocation.change.reason_digest = digest("other-reason");
    variants.push(bad);
    let mut bad = original.clone();
    bad.source_manifest.source_dataset_digests = vec![digest("forged-source")];
    variants.push(bad);
    let mut bad = original;
    bad.lineage.record_id = id("uncommitted");
    bad.evidence = signed(
        &f.sink.writer.lock().unwrap(),
        "privacy-owner",
        LearningEvidenceRoleV1::UnlearningAuthority,
        &led::unlearning_signing_payload_v1(&bad.lineage),
    );
    variants.push(bad);
    for input in variants {
        assert!(
            f.sink
                .revoke_artifact_from_unlearning(&mut f.service, input)
                .is_err()
        );
        assert_eq!(f.service.registry().snapshot(), before);
        assert!(f.service.recovery_required().is_none());
    }
}

#[test]
fn confirmed_bridge_preserves_original_observation_fence_and_same_id_retry() {
    let mut f = case();
    f.sink = f
        .sink
        .with_artifact_unlearning_owner(pins(&f.config))
        .unwrap();
    let input = request(&f);
    let guard = OpenOptions::new()
        .read(true)
        .write(true)
        .open(f.config.root.join("writer/current-observation.lock"))
        .unwrap();
    guard.try_lock_shared().unwrap();
    assert!(
        f.sink
            .revoke_artifact_from_unlearning(&mut f.service, input.clone())
            .is_err()
    );
    assert!(f.service.registry().is_eligible(&f.source.artifact_id));
    guard.unlock().unwrap();
    f.sink
        .revoke_artifact_from_unlearning(&mut f.service, input)
        .unwrap();
    assert!(!f.service.registry().is_eligible(&f.source.artifact_id));
}

#[test]
fn confirmed_bridge_rejects_copied_history_under_other_legitimate_owner_domains() {
    let mut f = case();
    let expected_owner = pins(&f.config);
    let original_records = f.sink.writer.lock().unwrap().records().unwrap();
    let frontier = f.sink.writer.lock().unwrap().witness_frontier().unwrap();
    for (root_seed, generation, binding) in [
        (98, 1, expected_owner.ledger_binding),
        (99, 2, expected_owner.ledger_binding),
        (99, 1, digest("other-ledger-binding")),
    ] {
        let temp = tempfile::tempdir().unwrap();
        for name in ["learning.ledger", "learning.witness"] {
            let mut bytes = fs::read(f.temp.path().join(name)).unwrap();
            bytes[8..40].copy_from_slice(binding.as_array());
            let checksum = Digest32::of_bytes(&bytes[..40]);
            bytes[40..72].copy_from_slice(checksum.as_array());
            fs::write(temp.path().join(name), bytes).unwrap();
        }
        let open = |name| {
            OpenOptions::new()
                .read(true)
                .write(true)
                .open(temp.path().join(name))
                .unwrap()
        };
        let ledger = DurableLedger::recover(
            open("learning.ledger"),
            binding,
            /*max_records*/ 128,
            led::LedgerRecovery::Acknowledged(frontier.anchor),
        )
        .unwrap();
        let witness = LedgerWitnessStore::recover(open("learning.witness"), binding).unwrap();
        let directory = File::open(temp.path()).unwrap();
        let writer = LedgerWriter::from_durable(
            ledger,
            witness,
            activated_trust_for_domain(root_seed, generation),
            &directory,
            &directory,
        )
        .unwrap();
        assert_eq!(writer.records().unwrap(), original_records);
        assert!(
            writer
                .verify_committed_unlearning(&f.lineage, &f.dataset, &f.evidence, /*now*/ 50)
                .is_ok()
        );
        let other = CognitiveRetrievalLearningSink::new(writer)
            .with_artifact_unlearning_owner(expected_owner)
            .unwrap();
        let input = request(&f);
        assert!(matches!(
            other.revoke_artifact_from_unlearning(&mut f.service, input),
            Err(crate::CognitiveArtifactUnlearningError::OwnerBinding)
        ));
        assert!(f.service.registry().is_eligible(&f.source.artifact_id));
        assert!(f.service.recovery_required().is_none());
    }
}
