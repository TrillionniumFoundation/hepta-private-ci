#!/usr/bin/env python3
"""Finish the AuthBus trust-boundary migration on the pinned hardening branch.

This is intentionally a one-shot, exact-source migration. It refuses source drift
instead of silently weakening the security boundary.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def replace(path: str, old: str, new: str, count: int = 1) -> None:
    text = read(path)
    observed = text.count(old)
    if observed != count:
        raise SystemExit(f"{path}: expected {count} exact occurrence(s), found {observed}")
    write(path, text.replace(old, new))


def main() -> None:
    subprocess.run(
        ["python3", str(ROOT / "scripts/migrate-authbus-sealed-callers.py")],
        cwd=ROOT,
        check=True,
    )

    write(
        "codex-rs/hepta-evidence/src/authbus_test_support.rs",
        '''use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::PrivateIssuerRegistryDocument;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::SigningKey;

#[cfg(unix)]
pub(crate) fn issuer_registration(
    issuer_id: &str,
    key_epoch: u64,
    key: &SigningKey,
    revoked: bool,
) -> IssuerRegistration {
    use std::io::Write;
    use std::os::unix::fs::OpenOptionsExt;
    use std::os::unix::fs::PermissionsExt;

    let root = tempfile::tempdir().expect("private issuer registry root");
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700))
        .expect("private issuer registry root mode");
    let path = root.path().join("issuer-registry.json");
    let public_key_hex = key
        .verifying_key()
        .as_bytes()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    let mut file = std::fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(&path)
        .expect("create private issuer registry");
    serde_json::to_writer(
        &mut file,
        &serde_json::json!({
            "issuer_id": issuer_id,
            "key_epoch": key_epoch,
            "public_key_hex": public_key_hex,
            "revoked": revoked,
        }),
    )
    .expect("write private issuer registry");
    file.flush().expect("flush private issuer registry");
    file.sync_all().expect("sync private issuer registry");
    let registry = PrivateIssuerRegistryDocument::load(&path, root.path(), 16 * 1024)
        .expect("load private issuer registry");
    registry
        .message_issuer(
            &StableId::new(issuer_id.to_owned()).expect("issuer id"),
            Generation::new(key_epoch).expect("issuer epoch"),
        )
        .expect("resolve sealed issuer")
}

#[cfg(not(unix))]
pub(crate) fn issuer_registration(
    _issuer_id: &str,
    _key_epoch: u64,
    _key: &SigningKey,
    _revoked: bool,
) -> IssuerRegistration {
    panic!("private issuer registries require Unix metadata semantics")
}
''',
    )

    replace(
        "codex-rs/hepta-evidence/src/lib.rs",
        "mod authbus_store;\n",
        "mod authbus_store;\n#[cfg(test)]\nmod authbus_test_support;\n",
    )

    replace(
        "codex-rs/hepta-evidence/src/authbus_outbox_tests.rs",
        "use codex_hepta_types::Generation;\n",
        "",
    )
    replace(
        "codex-rs/hepta-evidence/src/authbus_outbox_tests.rs",
        "use crate::authbus_outbox::maintain;\n",
        "use crate::authbus_outbox::maintain;\nuse crate::authbus_test_support::issuer_registration;\n",
    )
    replace(
        "codex-rs/hepta-evidence/src/authbus_outbox_tests.rs",
        '''    let issuer = IssuerRegistration {
        issuer_id: StableId::new("issuer:queue").unwrap(),
        key_epoch: Generation::new(1).unwrap(),
        verifying_key: key.verifying_key(),
        revoked: false,
    };''',
        '''    let issuer = issuer_registration("issuer:queue", 1, &key, false);''',
    )
    replace(
        "codex-rs/hepta-evidence/src/authbus_outbox_tests.rs",
        '''    let revoked = IssuerRegistration {
        revoked: true,
        ..issuer
    };''',
        '''    let revoked = issuer_registration(
        "issuer:queue",
        1,
        &SigningKey::from_bytes(&[37; 32]),
        true,
    );''',
    )

    replace(
        "codex-rs/hepta-evidence/src/qualification_tests.rs",
        "use codex_hepta_types::Generation;\n",
        "",
    )
    replace(
        "codex-rs/hepta-evidence/src/qualification_tests.rs",
        "use crate::EvidenceCandidateV1;\n",
        "use crate::EvidenceCandidateV1;\nuse crate::authbus_test_support::issuer_registration;\n",
    )
    replace(
        "codex-rs/hepta-evidence/src/qualification_tests.rs",
        '''    (
        IssuerRegistration {
            issuer_id: StableId::new(principal).expect("principal"),
            key_epoch: Generation::new(1).expect("epoch"),
            verifying_key: key.verifying_key(),
            revoked: false,
        },
        key,
    )''',
        '''    let issuer = issuer_registration(principal, 1, &key, false);
    (issuer, key)''',
    )
    replace(
        "codex-rs/hepta-evidence/src/qualification_tests.rs",
        '''    IssuerRegistration {
        issuer_id: StableId::new(principal).expect("principal"),
        key_epoch: Generation::new(1).expect("epoch"),
        verifying_key: key.verifying_key(),
        revoked: false,
    }''',
        '''    issuer_registration(principal, 1, key, false)''',
    )

    replace(
        "codex-rs/hepta-evidence/src/authbus_recovery_tests.rs",
        "use codex_hepta_authbus::AuthBusAuthorityStore;\n",
        "use codex_hepta_authbus::AuthBusAuthorityHost;\n",
    )
    replace(
        "codex-rs/hepta-evidence/src/authbus_recovery_tests.rs",
        "use crate::AuthBusAdmissionError;\n",
        "use crate::AuthBusAdmissionError;\nuse crate::authbus_test_support::issuer_registration;\n",
    )
    replace(
        "codex-rs/hepta-evidence/src/authbus_recovery_tests.rs",
        '''    let issuer = IssuerRegistration {
        issuer_id: StableId::new("issuer:rollback").unwrap(),
        key_epoch: Generation::new(7).unwrap(),
        verifying_key: key.verifying_key(),
        revoked: false,
    };''',
        '''    let issuer = issuer_registration("issuer:rollback", 7, &key, false);''',
    )
    replace(
        "codex-rs/hepta-evidence/src/authbus_recovery_tests.rs",
        '''    let authority = AuthBusAuthorityStore::open(&temp.path().join("authbus-authority.sqlite"))
        .await
        .unwrap();''',
        '''    let authority = AuthBusAuthorityHost::bootstrap(
        &temp.path().join("authbus-authority.sqlite"),
        temp.path().join("authbus-authority.checkpoint.json"),
        "evidence-recovery-test-owner",
    )
    .await
    .unwrap();''',
    )

    store_files = [
        "authority_store.rs",
        "quota_store.rs",
        "recovery.rs",
        "settlement_store.rs",
        "trust_store.rs",
    ]
    authority = "codex-rs/hepta-authbus/src/authority_store.rs"
    replace(authority, "pub struct AuthBusAuthorityStore {", "pub(crate) struct AuthBusAuthorityStore {")
    for name in store_files:
        path = f"codex-rs/hepta-authbus/src/{name}"
        text = read(path)
        text = re.sub(r"(?m)^(    )pub async fn ", r"\1pub(crate) async fn ", text)
        text = re.sub(r"(?m)^(    )pub fn ", r"\1pub(crate) fn ", text)
        write(path, text)

    checker = "scripts/check-authbus-closed-world.py"
    text = read(checker)
    marker = "\n\ndef source(path: Path) -> str:\n"
    store_inventory = '''
STORE_OPERATIONS = {
    "open",
    "observe_time",
    "last_trusted_time",
    "create_policy",
    "replace_policy",
    "revoke_policy",
    "retire_policy",
    "authorize",
    "create_quota",
    "replace_quota",
    "reserve",
    "quota_snapshot",
    "reservation",
    "compact_terminal_reservations",
    "authority_frontier_digest",
    "authority_checkpoint",
    "initialize_authority_checkpoint",
    "reconcile_authority_checkpoint",
    "advance_authority_checkpoint",
    "recovery_required",
    "reconcile_after_restart",
    "mark_dispatch_attempted",
    "mark_indeterminate",
    "cancel_reservation",
    "reconcile_expired_reservation",
    "sweep_expired_reservations",
    "settle",
    "enroll_issuer",
    "rotate_issuer",
    "revoke_issuer",
    "retire_issuer_epoch",
    "issuer_record",
    "message_issuer",
    "settlement_issuer",
    "observe_trusted_time_attestation",
    "operational_snapshot",
}

STORE_FILES = [
    "authority_store.rs",
    "quota_store.rs",
    "recovery.rs",
    "settlement_store.rs",
    "trust_store.rs",
    "operations.rs",
]
'''
    if "STORE_OPERATIONS = {" in text or marker not in text:
        raise SystemExit("closed-world checker source drift before store inventory insertion")
    text = text.replace(marker, store_inventory + marker)
    anchor = '''    lib = source(AUTHBUS / "lib.rs")
    if "pub(crate) use authority_store::AuthBusAuthorityStore;" not in lib:
        errors.append("raw authority writer is not crate-private")
'''
    verification = '''    store_root = source(AUTHBUS / "authority_store.rs")
    if not re.search(r"(?m)^pub\\(crate\\) struct AuthBusAuthorityStore\\s*\\{", store_root):
        errors.append("raw authority writer type is not crate-private")
    store_sources = "\\n".join(source(AUTHBUS / name) for name in STORE_FILES)
    crate_private_store = set(
        re.findall(r"(?m)^\\s*pub\\(crate\\) async fn ([a-z][a-z0-9_]*)\\s*\\(", store_sources)
    )
    missing_store = sorted(STORE_OPERATIONS - crate_private_store)
    if missing_store:
        errors.append("store operations are not crate-private: " + ", ".join(missing_store))
    for name in STORE_FILES[:-1]:
        source_text = source(AUTHBUS / name)
        public_store = sorted(
            STORE_OPERATIONS
            & set(re.findall(r"(?m)^\\s*pub async fn ([a-z][a-z0-9_]*)\\s*\\(", source_text))
        )
        if public_store:
            errors.append(f"public raw writer methods in {name}: " + ", ".join(public_store))
    operations_source = source(AUTHBUS / "operations.rs")
    if "impl AuthBusAuthorityStore {\\n    pub(crate) async fn operational_snapshot" not in operations_source:
        errors.append("operational snapshot raw writer method is not crate-private")
'''
    if "store operations are not crate-private" in text or anchor not in text:
        raise SystemExit("closed-world checker source drift before visibility verification insertion")
    write(checker, text.replace(anchor, anchor + verification))

    subprocess.run(
        ["python3", str(ROOT / checker), "--write"],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        ["python3", str(ROOT / checker), "--check"],
        cwd=ROOT,
        check=True,
    )


if __name__ == "__main__":
    main()
