#!/usr/bin/env python3
"""One-shot, exact AuthBus sealed-registration test migration.

This script intentionally fails on source drift. It never creates a privileged
constructor: every external fixture goes through the production private-file
registry loader, while crate-internal settlement tests resolve the durable
registry through AuthBusAuthorityStore.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_exact(path: str, old: str, new: str, expected: int = 1) -> None:
    text = read(path)
    observed = text.count(old)
    if observed != expected:
        raise SystemExit(
            f"{path}: expected {expected} exact matches, observed {observed}: {old[:100]!r}"
        )
    write(path, text.replace(old, new))


def replace_regex(
    path: str,
    pattern: str,
    replacement: str,
    expected: int = 1,
    flags: int = re.MULTILINE | re.DOTALL,
) -> None:
    text = read(path)
    updated, count = re.subn(pattern, replacement, text, flags=flags)
    if count != expected:
        raise SystemExit(
            f"{path}: expected {expected} regex matches, observed {count}: {pattern[:100]!r}"
        )
    write(path, updated)


def migrate_outbox_tests() -> None:
    path = "codex-rs/hepta-evidence/src/authbus_outbox_tests.rs"
    replace_exact(
        path,
        "use codex_hepta_authbus::SignedMessageClaims;\n",
        "use codex_hepta_authbus::SignedMessageClaims;\n"
        "use codex_hepta_authbus_p1_3_qualification::persisted_message_issuer;\n",
    )
    replace_exact(path, "use codex_hepta_types::Generation;\n", "")
    replace_exact(
        path,
        """    let issuer = IssuerRegistration {
        issuer_id: StableId::new("issuer:queue").unwrap(),
        key_epoch: Generation::new(1).unwrap(),
        verifying_key: key.verifying_key(),
        revoked: false,
    };
""",
        """    let issuer = persisted_message_issuer(
        "issuer:queue",
        1,
        key.verifying_key().to_bytes(),
        false,
    )
    .unwrap();
""",
    )
    replace_exact(
        path,
        "    let (mut issuer, message) = fixture(1, u64::MAX);\n",
        "    let (issuer, message) = fixture(1, u64::MAX);\n",
    )
    replace_exact(
        path,
        "    issuer.revoked = true;\n",
        """    let issuer = persisted_message_issuer(
        "issuer:queue",
        1,
        SigningKey::from_bytes(&[37; 32]).verifying_key().to_bytes(),
        true,
    )
    .unwrap();
""",
    )


def migrate_quarantine_tests() -> None:
    path = "codex-rs/hepta-evidence/src/authbus_outbox_quarantine_tests.rs"
    replace_exact(
        path,
        "use codex_hepta_authbus::SignedMessageClaims;\n",
        "use codex_hepta_authbus::SignedMessageClaims;\n"
        "use codex_hepta_authbus_p1_3_qualification::persisted_message_issuer;\n",
    )
    replace_exact(path, "use codex_hepta_types::Generation;\n", "")
    replace_exact(
        path,
        """    let issuer = IssuerRegistration {
        issuer_id: StableId::new("issuer:relay").unwrap(),
        key_epoch: Generation::new(1).unwrap(),
        verifying_key: key.verifying_key(),
        revoked: false,
    };
""",
        """    let issuer = persisted_message_issuer(
        "issuer:relay",
        1,
        key.verifying_key().to_bytes(),
        false,
    )
    .unwrap();
""",
    )
    old = """    let (mut issuer, queued) = enqueue(&store, /*sequence*/ 1).await;
    let (_, other) = enqueue(&store, /*sequence*/ 2).await;
    let delivery = claim(
        &store,
        &issuer,
        queued.delivery_id,
        /*lease_ms*/ 60_000,
    )
    .await
    .unwrap();
    let mut expected = store
        .authbus_delivery_status(queued.delivery_id)
        .await
        .unwrap();
    issuer.key_epoch = Generation::new(2).unwrap();
    assert!(matches!(
        store
            .quarantine_authbus_delivery(&issuer, &delivery.lease)
            .await,
        Err(AuthBusOutboxError::Admission(
            AuthBusAdmissionError::Authentication(Error::IssuerMismatch)
        ))
    ));
    assert_eq!(
        store
            .authbus_delivery_status(queued.delivery_id)
            .await
            .unwrap(),
        expected
    );
    issuer.key_epoch = queued.key_epoch;
    issuer.revoked = true;
    assert!(matches!(
        store
            .quarantine_authbus_delivery(&issuer, &delivery.lease)
            .await,
        Err(AuthBusOutboxError::Admission(
            AuthBusAdmissionError::Authentication(Error::Revoked)
        ))
    ));
