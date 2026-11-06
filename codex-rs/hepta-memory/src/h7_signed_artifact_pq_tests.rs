use super::super::H7ArtifactSigner;
use super::*;
use crate::h7_runtime::H7QualificationRuntime;
use crate::h7_runtime::H7TrajectoryEvent;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use pretty_assertions::assert_eq;
use serde_json::json;

const ISSUED: u64 = 100;
const EXPIRES: u64 = 500;
const NOW: u64 = 200;

fn pq_signer(seed: u8) -> H7PqArtifactSigner {
    let seed = [seed; 32].into();
    let spki = PqNativeSigningKey::public_spki_from_seed(&seed);
    let key_id = ml_dsa_65_key_id_from_spki(&spki).expect("canonical SPKI");
    let key = PqNativeSigningKey::from_owned_seed(seed, key_id).expect("owned PQ key");
    H7PqArtifactSigner::new("artifact-role", /*signer_epoch*/ 7, key).expect("PQ artifact signer")
}

fn fixture() -> (H7QualificationRuntime, H7Artifact) {
    let mut runtime = H7QualificationRuntime::new();
    let event = H7TrajectoryEvent::new(
        "pq-artifact-trajectory",
        /*event_seq*/ 1,
        "abstain",
        /*reward_bps*/ 1_000,
        /*safety_ok*/ true,
        /*authority_epoch*/ 1,
        /*owner_epoch*/ 1,
        /*generation*/ 1,
        Sha256Digest::for_bytes(b"pq-artifact-fence"),
    )
    .expect("trajectory event");
    runtime
        .append_trajectory_event(event)
        .expect("append event");
    runtime
        .evaluate_trajectory("pq-artifact-trajectory")
        .expect("evaluate");
    let artifact = runtime
        .propose_artifact(
            "pq-artifact-v1",
            "pq-artifact-trajectory",
            /*generation*/ 1,
        )
        .expect("artifact");
    (runtime, artifact)
}

#[test]
fn pq_artifact_pins_canonical_identity_and_refuses_cross_profile_signatures() {
    let (_, artifact) = fixture();
    let signer = pq_signer(/*seed*/ 91);
    let envelope = signer
        .sign(
            &artifact,
            /*ope*/ None,
            H7SignedArtifactTransition::Reload,
            /*expected_runtime_generation*/ 0,
            /*predecessor_artifact_sha256*/ None,
            ISSUED,
            EXPIRES,
        )
        .expect("PQ sign");
    let verifier = H7ArtifactVerifier::from_pinned_spki(
        signer.signer_id(),
        signer.signer_epoch(),
        signer.public_spki(),
        signer.public_key_id(),
    )
    .expect("pinned verifier");
    verifier
        .verify(
            &envelope, &artifact, /*ope*/ None, NOW, /*expected_runtime_generation*/ 0,
            /*expected_predecessor_artifact_sha256*/ None,
        )
        .expect("verify complete body");
    assert_eq!(verifier.pq_public_key_id(), envelope.signer_public_key_id);
    assert!(
        H7ArtifactVerifier::from_pinned_spki(
            "artifact-role",
            /*signer_epoch*/ 7,
            signer.public_spki(),
            [9; 32]
        )
        .is_err()
    );
    assert!(
        H7ArtifactVerifier::from_pinned_spki(
            "artifact-role",
            /*signer_epoch*/ 7,
            &[9; 32],
            signer.public_key_id()
        )
        .is_err()
    );
    let mut trailing = signer.public_spki().to_vec();
    trailing.push(0);
    assert!(
        H7ArtifactVerifier::from_pinned_spki(
            "artifact-role",
            /*signer_epoch*/ 7,
            &trailing,
            signer.public_key_id()
        )
        .is_err()
    );

    let classical = H7ArtifactSigner::from_seed("artifact-role", /*signer_epoch*/ 7, [91; 32])
        .expect("classical fixture");
    let legacy = classical
        .sign(
            &artifact,
            /*ope*/ None,
            H7SignedArtifactTransition::Reload,
            /*expected_runtime_generation*/ 0,
            /*predecessor_artifact_sha256*/ None,
            ISSUED,
            EXPIRES,
        )
        .expect("legacy sign");
    classical
        .verifier()
        .verify_envelope_signature(&legacy, NOW)
        .expect("legacy remains explicit");
    assert!(
        serde_json::to_value(&legacy)
            .unwrap()
            .get("signer_public_key_id")
            .is_none()
    );
    assert_eq!(
        verifier.verify_envelope_signature(&legacy, NOW),
        Err(H7SignedArtifactError::SignatureInvalid)
    );
    assert_eq!(
        classical
            .verifier()
            .verify_envelope_signature(&envelope, NOW),
        Err(H7SignedArtifactError::SignatureInvalid)
    );
    let mut confused = envelope;
    confused.signer_public_key_id = None;
    assert_eq!(
        confused.validate_shape(),
        Err(H7SignedArtifactError::ProductionBoundary)
    );
    let mut confused = legacy;
    confused.signer_public_key_id = Some(signer.public_key_id());
    assert_eq!(
        confused.validate_shape(),
        Err(H7SignedArtifactError::ProductionBoundary)
    );
}

