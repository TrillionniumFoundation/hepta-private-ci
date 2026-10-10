use std::collections::BTreeSet;
use std::path::Path;

use serde::Deserialize;
use serde::Serialize;

use crate::AcceptanceError;
use crate::manifest_inventory::VerifiedManifest;
use crate::manifest_inventory::digest_shape;
use crate::model::QualificationRunBinding;
use crate::qualification_evidence::CANDIDATE_HEAD;
use crate::qualification_evidence::CANDIDATE_TREE;
use crate::qualification_evidence::NORMALIZED_RECEIPT_SHA256;
use crate::qualification_evidence::ORACLE_CORPUS_SHA256;
use crate::qualification_evidence::ORACLE_SAMPLE_ID_SHA256;
use crate::qualification_evidence::PRODUCT_BINARY_RELATIVE_PATH;
use crate::qualification_evidence::PRODUCT_BINARY_SHA256;
use crate::qualification_evidence::PRODUCT_SOURCE_COMMIT;
use crate::qualification_evidence::PRODUCT_SOURCE_TREE;

pub(crate) fn validate_soak(
    manifest: &VerifiedManifest,
    product_root: &Path,
) -> Result<Vec<QualificationRunBinding>, AcceptanceError> {
    let soak = manifest.json_pinned::<SoakSummary>("shadow-soak/soak-summary.json")?;
    validate_soak_header(&soak, product_root)?;
    validate_runs(manifest, &soak)
}

fn validate_soak_header(soak: &SoakSummary, product_root: &Path) -> Result<(), AcceptanceError> {
    if soak.schema != "hepta_shadow_bounded_soak_receipt_v1"
        || soak.candidate_head != CANDIDATE_HEAD
        || soak.candidate_tree != CANDIDATE_TREE
        || soak.frozen_oracle_commit != PRODUCT_SOURCE_COMMIT
        || soak.frozen_product_sha256 != PRODUCT_BINARY_SHA256
        || soak.frozen_product
            != product_root
                .join(PRODUCT_BINARY_RELATIVE_PATH)
                .to_string_lossy()
        || !soak.authority.none()
        || !soak.bounded
        || !soak.exact_closure
        || !soak.sustainable
        || !soak.run_ids_unique
        || soak.run_count != 3
        || soak.runs.len() != 3
        || soak.run_timeout_seconds == 0
        || soak.run_timeout_seconds > 300
        || !soak.total_duration_seconds.is_finite()
        || soak.total_duration_seconds <= 0.0
        || soak.total_duration_seconds > f64::from(soak.run_timeout_seconds) * 3.0
        || !soak.binary.starts_with(
            "/Volumes/T5/hepta-vnext/tmp/active-refactor/final-mac-cargo-3110c5aba5-r1/",
        )
        || !digest_shape(&soak.binary_sha256)
    {
        return Err(invalid(
            "bounded soak header differs from the frozen qualification",
        ));
    }
    Ok(())
}

