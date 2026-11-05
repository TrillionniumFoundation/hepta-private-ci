//! Cryptographic statement controls; these contact no provider.
use super::*;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use ed25519_dalek::Signer;
use pretty_assertions::assert_eq;

#[test]
fn pq_contract_binds_profile_root_epoch_and_complete_authority_scope() {
    let seed = [71; 32].into();
    let spki = PqNativeSigningKey::public_spki_from_seed(&seed);
    let signer = PqNativeSigningKey::from_owned_seed(
        seed,
        ml_dsa_65_key_id_from_spki(&spki).expect("key id"),
    )
    .expect("PQ signer");
    let key = PqAuthorityTrustKey {
        key_id: "provider-contract-root".into(),
        public_key_id: signer.public_key_id(),
        public_key_spki: spki.to_vec(),
        not_before_authority_epoch: 2,
        not_after_authority_epoch: 3,
    };
    let digest = Sha256Digest::for_bytes(b"exact endpoints, headers, timeout and contract");
    let scope =
        Sha256Digest::for_bytes(b"exact agent, generation, destination, grant and trust policy");
    let message = HttpProviderEffectContractAttestation::statement_for_pq(
        "provider-contract",
        &digest,
        2,
        &scope,
    );
    let signature = signer
        .sign_exact_message(&message)
        .expect("PQ contract signature");
    let proof = HttpProviderEffectContractAttestation::verify_pq_signed(
        "provider-contract",
        digest.clone(),
        2,
        &scope,
        &signature,
        &key,
    )
    .expect("PQ attestation");
    assert_eq!(
        (
            proof.authentication_profile(),
            proof.authority_epoch(),
            proof.contract_sha256()
        ),
        (FinalUseAuthenticationProfile::MlDsa65V2, 2, &digest)
    );
    for (id, body, epoch, binding) in [
        ("different-contract", digest.clone(), 2, scope.clone()),
        (
            "provider-contract",
            Sha256Digest::for_bytes(b"different endpoint or credential"),
            2,
            scope.clone(),
        ),
        ("provider-contract", digest.clone(), 1, scope.clone()),
        ("provider-contract", digest.clone(), 4, scope.clone()),
        (
            "provider-contract",
            digest.clone(),
            2,
            Sha256Digest::for_bytes(b"another owner or trust policy"),
        ),
    ] {
        assert!(
            HttpProviderEffectContractAttestation::verify_pq_signed(
                id, body, epoch, &binding, &signature, &key
            )
            .is_err()
        );
    }
    let mut wrong = key.clone();
    wrong.public_key_id[0] ^= 1;
    assert!(
        HttpProviderEffectContractAttestation::verify_pq_signed(
            "provider-contract",
            digest.clone(),
            2,
            &scope,
            &signature,
            &wrong
        )
        .is_err()
    );
    let classic = ed25519_dalek::SigningKey::from_bytes(&[72; 32]);
    let old_message =
        HttpProviderEffectContractAttestation::statement_for("provider-contract", &digest, 2);
    let old_signature = classic.sign(&old_message).to_bytes();
    let old = HttpProviderEffectContractAttestation::verify_signed(
        "provider-contract",
        digest.clone(),
        2,
        &old_signature,
        &classic.verifying_key().to_bytes(),
    )
    .expect("explicit historical proof");
    assert_eq!(
        old.authentication_profile(),
        FinalUseAuthenticationProfile::ClassicalV1
    );
    assert!(
        HttpProviderEffectContractAttestation::verify_pq_signed(
            "provider-contract",
            digest.clone(),
            2,
            &scope,
            &old_signature,
            &key
        )
        .is_err()
    );
    let wrong_domain = signer
        .sign_exact_message(&old_message)
        .expect("signature on historical domain");
    assert!(
        HttpProviderEffectContractAttestation::verify_pq_signed(
            "provider-contract",
            digest,
            2,
            &scope,
            &wrong_domain,
            &key
        )
        .is_err()
    );
}
