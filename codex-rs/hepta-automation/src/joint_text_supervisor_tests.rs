//! Transport fault fixtures only; no real Python worker, Torch, authorization
//! service or Training job is exercised by these shell response probes.

use super::*;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;

use crate::fixed_job_supervisor::file_digest;
use crate::joint_text_job::JointTextInputManifestV1;
use crate::joint_text_job::JointTextInputRefV1;
use crate::joint_text_job::JointTextJobIdentityV1;
use crate::joint_text_job::JointTextJobStateV1;
use crate::joint_text_job::JointTextProfileV1;
use pretty_assertions::assert_eq;

struct Fixture {
    _directory: tempfile::TempDir,
    config: JointTextProcessSupervisorConfig,
    command: JointTextJobCommandV1,
}

impl Fixture {
    fn new(body: &str) -> Self {
        let directory = tempfile::tempdir().expect("fault fixture");
        let repository = directory.path().canonicalize().expect("canonical fixture");
        let scripts = repository.join("qualification/hcsn_training");
        std::fs::create_dir_all(&scripts).expect("fixed source path");
        let script = scripts.join("joint_supervisor.py");
        std::fs::write(&script, b"# exact transport-only fixture\n").expect("source pin");
        let executable = repository.join("fault-executable");
        std::fs::write(&executable, format!("#!/bin/sh\n{body}\n")).expect("executable");
        std::fs::set_permissions(&executable, std::fs::Permissions::from_mode(0o700))
            .expect("mode");
        let root = repository.join("store");
        std::fs::create_dir(&root).expect("test store");
        std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700))
            .expect("store mode");
        let metadata = std::fs::metadata(&root).expect("actual identity");
        let descriptor = JointTextInputRefV1::from_manifest(JointTextInputManifestV1 {
            schema_version: 1,
            profile: JointTextProfileV1::VerifiedMemoryTextSgdV1,
            request_sha256: Sha256Digest::for_bytes(b"request"),
            request_bytes: 7,
            request_binding_digest: Sha256Digest::for_bytes(b"request binding"),
            predecessor_sha256: Sha256Digest::for_bytes(b"packet"),
            predecessor_bytes: 6,
            worker_execution_source_digest: Sha256Digest::for_bytes(b"worker closure"),
        })
        .expect("input shape");
        let payload = descriptor.encode().expect("payload");
        let identity = JointTextJobIdentityV1::for_taskflow(
            "joint-provider",
            "run",
            "training",
            Sha256Digest::for_bytes(&payload),
        )
        .expect("identity");
        Self {
            command: JointTextJobCommandV1::start(
                identity,
                String::from_utf8(payload).expect("UTF8"),
            )
            .expect("start"),
            config: JointTextProcessSupervisorConfig {
                python_sha256: file_digest(&executable).expect("executable pin"),
                python_executable: executable,
                repository_root: repository,
                supervisor_sha256: file_digest(&script).expect("source pin"),
                durable_root: root,
                root_identity: JointTextRootIdentityV1 {
                    device: metadata.dev(),
                    inode: metadata.ino(),
                    uid: metadata.uid(),
                },
                deadline: Duration::from_secs(2),
            },
            _directory: directory,
        }
    }
}

#[test]
fn joint_cli_carries_only_the_signed_root_tuple_and_validates_the_response() {
    let fixture = Fixture::new(
        "printf '%s\\n' \"$@\" > \"$5/argv\"\ncat > \"$5/request\"\nexec cat \"$5/reply\"",
    );
    let expected = JointTextJobObservationV1 {
        schema_version: 1,
        profile: JointTextProfileV1::VerifiedMemoryTextSgdV1,
        dispatch: fixture.command.dispatch.clone(),
        target: fixture.command.target.clone(),
        state: JointTextJobStateV1::Reserved,
        process: None,
        evidence: None,
    };
    std::fs::write(
        fixture.config.durable_root.join("reply"),
        serde_json::to_vec(&expected).expect("response"),
    )
    .expect("reply");
    let mut supervisor =
        JointTextProcessSupervisor::new_with_contact_guard(fixture.config.clone(), || Ok(()))
            .expect("transport only");
    assert_eq!(supervisor.exchange(&fixture.command), Ok(expected));
    let actual = std::fs::read_to_string(fixture.config.durable_root.join("argv")).expect("argv");
    let identity = &fixture.config.root_identity;
    let expected_args = vec![
        "-I".to_owned(),
        "-B".to_owned(),
        fixture
            .config
            .repository_root
            .join("qualification/hcsn_training/joint_supervisor.py")
            .display()
            .to_string(),
        "--root".to_owned(),
        fixture.config.durable_root.display().to_string(),
        "--root-device".to_owned(),
        identity.device.to_string(),
        "--root-inode".to_owned(),
        identity.inode.to_string(),
        "--root-uid".to_owned(),
        identity.uid.to_string(),
    ];
    assert_eq!(
        actual.lines().map(str::to_owned).collect::<Vec<_>>(),
        expected_args
    );
    assert_eq!(
        std::fs::read(fixture.config.durable_root.join("request")).expect("request"),
        serde_json::to_vec(&fixture.command).expect("command bytes")
    );
}

#[test]
fn replacement_root_refuses_contact_and_cleans_only_original_rpc_files() {
    let fixture = Fixture::new("touch \"$5/contacted\"");
    let root = fixture.config.durable_root.clone();
    let moved = root.with_extension("retained");
    let held_root = root.clone();
    let held_moved = moved.clone();
    let mut supervisor =
        JointTextProcessSupervisor::new_with_contact_guard(fixture.config.clone(), move || {
            std::fs::rename(&held_root, &held_moved).expect("replace test root");
            std::fs::create_dir(&held_root).expect("replacement");
            std::fs::set_permissions(&held_root, std::fs::Permissions::from_mode(0o700))
                .expect("mode");
            std::fs::write(held_root.join("unrelated"), b"preserve me")
                .expect("replacement contents");
            Ok(())
        })
        .expect("transport");
    assert_eq!(
        supervisor.exchange(&fixture.command),
        Err(JointTextSupervisorError::BeforeContact)
    );
    assert!(!root.join("contacted").exists());
    assert_eq!(
        std::fs::read(root.join("unrelated")).expect("untouched replacement"),
        b"preserve me"
    );
    assert_eq!(std::fs::read_dir(&moved).expect("original root").count(), 0);
}

#[test]
fn invalid_or_nonzero_reply_after_contact_never_becomes_before_contact_or_success() {
    for body in ["printf 'not JSON'", "exit 7"] {
        let fixture = Fixture::new(body);
        let mut supervisor =
            JointTextProcessSupervisor::new_with_contact_guard(fixture.config, || Ok(()))
                .expect("transport");
        assert_eq!(
            supervisor.exchange(&fixture.command),
            Err(JointTextSupervisorError::Unknown)
        );
    }
}