"""
    new = """    let (issuer, queued) = enqueue(&store, /*sequence*/ 1).await;
    let (_, other) = enqueue(&store, /*sequence*/ 2).await;
    let delivery = claim(
        &store,
        &issuer,
        queued.delivery_id,
        /*lease_ms*/ 60_000,
    )
    .await
    .unwrap();
    let mut expected = store
        .authbus_delivery_status(queued.delivery_id)
        .await
        .unwrap();
    let key = SigningKey::from_bytes(&[43; 32]);
    let wrong_epoch = persisted_message_issuer(
        "issuer:relay",
        2,
        key.verifying_key().to_bytes(),
        false,
    )
    .unwrap();
    assert!(matches!(
        store
            .quarantine_authbus_delivery(&wrong_epoch, &delivery.lease)
            .await,
        Err(AuthBusOutboxError::Admission(
            AuthBusAdmissionError::Authentication(Error::IssuerMismatch)
        ))
    ));
    assert_eq!(
        store
            .authbus_delivery_status(queued.delivery_id)
            .await
            .unwrap(),
        expected
    );
    let revoked = persisted_message_issuer(
        "issuer:relay",
        1,
        key.verifying_key().to_bytes(),
        true,
    )
    .unwrap();
    assert!(matches!(
        store
            .quarantine_authbus_delivery(&revoked, &delivery.lease)
            .await,
        Err(AuthBusOutboxError::Admission(
            AuthBusAdmissionError::Authentication(Error::Revoked)
        ))
    ));
"""
    replace_exact(path, old, new)


def migrate_recovery_tests() -> None:
    path = "codex-rs/hepta-evidence/src/authbus_recovery_tests.rs"
    replace_exact(
        path,
        "use codex_hepta_authbus::AuthBusAuthorityStore;\n",
        "use codex_hepta_authbus::AuthBusAuthorityHost;\n",
    )
    replace_exact(
        path,
        "use codex_hepta_authbus::SignedMessageClaims;\n",
        "use codex_hepta_authbus::SignedMessageClaims;\n"
        "use codex_hepta_authbus_p1_3_qualification::persisted_message_issuer;\n",
    )
    replace_exact(path, "use codex_hepta_types::Generation;\n", "")
    replace_exact(
        path,
        "use tempfile::TempDir;\n",
        "#[cfg(unix)]\nuse std::os::unix::fs::PermissionsExt;\n"
        "use tempfile::TempDir;\n",
    )
    replace_exact(
        path,
        """    let issuer = IssuerRegistration {
        issuer_id: StableId::new("issuer:rollback").unwrap(),
        key_epoch: Generation::new(7).unwrap(),
        verifying_key: key.verifying_key(),
        revoked: false,
    };
""",
        """    let issuer = persisted_message_issuer(
        "issuer:rollback",
        7,
        key.verifying_key().to_bytes(),
        false,
    )
    .unwrap();
""",
    )
    replace_exact(
        path,
        "#[tokio::test]\nasync fn issuer_retirement_proof_prunes_replay_rows_but_tombstone_prevents_resurrection()",
        "#[cfg(unix)]\n#[tokio::test]\nasync fn issuer_retirement_proof_prunes_replay_rows_but_tombstone_prevents_resurrection()",
    )
    old = """    let authority = AuthBusAuthorityStore::open(&temp.path().join("authbus-authority.sqlite"))
        .await
        .unwrap();
    authority
        .enroll_issuer(
            IssuerPurpose::Message,
            IssuerSpec {
                issuer_id: issuer.issuer_id.clone(),
                key_epoch: issuer.key_epoch,
                verifying_key: key.verifying_key(),
            },
        )
        .await
        .unwrap();
