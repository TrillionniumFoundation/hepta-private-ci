use super::*;

#[test]
fn unsupported_profile_cannot_acknowledge_a_store() {
    assert!(
        matches!(RunFile::open(PathBuf::from("uncreated-run-store.json")),
        Err(AgentRunError::Persistence(reason)) if reason.contains("non-Unix qualification is pending"))
    );
}
