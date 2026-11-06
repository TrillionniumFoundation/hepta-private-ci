//! Regular-byte fixtures exercise pre-spawn rejection; they are never executed
//! and provide no actual Python/model/device qualification.
use super::*;
use pretty_assertions::assert_eq;
use std::fs;
use std::os::unix::fs::symlink;
use std::path::PathBuf;
use std::time::Duration;
use std::time::Instant;
use tokio_util::sync::CancellationToken;

fn snapshot(path: &Path, bytes: &[u8]) -> Vec<u8> {
    serde_json::to_vec(&serde_json::json!({
        "schema":"hepta-controlled-cold-runtime-snapshot-v2",
        "python":{"executable":path},
        "files":{path.to_str().unwrap():Digest32::of_bytes(bytes).to_string()}
    }))
    .unwrap()
}

#[test]
fn pre_spawn_interpreter_replacement_is_rejected_at_the_same_path() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory
        .path()
        .canonicalize()
        .unwrap()
        .join("not-executed-python-fixture");
    let bytes = b"fixed-image-A";
    fs::write(&path, bytes).unwrap();
    let raw = snapshot(&path, bytes);
    let execution = NeuralCognitiveExecutionV1::with_deadline(
        Instant::now() + Duration::from_secs(1),
        CancellationToken::new(),
    );
    assert_eq!(verify_interpreter(&path, &raw, &execution), Ok(()));
    fs::write(&path, b"fixed-image-B").unwrap();
    assert_eq!(
        verify_interpreter(&path, &raw, &execution),
        Err("neural runtime interpreter bytes changed".to_owned())
    );
}

#[test]
fn pre_spawn_requires_the_declared_interpreter_and_nonempty_contract() {
    let directory = tempfile::tempdir().unwrap();
    let root = directory.path().canonicalize().unwrap();
    let path = root.join("declared");
    let other = root.join("other");
    fs::write(&path, b"same bytes").unwrap();
    fs::write(&other, b"same bytes").unwrap();
    let raw = snapshot(&path, b"same bytes");
    let execution = NeuralCognitiveExecutionV1::with_deadline(
        Instant::now() + Duration::from_secs(1),
        CancellationToken::new(),
    );
    assert!(verify_interpreter(&other, &raw, &execution).is_err());
    assert!(snapshot_digest(&[]).is_err());
    assert!(verify_interpreter(&path, b"{}", &execution).is_err());
}

#[test]
fn runtime_check_keeps_original_deadline_and_cancellation() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory
        .path()
        .canonicalize()
        .unwrap()
        .join("not-executed");
    fs::write(&path, b"fixture").unwrap();
    let raw = snapshot(&path, b"fixture");
    let cancellation = CancellationToken::new();
    cancellation.cancel();
    let execution = NeuralCognitiveExecutionV1::with_deadline(
        Instant::now() + Duration::from_secs(1),
        cancellation,
    );
    assert!(verify_interpreter(&path, &raw, &execution).is_err());
    let execution =
        NeuralCognitiveExecutionV1::with_deadline(Instant::now(), CancellationToken::new());
    assert!(verify_interpreter(&path, &raw, &execution).is_err());
}

fn installed_snapshot(root: &Path) -> (PathBuf, Vec<u8>, PathBuf, PathBuf) {
    let base = root.join("base");
    let prefix = root.join("venv");
    let stdlib = root.join("canonical/lib/python3.12");
    fs::create_dir_all(base.join("bin")).unwrap();
    fs::create_dir_all(base.join("lib")).unwrap();
    fs::create_dir_all(prefix.join("bin")).unwrap();
    fs::create_dir_all(prefix.join("lib/python3.12/site-packages")).unwrap();
    fs::create_dir_all(&stdlib).unwrap();
    let executable = base.join("bin/python3.12");
    fs::write(&executable, b"not an executed Python image").unwrap();
    symlink(&stdlib, base.join("lib/python3.12")).unwrap();
    let launch = prefix.join("bin/python");
    symlink(&executable, &launch).unwrap();
    let cfg = prefix.join("pyvenv.cfg");
    fs::write(&cfg, format!("home = {}\n", base.join("bin").display())).unwrap();
    let dependency = prefix.join("lib/python3.12/site-packages/dependency.py");
    fs::write(&dependency, b"VERSION = 'same'\nVALUE = 'approved'\n").unwrap();
    let bootstrap = stdlib.join("hashlib.py");
    fs::write(&bootstrap, b"# unused bootstrap fixture A\n").unwrap();
    let inventory = BTreeSet::from([launch.clone(), cfg, dependency, bootstrap]);
    let mut files = serde_json::Map::new();
    for path in inventory.iter().chain(std::iter::once(&executable)) {
        files.insert(
            path.to_str().unwrap().to_owned(),
            serde_json::json!(Digest32::of_bytes(&fs::read(path).unwrap()).to_string()),
        );
    }
    let raw = serde_json::to_vec(&serde_json::json!({
        "schema":"hepta-controlled-cold-runtime-snapshot-v2", "python":{"executable":executable},
        "prefix":prefix,"stdlib_root":stdlib,"files":files,"managed_inventory":inventory,
    }))
    .unwrap();
    (launch, raw, base, stdlib)
}

