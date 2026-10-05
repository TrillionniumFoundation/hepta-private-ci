#![allow(clippy::expect_used, clippy::unwrap_used)]
use super::*;
use crate::LearningEvidenceTrustV1;
use crate::LearningTrustDistributionV1;
use crate::LearningTrustRootV1;
use crate::SignedLearningTrustDistributionV1;
use crate::activate_learning_trust;
use std::fs;
use std::os::unix::fs::PermissionsExt;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn lineage() -> UnlearningLineageRequestV1 {
    UnlearningLineageRequestV1 {
        record_id: id("fixture-record"),
        lineage_id: id("fixture-lineage"),
        source_record_id: id("fixture-source"),
        dataset_snapshot_id: id("fixture-dataset"),
        dataset_digest: digest("fixture-dataset"),
        artifact_id: id("fixture-artifact"),
        reason_digest: digest("withdrawal"),
    }
}
fn trust(now: u64, program: Digest32, wrong_controller: bool) -> ActivatedLearningTrustV1 {
    let root_key = SigningKey::from_bytes(&[99; 32]);
    let key = SigningKey::from_bytes(&[77; 32]);
    let scope = digest("fixture-scope");
    let root = LearningTrustRootV1 {
        root_id: id("fixture-root"),
        scope_digest: scope,
        verifying_key: root_key.verifying_key().to_bytes(),
        valid_from: now - 1000,
        expires_at: now + 120_000,
        revoked_at: None,
    };
    let signers = vec![TrustedLearningSignerV1 {
        principal: AuthenticatedPrincipalV1 {
            principal_id: id("fixed-root-unlearning-authority"),
            credential_chain_digest: digest("fixture-admitted-chain"),
            signing_key_digest: Digest32::of_bytes(key.verifying_key().as_bytes()),
            scope_digest: scope,
            authority_epoch: 1,
            authenticated_at: now - 1000,
            expires_at: now + 120_000,
        },
        controller_id: if wrong_controller {
            id("another-operational-controller")
        } else {
            controller(&key.verifying_key().to_bytes(), program, scope).unwrap()
        },
        verifying_key: key.verifying_key().to_bytes(),
        roles: vec![LearningEvidenceRoleV1::UnlearningAuthority],
        revoked_at: None,
    }];
    let mut signed = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("fixture-distribution"),
            generation: 1,
            effective_at: now - 1000,
            trust: LearningEvidenceTrustV1 {
                scope_digest: scope,
                objective_digest: digest("fixture-objective"),
                authority_epoch: 1,
                signers,
            },
        },
        root_id: root.root_id.clone(),
        issued_at: now - 1000,
        expires_at: now + 120_000,
        signature: [0; 64],
    };
    signed.signature = root_key.sign(&signed.signing_bytes().unwrap()).to_bytes();
    activate_learning_trust(&root, signed, None, now).unwrap()
}

#[test]
fn ordinary_process_cannot_open_or_use_root_unlearning_signing_key() {
    let now = u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis(),
    )
    .unwrap();
    let trusted = trust(now, digest("fixture-program"), false);
    let error = sign_root_learning_unlearning_v1(
        Path::new("/does-not-exist/config"),
        Path::new("/does-not-exist/key"),
        &trusted,
        &lineage(),
    )
    .unwrap_err();
    assert!(error.to_string().contains("original Root controller"));
}

