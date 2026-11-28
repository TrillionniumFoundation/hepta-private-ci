use super::*;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

fn documents() -> (Value, Value, Value) {
    let scope = Digest32::of_bytes(b"scope").to_string();
    let objective = Digest32::of_bytes(b"objective").to_string();
    let pin = json!({
        "schema_version": 1, "operation": "hepta.learning-ledger.root-pin.v1",
        "root_id": "codec-root", "scope_digest": scope,
        "verifying_key": vec![7_u8; 32], "valid_from": 10, "expires_at": 100,
        "revoked_at": 95,
    });
    // These synthetic bytes are intentionally not a valid Root signature.
    let distribution = json!({
        "schema_version": 1, "operation": "hepta.learning-ledger.signed-distribution.v1",
        "root_id": "codec-root", "distribution_id": "codec-distribution",
        "generation": 2, "effective_at": 30, "issued_at": 20, "expires_at": 90,
        "signature": (0_u8..64).collect::<Vec<_>>(), "scope_digest": scope,
        "objective_digest": objective, "authority_epoch": 5,
        "signers": [{
            "principal_id": "codec-principal",
            "credential_chain_digest": Digest32::of_bytes(b"credential").to_string(),
            "signing_key_digest": Digest32::of_bytes(&[9_u8; 32]).to_string(),
            "scope_digest": scope, "authority_epoch": 5,
            "authenticated_at": 15, "expires_at": 80,
            "controller_id": "codec-controller", "verifying_key": vec![9_u8; 32],
            "roles": ["generator", "observer", "evaluator", "credit_allocator", "unlearning_authority", "selector"],
            "revoked_at": 75,
        }],
    });
    let acknowledgement = json!({
        "schema_version": 1, "operation": "hepta.learning-ledger.root-ack-declaration.v1",
        "owner_id": "codec-agent", "workspace_digest": Digest32::of_bytes(b"workspace").to_string(),
        "objective_digest": objective, "ledger_binding": Digest32::of_bytes(b"ledger").to_string(),
        "sequence": 3, "chain_digest": Digest32::of_bytes(b"chain").to_string(),
    });
    (pin, distribution, acknowledgement)
}

fn decode(
    pin: Value,
    distribution: Value,
    acknowledgement: Value,
) -> io::Result<OriginalLearningTrustInputs> {
    OriginalLearningTrustInputs::from_parts(
        serde_json::from_slice(&serde_json::to_vec(&pin).map_err(io::Error::other)?)
            .map_err(io::Error::other)?,
        serde_json::from_slice(&serde_json::to_vec(&distribution).map_err(io::Error::other)?)
            .map_err(io::Error::other)?,
        serde_json::from_slice(&serde_json::to_vec(&acknowledgement).map_err(io::Error::other)?)
            .map_err(io::Error::other)?,
    )
}

#[test]
fn complete_material_maps_to_exact_native_values_without_authority()
-> Result<(), Box<dyn std::error::Error>> {
    let (pin, distribution, acknowledgement) = documents();
    let expected_ack: RootAcknowledgementDeclaration =
        serde_json::from_value(acknowledgement.clone())?;
    let input = decode(pin, distribution, acknowledgement)?;
    let scope = Digest32::of_bytes(b"scope");
    let expected_root = LearningTrustRootV1 {
        root_id: StableId::new("codec-root")?,
        scope_digest: scope,
        verifying_key: [7; 32],
        valid_from: 10,
        expires_at: 100,
        revoked_at: Some(95),
    };
    let expected_signed = SignedLearningTrustDistributionV1 {
        root_id: StableId::new("codec-root")?,
        issued_at: 20,
        expires_at: 90,
        signature: std::array::from_fn(|index| index as u8),
        distribution: LearningTrustDistributionV1 {
            distribution_id: StableId::new("codec-distribution")?,
            generation: 2,
            effective_at: 30,
            trust: LearningEvidenceTrustV1 {
                scope_digest: scope,
                objective_digest: Digest32::of_bytes(b"objective"),
                authority_epoch: 5,
                signers: vec![TrustedLearningSignerV1 {
                    principal: AuthenticatedPrincipalV1 {
                        principal_id: StableId::new("codec-principal")?,
                        credential_chain_digest: Digest32::of_bytes(b"credential"),
                        signing_key_digest: Digest32::of_bytes(&[9; 32]),
                        scope_digest: scope,
                        authority_epoch: 5,
                        authenticated_at: 15,
                        expires_at: 80,
                    },
                    controller_id: StableId::new("codec-controller")?,
                    verifying_key: [9; 32],
                    roles: vec![
                        LearningEvidenceRoleV1::Generator,
                        LearningEvidenceRoleV1::Observer,
                        LearningEvidenceRoleV1::Evaluator,
                        LearningEvidenceRoleV1::CreditAllocator,
                        LearningEvidenceRoleV1::UnlearningAuthority,
                        LearningEvidenceRoleV1::Selector,
                    ],
                    revoked_at: Some(75),
                }],
            },
        },
    };
    assert_eq!(
        (input.root, input.signed, input.acknowledgement),
        (expected_root, expected_signed, expected_ack)
    );
    Ok(())
}

