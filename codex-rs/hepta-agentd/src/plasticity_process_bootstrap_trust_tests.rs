//! The original whole public roster remains intact through context decoding.
use super::*;
use codex_hepta_agent_components::learning_ledger::SignedLearningEvidenceV1;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde_json::json;

#[test]
fn whole_public_context_verifier_preserves_all_four_independent_roles_and_rejects_unknown_roles() {
    let scope = Digest32::of_bytes(b"fixture full learning scope");
    let objective = Digest32::of_bytes(b"fixture training objective");
    let roles = [
        ("generator", LearningEvidenceRoleV1::Generator),
        ("observer", LearningEvidenceRoleV1::Observer),
        ("evaluator", LearningEvidenceRoleV1::Evaluator),
        ("selector", LearningEvidenceRoleV1::Selector),
    ];
    let signers = roles.iter().enumerate().map(|(index, (role, _))| {
        let key = SigningKey::from_bytes(&[u8::try_from(index + 11).expect("fixture key"); 32]);
        json!({"principal":{
            "principal_id":format!("fixture.actor.{index}"),
            "credential_chain_digest":Digest32::of_bytes(format!("fixture.chain.{index}").as_bytes()).to_string(),
            "signing_key_digest":Digest32::of_bytes(&key.verifying_key().to_bytes()).to_string(),
            "scope_digest":scope.to_string(),"authority_epoch":7,"authenticated_at":10,"expires_at":100
        },"controller_id":format!("fixture.controller.{index}"),
        "verifying_key_hex":key.verifying_key().to_bytes().iter().map(|b|format!("{b:02x}")).collect::<String>(),
        "roles":[role],"revoked_at":null})
    }).collect::<Vec<_>>();
    let mut value = json!({"scope_digest":scope.to_string(),"objective_digest":objective.to_string(),"authority_epoch":7,"signers":signers});
    let descriptor: TrustDescriptorV1 =
        serde_json::from_value(value.clone()).expect("whole original public descriptor");
    let verifier =
        build_verifier(&descriptor, objective).expect("full original verifier including Selector");
    let payload = b"original whole-context role fixture";
    for (index, (_, role)) in roles.into_iter().enumerate() {
        let key = SigningKey::from_bytes(&[u8::try_from(index + 11).expect("fixture key"); 32]);
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: StableId::new(format!("fixture.evidence.{index}")).expect("id"),
            principal_id: StableId::new(format!("fixture.actor.{index}")).expect("id"),
            role,
            trust_digest: verifier.trust_digest(),
            scope_digest: scope,
            objective_digest: objective,
            authority_epoch: 7,
            issued_at: 20,
            expires_at: 90,
            payload_digest: Digest32::of_bytes(payload),
            signature: [0; 64],
        };
        evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
        verifier
            .verify(role, &evidence, payload, 50)
            .expect("same independent role remains authenticated");
        let other = if role == LearningEvidenceRoleV1::Selector {
            LearningEvidenceRoleV1::Evaluator
        } else {
            LearningEvidenceRoleV1::Selector
        };
        assert!(
            verifier.verify(other, &evidence, payload, 50).is_err(),
            "a role is not interchangeable"
        );
    }
    value["signers"][3]["roles"] = json!(["unregistered-role"]);
    let unknown: TrustDescriptorV1 =
        serde_json::from_value(value).expect("typed unknown role input");
    assert!(
        build_verifier(&unknown, objective).is_err(),
        "whole roster does not silently filter unknown roles"
    );
}
