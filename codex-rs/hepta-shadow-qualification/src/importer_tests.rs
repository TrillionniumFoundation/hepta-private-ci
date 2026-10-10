use std::fs;
use std::io::Write;

use super::importer::ImportCheckpoint;
use super::test_support::completed_run;
use super::test_support::product_receipts;
use super::test_support::transport_evidence;
use crate::FrozenOracle;
use crate::QualificationError;

#[test]
fn imports_exactly_four_artifacts_and_writes_a_checkpoint() -> Result<(), QualificationError> {
    let (completed, _temp) = completed_run()?;
    let _transport = transport_evidence(&completed)?;
    let products = product_receipts(&completed, &FrozenOracle::load_embedded()?)?;
    let checkpoint = ImportCheckpoint::create(&completed, &products)?;
    assert!(checkpoint.is_complete());
    assert_eq!(checkpoint.verified_count(), 4);
    assert!(checkpoint.failures().is_empty());
    assert_eq!(checkpoint.run_id(), completed.run_id());
    assert_eq!(checkpoint.evidence_set_sha256().len(), 64);
    assert!(
        checkpoint
            .run_root()
            .join("import-checkpoint.json")
            .is_file()
    );
    Ok(())
}

#[test]
fn inventories_all_broken_samples_before_checkpointing_failure() -> Result<(), QualificationError> {
    let (completed, _temp) = completed_run()?;
    let _transport = transport_evidence(&completed)?;
    let products = product_receipts(&completed, &FrozenOracle::load_embedded()?)?;
    fs::remove_file(completed.run_root().join("app_server-01.raw.json"))?;
    fs::write(completed.run_root().join("mcp-02.pre-send.json"), b"{}")?;
    let mut unexpected = fs::File::create(completed.run_root().join("unexpected.txt"))?;
    unexpected.write_all(b"unexpected")?;
    unexpected.sync_all()?;
    let checkpoint = ImportCheckpoint::create(&completed, &products)?;
    assert!(!checkpoint.is_complete());
    assert_eq!(checkpoint.verified_count(), 2);
    assert_eq!(checkpoint.failures().len(), 3);
    for expected in ["app_server-01", "mcp-02", "unexpected.txt"] {
        assert!(
            checkpoint
                .failures()
                .iter()
                .any(|failure| failure.artifact == expected)
        );
    }
    Ok(())
}
