#!/usr/bin/env python3
"""One-shot source migration for the sealed AuthBus authority boundary."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace(path: str, old: str, new: str, count: int = 1) -> None:
    text = read(path)
    observed = text.count(old)
    if observed != count:
        raise SystemExit(f"{path}: expected {count} exact occurrence(s), found {observed}")
    write(path, text.replace(old, new))


def sub(path: str, pattern: str, replacement: str, count: int = 1) -> None:
    text = read(path)
    updated, observed = re.subn(pattern, replacement, text, count=count, flags=re.DOTALL)
    if observed != count:
        raise SystemExit(f"{path}: expected {count} regex occurrence(s), found {observed}")
    write(path, updated)


# Make the source inventory distinguish a Rust return type from a struct literal
# without weakening the external construction check.
replace(
    "scripts/check-authbus-closed-world.py",
    '''def verify_boundaries() -> list[str]:
    errors: list[str] = []
''',
    '''def contains_registration_literal(text: str, type_name: str) -> bool:
    for match in re.finditer(rf"\\b{re.escape(type_name)}\\s*\\{{", text):
        line_start = text.rfind("\\n", 0, match.start()) + 1
        prefix = text[line_start : match.start()]
        if re.search(r"(?:->|\\bstruct)\\s*$", prefix):
            continue
        return True
    return False


def verify_boundaries() -> list[str]:
    errors: list[str] = []
''',
)
replace(
    "scripts/check-authbus-closed-world.py",
    '''        if path != allowed_message_literal and re.search(
            r"\\bIssuerRegistration\\s*\\{", text
        ):
''',
    '''        if path != allowed_message_literal and contains_registration_literal(
            text, "IssuerRegistration"
        ):
''',
)
replace(
    "scripts/check-authbus-closed-world.py",
    '''        if path != allowed_settlement_literal and re.search(
            r"\\bSettlementIssuerRegistration\\s*\\{", text
        ):
''',
    '''        if path != allowed_settlement_literal and contains_registration_literal(
            text, "SettlementIssuerRegistration"
        ):
''',
)

# Bao product tests bootstrap through the public host, never the raw writer.
replace(
    "codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs",
    "use codex_hepta_authbus::AuthBusAuthorityStore;\n",
    "",
)
replace(
    "codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs",
    "    use std::io::Write;\n    use std::os::unix::fs::OpenOptionsExt;\n\n",
    "",
)
replace(
    "codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs",
    '''    let raw = AuthBusAuthorityStore::open(&database).await?;
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
''',
    '''    let host =
        AuthBusAuthorityHost::bootstrap(&database, checkpoint, "bao-product-owner").await?;
''',
)

# The direct Agentd recovery fixture resolves a sealed handle from an independently
# persisted private registry instead of constructing trusted fields in memory.
replace(
    "codex-rs/hepta-agentd/tests/kernel_evidence_product.rs",
    "use codex_hepta_authbus::IssuerRegistration;\n",
    "use codex_hepta_authbus::PrivateIssuerRegistryDocument;\n",
)
replace(
    "codex-rs/hepta-agentd/tests/kernel_evidence_product.rs",
    "use codex_hepta_types::Generation;\nuse codex_hepta_types::StableId;\n",
    "",
)
replace(
    "codex-rs/hepta-agentd/tests/kernel_evidence_product.rs",
    '''    let message = SignedMessage {
        signature: key.sign(&claims.signing_bytes()).to_bytes(),
        claims,
    };
    let issuer = IssuerRegistration {
        issuer_id: StableId::new(issuer_id.to_string()).map_err(anyhow::Error::msg)?,
        key_epoch: Generation::new(1).map_err(anyhow::Error::msg)?,
        verifying_key: key.verifying_key(),
        revoked: false,
    };
''',
    '''    let registry_root = tempfile::tempdir()?;
    std::fs::set_permissions(
        registry_root.path(),
        std::fs::Permissions::from_mode(0o700),
    )?;
    let registry_path = registry_root.path().join("message-issuer-registry.json");
    write_private_json(
        &registry_path,
        &json!({
            "issuer_id": issuer_id,
            "key_epoch": 1,
            "public_key_hex": hex(key.verifying_key().as_bytes()),
            "revoked": false,
        }),
    )?;
    let registry = PrivateIssuerRegistryDocument::load(
        &registry_path,
        registry_root.path(),
        16 * 1024,
    )?;
    let issuer = registry.message_issuer(&claims.issuer_id, claims.key_epoch)?;
    let message = SignedMessage {
        signature: key.sign(&claims.signing_bytes()).to_bytes(),
        claims,
    };
''',
)

# Evidence outbox tests model epoch substitution and revocation with separately
# persisted registry snapshots rather than mutating trusted fields.
replace(
    "codex-rs/hepta-evidence/src/authbus_outbox_quarantine_tests.rs",
    "use std::time::Duration;\n",
    "#![cfg(unix)]\n\nuse std::os::unix::fs::PermissionsExt;\nuse std::time::Duration;\n",
)
replace(
    "codex-rs/hepta-evidence/src/authbus_outbox_quarantine_tests.rs",
    "use codex_hepta_authbus::IssuerRegistration;\n",
    "use codex_hepta_authbus::IssuerRegistration;\nuse codex_hepta_authbus::PrivateIssuerRegistryDocument;\n",
)
replace(
    "codex-rs/hepta-evidence/src/authbus_outbox_quarantine_tests.rs",
    '''fn config(path: &std::path::Path) -> SqliteConfig {
    SqliteConfig::new_for_testing(AbsolutePathBuf::try_from(path.to_path_buf()).unwrap())
}
''',
    '''fn config(path: &std::path::Path) -> SqliteConfig {
    SqliteConfig::new_for_testing(AbsolutePathBuf::try_from(path.to_path_buf()).unwrap())
}

fn issuer_registration(
    key: &SigningKey,
    epoch: u64,
    revoked: bool,
) -> IssuerRegistration {
    let root = TempDir::new().unwrap();
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let path = root.path().join("issuer-registry.json");
    let mut temporary = tempfile::NamedTempFile::new_in(root.path()).unwrap();
    temporary
        .as_file()
        .set_permissions(std::fs::Permissions::from_mode(0o600))
        .unwrap();
    serde_json::to_writer(
        temporary.as_file_mut(),
        &serde_json::json!({
            "issuer_id": "issuer:relay",
            "key_epoch": epoch,
            "public_key_hex": key
                .verifying_key()
                .as_bytes()
                .iter()
                .map(|byte| format!("{byte:02x}"))
                .collect::<String>(),
            "revoked": revoked,
        }),
    )
    .unwrap();
    temporary.as_file().sync_all().unwrap();
    temporary.persist(&path).unwrap();
    PrivateIssuerRegistryDocument::load(&path, root.path(), 16 * 1024)
        .unwrap()
        .message_issuer(
            &StableId::new("issuer:relay").unwrap(),
            Generation::new(epoch).unwrap(),
        )
        .unwrap()
}
''',
)
replace(
    "codex-rs/hepta-evidence/src/authbus_outbox_quarantine_tests.rs",
    '''    let issuer = IssuerRegistration {
        issuer_id: StableId::new("issuer:relay").unwrap(),
        key_epoch: Generation::new(1).unwrap(),
        verifying_key: key.verifying_key(),
        revoked: false,
    };
''',
    '''    let issuer = issuer_registration(&key, 1, false);
''',
)
replace(
    "codex-rs/hepta-evidence/src/authbus_outbox_quarantine_tests.rs",
    "    let (mut issuer, queued) = enqueue(&store, /*sequence*/ 1).await;\n",
    "    let (issuer, queued) = enqueue(&store, /*sequence*/ 1).await;\n",
)
replace(
    "codex-rs/hepta-evidence/src/authbus_outbox_quarantine_tests.rs",
    '''    issuer.key_epoch = Generation::new(2).unwrap();
    assert!(matches!(
        store
            .quarantine_authbus_delivery(&issuer, &delivery.lease)
''',
    '''    let key = SigningKey::from_bytes(&[43; 32]);
    let wrong_epoch = issuer_registration(&key, 2, false);
    assert!(matches!(
        store
            .quarantine_authbus_delivery(&wrong_epoch, &delivery.lease)
''',
)
replace(
    "codex-rs/hepta-evidence/src/authbus_outbox_quarantine_tests.rs",
    '''    issuer.key_epoch = queued.key_epoch;
    issuer.revoked = true;
    assert!(matches!(
        store
            .quarantine_authbus_delivery(&issuer, &delivery.lease)
''',
    '''    let revoked = issuer_registration(&key, queued.key_epoch.get(), true);
    assert!(matches!(
        store
            .quarantine_authbus_delivery(&revoked, &delivery.lease)
''',
)

# Settlement white-box tests enroll the same durable issuer record that settle
# subsequently reloads; the handle remains sealed even inside ordinary callers.
replace(
    "codex-rs/hepta-authbus/src/settlement_store_tests.rs",
    '''    let store = AuthBusAuthorityStore::open(&root.path().join("authbus.sqlite"))
        .await
        .expect("open authority store");
''',
    '''    let store = AuthBusAuthorityStore::open(&root.path().join("authbus.sqlite"))
        .await
        .expect("open authority store");
    let settlement_key = SigningKey::from_bytes(&[9; 32]);
    store
        .enroll_issuer(
            crate::IssuerPurpose::Settlement,
            crate::IssuerSpec {
                issuer_id: id("issuer:settlement"),
                key_epoch: Generation::new(1).expect("generation"),
                verifying_key: settlement_key.verifying_key(),
            },
        )
        .await
        .expect("enroll settlement issuer");
''',
)
replace(
    "codex-rs/hepta-authbus/src/settlement_store_tests.rs",
    '''fn issuer(key: &SigningKey) -> SettlementIssuerRegistration {
    SettlementIssuerRegistration {
        issuer_id: id("issuer:settlement"),
        key_epoch: Generation::new(1).expect("generation"),
        verifying_key: key.verifying_key(),
        revoked: false,
    }
}
''',
    '''fn issuer(key: &SigningKey) -> SettlementIssuerRegistration {
    SettlementIssuerRegistration::from_record(&crate::IssuerRecord {
        issuer_id: id("issuer:settlement"),
        purpose: crate::IssuerPurpose::Settlement,
        key_epoch: Generation::new(1).expect("generation"),
        verifying_key: key.verifying_key(),
        state: crate::IssuerLifecycleState::Active,
        revision: 1,
    })
    .expect("settlement issuer registration")
}
''',
)
replace(
    "codex-rs/hepta-authbus/src/settlement_store_tests.rs",
    "SigningKey::from_bytes(&[10; 32])",
    "SigningKey::from_bytes(&[9; 32])",
)
replace(
    "codex-rs/hepta-authbus/src/settlement_store_tests.rs",
    "SigningKey::from_bytes(&[33; 32])",
    "SigningKey::from_bytes(&[9; 32])",
)
