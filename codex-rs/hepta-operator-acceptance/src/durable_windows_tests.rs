use super::FileSnapshot;
use super::open_without_following;
use super::verify_unchanged;
use crate::durable::secure_hash;
use crate::durable::secure_read;
use crate::durable::write_private_new;
use crate::test_support::private_tempdir;
use pretty_assertions::assert_eq;

#[test]
fn hardlinked_artifacts_are_rejected_before_reading_or_hashing() {
    let temporary = private_tempdir("temporary artifact directory");
    let artifact = temporary.path().join("artifact");
    write_private_new(&artifact, b"sealed").expect("write private artifact");
    assert_eq!(
        secure_read(&artifact, 64).expect("valid private input"),
        b"sealed"
    );
    assert!(secure_hash(&artifact).is_ok());
    std::fs::hard_link(&artifact, temporary.path().join("alias")).expect("create hardlink");

    assert!(secure_read(&artifact, /*max_bytes*/ 64).is_err());
    assert!(secure_hash(&artifact).is_err());
}

#[test]
fn hardlinks_added_after_open_are_rejected() {
    let temporary = private_tempdir("temporary artifact directory");
    let artifact = temporary.path().join("artifact");
    write_private_new(&artifact, b"sealed").expect("write private artifact");
    let file = open_without_following(&artifact).expect("open artifact");
    let before = FileSnapshot::capture(&file, "artifact").expect("capture original handle");
    std::fs::hard_link(&artifact, temporary.path().join("alias")).expect("create hardlink");

    assert!(verify_unchanged(&file, &artifact, &before, "artifact").is_err());
}

#[test]
fn private_creation_replacement_and_reopen_preserve_bytes_and_collisions() {
    let temporary = private_tempdir("durable Windows publication");
    let artifact = temporary.path().join("receipt");
    let staged = temporary.path().join("receipt.next");
    write_private_new(&artifact, b"first").expect("durable create");
    assert!(write_private_new(&artifact, b"overwrite").is_err());
    assert_eq!(secure_read(&artifact, 64).unwrap(), b"first");
    crate::durable::write_private_atomic_replace(&artifact, &staged, b"second")
        .expect("durable replacement");
    assert!(!staged.exists());
    assert_eq!(secure_read(&artifact, 64).unwrap(), b"second");
    assert_eq!(
        secure_hash(&artifact).unwrap(),
        (crate::durable::sha256(b"second"), 6)
    );

    write_private_new(&staged, b"occupied").expect("occupied stage");
    assert!(crate::durable::write_private_atomic_replace(&artifact, &staged, b"third").is_err());
    assert_eq!(secure_read(&artifact, 64).unwrap(), b"second");
    assert_eq!(secure_read(&staged, 64).unwrap(), b"occupied");
    let absent = temporary.path().join("absent").join("receipt");
    assert!(write_private_new(&absent, b"must not create a parent").is_err());
    assert!(!absent.parent().unwrap().exists());
}

#[test]
fn frozen_inputs_exclude_live_writers_and_namespace_replacement() {
    let temporary = private_tempdir("frozen Windows input");
    let artifact = temporary.path().join("artifact");
    let moved = temporary.path().with_extension("moved");
    write_private_new(&artifact, b"sealed").unwrap();
    let (file, directory) = super::open_input(&artifact).expect("frozen input");
    assert!(
        std::fs::OpenOptions::new()
            .write(true)
            .open(&artifact)
            .is_err()
    );
    assert!(std::fs::rename(&artifact, temporary.path().join("replacement")).is_err());
    assert!(std::fs::rename(temporary.path(), &moved).is_err());
    drop(file);
    drop(directory);
    drop(
        std::fs::OpenOptions::new()
            .write(true)
            .open(&artifact)
            .expect("released writer"),
    );
    std::fs::rename(temporary.path(), &moved).expect("released directory");
    std::fs::rename(&moved, temporary.path()).expect("restore owned fixture path");
    assert_eq!(secure_read(&artifact, 64).unwrap(), b"sealed");
}

fn icacls(path: &std::path::Path, grant: bool) -> Vec<u8> {
    let executable = std::path::PathBuf::from(std::env::var_os("SystemRoot").expect("SystemRoot"))
        .join("System32")
        .join("icacls.exe");
    let mut command = std::process::Command::new(executable);
    command.arg(path);
    if grant {
        command.args(["/grant", "*S-1-1-0:(R)"]);
    }
    let output = command.output().expect("run native ACL control");
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    output.stdout
}

