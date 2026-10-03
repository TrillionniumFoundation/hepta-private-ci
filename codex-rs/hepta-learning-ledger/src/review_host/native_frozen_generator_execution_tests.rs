use super::execute_root_approved_frozen_generator;
use std::path::Path;

#[test]
fn ordinary_peer_cannot_dispatch_or_read_a_generator_request() {
    let status = std::fs::read_to_string("/proc/self/status").unwrap();
    let ordinary = status
        .lines()
        .find_map(|line| line.strip_prefix("Uid:"))
        .unwrap()
        .split_whitespace()
        .any(|id| id != "0");
    if ordinary {
        let error = execute_root_approved_frozen_generator(
            Path::new("/absent-program"),
            Path::new("/absent-request"),
            Path::new("/absent-output"),
        )
        .err()
        .unwrap();
        assert_eq!(
            error.to_string(),
            "fixed Generator dispatch requires the actual Root owner"
        );
    }
}

#[test]
#[ignore = "Requires an actual Root process and isolated protected /run custody"]
fn actual_root_preserves_a_consumed_output_slot_without_redispatch() {
    use super::GeneratorPurpose;
    use super::create_private;
    use super::launch_generator;
    use codex_hepta_types::Digest32;
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::PermissionsExt;

    let root = std::fs::metadata("/proc/self").unwrap().uid();
    assert_eq!(root, 0);
    let directory = std::path::PathBuf::from(format!(
        "/run/hepta-generator-consumed-test-{}-{}",
        std::process::id(),
        super::now_ms().unwrap()
    ));
    std::fs::create_dir(&directory).unwrap();
    std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o700)).unwrap();
    let output = directory.join("original-output.json");
    let original = b"original incomplete execution bytes";
    create_private(&output, original).unwrap();
    // The fixed launcher must fail before opening stderr or dispatching even
    // when an original output is partial and has no successful status.
    assert!(
        launch_generator(
            /*uid*/ 65534,
            Path::new("/absent-program"),
            Digest32::of_bytes(b"original request"),
            GeneratorPurpose::FrozenIteration,
            Path::new("/absent-request"),
            &output,
        )
        .is_err()
    );
    assert_eq!(std::fs::read(&output).unwrap(), original);
    assert!(!output.with_extension("stderr.log").exists());
    assert!(!output.with_extension("status.json").exists());
    std::fs::remove_file(output).unwrap();
    std::fs::remove_dir(directory).unwrap();
}
