use super::*;

#[test]
fn protected_context_refuses_unsupported_file_identity() -> Result<(), Box<dyn std::error::Error>> {
    let root = tempfile::tempdir()?;
    let path = root.path().join("absent-context");
    assert!(matches!(
        protected_context_bytes(&path, Digest32::of_bytes(b"context"), /*max*/ 1024),
        Err(AgentdError::Invalid(message)) if message == "protected context requires Unix file identity and Root custody"
    ));
    assert!(!path.exists());
    Ok(())
}
