use super::tests::*;
use super::*;

use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use crate::test_support::FixtureValue;

fn rotated_configuration() -> (
    ArtifactOwnerTrustV1,
    SignedArtifactWriterLeaseV1,
    SignedCurrentArtifactHeadV1,
    SignedCurrentArtifactHeadV1,
) {
    let old_key = signer();
    let new_key = SigningKey::from_bytes(&[39; 32]);
    let scope_digest = withdrawal_scope().digest();
    let mut owner_trust = trust(&old_key, scope_digest);
    owner_trust.minimum_registry_generation = Generation::new(2).fixture("current floor");
    owner_trust.minimum_authority_epoch = 2;
    owner_trust.head_signers[0].maximum_authority_epoch = 1;
    let mut replacement_signer = owner_trust.head_signers[0].clone();
    replacement_signer.signer_id = id("owner-authority-v2");
    replacement_signer.verifying_key = new_key.verifying_key().to_bytes();
    replacement_signer.minimum_authority_epoch = 2;
    replacement_signer.maximum_authority_epoch = 10;
    owner_trust.head_signers.push(replacement_signer);

    let mut writer_lease = lease(&old_key, scope_digest);
    writer_lease.authority_epoch = 2;
    writer_lease.signature = old_key.sign(&writer_lease.signing_bytes()).to_bytes();
    let historical = signed_head(&old_key, scope_digest, digest("historical head"));
    let mut current = historical.clone();
    current.witness.generation = Generation::new(2).fixture("current generation");
    current.witness.head_digest = digest("replacement head");
    current.witness.predecessor_head_digest = historical.witness.head_digest;
    current.witness.authority_epoch = 2;
    current.witness.signer_id = id("owner-authority-v2");
    current.witness.signing_key_digest = Digest32::of_bytes(&new_key.verifying_key().to_bytes());
    current.witness.issued_at = 30;
    current.signature = new_key.sign(&current.signing_bytes()).to_bytes();
    (owner_trust, writer_lease, historical, current)
}

#[test]
fn advanced_current_floors_preserve_signed_history_and_old_restart_anchor() {
    let directory = TestDir::new();
    let (owner_trust, writer_lease, historical, current) = rotated_configuration();
    let owner = LearningArtifactOwnerHost::open(
        &directory.0,
        owner_trust.clone(),
        writer_lease.clone(),
        40,
    )
    .fixture("advanced-floor owner");
    owner
        .persist_signed_head_record(&historical)
        .fixture("signed historical head");
    owner
        .persist_signed_head_record(&current)
        .fixture("signed replacement head");
    assert_eq!(
        owner
            .discover_current_head(40)
            .fixture("current chain")
            .fixture("current head")
            .signed,
        current
    );
    drop(owner);
    let reopened = LearningArtifactOwnerHost::open_with_required_current_head(
        &directory.0,
        owner_trust,
        writer_lease,
        historical,
        40,
    )
    .fixture("old independent anchor remains valid");
    assert_eq!(
        reopened
            .discover_current_head(40)
            .fixture("anchored current chain")
            .fixture("current head")
            .signed,
        current
    );
}

#[test]
fn each_advanced_floor_rejects_a_still_old_current_head() {
    for floor in ["generation", "epoch"] {
        let directory = TestDir::new();
        let (mut owner_trust, writer_lease, historical, _) = rotated_configuration();
        match floor {
            "generation" => owner_trust.minimum_authority_epoch = 1,
            "epoch" => {
                owner_trust.minimum_registry_generation = Generation::new(1).fixture("generation")
            }
            _ => unreachable!(),
        }
        let owner = LearningArtifactOwnerHost::open(&directory.0, owner_trust, writer_lease, 40)
            .fixture("owner");
        owner
            .persist_signed_head_record(&historical)
            .fixture("old current head");
        assert!(
            matches!(
                owner.discover_current_head(40),
                Err(ArtifactOwnerHostError::CurrentHeadContext)
            ),
            "floor {floor}"
        );
    }
}

