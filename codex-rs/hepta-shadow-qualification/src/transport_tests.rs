use super::test_support::completed_run;
use super::test_support::transport_evidence;
use crate::QualificationError;

#[test]
fn detects_transport_artifact_changes_after_capture() -> Result<(), QualificationError> {
    let (completed, _temp) = completed_run()?;
    let evidence = transport_evidence(&completed)?;
    evidence.verify()?;
    std::fs::write(completed.run_root().join("http/fixture.http"), b"changed")?;
    assert!(evidence.verify().is_err());
    Ok(())
}