"""
    new = """    let authority_database_root = temp.path().join("authbus-authority-database");
    let authority_checkpoint_root = temp.path().join("authbus-authority-checkpoint");
    std::fs::create_dir_all(&authority_database_root).unwrap();
    std::fs::create_dir_all(&authority_checkpoint_root).unwrap();
    std::fs::set_permissions(
        &authority_database_root,
        std::fs::Permissions::from_mode(0o700),
    )
    .unwrap();
    std::fs::set_permissions(
        &authority_checkpoint_root,
        std::fs::Permissions::from_mode(0o700),
    )
    .unwrap();
    let authority = AuthBusAuthorityHost::bootstrap(
        &authority_database_root.join("authbus-authority.sqlite"),
        authority_checkpoint_root.join("authbus-authority-checkpoint.json"),
        "evidence-recovery-test-owner",
    )
    .await
    .unwrap();
    authority
        .enroll_issuer(
            IssuerPurpose::Message,
            IssuerSpec {
                issuer_id: issuer.issuer_id.clone(),
                key_epoch: issuer.key_epoch,
                verifying_key: key.verifying_key(),
            },
        )
        .await
        .unwrap();
"""
    replace_exact(path, old, new)


def migrate_qualification_tests() -> None:
    path = "codex-rs/hepta-evidence/src/qualification_tests.rs"
    replace_exact(
        path,
        "use codex_hepta_authbus::SignedMessageClaims;\n",
        "use codex_hepta_authbus::SignedMessageClaims;\n"
        "use codex_hepta_authbus_p1_3_qualification::persisted_message_issuer;\n",
    )
    replace_exact(path, "use codex_hepta_types::Generation;\n", "")
    old = """fn issuer(principal: &str, seed: u8) -> (IssuerRegistration, SigningKey) {
    let key = SigningKey::from_bytes(&[seed; 32]);
    (
        IssuerRegistration {
            issuer_id: StableId::new(principal).expect("principal"),
            key_epoch: Generation::new(1).expect("epoch"),
            verifying_key: key.verifying_key(),
            revoked: false,
        },
        key,
    )
}

fn issuer_with_key(principal: &str, key: &SigningKey) -> IssuerRegistration {
    IssuerRegistration {
        issuer_id: StableId::new(principal).expect("principal"),
        key_epoch: Generation::new(1).expect("epoch"),
        verifying_key: key.verifying_key(),
        revoked: false,
    }
}
"""
    new = """fn issuer(principal: &str, seed: u8) -> (IssuerRegistration, SigningKey) {
    let key = SigningKey::from_bytes(&[seed; 32]);
    let issuer = persisted_message_issuer(
        principal,
        1,
        key.verifying_key().to_bytes(),
        false,
    )
    .expect("persisted issuer");
    (issuer, key)
}

fn issuer_with_key(principal: &str, key: &SigningKey) -> IssuerRegistration {
    persisted_message_issuer(
        principal,
        1,
        key.verifying_key().to_bytes(),
        false,
    )
    .expect("persisted issuer")
}
"""
    replace_exact(path, old, new)


def migrate_agentd_product_test() -> None:
    path = "codex-rs/hepta-agentd/tests/kernel_evidence_product.rs"
    replace_exact(
        path,
        "use codex_hepta_authbus::SignedMessage;\n",
        "use codex_hepta_authbus::SignedMessage;\n"
        "use codex_hepta_authbus_p1_3_qualification::persisted_message_issuer;\n",
    )
    old = """    let issuer = IssuerRegistration {
        issuer_id: StableId::new(issuer_id.to_string()).map_err(anyhow::Error::msg)?,
        key_epoch: Generation::new(1).map_err(anyhow::Error::msg)?,
        verifying_key: key.verifying_key(),
        revoked: false,
    };
"""
    new = """    let issuer = persisted_message_issuer(
        issuer_id,
        1,
        key.verifying_key().to_bytes(),
        false,
    )
    .map_err(anyhow::Error::msg)?;
