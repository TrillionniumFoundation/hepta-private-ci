use super::*;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde_json::json;

#[test]
fn bootstrap_accepts_exact_root_signature_and_rejects_tampering()
-> Result<(), Box<dyn std::error::Error>> {
    let now = 100_u64;
    let scope = Digest32::of_bytes(b"bootstrap-scope");
    let objective = Digest32::of_bytes(b"bootstrap-objective");
    let signer_key = SigningKey::from_bytes(&[17; 32]);
    let root_key = SigningKey::from_bytes(&[23; 32]);
    let principal = AuthenticatedPrincipalV1 {
        principal_id: StableId::new("bootstrap-generator")?,
        credential_chain_digest: Digest32::of_bytes(b"bootstrap-credential"),
        signing_key_digest: Digest32::of_bytes(&signer_key.verifying_key().to_bytes()),
        scope_digest: scope,
        authority_epoch: 7,
        authenticated_at: 50,
        expires_at: 950,
    };
    let root = LearningTrustRootV1 {
        root_id: StableId::new("bootstrap-root")?,
        scope_digest: scope,
        verifying_key: root_key.verifying_key().to_bytes(),
        valid_from: 40,
        expires_at: 1_000,
        revoked_at: None,
    };
    let trust = LearningEvidenceTrustV1 {
        scope_digest: scope,
        objective_digest: objective,
        authority_epoch: 7,
        signers: vec![TrustedLearningSignerV1 {
            principal: principal.clone(),
            controller_id: StableId::new("bootstrap-controller")?,
            verifying_key: signer_key.verifying_key().to_bytes(),
            roles: vec![LearningEvidenceRoleV1::Generator],
            revoked_at: None,
        }],
    };
    let mut signed = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: StableId::new("bootstrap-distribution")?,
            generation: 1,
            effective_at: 70,
            trust,
        },
        root_id: root.root_id.clone(),
        issued_at: 60,
        expires_at: 900,
        signature: [0; 64],
    };
    signed.signature = root_key.sign(&signed.signing_bytes()?).to_bytes();
    let descriptor = json!({
        "schemaVersion": 1,
        "agentId": "019153a4-3088-7e03-a56a-9b1964f75dde",
        "spawnGeneration": 1,
        "revocationFrontierDigest": Digest32::of_bytes(b"revocation-frontier").to_string(),
        "ownerImplementationDigest": Digest32::of_bytes(b"intuition-implementation").to_string(),
        "selectedProfileDigest": Digest32::of_bytes(b"selected-profile").to_string(),
        "policyGeneration": 1,
        "modelArtifactDigest": Digest32::of_bytes(b"model").to_string(),
        "scorerContractDigest": Digest32::of_bytes(b"scorer").to_string(),
        "rngOwnerDigest": null,
        "root": {
            "rootId": root.root_id.as_str(),
            "scopeDigest": root.scope_digest.to_string(),
            "verifyingKey": root.verifying_key.to_vec(),
            "validFrom": root.valid_from,
            "expiresAt": root.expires_at,
            "revokedAt": root.revoked_at,
        },
        "distribution": {
            "distributionId": signed.distribution.distribution_id.as_str(),
            "generation": signed.distribution.generation,
            "effectiveAt": signed.distribution.effective_at,
            "scopeDigest": scope.to_string(),
            "objectiveDigest": objective.to_string(),
            "authorityEpoch": 7,
            "signers": [{
                "principalId": principal.principal_id.as_str(),
                "credentialChainDigest": principal.credential_chain_digest.to_string(),
                "signingKeyDigest": principal.signing_key_digest.to_string(),
                "scopeDigest": principal.scope_digest.to_string(),
                "authorityEpoch": principal.authority_epoch,
                "authenticatedAt": principal.authenticated_at,
                "expiresAt": principal.expires_at,
                "controllerId": "bootstrap-controller",
                "verifyingKey": signer_key.verifying_key().to_bytes().to_vec(),
                "roles": ["generator"],
                "revokedAt": null,
            }],
            "rootId": signed.root_id.as_str(),
            "issuedAt": signed.issued_at,
            "expiresAt": signed.expires_at,
            "signature": signed.signature.to_vec(),
        }
    });
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("intuition-bootstrap.json");
    std::fs::write(&path, serde_json::to_vec(&descriptor)?)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))?;
    }
    let agent_id = AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dde")?;
    let pin = Digest32::of_bytes(&serde_json::to_vec(&descriptor)?);
    let _host = load_intuition_policy_bootstrap_v1(&path, pin, agent_id.clone(), 1, now)?;
    assert!(
        load_intuition_policy_bootstrap_v1(&path, Digest32::ZERO, agent_id.clone(), 1, now)
            .is_err()
    );
    assert!(load_intuition_policy_bootstrap_v1(&path, pin, agent_id.clone(), 2, now).is_err());
    assert!(load_intuition_policy_bootstrap_v1(&path, pin, agent_id.clone(), 1, 901).is_err());
    let mut unknown = descriptor.clone();
    unknown["uncheckedAuthority"] = json!(true);
    let unknown_bytes = serde_json::to_vec(&unknown)?;
    std::fs::write(&path, &unknown_bytes)?;
    assert!(
        load_intuition_policy_bootstrap_v1(
            &path,
            Digest32::of_bytes(&unknown_bytes),
            agent_id.clone(),
            1,
            now
        )
        .is_err()
    );

    let mut tampered = descriptor;
    let signature = tampered["distribution"]["signature"]
        .as_array_mut()
        .ok_or_else(|| std::io::Error::other("signature array"))?;
    let first = signature
        .first_mut()
        .ok_or_else(|| std::io::Error::other("signature byte"))?;
    *first = json!(
        first
            .as_u64()
            .ok_or_else(|| std::io::Error::other("signature integer"))?
            ^ 1
    );
    std::fs::write(&path, serde_json::to_vec(&tampered)?)?;
    assert!(load_intuition_policy_bootstrap_v1(&path, pin, agent_id.clone(), 1, now).is_err());
    let tampered_pin = Digest32::of_bytes(&serde_json::to_vec(&tampered)?);
    assert!(load_intuition_policy_bootstrap_v1(&path, tampered_pin, agent_id, 1, now).is_err());
    Ok(())
}
