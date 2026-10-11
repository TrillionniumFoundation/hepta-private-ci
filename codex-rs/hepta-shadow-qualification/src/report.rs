use std::collections::BTreeSet;
use std::path::Path;
use std::path::PathBuf;

use serde::Serialize;

use crate::CompletedPreSend;
use crate::FrozenOracle;
use crate::QualificationError;
use crate::Surface;
use crate::TerminalSeal;
use crate::TerminalStatus;
use crate::VerifiedSemanticReceipt;
use crate::digest::sha256;
use crate::durable::read_private_bounded;
use crate::durable::sync_directory;
use crate::durable::write_private_new;
use crate::request::canonical_json;
use crate::transport::TransportEvidence;

const MAX_FAILURE_REASON_BYTES: usize = 1_024;
const MAX_MANIFEST_BYTES: usize = 32 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
struct AuthorityFlags {
    enforce: bool,
    operator_acceptance: bool,
    outbound: bool,
    promotion: bool,
    qualification: bool,
    retirement: bool,
}

impl AuthorityFlags {
    const fn none() -> Self {
        Self {
            enforce: false,
            operator_acceptance: false,
            outbound: false,
            promotion: false,
            qualification: false,
            retirement: false,
        }
    }
}

#[derive(Serialize)]
struct OracleBinding<'a> {
    corpus_sha256: &'a str,
    expected_normalized_receipt_sha256: &'a str,
    oracle_commit: &'a str,
    oracle_tree: &'a str,
    sample_id_sha256: &'a str,
}

impl<'a> OracleBinding<'a> {
    fn new(oracle: &'a FrozenOracle) -> Self {
        Self {
            corpus_sha256: oracle.corpus_sha256(),
            expected_normalized_receipt_sha256: oracle.expected_normalized_receipt_sha256(),
            oracle_commit: oracle.oracle_commit(),
            oracle_tree: oracle.oracle_tree(),
            sample_id_sha256: oracle.sample_id_sha256(),
        }
    }
}

#[derive(Debug)]
pub struct QualificationManifest {
    file_sha256: String,
    run_id: String,
    run_root: PathBuf,
    transport_artifact_count: usize,
    transport_evidence_sha256: String,
    transport_manifest_sha256: String,
}

impl QualificationManifest {
    pub fn write(
        completed: &CompletedPreSend,
        oracle: &FrozenOracle,
    ) -> Result<Self, QualificationError> {
        let transport = TransportEvidence::load(completed.run_id(), completed.run_root())?;
        let expected_work_directory_sha256 = sha256(completed.expected_work_directory().as_bytes());
        let document = ManifestDocument {
            authority: AuthorityFlags::none(),
            duration_soak: false,
            expected_artifact_count: 4,
            expected_work_directory_sha256: &expected_work_directory_sha256,
            oracle: OracleBinding::new(oracle),
            qualification_kind: "controlled_short_trial",
            qualification_only: true,
            run_id: completed.run_id(),
            schema: "hepta_shadow_qualification_manifest_v3",
            schema_version: 3,
            surfaces: [Surface::AppServer, Surface::Mcp],
            transport_artifact_count: transport.artifact_count(),
            transport_evidence_sha256: transport.transport_evidence_sha256(),
            transport_manifest_sha256: transport.file_sha256(),
        };
        let bytes = canonical_json(&document)?;
        write_private_new(
            &completed.run_root().join("qualification-manifest.json"),
            &bytes,
        )?;
        sync_directory(completed.run_root())?;
        Ok(Self {
            file_sha256: sha256(&bytes),
            run_id: completed.run_id().to_string(),
            run_root: completed.run_root().to_path_buf(),
            transport_artifact_count: transport.artifact_count(),
            transport_evidence_sha256: transport.transport_evidence_sha256().to_string(),
            transport_manifest_sha256: transport.file_sha256().to_string(),
        })
    }

    pub fn file_sha256(&self) -> &str {
        &self.file_sha256
    }

    pub fn run_id(&self) -> &str {
        &self.run_id
    }

    pub fn run_root(&self) -> &Path {
        &self.run_root
    }
}

