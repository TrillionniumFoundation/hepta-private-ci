//! Sealed data checks only. These fixtures never construct a Root trust capsule.

use super::*;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use ed25519_dalek::SigningKey;
use serde_json::json;

fn deployment() -> serde_json::Value {
    json!({
        "schema": "hepta.agentd.original_initial_q24_ledger.v1",
        "mode": "create",
        "ledger": "/original/ledger",
        "ledger_witness": "/original/ledger.witness",
        "binding": vec![1_u8; 32],
        "maximum_records": 4,
        "generator_key": "/original/generator.key",
        "signature_journal": "/original/signatures",
        "signature_witness": {
            "path": "/original/signatures.witness",
            "scope": vec![2_u8; 32],
            "generation": 1,
            "maximum_records": 5
        },
        "contract": {
            "episode_id": "original-episode",
            "candidate_set_id": "original-candidate-set",
            "generator_code_digest": vec![3_u8; 32],
            "grammar_digest": vec![4_u8; 32],
            "hard_filter_digest": vec![5_u8; 32],
            "truncation_digest": vec![6_u8; 32],
            "outcome_record_id": "original-outcome-record",
            "outcome_id": "original-outcome",
            "unit_profile_digest": vec![7_u8; 32],
            "expected_delay_profile_digest": vec![8_u8; 32],
            "claim_deadline_unix_seconds": 100,
            "maximum_signature_lifetime_seconds": 60
        }
    })
}

fn signer(
    name: &str,
    role: LearningEvidenceRoleV1,
    seed: u8,
) -> anyhow::Result<TrustedLearningSignerV1> {
    let verifying_key = SigningKey::from_bytes(&[seed; 32])
        .verifying_key()
        .to_bytes();
    Ok(TrustedLearningSignerV1 {
        principal: AuthenticatedPrincipalV1 {
            principal_id: StableId::new(name)?,
            credential_chain_digest: Digest32::of_bytes(name.as_bytes()),
            signing_key_digest: Digest32::of_bytes(&verifying_key),
            scope_digest: Digest32::of_bytes(b"fixture-scope"),
            authority_epoch: 1,
            authenticated_at: 1,
            expires_at: 200,
        },
        controller_id: StableId::new(format!("{name}-controller"))?,
        verifying_key,
        roles: vec![role],
        revoked_at: None,
    })
}

#[test]
fn initial_q24_ledger_data_requires_explicit_create_without_authority_fields() -> anyhow::Result<()>
{
    let _: LedgerDeploymentData = serde_json::from_value(deployment())?;
    for (pointer, value) in [
        ("/mode", json!("recover")),
        ("/root_key", json!(vec![1_u8; 32])),
        ("/generator", json!({"principal_id": "self-selected"})),
        ("/observer", json!({"controller_id": "self-selected"})),
        ("/contract/trust", json!({})),
        ("/signature_witness/objective", json!(vec![1_u8; 32])),
    ] {
        let mut value_with_field = deployment();
        let (parent, field) = pointer
            .rsplit_once('/')
            .ok_or_else(|| anyhow::anyhow!("fixture pointer"))?;
        value_with_field
            .pointer_mut(parent)
            .ok_or_else(|| anyhow::anyhow!("fixture parent"))?[field] = value;
        assert!(
            serde_json::from_value::<LedgerDeploymentData>(value_with_field).is_err(),
            "accepted {pointer}"
        );
    }
    let mut absent = deployment();
    let _removed = absent
        .as_object_mut()
        .ok_or_else(|| anyhow::anyhow!("fixture object"))?
        .remove("mode");
    assert!(serde_json::from_value::<LedgerDeploymentData>(absent).is_err());
    Ok(())
}

#[test]
fn initial_q24_ledger_data_preserves_fixed_roles_and_original_deadline() -> anyhow::Result<()> {
    let data: LedgerDeploymentData = serde_json::from_value(deployment())?;
    let generator = signer(
        "fixed-generator",
        LearningEvidenceRoleV1::Generator,
        /*seed*/ 11,
    )?;
    let observer = signer(
        "fixed-observer",
        LearningEvidenceRoleV1::Observer,
        /*seed*/ 12,
    )?;
    let config = data.configuration(generator.clone(), observer.clone(), /*now*/ 99)?;
    assert_eq!(
        (
            config.generator,
            config.observer,
            config.claim_deadline_unix_seconds,
            config.maximum_signature_lifetime_seconds,
        ),
        (generator.clone(), observer.clone(), 100, 60),
    );
    assert!(
        data.configuration(generator, observer, /*now*/ 100)
            .is_err()
    );
    Ok(())
}

#[test]
fn initial_q24_ledger_data_rejects_invalid_original_contract_and_capacity() -> anyhow::Result<()> {
    let generator = signer(
        "fixed-generator",
        LearningEvidenceRoleV1::Generator,
        /*seed*/ 11,
    )?;
    let observer = signer(
        "fixed-observer",
        LearningEvidenceRoleV1::Observer,
        /*seed*/ 12,
    )?;
    for (pointer, invalid_value) in [
        ("/schema", json!("hepta.untrusted.v1")),
        ("/binding", json!(vec![0_u8; 32])),
        ("/maximum_records", json!(3)),
        ("/maximum_records", json!(8193)),
        ("/signature_witness/scope", json!(vec![0_u8; 32])),
        ("/signature_witness/generation", json!(0)),
        ("/signature_witness/maximum_records", json!(4)),
        ("/signature_witness/maximum_records", json!(4097)),
        ("/contract/episode_id", json!("")),
        ("/contract/candidate_set_id", json!("x".repeat(129))),
        ("/contract/generator_code_digest", json!(vec![0_u8; 32])),
        (
            "/contract/expected_delay_profile_digest",
            json!(vec![0_u8; 32]),
        ),
        ("/contract/claim_deadline_unix_seconds", json!(20)),
        ("/contract/maximum_signature_lifetime_seconds", json!(0)),
        ("/contract/maximum_signature_lifetime_seconds", json!(86401)),
    ] {
        let mut invalid_data = deployment();
        *invalid_data
            .pointer_mut(pointer)
            .ok_or_else(|| anyhow::anyhow!("fixture pointer"))? = invalid_value;
        let invalid_data: LedgerDeploymentData = serde_json::from_value(invalid_data)?;
        assert!(
            invalid_data
                .configuration(generator.clone(), observer.clone(), /*now*/ 20)
                .is_err(),
            "accepted {pointer}"
        );
    }
    Ok(())
}
