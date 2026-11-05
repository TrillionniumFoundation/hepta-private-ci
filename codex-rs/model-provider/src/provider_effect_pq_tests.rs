use std::time::Duration;

use codex_hepta_contracts::ProviderEffectAdapter;
use codex_hepta_contracts::ProviderEffectIdempotencyCapability;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use http::HeaderMap;
use http::HeaderValue;
use pretty_assertions::assert_eq;

use super::HttpProviderEffectAuthenticationProfile;
use super::HttpProviderEffectContractAttestation;
use crate::HttpProviderEffectAdapter;
use crate::HttpProviderEffectConfig;

fn pq_signer(seed_byte: u8) -> PqNativeSigningKey {
    let seed = [seed_byte; 32].into();
    let spki = PqNativeSigningKey::public_spki_from_seed(&seed);
    let key_id = ml_dsa_65_key_id_from_spki(&spki).expect("canonical PQ key");
    PqNativeSigningKey::from_owned_seed(seed, key_id).expect("owned PQ signer")
}

fn pq_config(signer: &PqNativeSigningKey) -> HttpProviderEffectConfig {
    let mut config = HttpProviderEffectConfig {
        dispatch_url: "http://127.0.0.1:9/dispatch".to_string(),
        lookup_url_template: "http://127.0.0.1:9/status/{key}".to_string(),
        headers: HeaderMap::new(),
        timeout: Duration::from_secs(5),
        contract_id: "pq-contract".to_string(),
        attestation: None,
    };
    let digest = config.contract_sha256().expect("contract digest");
    let statement = HttpProviderEffectContractAttestation::statement_for_pq(
        &config.contract_id,
        &digest,
        /*authority_epoch*/ 7,
    );
    let signature = signer.sign_exact_message(&statement).expect("PQ signature");
    config.attestation = Some(
        HttpProviderEffectContractAttestation::verify_pq_signed(
            &config.contract_id,
            digest,
            /*authority_epoch*/ 7,
            &signature,
            signer.public_spki(),
            signer.public_key_id(),
        )
        .expect("PQ contract"),
    );
    config
}

#[test]
fn pq_contract_retains_verified_profile_through_adapter_construction() {
    let signer = pq_signer(31);
    let config = pq_config(&signer);
    let expected = config.attestation.clone().expect("attestation");
    assert!(expected.is_pq_verified());
    assert_eq!(
        expected.authentication_profile(),
        HttpProviderEffectAuthenticationProfile::MlDsa65V2
    );
    let adapter = HttpProviderEffectAdapter::new(config).expect("PQ adapter");
    assert_eq!(adapter.config().attestation, Some(expected));
    assert_eq!(
        adapter.capability(),
        ProviderEffectIdempotencyCapability::KeyAndStatusLookup
    );
}

#[test]
fn pq_contract_rejects_every_changed_signed_binding() {
    let signer = pq_signer(32);
    let digest = Sha256Digest::for_bytes(b"contract");
    let statement = HttpProviderEffectContractAttestation::statement_for_pq(
        "contract",
        &digest,
        /*authority_epoch*/ 7,
    );
    let signature = signer.sign_exact_message(&statement).expect("PQ signature");
    for (id, changed_digest, epoch) in [
        ("changed", digest.clone(), 7),
        ("contract", Sha256Digest::for_bytes(b"changed"), 7),
        ("contract", digest.clone(), 8),
        ("contract", digest.clone(), 0),
        ("contract\nauthority_epoch=7", digest.clone(), 7),
    ] {
        assert!(
            HttpProviderEffectContractAttestation::verify_pq_signed(
                id,
                changed_digest,
                epoch,
                &signature,
                signer.public_spki(),
                signer.public_key_id(),
            )
            .is_err(),
            "changed binding must refuse: {id} / {epoch}"
        );
    }
    let mut corrupted = signature;
    corrupted[117] ^= 1;
    for invalid in [&corrupted[..], &signature[..signature.len() - 1], &[0; 64]] {
        assert!(
            HttpProviderEffectContractAttestation::verify_pq_signed(
                "contract",
                digest.clone(),
                /*authority_epoch*/ 7,
                invalid,
                signer.public_spki(),
                signer.public_key_id(),
            )
            .is_err()
        );
    }
}