#[test]
#[ignore = "Run as Root from a protected copy of this test ELF in isolated /var/lib custody"]
fn protected_root_program_signs_only_its_dedicated_current_unlearning_role() {
    let now = u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis(),
    )
    .unwrap();
    let program_path = std::env::current_exe().unwrap();
    let program = program_digest(&program_path).unwrap();
    let root = PathBuf::from(format!(
        "/var/lib/hepta/native-unlearning-authority-tests/fixture-{}-{now}",
        std::process::id()
    ));
    fs::create_dir_all(&root).unwrap();
    fs::set_permissions(&root, fs::Permissions::from_mode(0o700)).unwrap();
    let key = SigningKey::from_bytes(&[77; 32]);
    let public_path = root.join("dedicated-public");
    let key_path = root.join("dedicated-key");
    let wrong_key = root.join("wrong-key");
    let config_path = root.join("trust.json");
    for (path, bytes) in [
        (&key_path, [77; 32]),
        (&wrong_key, [78; 32]),
        (&public_path, key.verifying_key().to_bytes()),
    ] {
        fs::write(path, bytes).unwrap();
        fs::set_permissions(path, fs::Permissions::from_mode(0o600)).unwrap();
    }
    let mut value = serde_json::json!({"schema":"hepta.fixed-custody-evaluator-trust.v1",
        "root_key_path":"/unused/root", "observer_key_path":"/unused/observer", "evaluator_key_path":"/unused/evaluator",
        "generator_verifying_key_path":"/unused/generator", "generator_program_path":"/usr/bin/true",
        "generator_program_digest":digest("generator").to_string(),"scorer_path":"/usr/bin/false","scorer_digest":digest("scorer").to_string(),
        "generator_uid":123,"scope_digest":digest("fixture-scope").to_string(),"objective_digest":digest("fixture-objective").to_string(),
        "authority_epoch":1,"valid_from":now-1000,"expires_at":now+120000,
        "unlearning_authority":{"public_key_path":public_path,"program_path":program_path,"program_digest":program.to_string()}});
    fs::write(&config_path, serde_json::to_vec(&value).unwrap()).unwrap();
    fs::set_permissions(&config_path, fs::Permissions::from_mode(0o600)).unwrap();
    let trusted = trust(now, program, false);
    let signed =
        sign_root_learning_unlearning_v1(&config_path, &key_path, &trusted, &lineage()).unwrap();
    let verified = trusted
        .verifier()
        .verify(
            LearningEvidenceRoleV1::UnlearningAuthority,
            &signed,
            &unlearning_signing_payload_v1(&lineage()),
            signed.issued_at,
        )
        .unwrap();
    assert_eq!(
        verified.controller_id(),
        &controller(
            &key.verifying_key().to_bytes(),
            program,
            digest("fixture-scope")
        )
        .unwrap()
    );
    assert!(signed.expires_at <= signed.issued_at + 60_000);
    assert!(
        sign_root_learning_unlearning_v1(&config_path, &wrong_key, &trusted, &lineage()).is_err()
    );
    assert!(
        sign_root_learning_unlearning_v1(
            &config_path,
            &key_path,
            &trust(now, program, true),
            &lineage()
        )
        .is_err()
    );
    value["unlearning_authority"]["program_path"] = serde_json::json!("/usr/bin/true");
    value["unlearning_authority"]["program_digest"] = serde_json::json!(
        program_digest(Path::new("/usr/bin/true"))
            .unwrap()
            .to_string()
    );
    fs::write(&config_path, serde_json::to_vec(&value).unwrap()).unwrap();
    assert!(
        sign_root_learning_unlearning_v1(&config_path, &key_path, &trusted, &lineage()).is_err()
    );

    // The original custody factory admits the additional public role without
    // reading that role's private seed or lending its ordinary O/E signer.
    for (name, seed) in [("root", 99), ("observer", 81), ("evaluator", 82)] {
        let path = root.join(name);
        fs::write(&path, [seed; 32]).unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
        value[format!("{name}_key_path")] = serde_json::json!(path);
    }
    for (name, seed) in [("generator", 83), ("reviewer", 84)] {
        let path = root.join(name);
        fs::write(
            &path,
            SigningKey::from_bytes(&[seed; 32])
                .verifying_key()
                .to_bytes(),
        )
        .unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
    }
    value["generator_verifying_key_path"] = serde_json::json!(root.join("generator"));
    value["generator_program_path"] = serde_json::json!("/usr/bin/false");
    value["generator_program_digest"] = serde_json::json!(
        program_digest(Path::new("/usr/bin/false"))
            .unwrap()
            .to_string()
    );
    value["scorer_path"] = serde_json::json!("/usr/bin/true");
    value["scorer_digest"] = serde_json::json!(
        program_digest(Path::new("/usr/bin/true"))
            .unwrap()
            .to_string()
    );
    value["independent_reviewer"] = serde_json::json!({"public_key_path":root.join("reviewer"),
        "program_path":"/usr/bin/printf", "program_digest":program_digest(Path::new("/usr/bin/printf")).unwrap().to_string(),
        "uid":124,"gid":125,"publication_directory":root});
    value["unlearning_authority"]["program_path"] = serde_json::json!("/usr/bin/echo");
    value["unlearning_authority"]["program_digest"] = serde_json::json!(
        program_digest(Path::new("/usr/bin/echo"))
            .unwrap()
            .to_string()
    );
    fs::write(&config_path, serde_json::to_vec(&value).unwrap()).unwrap();
    let custody =
        super::super::independent_trust::IndependentTrust::open_for_cycle(&config_path, now, None)
            .unwrap();
    assert_eq!(custody.distribution.distribution.trust.signers.len(), 5);
    assert_eq!(
        custody.distribution.distribution.trust.signers[4].roles,
        vec![LearningEvidenceRoleV1::UnlearningAuthority]
    );
    assert!(
        custody
            .sign(
                LearningEvidenceRoleV1::UnlearningAuthority,
                id("forbidden-custody-sign"),
                &unlearning_signing_payload_v1(&lineage()),
                now,
                now
            )
            .is_err()
    );
    value["unlearning_authority"]["public_key_path"] =
        serde_json::json!(root.join("observer-public"));
    fs::write(
        root.join("observer-public"),
        SigningKey::from_bytes(&[81; 32]).verifying_key().to_bytes(),
    )
    .unwrap();
    fs::set_permissions(
        root.join("observer-public"),
        fs::Permissions::from_mode(0o600),
    )
    .unwrap();
    fs::write(&config_path, serde_json::to_vec(&value).unwrap()).unwrap();
    assert!(
        super::super::independent_trust::IndependentTrust::open_for_cycle(&config_path, now, None)
            .is_err()
    );
    fs::remove_dir_all(root).unwrap();
}