"""
    replace_exact(path, old, new)
    text = read(path)
    if "Generation::" not in text:
        text = text.replace("use codex_hepta_types::Generation;\n", "")
    if "StableId::" not in text:
        text = text.replace("use codex_hepta_types::StableId;\n", "")
    if text.count("IssuerRegistration") == 1:
        text = text.replace("use codex_hepta_authbus::IssuerRegistration;\n", "")
    write(path, text)


def migrate_settlement_store_tests() -> None:
    path = "codex-rs/hepta-authbus/src/settlement_store_tests.rs"
    replace_exact(
        path,
        "use crate::PolicySpec;\n",
        "use crate::PolicySpec;\nuse crate::IssuerSpec;\n",
    )
    old = """    let store = AuthBusAuthorityStore::open(&root.path().join("authbus.sqlite"))
        .await
        .expect("open authority store");
    let scope = Digest32::of_bytes(b"provider-scope");
"""
    new = """    let store = AuthBusAuthorityStore::open(&root.path().join("authbus.sqlite"))
        .await
        .expect("open authority store");
    let settlement_key = SigningKey::from_bytes(&[9; 32]);
    store
        .enroll_issuer(
            IssuerPurpose::Settlement,
            IssuerSpec {
                issuer_id: id("issuer:settlement"),
                key_epoch: Generation::new(1).expect("generation"),
                verifying_key: settlement_key.verifying_key(),
            },
        )
        .await
        .expect("enroll settlement issuer");
    let scope = Digest32::of_bytes(b"provider-scope");
"""
    replace_exact(path, old, new)
    replace_regex(
        path,
        r"fn issuer\(key: &SigningKey\) -> SettlementIssuerRegistration \{.*?\n\}\n\nfn evidence",
        """async fn issuer(store: &AuthBusAuthorityStore) -> SettlementIssuerRegistration {
    store
        .settlement_issuer(
            &id("issuer:settlement"),
            Generation::new(1).expect("generation"),
        )
        .await
        .expect("registered settlement issuer")
}

fn evidence""",
    )
    text = read(path)
    text = text.replace("SigningKey::from_bytes(&[10; 32])", "SigningKey::from_bytes(&[9; 32])")
    text = text.replace("SigningKey::from_bytes(&[33; 32])", "SigningKey::from_bytes(&[9; 32])")
    text = text.replace("issuer(&key)", "issuer(&store).await")
    write(path, text)
    append = r'''

#[tokio::test]
async fn settlement_reloads_registry_and_rejects_forged_or_revoked_keys() {
    let (_root, store, _decision, reservation) = configured().await;
    let dispatched = store
        .mark_dispatch_attempted(
            &reservation.reservation_id,
            reservation.revision,
            reservation.effect_digest,
            sample(5, 1_500),
        )
        .await
        .expect("mark dispatch");
    let sealed = issuer(&store).await;
    let forged_key = SigningKey::from_bytes(&[88; 32]);
    let forged = evidence(
        &forged_key,
        &dispatched,
        SettlementStatus::Completed,
        5,
        1_600,
    );
    assert!(matches!(
        store.settle(&sealed, &forged, sample(6, 1_600)).await,
        Err(AuthBusAuthorityError::InvalidSettlementSignature)
    ));

    store
        .revoke_issuer(
            IssuerPurpose::Settlement,
            &sealed.issuer_id,
            sealed.key_epoch,
            sealed.registry_revision(),
        )
        .await
        .expect("revoke settlement issuer");
    let trusted_key = SigningKey::from_bytes(&[9; 32]);
    let legitimate = evidence(
        &trusted_key,
        &dispatched,
        SettlementStatus::Completed,
        5,
        1_700,
    );
    assert!(matches!(
        store
            .settle(&sealed, &legitimate, sample(7, 1_700))
            .await,
        Err(AuthBusAuthorityError::SettlementIssuerRevoked)
    ));
}

#[tokio::test]
async fn message_purpose_cannot_be_substituted_for_settlement_purpose() {
    let root = TempDir::new().expect("temp dir");
    let store = AuthBusAuthorityStore::open(&root.path().join("authbus.sqlite"))
        .await
        .expect("open authority store");
    let key = SigningKey::from_bytes(&[9; 32]);
    store
        .enroll_issuer(
            IssuerPurpose::Message,
            IssuerSpec {
                issuer_id: id("issuer:settlement"),
                key_epoch: Generation::new(1).expect("generation"),
                verifying_key: key.verifying_key(),
            },
        )
        .await
        .expect("enroll message issuer");
    assert!(matches!(
        store
            .settlement_issuer(
                &id("issuer:settlement"),
                Generation::new(1).expect("generation"),
            )
            .await,
        Err(AuthBusAuthorityError::IssuerMissing)
    ));
}

#[tokio::test]
async fn bounded_expired_reservation_sweep_refunds_only_undispatched_holds() {
    let (_root, store, _decision, reservation) = configured().await;
    let report = store
        .sweep_expired_reservations(sample(5, 5_100), 1)
        .await
        .expect("sweep expired holds");
    assert_eq!((report.examined, report.expired_held, report.marked_indeterminate), (1, 1, 0));
    assert!(!report.remaining);
    assert_eq!(
        store
            .reservation(&reservation.reservation_id)
            .await
            .expect("reservation")
            .state,
        ReservationState::Expired
    );
    let quota = store
        .quota_snapshot(&reservation.quota_key)
        .await
        .expect("quota");
    assert_eq!((quota.available, quota.reserved, quota.consumed), (10, 0, 0));
    let empty = store
        .sweep_expired_reservations(sample(6, 5_200), 1)
        .await
        .expect("empty sweep");
    assert_eq!(empty.examined, 0);
}
'''
    text = read(path)
    if "settlement_reloads_registry_and_rejects_forged_or_revoked_keys" in text:
        raise SystemExit(f"{path}: hardening tests already present")
    write(path, text.rstrip() + append + "\n")


def migrate_bao_product_test() -> None:
    path = "codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs"
    replace_exact(path, "use codex_hepta_authbus::AuthBusAuthorityStore;\n", "")
    old = """    use std::io::Write;
    use std::os::unix::fs::OpenOptionsExt;

