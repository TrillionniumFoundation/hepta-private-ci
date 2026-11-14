use std::fs::OpenOptions;
use std::io::Write;
use std::process::Command;
use std::process::Stdio;

use pretty_assertions::assert_eq;

use super::ActiveVerifier;
use super::Inputs;
use super::TrustedOpenSsh;
use super::reconcile_pending;

type TestResult = Result<(), Box<dyn std::error::Error>>;

#[test]
fn frozen_private_inputs_deny_writes_deletes_and_directory_replacement() -> TestResult {
    let inputs = Inputs::new(b"pinned allowed signer\n", b"pinned signature\n")?;
    inputs.verify()?;
    for input in [&inputs.allowed, &inputs.signature] {
        assert!(
            OpenOptions::new()
                .write(true)
                .open(&input.owned.path)
                .is_err()
        );
        assert!(std::fs::remove_file(&input.owned.path).is_err());
        assert!(
            std::fs::rename(&input.owned.path, input.owned.path.with_extension("moved")).is_err()
        );
    }
    assert!(
        std::fs::rename(
            &inputs.directory.path,
            inputs.directory.path.with_extension("moved")
        )
        .is_err()
    );
    inputs.verify()?;
    let directory = inputs.directory.path.clone();
    drop(inputs);
    assert!(
        !directory.exists(),
        "only the owned private directory is removed"
    );
    Ok(())
}

#[test]
fn hardlink_added_to_frozen_input_is_refused() -> TestResult {
    let inputs = Inputs::new(b"pinned allowed signer\n", b"pinned signature\n")?;
    let alias = inputs.directory.path.join("alias");
    match std::fs::hard_link(&inputs.allowed.owned.path, &alias) {
        Ok(()) => {
            assert!(inputs.verify().is_err());
            let original = inputs.allowed.owned.path.clone();
            let directory = inputs.directory.path.clone();
            drop(inputs);
            // Cleanup must preserve a multiply-linked object, including the
            // extra name this test deliberately created.
            assert!(original.exists());
            assert!(alias.exists());
            std::fs::remove_file(alias)?;
            std::fs::remove_file(original)?;
            std::fs::remove_dir(directory)?;
        }
        Err(_) => inputs.verify()?,
    }
    Ok(())
}

#[test]
fn retained_unknown_verifier_reconciles_only_its_original_child() -> TestResult {
    let inputs = Inputs::new(b"pinned allowed signer\n", b"pinned signature\n")?;
    let directory = inputs.directory.path.clone();
    let verifier = TrustedOpenSsh::open()?;
    // The OS command interpreter blocks on its inherited stdin. No executable
    // or command text is selected by environment or request input.
    let child = Command::new(verifier.system_directory.join("cmd.exe"))
        .args(["/D", "/Q", "/C", "set /p held="])
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()?;
    let original_pid = child.id();
    let mut pending = Some(ActiveVerifier {
        child,
        inputs,
        verifier,
    });
    assert!(reconcile_pending(&mut pending).is_err());
    let active = pending.as_mut().ok_or("original verifier was released")?;
    assert_eq!(active.child.id(), original_pid);
    assert!(directory.exists());
    active.inputs.verify()?;

    let mut stdin = active.child.stdin.take().ok_or("child stdin missing")?;
    let write_result = stdin.write_all(b"complete\n");
    drop(stdin);
    let status = active.child.wait()?;
    write_result?;
    assert!(status.success());
    assert!(reconcile_pending(&mut pending).is_err());
    assert!(pending.is_none());
    assert!(!directory.exists());
    // A later admission can start fresh, but the reconciliation above did not.
    reconcile_pending(&mut pending)?;
    Ok(())
}