#[test]
fn pq_artifact_message_binds_payload_and_rejects_malformed_signatures() {
    let (_, artifact) = fixture();
    let signer = pq_signer(/*seed*/ 92);
    let envelope = signer
        .sign(
            &artifact,
            /*ope*/ None,
            H7SignedArtifactTransition::Rollback,
            /*expected_runtime_generation*/ 2,
            Some(Sha256Digest::for_bytes(b"predecessor")),
            ISSUED,
            EXPIRES,
        )
        .expect("PQ rollback sign");
    let verifier = signer.verifier();
    verifier
        .verify_envelope_signature(&envelope, NOW)
        .expect("original signature");
    let source = serde_json::to_value(&envelope).unwrap();
    let changed_digest = Sha256Digest::for_bytes(b"changed");
    for (field, changed) in [
        ("artifact_id", json!("other-artifact")),
        ("artifact_sha256", json!(changed_digest)),
        ("trajectory_sha256", json!(changed_digest)),
        ("evaluation_sha256", json!(changed_digest)),
        ("ope_evaluation_sha256", json!(changed_digest)),
        ("predecessor_artifact_sha256", json!(changed_digest)),
        ("transition", json!("reload")),
        ("expected_runtime_generation", json!(3)),
        ("issued_at_unix_seconds", json!(ISSUED + 1)),
        ("expires_at_unix_seconds", json!(EXPIRES + 1)),
        (
            "signer_public_key_id",
            serde_json::to_value([9_u8; 32]).unwrap(),
        ),
    ] {
        let mut value = source.clone();
        value[field] = changed;
        let mut changed: H7SignedArtifactEnvelope = serde_json::from_value(value).unwrap();
        // Recomputing the public digest cannot replace the detached signature.
        changed.envelope_sha256 = changed.payload_digest();
        assert_eq!(
            verifier.verify_envelope_signature(&changed, NOW),
            Err(H7SignedArtifactError::SignatureInvalid),
            "unbound {field}"
        );
    }
    let mut bad = envelope.clone();
    let mut bytes = STANDARD.decode(&bad.signature_base64).unwrap();
    bytes[100] ^= 1;
    bad.signature_base64 = STANDARD.encode(bytes);
    assert_eq!(
        verifier.verify_envelope_signature(&bad, NOW),
        Err(H7SignedArtifactError::SignatureInvalid)
    );
    for signature in [
        STANDARD.encode([0; 64]),
        format!("{}A", envelope.signature_base64),
        "!".repeat(4412),
    ] {
        let mut bad = envelope.clone();
        bad.signature_base64 = signature;
        assert_eq!(
            verifier.verify_envelope_signature(&bad, NOW),
            Err(H7SignedArtifactError::SignatureMalformed)
        );
    }
    assert_eq!(
        verifier.verify_envelope_signature(&envelope, ISSUED - 1),
        Err(H7SignedArtifactError::NotYetValid)
    );
    assert_eq!(
        verifier.verify_envelope_signature(&envelope, EXPIRES),
        Err(H7SignedArtifactError::Expired)
    );
    let other = pq_signer(/*seed*/ 93).verifier();
    assert_eq!(
        other.verify_envelope_signature(&envelope, NOW),
        Err(H7SignedArtifactError::SignatureInvalid)
    );
}