"""
    replace_exact(path, old, "")
    old = """    let raw = AuthBusAuthorityStore::open(&database).await?;
    let frontier = raw.authority_frontier_digest().await?;
    drop(raw);
    let document = serde_json::json!({
        "schema_version": 1,
        "owner_id": "bao-product-owner",
        "generation": 1,
        "digest": frontier.to_string(),
    });
    let mut file = std::fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(&checkpoint)?;
    serde_json::to_writer(&mut file, &document)?;
    file.flush()?;
    file.sync_all()?;

    let host = AuthBusAuthorityHost::open(&database, checkpoint, "bao-product-owner").await?;
"""
    new = """    let host =
        AuthBusAuthorityHost::bootstrap(&database, checkpoint, "bao-product-owner").await?;
"""
    replace_exact(path, old, new)


def assert_closed_world() -> None:
    allowed_registration_literals = {
        ROOT / "codex-rs/hepta-authbus/src/signed.rs",
        ROOT / "codex-rs/hepta-authbus/src/settlement.rs",
    }
    violations: list[str] = []
    for path in (ROOT / "codex-rs").rglob("*.rs"):
        text = path.read_text(encoding="utf-8")
        if path not in allowed_registration_literals:
            if re.search(r"\bIssuerRegistration\s*\{", text):
                violations.append(f"constructible message issuer: {path.relative_to(ROOT)}")
            if re.search(r"\bSettlementIssuerRegistration\s*\{", text):
                violations.append(f"constructible settlement issuer: {path.relative_to(ROOT)}")
        if (
            "use codex_hepta_authbus::AuthBusAuthorityStore;" in text
            and "codex-rs/hepta-authbus/" not in path.as_posix()
        ):
            violations.append(f"external raw authority writer: {path.relative_to(ROOT)}")
    if violations:
        raise SystemExit("closed-world inventory failed:\n" + "\n".join(sorted(violations)))


def main() -> None:
    migrate_outbox_tests()
    migrate_quarantine_tests()
    migrate_recovery_tests()
    migrate_qualification_tests()
    migrate_agentd_product_test()
    migrate_settlement_store_tests()
    migrate_bao_product_test()
    assert_closed_world()
    print("AuthBus sealed-registration migration completed")


if __name__ == "__main__":
    main()
