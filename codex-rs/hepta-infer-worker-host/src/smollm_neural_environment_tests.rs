use super::*;
use pretty_assertions::assert_eq;
use std::fs;

#[test]
fn explicit_loader_overrides_are_refused_before_spawn() {
    for name in [
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "LD_AUDIT",
        "LD_UNRECOGNIZED",
        "GLIBC_TUNABLES",
    ] {
        let mut command = Command::new("python3");
        command.env(name, "unapproved");
        assert_eq!(
            configure_python_environment_from_ambient(&mut command, std::iter::empty()),
            Err("neural Python loader overrides are not allowed".to_owned())
        );
    }
}

#[test]
fn ambient_loader_overrides_are_refused_before_spawn() {
    for name in [
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "LD_AUDIT",
        "LD_UNRECOGNIZED",
        "GLIBC_TUNABLES",
    ] {
        let mut command = Command::new("python3");
        assert_eq!(
            configure_python_environment_from_ambient(
                &mut command,
                [(name.into(), "unapproved".into())].into_iter(),
            ),
            Err("neural Python loader overrides are not allowed".to_owned())
        );
    }
}

#[test]
fn ambient_python_injection_cannot_enter_supervisor_or_descendant() {
    let directory = tempfile::tempdir().unwrap();
    let marker = directory.path().join("ambient-imported");
    fs::write(
        directory.path().join("sitecustomize.py"),
        format!("from pathlib import Path\nPath({marker:?}).write_text('injected')\n"),
    )
    .unwrap();
    let script = directory.path().join("trusted-script.py");
    // Keep the trusted script outside the poisoned import directory.
    let trusted = tempfile::tempdir().unwrap();
    let script = trusted.path().join(script.file_name().unwrap());
    fs::write(
        &script,
        "import subprocess,sys\nassert sys.flags.ignore_environment == 1\nassert sys.flags.no_user_site == 1\nsubprocess.run([sys.executable,'-c','import sys; assert sys.flags.no_user_site == 1; print(\"clean descendant\")'],check=True)\n",
    )
    .unwrap();
    let mut command = Command::new("python3");
    // Cargo/nextest may inject LD_LIBRARY_PATH for the Rust test executable.
    // The Python fixture has a separate, explicit environment; production's
    // ambient-loader refusal is exercised independently above.
    command.env_clear();
    if let Some(path) = std::env::var_os("PATH") {
        command.env("PATH", path);
    }
    command
        .env("PYTHONPATH", directory.path())
        .env("PYTHONHOME", directory.path().join("missing-python-home"))
        .env("PYTHONUSERBASE", directory.path());
    configure_python_environment_from_ambient(&mut command, std::iter::empty()).unwrap();
    let output = command.arg(script).output().unwrap();
    assert!(output.status.success(), "{output:?}");
    assert_eq!(
        String::from_utf8(output.stdout).unwrap(),
        "clean descendant\n"
    );
    assert!(!marker.exists());
}