#[derive(Serialize)]
struct ManifestDocument<'a> {
    authority: AuthorityFlags,
    duration_soak: bool,
    expected_artifact_count: usize,
    expected_work_directory_sha256: &'a str,
    oracle: OracleBinding<'a>,
    qualification_kind: &'static str,
    qualification_only: bool,
    run_id: &'a str,
    schema: &'static str,
    schema_version: u32,
    surfaces: [Surface; 2],
    transport_artifact_count: usize,
    transport_evidence_sha256: &'a str,
    transport_manifest_sha256: &'a str,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct SemanticSampleReport {
    byte_for_byte_equal: bool,
    failure: Option<String>,
    normalized_receipt_sha256: Option<String>,
    oracle_sample_id_sha256: String,
    ordinal: u8,
    source_receipt_sha256: Option<String>,
    surface: Surface,
}

impl SemanticSampleReport {
    pub fn verified(surface: Surface, ordinal: u8, receipt: &VerifiedSemanticReceipt) -> Self {
        Self {
            byte_for_byte_equal: true,
            failure: None,
            normalized_receipt_sha256: Some(receipt.normalized_receipt_sha256().to_string()),
            oracle_sample_id_sha256: receipt.oracle_sample_id_sha256().to_string(),
            ordinal,
            source_receipt_sha256: Some(receipt.source_receipt_sha256().to_string()),
            surface,
        }
    }

