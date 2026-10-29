//! Actual original owner, CURRENT, selector and pinned-load PQ authorization.
use super::tests::*;
use super::*;
use crate::ArtifactOwnerVerifierV1;
use crate::ArtifactSelectionTrustV1;
use crate::ArtifactSelectionVerifierV1;
use crate::LearningAuthenticationProfile;
use crate::LearningSignature;
use crate::LearningVerificationKey;
use crate::PinnedCandidateLoadError;
use crate::SignedArtifactSelectionV1;
use crate::TrustedArtifactSelectorV1;
use crate::VerifiedCurrentRegistryViewV1;
use crate::load_selected_candidate;
use crate::test_support::FixtureValue;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;
use std::fs::File;

fn pq_key(seed: u8) -> PqNativeSigningKey {
    let spki = PqNativeSigningKey::public_spki_from_seed(&[seed; 32].into());
    PqNativeSigningKey::from_owned_seed(
        [seed; 32].into(),
        ml_dsa_65_key_id_from_spki(&spki).fixture("PQ public ID"),
    )
    .fixture("PQ signer")
}

fn pq_signature(key: &PqNativeSigningKey, message: &[u8]) -> LearningSignature {
    LearningSignature::MlDsa65V2(key.sign_exact_message(message).fixture("PQ sign").to_vec())
}

fn config(
    root: PathBuf,
    writer: &PqNativeSigningKey,
    head: &PqNativeSigningKey,
) -> LearningArtifactOwnerServiceConfigV1 {
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let scope_digest = withdrawals.scope_digest().fixture("scope");
    let classic = key();
    let mut trust = trust(&classic, scope_digest);
    trust.writer_signers[0].verifying_key =
        LearningVerificationKey::MlDsa65V2(writer.public_spki().to_vec());
    trust.head_signers[0].verifying_key =
        LearningVerificationKey::MlDsa65V2(head.public_spki().to_vec());
    let mut writer_lease = lease(&classic, scope_digest);
    writer_lease.signing_key_digest = Digest32::of_bytes(writer.public_spki());
    writer_lease.signature = LearningSignature::MlDsa65V2(Vec::new());
    writer_lease.signature = pq_signature(writer, &writer_lease.signing_bytes());
    LearningArtifactOwnerServiceConfigV1 {
        root,
        trust,
        writer_lease,
        required_current_head: None,
        withdrawal_registry: withdrawals,
        storage_binding: digest("binding"),
        now: 20,
    }
}

fn request(
    service: &LearningArtifactOwnerService,
    config: &LearningArtifactOwnerServiceConfigV1,
    head: &PqNativeSigningKey,
) -> LearningArtifactPublishRequestV1 {
    let predecessor = service.registry().snapshot().head_digest;
    let mut request = publish_request(
        &key(),
        &config.withdrawal_registry,
        predecessor,
        digest("pending"),
    );
    let preview = ArtifactPublicationTransactionV1::begin(
        request.operation_id.clone(),
        request.admission.clone(),
        &config.withdrawal_registry,
        service.registry(),
        predecessor,
        /*now*/ 20,
    )
    .fixture("publication preview");
    let mut staged = service.registry().clone();
    service
        .host
        .stage_compatibility_registration(&preview, &mut staged, /*now*/ 20)
        .fixture("stage");
    request.signed_current_head.witness.head_digest = staged.snapshot().head_digest;
    request.signed_current_head.witness.signing_key_digest = Digest32::of_bytes(head.public_spki());
    request.signed_current_head.signature = LearningSignature::MlDsa65V2(Vec::new());
    request.signed_current_head.signature =
        pq_signature(head, &request.signed_current_head.signing_bytes());
    request
}

fn selection(
    key: &PqNativeSigningKey,
    service: &LearningArtifactOwnerService,
    current: &VerifiedCurrentRegistryViewV1,
) -> SignedArtifactSelectionV1 {
    let manifest = service
        .registry()
        .manifest(&id("candidate"))
        .fixture("published manifest");
    let mut signed = SignedArtifactSelectionV1 {
        selection_id: id("independent-selection"),
        artifact_id: manifest.artifact_id.clone(),
        registry_id: id("learning-artifacts"),
        withdrawal_scope_digest: scope().digest(),
        registry_head_digest: current.receipt().head_digest,
        current_witness_digest: current.witness_digest(),
        current_trust_digest: current.trust_digest(),
        artifact_kind: manifest.kind,
        artifact_generation: manifest.generation,
        predecessor_id: manifest.predecessor_id.clone(),
        content_digest: manifest.content_digest,
        objective_digest: manifest.objective_digest,
        support_digest: manifest.support_digest,
        compatibility_digest: manifest.compatibility_digest,
        encoded_size_bytes: manifest.encoded_size_bytes,
        selector_id: id("selector"),
        selector_credential_digest: digest("selector credential"),
        signing_key_digest: Digest32::of_bytes(key.public_spki()),
        authority_epoch: 1,
        issued_at: 20,
        expires_at: 900,
        signature: LearningSignature::MlDsa65V2(Vec::new()),
    };
    signed.signature = pq_signature(key, &signed.signing_bytes());
    signed
}

