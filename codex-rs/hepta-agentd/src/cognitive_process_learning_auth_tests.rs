use super::*;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;

#[test]
fn versioned_learning_wire_requires_canonical_pq_keys_and_exact_signature_size() {
    let public = PqNativeSigningKey::public_spki_from_seed(&[73; 32].into());
    let pq = LearningKey(NativeKey::MlDsa65V2(public.to_vec()));
    let encoded = serde_json::to_string(&pq).unwrap();
    let decoded: LearningKey = serde_json::from_str(&encoded).unwrap();
    assert_eq!(decoded.0, pq.0);
    assert!(encoded.starts_with("\"ml-dsa-65-v2:"));
    let classic = LearningKey(NativeKey::ClassicalV1(
        ed25519_dalek::SigningKey::from_bytes(&[74; 32])
            .verifying_key()
            .to_bytes(),
    ));
    let encoded = serde_json::to_string(&classic).unwrap();
    assert!(!encoded.contains(PREFIX));
    assert_eq!(
        serde_json::from_str::<LearningKey>(&encoded).unwrap().0,
        classic.0
    );
    let mut malformed_spki = public.to_vec();
    malformed_spki[21] ^= 1;
    for value in [
        format!("ml-dsa-65-v1:{}", hex(&public)),
        hex(&public),
        format!("{PREFIX}{}00", hex(&public)),
        format!("{PREFIX}{}", hex(&malformed_spki)),
    ] {
        assert!(serde_json::from_value::<LearningKey>(serde_json::Value::String(value)).is_err());
    }
    let signature = LearningSignature(NativeSignature::MlDsa65V2(vec![0; 3309]));
    let encoded = serde_json::to_string(&signature).unwrap();
    assert_eq!(
        serde_json::from_str::<LearningSignature>(&encoded)
            .unwrap()
            .0,
        signature.0
    );
    for bytes in [vec![0; 64], vec![0; 3308], vec![0; 3310]] {
        let value = serde_json::Value::String(format!("{PREFIX}{}", hex(&bytes)));
        assert!(serde_json::from_value::<LearningSignature>(value).is_err());
    }
}