#[test]
fn historical_replay_retains_key_epoch_and_signature_checks() {
    for damage in ["epoch", "signature"] {
        let directory = TestDir::new();
        let (owner_trust, writer_lease, mut historical, current) = rotated_configuration();
        match damage {
            "epoch" => {
                historical.witness.authority_epoch = 2;
                historical.signature = signer().sign(&historical.signing_bytes()).to_bytes();
            }
            "signature" => historical.signature[0] ^= 1,
            _ => unreachable!(),
        }
        let owner = LearningArtifactOwnerHost::open(&directory.0, owner_trust, writer_lease, 40)
            .fixture("owner");
        owner
            .persist_signed_head_record(&historical)
            .fixture("damaged historical head");
        owner
            .persist_signed_head_record(&current)
            .fixture("replacement head");
        let failure = owner.discover_current_head(40);
        match damage {
            "epoch" => assert!(matches!(
                failure,
                Err(ArtifactOwnerHostError::SignerContext)
            )),
            "signature" => assert!(matches!(
                failure,
                Err(ArtifactOwnerHostError::InvalidSignature)
            )),
            _ => unreachable!(),
        }
    }
}

#[test]
fn signed_chain_cannot_hide_future_or_backwards_historical_issuance() {
    for (historical_issued_at, now, expected_valid) in
        [(50, 40, false), (50, 60, false), (30, 40, true)]
    {
        let directory = TestDir::new();
        let (owner_trust, writer_lease, mut historical, current) = rotated_configuration();
        historical.witness.issued_at = historical_issued_at;
        historical.signature = signer().sign(&historical.signing_bytes()).to_bytes();
        let owner = LearningArtifactOwnerHost::open(&directory.0, owner_trust, writer_lease, now)
            .fixture("owner");
        owner
            .persist_signed_head_record(&historical)
            .fixture("historical head");
        owner
            .persist_signed_head_record(&current)
            .fixture("replacement head issued at 30");
        let discovered = owner.discover_current_head(now);
        if expected_valid {
            assert_eq!(
                discovered
                    .fixture("equal issuance times allowed")
                    .fixture("current head")
                    .signed,
                current
            );
        } else {
            assert!(matches!(
                discovered,
                Err(ArtifactOwnerHostError::CurrentHeadContext)
            ));
        }
    }
}

#[test]
fn backwards_signed_successor_rejects_before_publishing_a_witness_or_head() {
    let directory = TestDir::new();
    let key = signer();
    let scope = withdrawal_scope();
    let scope_digest = scope.digest();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope);
    let owner = LearningArtifactOwnerHost::open(
        &directory.0,
        trust(&key, scope_digest),
        lease(&key, scope_digest),
        20,
    )
    .fixture("owner");
    let (mut registry, mut initial) = deterministic_publication(&owner, &withdrawals, 20);
    owner
        .ensure_payload_durable(&mut initial, &registry, b"payload", 20)
        .fixture("initial payload");
    owner
        .ensure_registry_durable(&mut initial, &registry, &withdrawals, digest("binding"), 20)
        .fixture("initial registry");
    let current = signed_head(&key, scope_digest, registry.snapshot().head_digest);
    owner
        .ensure_witness_durable(&mut initial, &current, &withdrawals, 20)
        .fixture("initial witness");
    owner
        .acknowledge(&mut initial, &withdrawals, 20)
        .fixture("initial acknowledgement");

    let predecessor = registry.snapshot().head_digest;
    let mut next_manifest = manifest();
    next_manifest.artifact_id = id("successor-candidate");
    next_manifest.generation = Generation::new(2).fixture("generation");
    let admission = crate::admit_manifest_at_withdrawal_head_v3(
        &withdrawals,
        withdrawals.head_digest(),
        next_manifest,
        40,
    )
    .fixture("next admission");
    let mut next = owner
        .begin_publication(
            id("next-operation"),
            admission,
            &withdrawals,
            &registry,
            predecessor,
            40,
        )
        .fixture("next publication");
    owner
        .stage_compatibility_registration(&next, &mut registry, 40)
        .fixture("next registration");
    owner
        .ensure_payload_durable(&mut next, &registry, b"payload", 40)
        .fixture("next payload");
    owner
        .ensure_registry_durable(&mut next, &registry, &withdrawals, digest("binding"), 40)
        .fixture("next registry");
    let mut signed_next = current.clone();
    signed_next.witness.generation = Generation::new(2).fixture("head generation");
    signed_next.witness.head_digest = registry.snapshot().head_digest;
    signed_next.witness.predecessor_head_digest = predecessor;
    signed_next.witness.issued_at = current.witness.issued_at - 1;
    signed_next.signature = key.sign(&signed_next.signing_bytes()).to_bytes();
    let requirement = RegistryHeadRequirementV1 {
        registry_id: signed_next.witness.registry_id.clone(),
        minimum_generation: signed_next.witness.generation,
        expected_predecessor_head_digest: predecessor,
        minimum_authority_epoch: signed_next.witness.authority_epoch,
        now: 40,
    };
    owner
        .verifier
        .verify_signed_head(&signed_next, &requirement, true)
        .fixture("otherwise valid signed successor");
    let before = (
        fs::read_dir(directory.0.join("heads"))
            .fixture("heads")
            .count(),
        fs::read_dir(directory.0.join("witnesses"))
            .fixture("witnesses")
            .count(),
        next.snapshot(),
    );
    assert!(matches!(
        owner.ensure_witness_durable(&mut next, &signed_next, &withdrawals, 40),
        Err(ArtifactOwnerHostError::CurrentHeadContext)
    ));
    assert_eq!(
        (
            fs::read_dir(directory.0.join("heads"))
                .fixture("heads")
                .count(),
            fs::read_dir(directory.0.join("witnesses"))
                .fixture("witnesses")
                .count(),
            next.snapshot(),
        ),
        before,
    );
    assert_eq!(
        owner
            .discover_current_head(40)
            .fixture("unchanged current chain")
            .fixture("current head")
            .signed,
        current
    );
}