#[test]
fn pq_artifact_signature_cannot_promote_qualification_to_production() {
    let (_, artifact) = fixture();
    let signer = pq_signer(/*seed*/ 94);
    let envelope = signer
        .sign(
            &artifact,
            /*ope*/ None,
            H7SignedArtifactTransition::Reload,
            /*expected_runtime_generation*/ 0,
            /*predecessor_artifact_sha256*/ None,
            ISSUED,
            EXPIRES,
        )
        .expect("PQ sign");
    let source = serde_json::to_value(&envelope).unwrap();
    for (field, value) in [
        ("qualification_only", json!(false)),
        ("production_authority", json!(true)),
        ("external_effects", json!(true)),
        ("promotion_eligible", json!(true)),
        ("namespace", json!("production")),
    ] {
        let mut value_map = source.clone();
        value_map[field] = value;
        let mut changed: H7SignedArtifactEnvelope = serde_json::from_value(value_map).unwrap();
        changed.envelope_sha256 = changed.payload_digest();
        let signature = signer
            .signing_key
            .sign_exact_message(&changed.signing_bytes())
            .expect("real forged-policy signature");
        signer
            .verifier
            .verify_exact_message(&changed.signing_bytes(), &signature)
            .expect("cryptography alone is valid");
        changed.signature_base64 = STANDARD.encode(signature);
        assert_eq!(
            signer.verifier().verify_envelope_signature(&changed, NOW),
            Err(H7SignedArtifactError::ProductionBoundary),
            "promoted {field}"
        );
    }
}

#[test]
fn pq_artifact_runtime_preserves_reload_rollback_and_replay_fences() {
    let (mut runtime, first) = fixture();
    let second = runtime
        .propose_artifact(
            "pq-artifact-v2",
            "pq-artifact-trajectory",
            /*generation*/ 2,
        )
        .expect("second artifact");
    let signer = pq_signer(/*seed*/ 95);
    let verifier = signer.verifier();
    let initial = signer
        .sign(
            &first,
            /*ope*/ None,
            H7SignedArtifactTransition::Reload,
            /*expected_runtime_generation*/ 0,
            /*predecessor_artifact_sha256*/ None,
            ISSUED,
            EXPIRES,
        )
        .expect("first signed");
    assert_eq!(
        verifier.verify(
            &initial, &second, /*ope*/ None, NOW, /*expected_runtime_generation*/ 0,
            /*expected_predecessor_artifact_sha256*/ None
        ),
        Err(H7SignedArtifactError::ArtifactBinding)
    );
    let initial: H7SignedArtifactEnvelope =
        serde_json::from_slice(&serde_json::to_vec(&initial).unwrap()).expect("wire round trip");
    let active = runtime
        .apply_signed(&initial, &verifier, /*ope*/ None, NOW)
        .expect("PQ reload");
    assert_eq!(active.runtime_generation, 1);
    let next = signer
        .sign(
            &second,
            /*ope*/ None,
            H7SignedArtifactTransition::Reload,
            /*expected_runtime_generation*/ 1,
            Some(first.body_sha256.clone()),
            ISSUED,
            EXPIRES,
        )
        .expect("second signed");
    let active = runtime
        .apply_signed(&next, &verifier, /*ope*/ None, NOW)
        .expect("PQ successor");
    assert_eq!(active.runtime_generation, 2);
    let rollback = signer
        .sign(
            &first,
            /*ope*/ None,
            H7SignedArtifactTransition::Rollback,
            /*expected_runtime_generation*/ 2,
            Some(second.body_sha256),
            ISSUED,
            EXPIRES,
        )
        .expect("rollback signed");
    let active = runtime
        .apply_signed(&rollback, &verifier, /*ope*/ None, NOW)
        .expect("PQ rollback");
    assert_eq!(active.runtime_generation, 3);
    assert_eq!(active.active_artifact_id.as_deref(), Some("pq-artifact-v1"));
    assert!(
        runtime
            .apply_signed(&rollback, &verifier, /*ope*/ None, NOW)
            .is_err()
    );
}