fn admission() -> NeuralCognitiveExecutionV1 {
    NeuralCognitiveExecutionV1::with_deadline(
        Instant::now() + Duration::from_secs(2),
        CancellationToken::new(),
    )
}

#[test]
fn pre_spawn_snapshot_hashes_stdlib_before_any_python_code() {
    let directory = tempfile::tempdir().unwrap();
    let root = directory.path().canonicalize().unwrap();
    let (python, raw, _, stdlib) = installed_snapshot(&root);
    assert_eq!(verify_snapshot(&python, &raw, &admission()), Ok(()));
    fs::write(stdlib.join("hashlib.py"), b"# unused bootstrap fixture B\n").unwrap();
    assert!(verify_snapshot(&python, &raw, &admission()).is_err());
}

#[test]
fn pre_spawn_snapshot_rejects_unlisted_installed_file() {
    let directory = tempfile::tempdir().unwrap();
    let root = directory.path().canonicalize().unwrap();
    let (python, raw, _, _) = installed_snapshot(&root);
    fs::write(root.join("venv/unlisted.py"), b"not approved").unwrap();
    assert_eq!(
        verify_snapshot(&python, &raw, &admission()),
        Err("neural runtime installed inventory changed".to_owned())
    );
}

#[test]
fn pre_spawn_rejects_startup_zip_outside_the_canonical_stdlib_inventory() {
    let directory = tempfile::tempdir().unwrap();
    let root = directory.path().canonicalize().unwrap();
    let (python, raw, base, _) = installed_snapshot(&root);
    // The actual executable's base/lib may differ from canonical stdlib_root.
    // The archive need not be parsed: this profile disallows its very presence.
    fs::write(
        base.join("lib/python312.zip"),
        b"unadmitted startup archive",
    )
    .unwrap();
    assert_eq!(
        verify_snapshot(&python, &raw, &admission()),
        Err("neural runtime unpacked profile forbids startup ZIP".to_owned())
    );
}

#[test]
fn pre_spawn_rejects_underscore_pth_at_the_real_or_launch_executable() {
    for location in ["base/bin/python3.12._pth", "venv/bin/python._pth"] {
        let directory = tempfile::tempdir().unwrap();
        let root = directory.path().canonicalize().unwrap();
        let (python, raw, _, _) = installed_snapshot(&root);
        fs::write(root.join(location), b"/unadmitted/modules\n").unwrap();
        assert_eq!(
            verify_snapshot(&python, &raw, &admission()),
            Err("neural runtime unpacked profile forbids startup ._pth".to_owned())
        );
    }
}

#[test]
fn pre_spawn_rejects_bootstrap_stdlib_alias_replacement() {
    let directory = tempfile::tempdir().unwrap();
    let root = directory.path().canonicalize().unwrap();
    let (python, raw, base, _) = installed_snapshot(&root);
    let alternate = root.join("alternate");
    fs::create_dir(&alternate).unwrap();
    fs::remove_file(base.join("lib/python3.12")).unwrap();
    symlink(alternate, base.join("lib/python3.12")).unwrap();
    assert_eq!(
        verify_snapshot(&python, &raw, &admission()),
        Err("neural runtime bootstrap stdlib alias changed".to_owned())
    );
}