#[test]
fn uncertain_current_retry_requires_the_exact_already_published_signed_head() {
    let directory = TestDir::new();
    let key = signer();
    let scope = withdrawal_scope();
    let scope_digest = scope.digest();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope);
    let owner = LearningArtifactOwnerHost::open(
        &directory.0,
        trust(&key, scope_digest),
        lease(&key, scope_digest),
        20,
    )
    .fixture("owner");
    let (registry, mut transaction) = deterministic_publication(&owner, &withdrawals, 20);
    owner
        .ensure_payload_durable(&mut transaction, &registry, b"payload", 20)
        .fixture("payload");
    owner
        .ensure_registry_durable(
            &mut transaction,
            &registry,
            &withdrawals,
            digest("binding"),
            20,
        )
        .fixture("registry");
    let signed = signed_head(&key, scope_digest, registry.snapshot().head_digest);
    let requirement = RegistryHeadRequirementV1 {
        registry_id: signed.witness.registry_id.clone(),
        minimum_generation: signed.witness.generation,
        expected_predecessor_head_digest: signed.witness.predecessor_head_digest,
        minimum_authority_epoch: signed.witness.authority_epoch,
        now: 20,
    };
    let witness_digest = validate_registry_head_witness(&signed.witness, &requirement)
        .fixture("original witness")
        .witness_digest;
    let encoded = encode_head_witness(&signed.witness, signed.binding).fixture("witness bytes");
    let witness_path = directory.0.join("witnesses").join(format!(
        "{}-{}.witness",
        signed.witness.generation.get(),
        witness_digest
    ));
    records::write_record_with_limit(&witness_path, &encoded, encoded.len())
        .fixture("witness effect before checkpoint");
    owner
        .persist_signed_head_record(&signed)
        .fixture("CURRENT effect before checkpoint");
    let mut altered = signed.clone();
    altered.witness.issued_at = 21;
    altered.signature = key.sign(&altered.signing_bytes()).to_bytes();
    let altered_requirement = RegistryHeadRequirementV1 {
        now: 21,
        ..requirement
    };
    owner
        .verifier
        .verify_signed_head(&altered, &altered_requirement, true)
        .fixture("otherwise valid altered signed head");
    let before = (
        fs::read_dir(directory.0.join("heads"))
            .fixture("heads")
            .count(),
        fs::read_dir(directory.0.join("witnesses"))
            .fixture("witnesses")
            .count(),
        transaction.snapshot(),
    );
    assert!(matches!(
        owner.ensure_witness_durable(&mut transaction, &altered, &withdrawals, 21),
        Err(ArtifactOwnerHostError::CurrentHeadConflict)
    ));
    assert_eq!(
        (
            fs::read_dir(directory.0.join("heads"))
                .fixture("heads")
                .count(),
            fs::read_dir(directory.0.join("witnesses"))
                .fixture("witnesses")
                .count(),
            transaction.snapshot(),
        ),
        before,
    );
    assert_eq!(
        owner
            .discover_current_head(21)
            .fixture("original head remains current")
            .fixture("current head")
            .signed,
        signed
    );
    owner
        .ensure_witness_durable(&mut transaction, &signed, &withdrawals, 21)
        .fixture("exact original retry resumes");
    owner
        .acknowledge(&mut transaction, &withdrawals, 21)
        .fixture("acknowledgement");
    assert_eq!(
        transaction.phase(),
        ArtifactPublicationPhaseV1::Acknowledged
    );
}