#[test]
fn pq_owned_verifier_preserves_actual_signature_and_authority_checks() {
    let (_, artifact) = fixture();
    let signer = pq_signer(/*seed*/ 96);
    let key = PqNativeVerifier::from_pinned_spki(signer.public_spki(), signer.public_key_id())
        .expect("prepared canonical key");
    let verifier = H7ArtifactVerifier::from_pinned_pq_verifier(
        signer.signer_id(),
        signer.signer_epoch(),
        key,
        signer.public_key_id(),
    )
    .expect("owned pinned verifier");
    let envelope = signer
        .sign(
            &artifact,
            None,
            H7SignedArtifactTransition::Reload,
            0,
            None,
            ISSUED,
            EXPIRES,
        )
        .expect("real PQ envelope");
    verifier
        .verify(&envelope, &artifact, None, NOW, 0, None)
        .expect("complete artifact verification");
    assert_eq!(verifier.pq_public_key_id(), Some(signer.public_key_id()));

    let mut corrupt = envelope.clone();
    let mut signature = STANDARD.decode(&corrupt.signature_base64).unwrap();
    signature[100] ^= 1;
    corrupt.signature_base64 = STANDARD.encode(signature);
    assert_eq!(
        verifier.verify_envelope_signature(&corrupt, NOW),
        Err(H7SignedArtifactError::SignatureInvalid)
    );
    assert_eq!(
        verifier.verify_envelope_signature(&envelope, EXPIRES),
        Err(H7SignedArtifactError::Expired)
    );
    let mut promoted = envelope;
    promoted.production_authority = true;
    promoted.envelope_sha256 = promoted.payload_digest();
    promoted.signature_base64 = STANDARD.encode(
        signer
            .signing_key
            .sign_exact_message(&promoted.signing_bytes())
            .unwrap(),
    );
    assert_eq!(
        verifier.verify_envelope_signature(&promoted, NOW),
        Err(H7SignedArtifactError::ProductionBoundary)
    );
}

#[test]
fn pq_owned_verifier_refuses_identity_epoch_and_key_pin_mismatch() {
    let signer = pq_signer(/*seed*/ 97);
    let mut other_pin = signer.public_key_id();
    other_pin[0] ^= 1;
    for (id, epoch, pin) in [
        ("", signer.signer_epoch(), signer.public_key_id()),
        (signer.signer_id(), 0, signer.public_key_id()),
        (signer.signer_id(), signer.signer_epoch(), [0; 32]),
        (signer.signer_id(), signer.signer_epoch(), other_pin),
    ] {
        let key = PqNativeVerifier::from_pinned_spki(signer.public_spki(), signer.public_key_id())
            .expect("prepared key remains valid");
        assert!(H7ArtifactVerifier::from_pinned_pq_verifier(id, epoch, key, pin).is_err());
    }
    let other = pq_signer(/*seed*/ 98);
    let key = PqNativeVerifier::from_pinned_spki(other.public_spki(), other.public_key_id())
        .expect("other valid key");
    assert!(
        H7ArtifactVerifier::from_pinned_pq_verifier(
            signer.signer_id(),
            signer.signer_epoch(),
            key,
            signer.public_key_id(),
        )
        .is_err()
    );
}