    pub fn failed(
        surface: Surface,
        ordinal: u8,
        oracle: &FrozenOracle,
        reason: impl Into<String>,
    ) -> Result<Self, QualificationError> {
        let reason = reason.into();
        if reason.is_empty() || reason.len() > MAX_FAILURE_REASON_BYTES {
            return Err(invalid("semantic failure reason is empty or oversized"));
        }
        Ok(Self {
            byte_for_byte_equal: false,
            failure: Some(reason),
            normalized_receipt_sha256: None,
            oracle_sample_id_sha256: oracle.sample_id_sha256().to_string(),
            ordinal,
            source_receipt_sha256: None,
            surface,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct ReportFailure {
    artifact: String,
    reason: String,
    stage: String,
}

impl ReportFailure {
    pub fn artifact(&self) -> &str {
        &self.artifact
    }

    pub fn reason(&self) -> &str {
        &self.reason
    }

    pub fn stage(&self) -> &str {
        &self.stage
    }
}

#[derive(Debug)]
pub struct QualificationReport {
    exact_closure: bool,
    failures: Vec<ReportFailure>,
    file_sha256: String,
    run_id: String,
    run_root: PathBuf,
    sample_count: usize,
}

impl QualificationReport {
    pub fn write(
        manifest: &QualificationManifest,
        seal: &TerminalSeal,
        oracle: &FrozenOracle,
        mut samples: Vec<SemanticSampleReport>,
    ) -> Result<Self, QualificationError> {
        if manifest.run_id() != seal.run_id() || manifest.run_root() != seal.run_root() {
            return Err(invalid(
                "manifest and terminal seal belong to different runs",
            ));
        }
        let transport = TransportEvidence::load(manifest.run_id(), manifest.run_root())?;
        if manifest.transport_artifact_count != seal.transport_artifact_count()
            || manifest.transport_artifact_count != transport.artifact_count()
            || manifest.transport_evidence_sha256 != seal.transport_evidence_sha256()
            || manifest.transport_evidence_sha256 != transport.transport_evidence_sha256()
            || manifest.transport_manifest_sha256 != transport.file_sha256()
        {
            return Err(invalid(
                "manifest, terminal seal, and transport evidence differ",
            ));
        }
        let manifest_bytes = read_private_bounded(
            &manifest.run_root().join("qualification-manifest.json"),
            MAX_MANIFEST_BYTES,
        )?;
        if sha256(&manifest_bytes) != manifest.file_sha256() {
            return Err(invalid(
                "durable qualification manifest changed before reporting",
            ));
        }
        samples.sort_by(|left, right| {
            left.surface
                .as_str()
                .cmp(right.surface.as_str())
                .then(left.ordinal.cmp(&right.ordinal))
        });
        let mut failures = seal
            .failures()
            .iter()
            .map(|failure| ReportFailure {
                artifact: failure.artifact.clone(),
                reason: failure.reason.clone(),
                stage: "import".to_string(),
            })
            .collect::<Vec<_>>();
        let mut seen = BTreeSet::new();
        for sample in &samples {
            let artifact = format!("{}-{:02}", sample.surface.as_str(), sample.ordinal);
            if !(1..=2).contains(&sample.ordinal) {
                failures.push(failure(
                    "report",
                    &artifact,
                    "sample ordinal is outside 1..=2",
                ));
            }
            if !seen.insert((sample.surface.as_str(), sample.ordinal)) {
                failures.push(failure("report", &artifact, "duplicate semantic sample"));
            }
            if let Some(reason) = &sample.failure {
                failures.push(failure("semantic", &artifact, reason));
            } else if !sample.byte_for_byte_equal
                || sample.normalized_receipt_sha256.as_deref()
                    != Some(oracle.expected_normalized_receipt_sha256())
                || sample.oracle_sample_id_sha256 != oracle.sample_id_sha256()
                || sample.source_receipt_sha256.is_none()
            {
                failures.push(failure(
                    "semantic",
                    &artifact,
                    "sample does not carry an exact frozen-oracle comparison",
                ));
            }
        }
        for surface in [Surface::AppServer, Surface::Mcp] {
            for ordinal in 1..=2 {
                if !seen.contains(&(surface.as_str(), ordinal)) {
                    failures.push(failure(
                        "semantic",
                        &format!("{}-{ordinal:02}", surface.as_str()),
                        "semantic sample is missing",
                    ));
                }
            }
        }
        if seal.status() != TerminalStatus::Complete && seal.failures().is_empty() {
            failures.push(failure(
                "terminal",
                "terminal-seal.json",
                "terminal import status is failed",
            ));
        }
        failures.sort_by(|left, right| {
            left.stage
                .cmp(&right.stage)
                .then(left.artifact.cmp(&right.artifact))
                .then(left.reason.cmp(&right.reason))
        });
        let exact_closure = failures.is_empty()
            && seal.status() == TerminalStatus::Complete
            && seal.verified_count() == 4
            && transport.artifact_count() > 0
            && samples.len() == 4;
        let document = ReportDocument {
            authority: AuthorityFlags::none(),
            evidence_set_sha256: seal.evidence_set_sha256(),
            exact_closure,
            failures: &failures,
            import_checkpoint_sha256: seal.checkpoint_sha256(),
            manifest_sha256: manifest.file_sha256(),
            oracle: OracleBinding::new(oracle),
            run_id: seal.run_id(),
            samples: &samples,
            schema: "hepta_shadow_qualification_report_v3",
            schema_version: 3,
            terminal_seal_sha256: seal.terminal_seal_sha256(),
            terminal_status: seal.status(),
            transport_artifact_count: transport.artifact_count(),
            transport_evidence_sha256: transport.transport_evidence_sha256(),
            transport_manifest_sha256: transport.file_sha256(),
            verified_artifact_count: seal.verified_count(),
        };
        let bytes = canonical_json(&document)?;
        write_private_new(&seal.run_root().join("qualification-report.json"), &bytes)?;
        sync_directory(seal.run_root())?;
        Ok(Self {
            exact_closure,
            failures,
            file_sha256: sha256(&bytes),
            run_id: seal.run_id().to_string(),
            run_root: seal.run_root().to_path_buf(),
            sample_count: samples.len(),
        })
    }

    pub fn exact_closure(&self) -> bool {
        self.exact_closure
    }

    pub fn failures(&self) -> &[ReportFailure] {
        &self.failures
    }

    pub fn file_sha256(&self) -> &str {
        &self.file_sha256
    }

    pub fn run_id(&self) -> &str {
        &self.run_id
    }

    pub fn run_root(&self) -> &Path {
        &self.run_root
    }

    pub fn sample_count(&self) -> usize {
        self.sample_count
    }
}

#[derive(Serialize)]
struct ReportDocument<'a> {
    authority: AuthorityFlags,
    evidence_set_sha256: &'a str,
    exact_closure: bool,
    failures: &'a [ReportFailure],
    import_checkpoint_sha256: &'a str,
    manifest_sha256: &'a str,
    oracle: OracleBinding<'a>,
    run_id: &'a str,
    samples: &'a [SemanticSampleReport],
    schema: &'static str,
    schema_version: u32,
    terminal_seal_sha256: &'a str,
    terminal_status: TerminalStatus,
    transport_artifact_count: usize,
    transport_evidence_sha256: &'a str,
    transport_manifest_sha256: &'a str,
    verified_artifact_count: usize,
}

fn failure(stage: &str, artifact: &str, reason: &str) -> ReportFailure {
    ReportFailure {
        artifact: artifact.to_string(),
        reason: reason.to_string(),
        stage: stage.to_string(),
    }
}

fn invalid(message: impl Into<String>) -> QualificationError {
    QualificationError::Invalid(message.into())
}