fn validate_runs(
    manifest: &VerifiedManifest,
    soak: &SoakSummary,
) -> Result<Vec<QualificationRunBinding>, AcceptanceError> {
    let mut bindings = Vec::with_capacity(3);
    let mut run_ids = BTreeSet::new();
    for (offset, run) in soak.runs.iter().enumerate() {
        let index = u8::try_from(offset + 1).map_err(|_| invalid("soak run index overflow"))?;
        if run.index != index
            || !run.exact_closure
            || run.app_server_http_exchange_count != 4
            || run.mcp_http_exchange_count != 4
            || run.transport_artifact_count != 238
            || !run.duration_seconds.is_finite()
            || run.duration_seconds <= 0.0
            || run.duration_seconds > f64::from(soak.run_timeout_seconds)
            || !run_ids.insert(run.run_id.clone())
        {
            return Err(invalid("soak run summary differs from exact closure"));
        }
        for digest in [
            &run.checkpoint_sha256,
            &run.evidence_set_sha256,
            &run.manifest_sha256,
            &run.qualification_report_sha256,
            &run.summary_sha256,
            &run.terminal_seal_file_sha256,
            &run.terminal_seal_sha256,
            &run.transport_evidence_sha256,
            &run.transport_manifest_sha256,
        ] {
            if !digest_shape(digest) {
                return Err(invalid("soak run contains a malformed digest"));
            }
        }
        let relative_root = format!("shadow-soak/run-{index:02}/runtime/observer/{}", run.run_id);
        let expected_root = manifest.root.join(&relative_root);
        if run.run_root != expected_root.to_string_lossy()
            || run.runtime_root
                != manifest
                    .root
                    .join(format!("shadow-soak/run-{index:02}/runtime"))
                    .to_string_lossy()
        {
            return Err(invalid("soak run path escaped the sealed receipt root"));
        }
        let report_path = format!("{relative_root}/qualification-report.json");
        let seal_path = format!("{relative_root}/terminal-seal.json");
        manifest.require_hash(&report_path, &run.qualification_report_sha256)?;
        manifest.require_hash(&seal_path, &run.terminal_seal_file_sha256)?;
        let report = manifest.json_canonical::<QualificationReport>(&report_path)?;
        validate_report(&report, run)?;
        let seal = manifest.json_canonical::<TerminalSeal>(&seal_path)?;
        validate_seal(&seal, run)?;
        bindings.push(QualificationRunBinding {
            evidence_set_sha256: run.evidence_set_sha256.clone(),
            index,
            manifest_sha256: run.manifest_sha256.clone(),
            qualification_report_sha256: run.qualification_report_sha256.clone(),
            run_id: run.run_id.clone(),
            run_root_relative_path: relative_root,
            terminal_seal_file_sha256: run.terminal_seal_file_sha256.clone(),
            terminal_seal_sha256: run.terminal_seal_sha256.clone(),
            transport_evidence_sha256: run.transport_evidence_sha256.clone(),
            transport_manifest_sha256: run.transport_manifest_sha256.clone(),
        });
    }
    Ok(bindings)
}

fn validate_report(report: &QualificationReport, run: &SoakRun) -> Result<(), AcceptanceError> {
    if report.schema != "hepta_shadow_qualification_report_v3"
        || report.schema_version != 3
        || !report.authority.none()
        || !report.exact_closure
        || !report.failures.is_empty()
        || report.run_id != run.run_id
        || report.evidence_set_sha256 != run.evidence_set_sha256
        || report.import_checkpoint_sha256 != run.checkpoint_sha256
        || report.manifest_sha256 != run.manifest_sha256
        || report.terminal_seal_sha256 != run.terminal_seal_sha256
        || report.terminal_status != "complete"
        || report.transport_artifact_count != run.transport_artifact_count
        || report.transport_evidence_sha256 != run.transport_evidence_sha256
        || report.transport_manifest_sha256 != run.transport_manifest_sha256
        || report.verified_artifact_count != 4
        || report.oracle.corpus_sha256 != ORACLE_CORPUS_SHA256
        || report.oracle.expected_normalized_receipt_sha256 != NORMALIZED_RECEIPT_SHA256
        || report.oracle.oracle_commit != PRODUCT_SOURCE_COMMIT
        || report.oracle.oracle_tree != PRODUCT_SOURCE_TREE
        || report.oracle.sample_id_sha256 != ORACLE_SAMPLE_ID_SHA256
        || report.samples.len() != 4
    {
        return Err(invalid("qualification report differs from exact closure"));
    }
    for (sample, (surface, ordinal)) in
        report
            .samples
            .iter()
            .zip([("app_server", 1), ("app_server", 2), ("mcp", 1), ("mcp", 2)])
    {
        if !sample.byte_for_byte_equal
            || sample.failure.is_some()
            || sample.normalized_receipt_sha256.as_deref() != Some(NORMALIZED_RECEIPT_SHA256)
            || sample.oracle_sample_id_sha256 != ORACLE_SAMPLE_ID_SHA256
            || sample.ordinal != ordinal
            || sample.surface != surface
            || !sample
                .source_receipt_sha256
                .as_deref()
                .is_some_and(digest_shape)
        {
            return Err(invalid("qualification semantic sample is not exact"));
        }
    }
    Ok(())
}

