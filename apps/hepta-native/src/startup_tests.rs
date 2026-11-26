use super::*;
use crate::private_state_test_support::private_tempdir;

fn identity() -> (SessionIncarnation, RuntimeView) {
    let session = SessionIncarnation {
        endpoint_id: "test.endpoint".to_owned(),
        session_id: "test.session".to_owned(),
        generation: 1,
    };
    let view = RuntimeView {
        session_id: session.session_id.clone(),
        session_generation: session.generation,
        generation: 1,
        revision: 1,
        digest: "2".repeat(64),
        modules: vec!["ui.native".to_owned()],
    };
    (session, view)
}

#[test]
fn startup_recorder_pins_an_existing_parent_and_retains_exact_view_identity() {
    let root = private_tempdir();
    let path = root.path().join("startup.json");
    let recorder = StartupRecorder::new(path.clone(), Instant::now(), "1".repeat(64)).unwrap();
    let (session, view) = identity();
    recorder.record(&session, &view).unwrap();
    let observed: serde_json::Value =
        serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap();
    assert_eq!(observed["session"], serde_json::to_value(&session).unwrap());
    assert_eq!(observed["view_digest"], view.digest);
    assert_eq!(observed["view_revision"], view.revision);
    assert_eq!(observed["release"], false);
}

#[test]
fn startup_recorder_does_not_create_an_unprovisioned_parent() {
    let root = private_tempdir();
    let parent = root.path().join("missing");
    assert!(
        StartupRecorder::new(parent.join("startup.json"), Instant::now(), "1".repeat(64)).is_err()
    );
    assert!(!parent.exists());
}

#[cfg(unix)]
#[test]
fn startup_record_rejects_private_parent_replacement_after_construction() {
    let root = private_tempdir();
    let parent = root.path().join("state");
    PrivateStateRoot::open(&parent).unwrap();
    let path = parent.join("startup.json");
    let recorder = StartupRecorder::new(path.clone(), Instant::now(), "1".repeat(64)).unwrap();
    let original = root.path().join("original-state");
    std::fs::rename(&parent, &original).unwrap();
    PrivateStateRoot::open(&parent).unwrap();
    let (session, view) = identity();
    assert!(recorder.record(&session, &view).is_err());
    assert!(!path.exists());
    assert!(!original.join("startup.json").exists());
}