#[test]
fn publicly_readable_file_is_rejected_without_repairing_its_acl() {
    let temporary = private_tempdir("private artifact ACL control");
    let artifact = temporary.path().join("artifact");
    write_private_new(&artifact, b"sealed").unwrap();
    assert_eq!(secure_read(&artifact, 64).unwrap(), b"sealed");
    icacls(&artifact, true);
    let exposed = icacls(&artifact, false);
    assert!(secure_read(&artifact, 64).is_err());
    assert!(secure_hash(&artifact).is_err());
    assert_eq!(icacls(&artifact, false), exposed);
    assert_eq!(std::fs::read(&artifact).unwrap(), b"sealed");
}

#[test]
fn publicly_readable_parent_is_rejected_without_repair_or_creation() {
    let temporary = private_tempdir("private parent ACL control");
    let artifact = temporary.path().join("new-artifact");
    crate::durable::verify_secure_directory(temporary.path(), "valid parent").unwrap();
    icacls(temporary.path(), true);
    let exposed = icacls(temporary.path(), false);
    assert!(crate::durable::verify_secure_directory(temporary.path(), "unsafe parent").is_err());
    assert!(write_private_new(&artifact, b"forbidden").is_err());
    assert!(!artifact.exists());
    assert_eq!(icacls(temporary.path(), false), exposed);
}

#[test]
fn sidecar_lock_excludes_a_second_process_and_releases_for_recovery() {
    const CHILD_MODE: &str = "HEPTA_OPERATOR_LOCK_PROBE_MODE";
    const CHILD_ROOT: &str = "HEPTA_OPERATOR_LOCK_PROBE_ROOT";
    if let Ok(mode) = std::env::var(CHILD_MODE) {
        let root = std::path::PathBuf::from(std::env::var_os(CHILD_ROOT).expect("probe root"));
        let result = crate::durable::lock_existing_sidecar(&root);
        match mode.as_str() {
            "held" => assert!(result.is_err(), "a second process acquired the held lock"),
            "released" => assert!(
                result.is_ok(),
                "recovery could not acquire the released lock"
            ),
            _ => panic!("unknown lock probe mode"),
        }
        println!("operator-lock-probe:{}:{mode}", std::process::id());
        return;
    }

    let temporary = private_tempdir("cross-process Windows sidecar lock");
    assert!(crate::durable::lock_existing_sidecar(temporary.path()).is_err());
    assert!(!temporary.path().join(".operator-acceptance.lock").exists());
    let lock = crate::durable::lock_sidecar(temporary.path()).expect("first process lock");
    assert!(
        std::fs::rename(
            temporary.path().join(".operator-acceptance.lock"),
            temporary.path().join("replacement.lock"),
        )
        .is_err()
    );
    assert!(std::fs::rename(temporary.path(), temporary.path().with_extension("moved"),).is_err());

    let run_child = |mode: &str| {
        let executable = std::env::current_exe().expect("native test executable");
        let mut child = std::process::Command::new(executable)
            .args([
                "--exact",
                "durable::windows::tests::sidecar_lock_excludes_a_second_process_and_releases_for_recovery",
                "--nocapture",
            ])
            .env(CHILD_MODE, mode)
            .env(CHILD_ROOT, temporary.path())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .spawn()
            .expect("spawn independent lock probe");
        let child_pid = child.id();
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
        while child.try_wait().expect("poll owned lock probe").is_none() {
            if std::time::Instant::now() >= deadline {
                child.kill().expect("terminate only this owned probe");
                child.wait().expect("reap owned probe");
                panic!("independent lock probe exceeded its 5-second budget");
            }
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
        let output = child.wait_with_output().expect("collect owned probe");
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        let stdout = String::from_utf8(output.stdout).expect("probe output");
        assert!(stdout.contains("running 1 test"), "{stdout}");
        assert!(
            stdout.contains(&format!("operator-lock-probe:{child_pid}:{mode}")),
            "{stdout}"
        );
    };

    run_child("held");
    drop(lock);
    run_child("released");
    drop(crate::durable::lock_existing_sidecar(temporary.path()).expect("parent recovery lock"));
}

#[test]
fn path_replacement_after_open_is_rejected() {
    let temporary = private_tempdir("temporary artifact directory");
    let artifact = temporary.path().join("artifact");
    write_private_new(&artifact, b"sealed").expect("write private artifact");
    let file = open_without_following(&artifact).expect("open artifact");
    let before = FileSnapshot::capture(&file, "artifact").expect("capture original handle");
    std::fs::rename(&artifact, temporary.path().join("original")).expect("move original artifact");
    write_private_new(&artifact, b"sealed").expect("replace artifact with the same private bytes");

    assert!(verify_unchanged(&file, &artifact, &before, "artifact").is_err());
}
