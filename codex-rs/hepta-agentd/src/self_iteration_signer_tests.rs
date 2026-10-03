//! Fixed test credentials only. Production always loads installer-owned keys.
use super::*;
use codex_hepta_agent_components::learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_agent_components::learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_agent_components::learning_ledger::LearningTrustDistributionV1;
use codex_hepta_agent_components::learning_ledger::LearningTrustRootV1;
use codex_hepta_agent_components::learning_ledger::SignedLearningTrustDistributionV1;
use codex_hepta_agent_components::learning_ledger::TrustedLearningSignerV1;
use codex_hepta_agent_components::learning_ledger::activate_learning_trust;

const NOW: u64 = 10_000;
const TEST_SEED: [u8; 32] = [31; 32];
fn id(value: &str) -> StableId {
    StableId::new(value).expect("test id")
}
fn trust() -> Arc<ActivatedLearningTrustV1> {
    let key = SigningKey::from_bytes(&TEST_SEED);
    let scope = Digest32::of_bytes(b"test installed scope");
    let principal = AuthenticatedPrincipalV1 {
        principal_id: id("test.generator"),
        credential_chain_digest: Digest32::of_bytes(b"test chain"),
        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
        scope_digest: scope,
        authority_epoch: 1,
        authenticated_at: NOW - 100,
        expires_at: NOW + 60_000,
    };
    let definition = LearningEvidenceTrustV1 {
        scope_digest: scope,
        objective_digest: Digest32::of_bytes(b"test objective"),
        authority_epoch: 1,
        signers: vec![TrustedLearningSignerV1 {
            principal,
            controller_id: id("test.generator.controller"),
            verifying_key: key.verifying_key().to_bytes(),
            roles: vec![LearningEvidenceRoleV1::Generator],
            revoked_at: None,
        }],
    };
    let root_key = SigningKey::from_bytes(&[99; 32]);
    let root = LearningTrustRootV1 {
        root_id: id("test.root"),
        scope_digest: scope,
        verifying_key: root_key.verifying_key().to_bytes(),
        valid_from: NOW - 200,
        expires_at: NOW + 60_000,
        revoked_at: None,
    };
    let mut distribution = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("test.distribution"),
            generation: 1,
            effective_at: NOW - 100,
            trust: definition,
        },
        root_id: root.root_id.clone(),
        issued_at: NOW - 150,
        expires_at: NOW + 60_000,
        signature: [0; 64],
    };
    distribution.signature = root_key
        .sign(&distribution.signing_bytes().expect("distribution bytes"))
        .to_bytes();
    Arc::new(activate_learning_trust(&root, distribution, None, NOW).expect("test trust"))
}
fn directory() -> tempfile::TempDir {
    let mut builder = tempfile::Builder::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        builder.permissions(std::fs::Permissions::from_mode(0o700));
    }
    builder.tempdir().expect("private test directory")
}
fn key_file(directory: &Path, seed: &[u8; 32]) -> std::path::PathBuf {
    let path = directory.join("role.key");
    std::fs::write(&path, seed).expect("write test seed");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))
            .expect("private test key");
    }
    path
}

#[test]
fn installed_key_signs_only_its_current_trusted_role_and_exact_payload() {
    let directory = directory();
    let path = key_file(directory.path(), &TEST_SEED);
    let trust = trust();
    let generator = AgentdSelfIterationLocalSignerV1::from_existing_private_key(
        Arc::clone(&trust),
        id("test.generator"),
        LearningEvidenceRoleV1::Generator,
        &path,
    )
    .expect("installed generator");
    let evidence = generator
        .sign_payload(b"actual frozen material", NOW, NOW + 1_000)
        .expect("role evidence");
    assert!(
        trust
            .verifier()
            .verify(
                LearningEvidenceRoleV1::Generator,
                &evidence,
                b"actual frozen material",
                NOW
            )
            .is_ok()
    );
    assert!(
        trust
            .verifier()
            .verify(
                LearningEvidenceRoleV1::Generator,
                &evidence,
                b"changed material",
                NOW
            )
            .is_err()
    );
    let evaluator = AgentdSelfIterationLocalSignerV1::from_existing_private_key(
        trust,
        id("test.generator"),
        LearningEvidenceRoleV1::Evaluator,
        &path,
    )
    .expect("role remains to be verified");
    assert!(
        evaluator
            .sign_payload(b"pretend acceptance", NOW, NOW + 1_000)
            .is_err()
    );
    assert!(
        generator
            .sign_payload(b"material", NOW, NOW + 3_600_001)
            .is_err()
    );
}

#[test]
fn untrusted_key_cannot_make_installed_evidence() {
    let directory = directory();
    let path = key_file(directory.path(), &[77; 32]);
    let generator = AgentdSelfIterationLocalSignerV1::from_existing_private_key(
        trust(),
        id("test.generator"),
        LearningEvidenceRoleV1::Generator,
        &path,
    )
    .expect("read key only");
    assert!(
        generator
            .sign_payload(b"material", NOW, NOW + 1_000)
            .is_err()
    );
}