#[test]
fn pq_owner_current_selector_and_payload_use_the_original_durable_pipeline() {
    let directory = TestDir::new();
    let writer = pq_key(/*seed*/ 71);
    let head = pq_key(/*seed*/ 72);
    let selector = pq_key(/*seed*/ 73);
    let mut config = config(directory.0.clone(), &writer, &head);
    let mut service = LearningArtifactOwnerService::open(config.clone()).fixture("open PQ owner");
    let request = request(&service, &config, &head);
    let receipt = service.publish(request.clone()).fixture("PQ publication");
    assert_eq!(
        service
            .publish(request.clone())
            .fixture("PQ terminal retry"),
        receipt
    );
    let mut forged = request.clone();
    forged.signed_current_head.signature[10] ^= 1;
    assert!(matches!(
        service.publish(forged),
        Err(LearningArtifactOwnerServiceError::Host(
            ArtifactOwnerHostError::InvalidSignature
        ))
    ));
    assert!(service.recovery_required().is_none());

    let current = service
        .current_registry_view(/*now*/ 21)
        .fixture("PQ CURRENT");
    assert_eq!(
        current.authentication_profile(),
        LearningAuthenticationProfile::MlDsa65V2
    );
    let witness = &request.signed_current_head.witness;
    let mut requirement = RegistryHeadRequirementV1 {
        registry_id: witness.registry_id.clone(),
        minimum_generation: witness.generation,
        expected_predecessor_head_digest: witness.predecessor_head_digest,
        minimum_authority_epoch: witness.authority_epoch,
        now: witness.expires_at - 1,
    };
    let current_verifier =
        ArtifactOwnerVerifierV1::new(config.trust.clone()).fixture("PQ CURRENT verifier");
    let current_snapshot = directory.0.join("registries").join(format!(
        "{}-{}.snapshot",
        current.receipt().head_digest,
        current.receipt().file_digest
    ));
    current_verifier
        .verify_current_registry_view(
            File::open(&current_snapshot).fixture("CURRENT snapshot before expiry"),
            current.receipt(),
            &request.signed_current_head,
            &requirement,
        )
        .fixture("PQ head before expiry");
    requirement.now = witness.expires_at;
    assert!(matches!(
        current_verifier.verify_current_registry_view(
            File::open(&current_snapshot).fixture("CURRENT snapshot at expiry"),
            current.receipt(),
            &request.signed_current_head,
            &requirement,
        ),
        Err(ArtifactOwnerHostError::CurrentHeadContext)
    ));
    let selector_trust = ArtifactSelectionTrustV1 {
        registry_id: id("learning-artifacts"),
        withdrawal_scope_digest: scope().digest(),
        minimum_authority_epoch: 1,
        selectors: vec![TrustedArtifactSelectorV1 {
            selector_id: id("selector"),
            verifying_key: LearningVerificationKey::MlDsa65V2(selector.public_spki().to_vec()),
            minimum_authority_epoch: 1,
            maximum_authority_epoch: 10,
            valid_from: 1,
            expires_at: 1_000,
            revoked_at: None,
        }],
    };
    let verifier =
        ArtifactSelectionVerifierV1::new(selector_trust, &config.trust).fixture("PQ selector");
    let signed = selection(&selector, &service, &current);
    let mut downgraded = signed.clone();
    downgraded.signature = [0; 64].into();
    assert!(verifier.verify(&downgraded, &current, /*now*/ 21).is_err());
    let selected = verifier
        .verify(&signed, &current, /*now*/ 21)
        .fixture("verify selection");
    let registry = current.receipt();
    let snapshot = directory.0.join("registries").join(format!(
        "{}-{}.snapshot",
        registry.head_digest, registry.file_digest
    ));
    let payload = directory
        .0
        .join("payloads")
        .join(format!("candidate-{}.bin", digest("payload")));
    let mut cached = load_selected_candidate(
        File::open(snapshot).fixture("snapshot"),
        File::open(payload).fixture("payload"),
        selected,
    )
    .fixture("selected load");
    assert_eq!(
        cached.authentication_profile(),
        LearningAuthenticationProfile::MlDsa65V2
    );
    assert_eq!(
        cached
            .with_current(current, /*now*/ 21, <[u8]>::to_vec)
            .fixture("read-only use"),
        b"payload"
    );

    config.required_current_head = Some(request.signed_current_head.clone());
    drop(service);
    let mut reopened = LearningArtifactOwnerService::open(config).fixture("PQ anchored reopen");
    assert_eq!(
        reopened
            .publish(request.clone())
            .fixture("retry after restart"),
        receipt
    );
    let current = reopened
        .current_registry_view(/*now*/ 22)
        .fixture("reopened PQ CURRENT");
    let changed_profile = VerifiedCurrentRegistryViewV1::new(
        current.receipt(),
        current.registry().clone(),
        current.witness_digest(),
        current.trust_digest(),
        current.validity(),
        LearningAuthenticationProfile::ClassicalV1,
    );
    assert_eq!(
        cached.with_current(changed_profile, /*now*/ 22, |_| ()),
        Err(PinnedCandidateLoadError::AuthenticationProfile)
    );
    assert_eq!(
        cached.with_current(current, /*now*/ 22, |_| ()),
        Err(PinnedCandidateLoadError::Unavailable)
    );

    let mut staged = reopened.registry().clone();
    let change = crate::StateChange {
        event_id: id("pq-withdraw"),
        artifact_id: id("candidate"),
        evaluator_id: id("owner-authority"),
        reason_digest: digest("withdrawal decision"),
    };
    staged
        .append(crate::ArtifactEvent::Revoke(change.clone()))
        .fixture("revocation preview");
    let mut signed = request.signed_current_head;
    signed.witness.generation = Generation::new(/*value*/ 2).fixture("generation");
    signed.witness.predecessor_head_digest = receipt.registry_head_digest;
    signed.witness.head_digest = staged.snapshot().head_digest;
    signed.signature = pq_signature(&head, &signed.signing_bytes());
    let revoke = LearningArtifactRevokeRequestV1 {
        operation_id: change.event_id.clone(),
        change,
        signed_current_head: signed,
        expected_registry_predecessor_head: receipt.registry_head_digest,
        now: 22,
    };
    let revoked = reopened.revoke(revoke.clone()).fixture("PQ revocation");
    assert_eq!(
        reopened
            .revoke(revoke.clone())
            .fixture("PQ revocation retry"),
        revoked
    );
    let mut forged = revoke;
    forged.signed_current_head.signature[0] ^= 1;
    assert!(reopened.revoke(forged).is_err());
    assert!(!reopened.registry().is_eligible(&id("candidate")));
}