#[test]
fn strict_json_profiles_reject_duplicates_unknown_fields_and_versions()
-> Result<(), Box<dyn std::error::Error>> {
    let (pin, distribution, acknowledgement) = documents();
    let duplicate_pin =
        serde_json::to_string(&pin)?.replacen('{', "{\"schema_version\":1,", /*count*/ 1);
    let duplicate_distribution =
        serde_json::to_string(&distribution)?.replacen('{', "{\"generation\":2,", /*count*/ 1);
    let duplicate_ack = serde_json::to_string(&acknowledgement)?.replacen(
        '{',
        "{\"sequence\":3,",
        /*count*/ 1,
    );
    let duplicate_signer = serde_json::to_string(&distribution["signers"][0])?.replacen(
        '{',
        "{\"principal_id\":\"codec-principal\",",
        /*count*/ 1,
    );
    assert!(serde_json::from_str::<RootPin>(&duplicate_pin).is_err());
    assert!(serde_json::from_str::<Distribution>(&duplicate_distribution).is_err());
    assert!(serde_json::from_str::<RootAcknowledgementDeclaration>(&duplicate_ack).is_err());
    assert!(serde_json::from_str::<Signer>(&duplicate_signer).is_err());
    for index in 0..4 {
        let (mut pin, mut distribution, mut acknowledgement) = documents();
        match index {
            0 => pin["extra"] = json!(true),
            1 => distribution["extra"] = json!(true),
            2 => acknowledgement["extra"] = json!(true),
            3 => distribution["signers"][0]["extra"] = json!(true),
            _ => unreachable!(),
        }
        assert!(decode(pin, distribution, acknowledgement).is_err());
    }
    for index in 0..3 {
        let (mut pin, mut distribution, mut acknowledgement) = documents();
        match index {
            0 => pin["schema_version"] = json!(2),
            1 => distribution["operation"] = json!("wrong-profile"),
            2 => acknowledgement["schema_version"] = json!(2),
            _ => unreachable!(),
        }
        assert!(decode(pin, distribution, acknowledgement).is_err());
    }
    Ok(())
}

#[test]
fn native_shapes_reject_bad_ids_digests_numbers_keys_roles_and_signature_lengths() {
    for index in 0..9 {
        let (mut pin, mut distribution, acknowledgement) = documents();
        match index {
            0 => pin["root_id"] = json!(""),
            1 => distribution["signers"][0]["credential_chain_digest"] = json!("not-a-digest"),
            2 => distribution["generation"] = json!(1.0),
            3 => distribution["generation"] = json!(-1),
            4 => pin["verifying_key"] = json!(vec![0_u8; 31]),
            5 => distribution["signers"][0]["verifying_key"] = json!(vec![0_u8; 33]),
            6 => distribution["signers"][0]["roles"] = json!(["administrator"]),
            7 => distribution["signature"] = json!(vec![0_u8; 63]),
            8 => distribution["signature"] = json!(vec![0_u8; 65]),
            _ => unreachable!(),
        }
        assert!(decode(pin, distribution, acknowledgement).is_err());
    }
}

#[test]
fn input_sources_are_separate_and_mapping_does_not_discard_unverified_material()
-> Result<(), Box<dyn std::error::Error>> {
    let same = Path::new("/nonexistent-codec-fixture/material");
    let other = Path::new("/nonexistent-codec-fixture/other");
    for (pin, distribution, ack) in [
        (same, same, other),
        (same, other, same),
        (other, same, same),
    ] {
        let result = OriginalLearningTrustInputs::read_original_learning_trust_inputs(
            pin,
            distribution,
            ack,
        );
        assert_eq!(
            result.err().ok_or("same input path accepted")?.to_string(),
            "separate original Root input files required"
        );
    }
    let (pin, mut distribution, acknowledgement) = documents();
    let mut signer = distribution["signers"][0].clone();
    signer["roles"] = json!(["selector", "selector"]);
    distribution["signers"] = json!(vec![signer; 65]);
    let input = decode(pin, distribution, acknowledgement)?;
    assert_eq!(input.signed.distribution.trust.signers.len(), 65);
    assert!(
        input
            .signed
            .distribution
            .trust
            .signers
            .iter()
            .all(|signer| signer.roles == vec![LearningEvidenceRoleV1::Selector; 2])
    );
    // Later complete signature/verifier admission must reject this invalid trust;
    // the codec has not silently dropped signers or normalized duplicate roles.
    Ok(())
}
