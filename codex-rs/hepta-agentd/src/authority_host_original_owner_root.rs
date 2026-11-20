//! Fresh isolated Root plus original SQLite owner qualification, no application.
use super::*;
use pretty_assertions::assert_eq;

pub(super) fn binding(owner: &AgentId) -> FinalUseBinding {
    let golden: serde_json::Value =
        serde_json::from_str(include_str!("../tests/fixtures/notes-recovery-v1.json")).unwrap();
    let payload = golden["request_utf8"].as_str().unwrap();
    let request: serde_json::Value = serde_json::from_str(payload).unwrap();
    let identity: codex_hepta_memory::NotesTargetIdentity =
        serde_json::from_value(request["target"].clone()).unwrap();
    FinalUseBinding {
        subject_id: owner.to_string(),
        destination_id: identity.destination_id(),
        scope_sha256: *identity.scope_digest().as_array(),
        request_sha256: [1; 32],
        payload_sha256: *codex_hepta_types::Digest32::of_bytes(payload.as_bytes()).as_array(),
    }
}

/// Only called on a freshly generated qualification subtree, never on a real
/// deployment. All paths are owned by this test and symlinks are refused.
pub(super) fn handoff_fresh_tree(path: &Path) {
    let metadata = std::fs::symlink_metadata(path).unwrap();
    assert!(!metadata.file_type().is_symlink());
    if metadata.is_dir() {
        for child in std::fs::read_dir(path).unwrap() {
            handoff_fresh_tree(&child.unwrap().path());
        }
    }
    let path = std::ffi::CString::new(path.as_os_str().as_encoded_bytes()).unwrap();
    // SAFETY: private root-created fixture path; no links or caller pointers.
    assert_eq!(unsafe { libc::chown(path.as_ptr(), 60001, 60001) }, 0);
}

pub(super) fn verify_final(config: &HostAuthorityServiceConfig, report: &Path) {
    let report: serde_json::Value =
        serde_json::from_slice(&std::fs::read(report).unwrap()).unwrap();
    let head = codex_hepta_contracts::HostAuthorityFrontierStore::<
        codex_hepta_memory::CognitiveCheckpointHead,
    >::open(
        RootAuthorityDirectory::open(config.checkpoint_state_dir.as_ref().unwrap()).unwrap(),
        "root-cognitive-checkpoint-v1".into(),
    )
    .unwrap()
    .load("root-cognitive-checkpoint-v1")
    .unwrap();
    assert_eq!(
        head.phase,
        codex_hepta_memory::CognitiveCheckpointPhase::Current
    );
    assert_eq!(
        serde_json::to_value(head.last_current).unwrap(),
        report["original_current_cut"]
    );
    assert_eq!(report["dispatch_count"], 1);
    assert_eq!(report["receipt_retired"], 1);
    let retained = crate::DeploymentFrontierStore::<serde_json::Value>::open_protected(
        &config.state_dir.join("issuer"),
    )
    .unwrap();
    assert_eq!(
        retained.load("local-final-use-issuer").unwrap()["sequence"],
        2
    );
    println!("{report}");
}
