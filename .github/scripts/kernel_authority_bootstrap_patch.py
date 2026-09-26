#!/usr/bin/env python3
"""Patch the one-shot remediator against the live PR branch, then self-delete."""

from pathlib import Path

REMEDIATOR = Path(".github/scripts/kernel_authority_remediate.py")
SELF = Path(__file__)


def replace_once(content: str, old: str, new: str, label: str) -> str:
    count = content.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one predecessor, observed {count}")
    return content.replace(old, new, 1)


def replace_last(content: str, old: str, new: str, expected_count: int, label: str) -> str:
    count = content.count(old)
    if count != expected_count:
        raise SystemExit(
            f"{label}: expected {expected_count} predecessor copies, observed {count}"
        )
    index = content.rfind(old)
    return content[:index] + new + content[index + len(old) :]


def main() -> None:
    content = REMEDIATOR.read_text(encoding="utf-8")

    content = replace_once(
        content,
        '''    scaffold_changes = set(
        filter(
            None,
            output("git", "diff", "--name-only", f"{EXPECTED_HEAD}..HEAD").splitlines(),
        )
    )
    expected_scaffold = {
        ".github/scripts/kernel_authority_remediate.py",
        ".github/workflows/kernel-authority-remediation.yml",
    }
    if scaffold_changes != expected_scaffold:
        raise RuntimeError(
            f"branch drifted outside the one-shot scaffold: {sorted(scaffold_changes)}"
        )
''',
        "",
        "stale scaffold-drift guard",
    )

    content = replace_once(
        content,
        '''    run(
        "cargo",
        "fmt",
        "--manifest-path",
        "codex-rs/Cargo.toml",
        "-p",
        "codex-hepta-contracts",
        "-p",
        "codex-hepta-fleet",
    )''',
        '''    run(
        "cargo",
        "fmt",
        "--manifest-path",
        "codex-rs/Cargo.toml",
        "-p",
        "codex-hepta-contracts",
    )''',
        "remediator formatting predecessor",
    )

    content = replace_last(
        content,
        "              run format cargo fmt --check -p codex-hepta-automation -p codex-hepta-prompt-registry -p codex-hepta-fleet",
        "              run format cargo fmt --check -p codex-hepta-automation -p codex-hepta-prompt-registry",
        2,
        "generated product formatting command",
    )

    unsafe_test = '''    #[test]
    fn dispatch_boundary_serializes_revocation_until_local_entry_returns() {
        let (registry, _directory) = fixture().unwrap();
        registry.put_lease(lease(), 0).unwrap();
        let verifier = registry.verifier();
        let token = verifier.verify_use("lease-one", 1, &binding()).unwrap();
        let (entered_tx, entered_rx) = mpsc::channel();
        let (revoked_tx, revoked_rx) = mpsc::channel();
        std::thread::spawn(move || {
            entered_rx.recv().unwrap();
            let result = registry.revoke("lease-one", 1, [8; 32]);
            let _ = revoked_tx.send(result);
        });

        let expected = binding();
        let result = verifier
            .with_dispatch_boundary(token, &expected, || {
                entered_tx.send(()).unwrap();
                assert!(
                    revoked_rx.recv_timeout(Duration::from_millis(100)).is_err(),
                    "revocation crossed the local dispatch linearization fence"
                );
                11
            })
            .unwrap();
        assert_eq!(result, 11);
        assert!(
            revoked_rx
                .recv_timeout(Duration::from_secs(2))
                .expect("revocation did not complete after local dispatch boundary")
                .is_ok()
        );
    }
'''
    safe_test = '''    #[test]
    fn dispatch_boundary_serializes_revocation_until_local_entry_returns() {
        let (registry, _directory) = fixture().unwrap();
        registry.put_lease(lease(), 0).unwrap();
        let verifier = registry.verifier();
        let token = verifier.verify_use("lease-one", 1, &binding()).unwrap();
        let (entered_tx, entered_rx) = mpsc::channel();
        let (attempted_tx, attempted_rx) = mpsc::channel();
        let (release_tx, release_rx) = mpsc::channel();
        let (revoked_tx, revoked_rx) = mpsc::channel();
        let revoker = std::thread::spawn(move || {
            if entered_rx.recv().is_err() {
                return;
            }
            let _ = attempted_tx.send(());
            let result = registry.revoke("lease-one", 1, [8; 32]);
            let _ = revoked_tx.send(result);
        });

        let expected = binding();
        let dispatch = std::thread::spawn(move || {
            verifier.with_dispatch_boundary(token, &expected, || {
                let entered = entered_tx.send(()).is_ok();
                let released = release_rx.recv_timeout(Duration::from_secs(2)).is_ok();
                (entered, released, 11)
            })
        });
        attempted_rx
            .recv_timeout(Duration::from_secs(2))
            .expect("revocation worker did not reach the authority boundary");
        assert!(
            revoked_rx.recv_timeout(Duration::from_millis(100)).is_err(),
            "revocation crossed the local dispatch linearization fence"
        );
        release_tx
            .send(())
            .expect("dispatch worker did not retain the release channel");
        let (entered, released, result) = dispatch
            .join()
            .expect("dispatch worker panicked")
            .expect("dispatch boundary rejected a current lease");
        assert!(entered, "dispatch worker did not signal entry");
        assert!(released, "dispatch worker did not observe release");
        assert_eq!(result, 11);
        assert!(
            revoked_rx
                .recv_timeout(Duration::from_secs(2))
                .expect("revocation did not complete after local dispatch boundary")
                .is_ok()
        );
        revoker.join().expect("revocation worker panicked");
    }
'''
    content = replace_last(
        content,
        unsafe_test,
        safe_test,
        2,
        "generated dispatch serialization regression",
    )

    REMEDIATOR.write_text(content, encoding="utf-8")
    SELF.unlink()


if __name__ == "__main__":
    main()
