#![cfg(unix)]

use std::os::unix::fs::PermissionsExt;
use std::path::Path;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_evidence::EvidenceIssuerRoleV1;
use codex_hepta_evidence::EvidenceIssuerView;
use codex_hepta_evidence::EvidenceTrustSnapshotView;
use codex_hepta_evidence::HeptaEvidenceStore;
use codex_hepta_evidence::VerifiedEvidenceTrustSnapshot;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use ed25519_dalek::SigningKey;
use tempfile::TempDir;

async fn open(temp: &TempDir) -> HeptaEvidenceStore {
    std::fs::set_permissions(temp.path(), std::fs::Permissions::from_mode(0o700))
        .expect("private home");
    let config = SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute home"),
    );
    HeptaEvidenceStore::open(&config)
        .await
        .expect("evidence store")
}

fn registry(path: &Path, revoked: bool) -> Sha256Digest {
    let key = SigningKey::from_bytes(&[7_u8; 32]).verifying_key();
    let hex = key
        .as_bytes()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    // Production-pinned trust must exercise the monotonic V2 format. Keep the
    // field order canonical so this fixture tests the same bytes admitted by
    // `VerifiedEvidenceTrustSnapshot` rather than serde map ordering.
    let bytes = format!(
        "{{\"agent_id\":\"agent:test\",\"generation\":1,\"issuers\":[{{\"issuer_id\":\"issuer:test\",\"key_epoch\":1,\"public_key_hex\":\"{hex}\",\"revoked\":{revoked},\"roles\":[\"evaluator\"]}}],\"predecessor_sha256\":null,\"schema_version\":2}}"
    )
    .into_bytes();
    std::fs::write(path, &bytes).expect("registry bytes");
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))
        .expect("private registry");
    Sha256Digest::for_bytes(&bytes)
}

#[tokio::test]
async fn admitted_digest_rejects_a_valid_but_old_registry() {
    let temp = TempDir::new().expect("temp");
    let store = open(&temp).await;
    let path = temp.path().join("trust.json");
    let current = registry(&path, true);
    registry(&path, false);
    assert!(
        VerifiedEvidenceTrustSnapshot::load_owner_registry(
            &store,
            &path,
            "agent:test",
            Some(&current),
        )
        .is_err()
    );
    store.close().await;
}

#[tokio::test]
async fn already_verified_snapshot_rejects_changed_owner_bytes() {
    let temp = TempDir::new().expect("temp");
    let store = open(&temp).await;
    let path = temp.path().join("trust.json");
    let pin = registry(&path, false);
    let snapshot =
        VerifiedEvidenceTrustSnapshot::load_owner_registry(&store, &path, "agent:test", Some(&pin))
            .expect("verified snapshot");
    assert!(snapshot.validate_store(&store).is_ok());
    registry(&path, true);
    assert!(snapshot.validate_store(&store).is_err());
    store.close().await;
}

#[tokio::test]
async fn verified_issuer_cannot_cross_store_or_role_boundaries() {
    let temp = TempDir::new().expect("temp");
    let other_temp = TempDir::new().expect("other temp");
    let store = open(&temp).await;
    let other = open(&other_temp).await;
    let path = temp.path().join("trust.json");
    let pin = registry(&path, false);
    let snapshot =
        VerifiedEvidenceTrustSnapshot::load_owner_registry(&store, &path, "agent:test", Some(&pin))
            .expect("snapshot");
    let issuer = snapshot
        .issuer_for("issuer:test", 1, EvidenceIssuerRoleV1::Evaluator)
        .expect("issuer");
    assert!(
        issuer
            .validate_for(&store, EvidenceIssuerRoleV1::Evaluator)
            .is_ok()
    );
    assert!(
        issuer
            .validate_for(&other, EvidenceIssuerRoleV1::Evaluator)
            .is_err()
    );
    assert!(
        issuer
            .validate_for(&store, EvidenceIssuerRoleV1::Security)
            .is_err()
    );
    store.close().await;
    other.close().await;
}

#[tokio::test]
async fn revoked_registration_cannot_construct_a_verified_issuer() {
    let temp = TempDir::new().expect("temp");
    let store = open(&temp).await;
    let path = temp.path().join("trust.json");
    let pin = registry(&path, true);
    let snapshot =
        VerifiedEvidenceTrustSnapshot::load_owner_registry(&store, &path, "agent:test", Some(&pin))
            .expect("revocation registry remains readable");
    assert!(
        snapshot
            .issuer_for("issuer:test", 1, EvidenceIssuerRoleV1::Evaluator)
            .is_err()
    );
    store.close().await;
}

#[tokio::test]
async fn registry_agent_identity_is_not_caller_substitutable() {
    let temp = TempDir::new().expect("temp");
    let store = open(&temp).await;
    let path = temp.path().join("trust.json");
    let pin = registry(&path, false);
    assert!(
        VerifiedEvidenceTrustSnapshot::load_owner_registry(
            &store,
            &path,
            "agent:other",
            Some(&pin),
        )
        .is_err()
    );
    store.close().await;
}