#[test]
fn pq_contract_requires_matching_pinned_key_and_exact_mldsa65_spki() {
    let signer = pq_signer(33);
    let other = pq_signer(34);
    let digest = Sha256Digest::for_bytes(b"contract");
    let statement = HttpProviderEffectContractAttestation::statement_for_pq(
        "contract",
        &digest,
        /*authority_epoch*/ 7,
    );
    let signature = signer.sign_exact_message(&statement).expect("PQ signature");
    let mut wrong_algorithm = *signer.public_spki();
    wrong_algorithm[16] ^= 1;
    for (spki, pin) in [
        (&other.public_spki()[..], signer.public_key_id()),
        (&other.public_spki()[..], other.public_key_id()),
        (&signer.public_spki()[..], other.public_key_id()),
        (&wrong_algorithm[..], signer.public_key_id()),
        (&signer.public_spki()[..32], signer.public_key_id()),
    ] {
        assert!(
            HttpProviderEffectContractAttestation::verify_pq_signed(
                "contract",
                digest.clone(),
                /*authority_epoch*/ 7,
                &signature,
                spki,
                pin,
            )
            .is_err()
        );
    }
}

#[test]
fn pq_contract_refuses_v1_and_foreign_signing_domains() {
    let signer = pq_signer(35);
    let digest = Sha256Digest::for_bytes(b"contract");
    let legacy = HttpProviderEffectContractAttestation::statement_for(
        "contract",
        &digest,
        /*authority_epoch*/ 7,
    );
    let pq_statement = HttpProviderEffectContractAttestation::statement_for_pq(
        "contract",
        &digest,
        /*authority_epoch*/ 7,
    );
    let mut foreign = pq_statement.clone();
    foreign[0] ^= 1;
    for statement in [legacy, foreign] {
        let signature = signer.sign_exact_message(&statement).expect("PQ signature");
        assert!(
            HttpProviderEffectContractAttestation::verify_pq_signed(
                "contract",
                digest.clone(),
                /*authority_epoch*/ 7,
                &signature,
                signer.public_spki(),
                signer.public_key_id(),
            )
            .is_err()
        );
    }
    let classical = SigningKey::from_bytes(&[36; 32]);
    let signature = classical.sign(&pq_statement);
    assert!(
        HttpProviderEffectContractAttestation::verify_pq_signed(
            "contract",
            digest,
            /*authority_epoch*/ 7,
            &signature.to_bytes(),
            signer.public_spki(),
            signer.public_key_id(),
        )
        .is_err()
    );
}

#[test]
fn legacy_verified_contract_cannot_claim_pq_authentication() {
    let signer = SigningKey::from_bytes(&[37; 32]);
    let digest = Sha256Digest::for_bytes(b"legacy-contract");
    let statement = HttpProviderEffectContractAttestation::statement_for(
        "legacy-contract",
        &digest,
        /*authority_epoch*/ 7,
    );
    let attestation = HttpProviderEffectContractAttestation::verify_signed(
        "legacy-contract",
        digest,
        /*authority_epoch*/ 7,
        &signer.sign(&statement).to_bytes(),
        &signer.verifying_key().to_bytes(),
    )
    .expect("legacy V1 remains valid");
    assert!(attestation.is_verified());
    assert!(!attestation.is_pq_verified());
    assert_eq!(
        attestation.authentication_profile(),
        HttpProviderEffectAuthenticationProfile::ClassicalV1
    );
}

#[test]
fn pq_adapter_refuses_endpoint_header_and_timeout_changes_after_signing() {
    let signer = pq_signer(38);
    let original = pq_config(&signer);
    let mut changed_endpoint = original.clone();
    changed_endpoint.dispatch_url = "http://127.0.0.1:9/changed".to_string();
    let mut changed_header = original.clone();
    changed_header
        .headers
        .insert("x-provider-mode", HeaderValue::from_static("changed"));
    let mut changed_timeout = original;
    changed_timeout.timeout = Duration::from_secs(6);
    for config in [changed_endpoint, changed_header, changed_timeout] {
        assert_eq!(
            HttpProviderEffectAdapter::new(config).unwrap_err(),
            "contract attestation binding is invalid"
        );
    }
}
