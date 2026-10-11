use std::fs;

use serde_json::Value;

use super::importer::ImportCheckpoint;
use super::sealer::TerminalSeal;
use super::sealer::TerminalStatus;
use super::test_support::completed_run;
use super::test_support::product_receipts;
use super::test_support::transport_evidence;
use crate::FrozenOracle;
use crate::QualificationError;

#[test]
fn seals_a_complete_checkpoint_with_every_gate_disabled() -> Result<(), QualificationError> {
    let (completed, _temp) = completed_run()?;
    let _transport = transport_evidence(&completed)?;
    let products = product_receipts(&completed, &FrozenOracle::load_embedded()?)?;
    let checkpoint = ImportCheckpoint::create(&completed, &products)?;
    let seal = TerminalSeal::create(checkpoint)?;
    assert_eq!(seal.status(), TerminalStatus::Complete);
    assert_eq!(seal.verified_count(), 4);
    assert!(seal.failures().is_empty());
    assert_eq!(seal.checkpoint_sha256().len(), 64);
    assert_eq!(seal.evidence_set_sha256().len(), 64);
    assert_eq!(seal.terminal_seal_sha256().len(), 64);
    assert_eq!(seal.seal_file_sha256().len(), 64);
    assert_eq!(seal.run_id(), completed.run_id());
    let value: Value =
        serde_json::from_slice(&fs::read(seal.run_root().join("terminal-seal.json"))?)
            .map_err(|error| QualificationError::Serialization(error.to_string()))?;
    for gate in ["authority", "enforce", "outbound", "promotion"] {
        assert_eq!(value[gate], false);
    }
    assert_eq!(value["status"], "complete");
    assert_eq!(value["terminal"], true);
    Ok(())
}

#[test]
fn seals_a_failed_checkpoint_without_losing_failures() -> Result<(), QualificationError> {
    let (completed, _temp) = completed_run()?;
    let _transport = transport_evidence(&completed)?;
    let products = product_receipts(&completed, &FrozenOracle::load_embedded()?)?;
    fs::remove_file(completed.run_root().join("app_server-01.raw.json"))?;
    fs::write(completed.run_root().join("unexpected.txt"), b"unexpected")?;
    let checkpoint = ImportCheckpoint::create(&completed, &products)?;
    let expected_failures = checkpoint.failures().to_vec();
    let seal = TerminalSeal::create(checkpoint)?;
    assert_eq!(seal.status(), TerminalStatus::Failed);
    assert_eq!(seal.verified_count(), 3);
    assert_eq!(seal.failures(), expected_failures);
    Ok(())
}

#[test]
fn rejects_a_checkpoint_changed_before_sealing() -> Result<(), QualificationError> {
    let (completed, _temp) = completed_run()?;
    let _transport = transport_evidence(&completed)?;
    let products = product_receipts(&completed, &FrozenOracle::load_embedded()?)?;
    let checkpoint = ImportCheckpoint::create(&completed, &products)?;
    fs::write(completed.run_root().join("import-checkpoint.json"), b"{}")?;
    assert!(TerminalSeal::create(checkpoint).is_err());
    assert!(!completed.run_root().join("terminal-seal.json").exists());
    Ok(())
}
