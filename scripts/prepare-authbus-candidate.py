#!/usr/bin/env python3
"""Apply the reviewed one-shot caller migration to SOURCE, then verify its scope.

This is a preparation tool, not qualification. The workflow commits the resulting
Rust source and regenerated inventory before any exact-head qualification runs.
It never rebases, force-pushes, modifies main, or declares activation.
"""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def replace(path, old, new, count=1):
    target = ROOT / path
    text = target.read_text()
    if text.count(old) != count:
        raise RuntimeError(f"{path}: expected {count} exact patch anchors, got {text.count(old)}")
    target.write_text(text.replace(old, new))


def main():
    # Preserve and execute only the already-reviewed Bao/Agentd/settlement
    # substitutions from the obsolete, invalid-YAML migration recipe. Its blob
    # identity is fixed; the old regex weakening and broad git-add are NOT run.
    legacy = ROOT / ".github/workflows/authbus-trust-boundary-migrate.yml"
    actual = subprocess.check_output(["git", "hash-object", str(legacy)], text=True).strip()
    if actual != "03eb398708aca6911fd03d80b2f4d2df71506962":
        raise RuntimeError("legacy migration recipe changed; re-review required")
    raw = legacy.read_text().split("python3 - <<'PY'\n", 1)[1].split("\n          PY", 1)[0]
    body = "\n".join(line[10:] if line.startswith(" " * 10) else line for line in raw.splitlines())
    selected = body.split("# Inventory must", 1)[0]
    selected += "# Bao product tests" + body.split("# Bao product tests", 1)[1].split("# Evidence quarantine tests", 1)[0]
    selected += "# Settlement white-box tests" + body.split("# Settlement white-box tests", 1)[1]
    exec(compile(selected, str(legacy), "exec"), {"__name__": "reviewed_migration"})

    # All evidence fixtures resolve a real private persisted registry, rather
    # than exposing a production constructor or weakening privacy for tests.
    files = ["authbus_outbox_tests.rs", "authbus_outbox_quarantine_tests.rs",
             "authbus_recovery_tests.rs", "qualification_tests.rs"]
    pattern = re.compile(r"IssuerRegistration\s*\{\s*issuer_id:\s*(.*?),\s*key_epoch:\s*(.*?),\s*verifying_key:\s*(.*?),\s*revoked:\s*(.*?),\s*\}", re.S)
    for name in files:
        path = ROOT / "codex-rs/hepta-evidence/src" / name
        text = path.read_text()
        def fixture(match):
            return "crate::authbus_test_support::message_registration(" + ", ".join(match.groups()) + ")"
        text, count = pattern.subn(fixture, text)
        if not 1 <= count <= 16:
            raise RuntimeError(f"{name}: unexpected literal count {count}")
        if not text.startswith("#![cfg(unix)]"):
            text = "#![cfg(unix)]\n\n" + text
        # Rebinding a fixture through the registry loader preserves negative
        # revocation/epoch cases without allowing trusted-field mutation.
        text = re.sub(r"issuer\.key_epoch = (.*?);", r"issuer = crate::authbus_test_support::message_registration(issuer.issuer_id.clone(), \1, issuer.verifying_key, issuer.revoked);", text)
        text = re.sub(r"issuer\.revoked = (.*?);", r"issuer = crate::authbus_test_support::message_registration(issuer.issuer_id.clone(), issuer.key_epoch, issuer.verifying_key, \1);", text)
        path.write_text(text)
    evidence_lib = ROOT / "codex-rs/hepta-evidence/src/lib.rs"
    text = evidence_lib.read_text()
    if "mod authbus_test_support;" in text:
        raise RuntimeError("test support was already registered")
    evidence_lib.write_text(text + "\n#[cfg(all(test, unix))]\nmod authbus_test_support;\n")
    recovery = "codex-rs/hepta-evidence/src/authbus_recovery_tests.rs"
    replace(recovery, "use codex_hepta_authbus::AuthBusAuthorityStore;", "use codex_hepta_authbus::AuthBusAuthorityHost;\nuse std::os::unix::fs::PermissionsExt;")
    replace(recovery, '''    let authority = AuthBusAuthorityStore::open(&temp.path().join("authbus-authority.sqlite"))
        .await
        .unwrap();''', '''    let database_root = temp.path().join("authority-database");
    let checkpoint_root = temp.path().join("authority-witness");
    for path in [&database_root, &checkpoint_root] {
        std::fs::create_dir(path).unwrap();
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700)).unwrap();
    }
    let authority = AuthBusAuthorityHost::bootstrap(
        &database_root.join("authority.sqlite"),
        checkpoint_root.join("checkpoint.json"),
        "evidence-retirement-fixture",
    ).await.unwrap();''')

    host = "codex-rs/hepta-authbus/src/host.rs"
    replace(host, "    _owner_fence: OwnerFence,\n", "    _owner_fence: OwnerFence,\n    _checkpoint_owner_fence: OwnerFence,\n")
    replace(host, "        let owner_fence = OwnerFence::acquire(database_path, owner_id).await?;\n", "        let owner_fence = OwnerFence::acquire(database_path, owner_id).await?;\n        // A distinct database must not share this host's external witness.\n        let checkpoint_owner_fence = OwnerFence::acquire(&checkpoint_path, owner_id).await?;\n")
    replace(host, "            _owner_fence: owner_fence,\n", "            _owner_fence: owner_fence,\n            _checkpoint_owner_fence: checkpoint_owner_fence,\n")
    tests = ROOT / "codex-rs/hepta-authbus/src/host_tests.rs"
    tests.write_text(tests.read_text() + '''

#[tokio::test]
async fn distinct_databases_cannot_share_an_active_checkpoint_owner() {
    let first_paths = private_paths();
    let second_paths = private_paths();
    let first = AuthBusAuthorityHost::bootstrap(
        &first_paths.database, first_paths.checkpoint.clone(), "shared-owner"
    ).await.expect("first owner");
    let second = AuthBusAuthorityHost::bootstrap(
        &second_paths.database, second_paths.checkpoint.clone(), "shared-owner"
    ).await.expect("second independent owner");
    drop(second);
    let before = std::fs::read(&first_paths.checkpoint).expect("first checkpoint");
    assert!(matches!(
        AuthBusAuthorityHost::open(
            &second_paths.database, first_paths.checkpoint.clone(), "shared-owner"
        ).await,
        Err(AuthBusAuthorityError::OwnerAlreadyActive)
    ));
    assert_eq!(std::fs::read(&first_paths.checkpoint).expect("unchanged witness"), before);
    AuthBusAuthorityHost::open(
        &second_paths.database, second_paths.checkpoint.clone(), "shared-owner"
    ).await.expect("failed witness acquisition releases the database fence");
    first.enroll_issuer(IssuerPurpose::Message, issuer_spec("issuer:witness-owner", 54))
        .await.expect("the original owner remains usable");
}
''')
    replace("codex-rs/hepta-authbus/src/lib.rs", "#![forbid(unsafe_code)]", "#![forbid(unsafe_code)]\n#![doc = include_str!(\"../SEALED_API.md\")]")
    receipt = "scripts/authbus-exact-head-evidence.py"
    replace(receipt, '"inventory", "receipt_tests", "format", "authbus", "qualification",', '"inventory", "inventory_tests", "receipt_tests", "format", "authbus", "doc_tests", "qualification",')
    replace(receipt, '("authbus", "qualification", "evidence", "agentd", "bao", "workspace")', '("authbus", "doc_tests", "qualification", "evidence", "agentd", "bao", "workspace")')
    replace(receipt, '        "receipt_tests": [sys.executable, "scripts/test-authbus-exact-head-evidence.py"],', '        "receipt_tests": [sys.executable, "scripts/test-authbus-exact-head-evidence.py"],\n        "inventory_tests": [sys.executable, "scripts/test-authbus-closed-world.py"],\n        "doc_tests": cargo + ["-p", "codex-hepta-authbus", "--doc"],')
    # Report diagnostics in the job log as well as the immutable artifact.
    replace(receipt, '        atomic_json(state_file, row)\n\n\ndef executable_evidence', '        atomic_json(state_file, row)\n        print(f"{row[\'id\']}: {row[\'state\']} (exit={row.get(\'exit_code\')})", flush=True)\n        if row[\'state\'] != \'success\' and log.exists():\n            print("\\n".join(log.read_text(errors="replace").splitlines()[-80:]), flush=True)\n\n\ndef executable_evidence')
    # Failure must stay failure, but should not suppress all the native gates.
    replace(receipt, '            if row["state"] != "success":\n                break\n', '')
    workflow = "\.github/workflows/authbus-authority-qualification.yml".lstrip("\\")
    replace(workflow, 'branches: [main, codex/authbus-concurrency-closure-20260927]', 'branches: [main, codex/authbus-concurrency-closure-20260927, codex/authbus-final-hardening-20260928]')
    legacy.unlink()  # Remove the invalid, obsolete one-shot workflow, not production code.
    subprocess.run([sys.executable, "scripts/test-authbus-closed-world.py"], cwd=ROOT, check=True)
    print("Source migration applied. Native formatting and regenerated inventory are still required.")


if __name__ == "__main__":
    main()
