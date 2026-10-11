use std::fs;

use serde_json::Value;

use super::importer::ImportCheckpoint;
use super::oracle::FrozenOracle;
use super::report::QualificationManifest;
use super::report::QualificationReport;
use super::report::SemanticSampleReport;
use super::sealer::TerminalSeal;
use super::test_support::completed_run;
use super::test_support::product_receipts;
use super::test_support::transport_evidence;
use crate::QualificationError;
use crate::Surface;

#[test]
fn writes_an_exact_report_with_no_authority() -> Result<(), QualificationError> {
    let (completed, _temp) = completed_run()?;
    let _transport = transport_evidence(&completed)?;
    let oracle = FrozenOracle::load_embedded()?;
    let products = product_receipts(&completed, &oracle)?;
    let manifest = QualificationManifest::write(&completed, &oracle)?;
    assert_eq!(manifest.file_sha256().len(), 64);
    assert_eq!(manifest.run_id(), completed.run_id());
    assert!(
        manifest
            .run_root()
            .join("qualification-manifest.json")
            .is_file()
    );
    let seal = TerminalSeal::create(ImportCheckpoint::create(&completed, &products)?)?;
    let samples = products.semantic_reports(&oracle)?;
    let report = QualificationReport::write(&manifest, &seal, &oracle, samples)?;
    assert!(report.exact_closure());
    assert!(report.failures().is_empty());
    assert_eq!(report.sample_count(), 4);
    assert_eq!(report.run_id(), completed.run_id());
    assert_eq!(report.file_sha256().len(), 64);
    let value: Value = serde_json::from_slice(&fs::read(
        report.run_root().join("qualification-report.json"),
    )?)
    .map_err(|error| QualificationError::Serialization(error.to_string()))?;
    assert_eq!(value["exact_closure"], true);
    for gate in [
        "enforce",
        "operator_acceptance",
        "outbound",
        "promotion",
        "qualification",
        "retirement",
    ] {
        assert_eq!(value["authority"][gate], false);
    }
    Ok(())
}

#[test]
fn inventories_import_semantic_duplicate_and_missing_failures() -> Result<(), QualificationError> {
    let (completed, _temp) = completed_run()?;
    let _transport = transport_evidence(&completed)?;
    let oracle = FrozenOracle::load_embedded()?;
    let products = product_receipts(&completed, &oracle)?;
    let manifest = QualificationManifest::write(&completed, &oracle)?;
    fs::remove_file(completed.run_root().join("mcp-02.raw.json"))?;
    let seal = TerminalSeal::create(ImportCheckpoint::create(&completed, &products)?)?;
    let failed =
        SemanticSampleReport::failed(Surface::AppServer, 1, &oracle, "receipt artifact is absent")?;
    let report =
        QualificationReport::write(&manifest, &seal, &oracle, vec![failed.clone(), failed])?;
    assert!(!report.exact_closure());
    for expected in [
        ("import", "mcp-02"),
        ("report", "app_server-01"),
        ("semantic", "app_server-01"),
        ("semantic", "app_server-02"),
        ("semantic", "mcp-01"),
        ("semantic", "mcp-02"),
    ] {
        assert!(
            report
                .failures()
                .iter()
                .any(|failure| failure.stage() == expected.0 && failure.artifact() == expected.1)
        );
    }
    assert!(
        report
            .failures()
            .iter()
            .any(|failure| failure.reason().contains("absent"))
    );
    Ok(())
}
