use super::*;
use pretty_assertions::assert_eq;
use std::fs;

#[test]
fn ambient_python_injection_cannot_enter_supervisor_or_descendant() {
    let directory = tempfile::tempdir().unwrap();
    let marker = directory.path().join("ambient-imported");
    fs::write(
        directory.path().join("sitecustomize.py"),
        format!(
            "from pathlib import Path\nPath({:?}).write_text('injected')\n",
            marker
        ),
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
    command
        .env("PYTHONPATH", directory.path())
        .env("PYTHONHOME", directory.path().join("missing-python-home"))
        .env("PYTHONUSERBASE", directory.path());
    configure_python_environment(&mut command);
    let output = command.arg(script).output().unwrap();
    assert!(output.status.success(), "{:?}", output);
    assert_eq!(
        String::from_utf8(output.stdout).unwrap(),
        "clean descendant\n"
    );
    assert!(!marker.exists());
}