#[test]
fn pq_owner_rejects_classical_roles_signatures_and_store_relabelling() {
    let directory = TestDir::new();
    let writer = pq_key(/*seed*/ 74);
    let head = pq_key(/*seed*/ 75);
    let config = config(directory.0.clone(), &writer, &head);
    let mut mixed = config.clone();
    mixed.trust.head_signers[0].verifying_key = key().verifying_key().to_bytes().into();
    assert!(LearningArtifactOwnerService::open(mixed).is_err());
    assert_eq!(
        std::fs::read_dir(&directory.0)
            .fixture("empty store")
            .count(),
        0
    );
    let mut weak_lease = config.clone();
    weak_lease.writer_lease.signature = [0; 64].into();
    assert!(LearningArtifactOwnerService::open(weak_lease).is_err());
    assert_eq!(
        std::fs::read_dir(&directory.0)
            .fixture("empty store")
            .count(),
        0
    );
    let service = LearningArtifactOwnerService::open(config.clone()).fixture("PQ namespace");
    drop(service);
    let mut classical = config.clone();
    classical.trust = trust(&key(), scope().digest());
    classical.writer_lease = lease(&key(), scope().digest());
    assert!(LearningArtifactOwnerService::open(classical.clone()).is_err());
    let classic_directory = TestDir::new();
    classical.root = classic_directory.0.clone();
    drop(LearningArtifactOwnerService::open(classical).fixture("classic namespace"));
    let mut relabelled = config;
    relabelled.root = classic_directory.0.clone();
    assert!(LearningArtifactOwnerService::open(relabelled).is_err());
}