fn validate_seal(seal: &TerminalSeal, run: &SoakRun) -> Result<(), AcceptanceError> {
    if seal.schema != "hepta_shadow_qualification_terminal_seal_v3"
        || seal.schema_version != 3
        || seal.authority
        || seal.enforce
        || seal.outbound
        || seal.promotion
        || seal.checkpoint_sha256 != run.checkpoint_sha256
        || seal.evidence_set_sha256 != run.evidence_set_sha256
        || !seal.failures.is_empty()
        || seal.run_id != run.run_id
        || seal.status != "complete"
        || !seal.terminal
        || seal.terminal_seal_sha256 != run.terminal_seal_sha256
        || seal.transport_artifact_count != run.transport_artifact_count
        || seal.transport_evidence_sha256 != run.transport_evidence_sha256
        || seal.verified_artifact_count != 4
    {
        return Err(invalid(
            "qualification terminal seal differs from complete status",
        ));
    }
    Ok(())
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct AuthorityFlags {
    enforce: bool,
    operator_acceptance: bool,
    outbound: bool,
    promotion: bool,
    qualification: bool,
    retirement: bool,
}

impl AuthorityFlags {
    fn none(&self) -> bool {
        !self.enforce
            && !self.operator_acceptance
            && !self.outbound
            && !self.promotion
            && !self.qualification
            && !self.retirement
    }
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct SoakSummary {
    authority: AuthorityFlags,
    binary: String,
    binary_sha256: String,
    bounded: bool,
    candidate_head: String,
    candidate_tree: String,
    completed_at: String,
    exact_closure: bool,
    frozen_oracle_commit: String,
    frozen_product: String,
    frozen_product_sha256: String,
    run_count: usize,
    run_ids_unique: bool,
    run_timeout_seconds: u32,
    runs: Vec<SoakRun>,
    schema: String,
    started_at: String,
    sustainable: bool,
    total_duration_seconds: f64,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct SoakRun {
    app_server_http_exchange_count: usize,
    checkpoint_sha256: String,
    duration_seconds: f64,
    evidence_set_sha256: String,
    exact_closure: bool,
    index: u8,
    manifest_sha256: String,
    mcp_http_exchange_count: usize,
    qualification_report_sha256: String,
    run_id: String,
    run_root: String,
    runtime_root: String,
    summary_sha256: String,
    terminal_seal_file_sha256: String,
    terminal_seal_sha256: String,
    transport_artifact_count: usize,
    transport_evidence_sha256: String,
    transport_manifest_sha256: String,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct QualificationReport {
    authority: AuthorityFlags,
    evidence_set_sha256: String,
    exact_closure: bool,
    failures: Vec<ReportFailure>,
    import_checkpoint_sha256: String,
    manifest_sha256: String,
    oracle: StoredOracleBinding,
    run_id: String,
    samples: Vec<SemanticSample>,
    schema: String,
    schema_version: u32,
    terminal_seal_sha256: String,
    terminal_status: String,
    transport_artifact_count: usize,
    transport_evidence_sha256: String,
    transport_manifest_sha256: String,
    verified_artifact_count: usize,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ReportFailure {
    artifact: String,
    reason: String,
    stage: String,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredOracleBinding {
    corpus_sha256: String,
    expected_normalized_receipt_sha256: String,
    oracle_commit: String,
    oracle_tree: String,
    sample_id_sha256: String,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct SemanticSample {
    byte_for_byte_equal: bool,
    failure: Option<String>,
    normalized_receipt_sha256: Option<String>,
    oracle_sample_id_sha256: String,
    ordinal: u8,
    source_receipt_sha256: Option<String>,
    surface: String,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct TerminalSeal {
    authority: bool,
    checkpoint_sha256: String,
    enforce: bool,
    evidence_set_sha256: String,
    failures: Vec<serde_json::Value>,
    outbound: bool,
    promotion: bool,
    run_id: String,
    schema: String,
    schema_version: u32,
    status: String,
    terminal: bool,
    terminal_seal_sha256: String,
    transport_artifact_count: usize,
    transport_evidence_sha256: String,
    verified_artifact_count: usize,
}

fn invalid(message: impl Into<String>) -> AcceptanceError {
    AcceptanceError::Invalid(message.into())
}
