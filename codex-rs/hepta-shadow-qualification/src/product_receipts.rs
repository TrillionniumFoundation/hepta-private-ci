use std::path::Path;
use std::path::PathBuf;

use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;

use crate::FrozenOracle;
use crate::ImportFailure;
use crate::QualificationError;
use crate::QualificationTrialOutcome;
use crate::SemanticSampleReport;
use crate::SemanticVerifier;
use crate::Surface;
use crate::digest::framed_digest;
use crate::digest::sha256;
use crate::durable::create_or_verify_private_directory;
use crate::durable::read_private_bounded;
use crate::durable::sync_directory;
use crate::durable::write_private_new;
use crate::product_database::MAX_DATABASE_BYTES;
use crate::product_database::ProductReceiptRow;
use crate::product_database::snapshot_and_read;
use crate::request::canonical_json;
use crate::request::valid_dynamic_id;

const MAX_IMPORT_RECEIPT_BYTES: usize = 16 * 1024;
const MAX_PRODUCT_RECEIPT_BYTES: usize = 16 * 1024;

pub struct ProductReceiptSet {
    pub(crate) artifacts: Vec<ProductReceiptArtifact>,
    pub(crate) failures: Vec<ImportFailure>,
    pub(crate) run_id: String,
    pub(crate) run_root: PathBuf,
}

impl ProductReceiptSet {
    pub async fn import(
        trial: &QualificationTrialOutcome,
        oracle: &FrozenOracle,
    ) -> Result<Self, QualificationError> {
        let run_root = trial.completed().run_root();
        let snapshot_root = run_root.join("product-evidence");
        create_or_verify_private_directory(&snapshot_root)?;
        let mut artifacts = Vec::with_capacity(4);
        let mut failures = Vec::new();
        for surface in [Surface::AppServer, Surface::Mcp] {
            let result = import_surface(trial, oracle, surface, &snapshot_root).await;
            match result {
                Ok(mut imported) => {
                    artifacts.append(&mut imported.artifacts);
                    failures.append(&mut imported.failures);
                }
                Err(error) => {
                    for ordinal in 1..=2 {
                        failures.push(ImportFailure {
                            artifact: stem(surface, ordinal),
                            reason: format!("product database import failed: {error}"),
                        });
                    }
                }
            }
        }
        artifacts.sort_by_key(|artifact| (artifact.surface.as_str(), artifact.ordinal));
        failures.sort_by(|left, right| {
            left.artifact
                .cmp(&right.artifact)
                .then(left.reason.cmp(&right.reason))
        });
        sync_directory(run_root)?;
        Ok(Self {
            artifacts,
            failures,
            run_id: trial.completed().run_id().to_string(),
            run_root: run_root.to_path_buf(),
        })
    }

    pub fn failures(&self) -> &[ImportFailure] {
        &self.failures
    }

    pub fn run_id(&self) -> &str {
        &self.run_id
    }

    pub fn run_root(&self) -> &Path {
        &self.run_root
    }

    pub fn semantic_reports(
        &self,
        oracle: &FrozenOracle,
    ) -> Result<Vec<SemanticSampleReport>, QualificationError> {
        let mut reports = Vec::with_capacity(4);
        for surface in [Surface::AppServer, Surface::Mcp] {
            for ordinal in 1..=2 {
                let report = match self.artifact(surface, ordinal) {
                    Some(artifact) => {
                        let before = self.verify_artifact(surface, ordinal);
                        let verified =
                            read_private_bounded(&artifact.raw_path, MAX_PRODUCT_RECEIPT_BYTES)
                                .and_then(|bytes| SemanticVerifier::verify(oracle, &bytes));
                        let after = self.verify_artifact(surface, ordinal);
                        match (before, verified, after) {
                            (Ok(before), Ok(verified), Ok(after)) if before == after => {
                                SemanticSampleReport::verified(surface, ordinal, &verified)
                            }
                            (before, verified, after) => SemanticSampleReport::failed(
                                surface,
                                ordinal,
                                oracle,
                                bounded_reason(format!(
                                    "durable semantic verification failed: before={before:?}; \
                                     verify={verified:?}; after={after:?}"
                                )),
                            )?,
                        }
                    }
                    None => SemanticSampleReport::failed(
                        surface,
                        ordinal,
                        oracle,
                        self.failure_reason(surface, ordinal),
                    )?,
                };
                reports.push(report);
            }
        }
        Ok(reports)
    }

    pub(crate) fn verify_artifact(&self, surface: Surface, ordinal: u8) -> Result<String, String> {
        let artifact = self
            .artifact(surface, ordinal)
            .ok_or_else(|| self.failure_reason(surface, ordinal))?;
        let raw = read_private_bounded(&artifact.raw_path, MAX_PRODUCT_RECEIPT_BYTES)
            .map_err(error_string)?;
        let imported = read_private_bounded(&artifact.import_path, MAX_IMPORT_RECEIPT_BYTES)
            .map_err(error_string)?;
        let database = read_private_bounded(&artifact.database_path, MAX_DATABASE_BYTES)
            .map_err(error_string)?;
        let receipt: StoredImportReceipt =
            serde_json::from_slice(&imported).map_err(error_string)?;
        if canonical_json(&receipt).map_err(error_string)? != imported
            || receipt.authority
            || receipt.enforce
            || receipt.outbound
            || receipt.promotion
            || receipt.schema != "hepta_shadow_qualification_product_import_v2"
            || receipt.schema_version != 2
            || receipt.surface != surface
            || receipt.ordinal != ordinal
            || receipt.raw_receipt_sha256 != sha256(&raw)
            || receipt.raw_receipt_sha256 != artifact.raw_sha256
            || receipt.database_snapshot_sha256 != sha256(&database)
            || receipt.database_snapshot_sha256 != artifact.database_sha256
        {
            return Err("product import receipt binding differs from durable files".to_string());
        }
        Ok(framed_digest(
            b"hepta-shadow-imported-product-receipt:v2",
            [sha256(&raw).as_bytes(), sha256(&imported).as_bytes()],
        ))
    }

    fn artifact(&self, surface: Surface, ordinal: u8) -> Option<&ProductReceiptArtifact> {
        self.artifacts
            .iter()
            .find(|artifact| artifact.surface == surface && artifact.ordinal == ordinal)
    }

    fn failure_reason(&self, surface: Surface, ordinal: u8) -> String {
        let name = stem(surface, ordinal);
        self.failures
            .iter()
            .find(|failure| failure.artifact == name)
            .map(|failure| bounded_reason(failure.reason.clone()))
            .unwrap_or_else(|| "product receipt is missing".to_string())
    }
}

struct SurfaceImport {
    artifacts: Vec<ProductReceiptArtifact>,
    failures: Vec<ImportFailure>,
}

pub(crate) struct ProductReceiptArtifact {
    pub(crate) database_path: PathBuf,
    pub(crate) database_sha256: String,
    pub(crate) import_path: PathBuf,
    pub(crate) ordinal: u8,
    pub(crate) raw_path: PathBuf,
    pub(crate) raw_sha256: String,
    pub(crate) surface: Surface,
}

async fn import_surface(
    trial: &QualificationTrialOutcome,
    oracle: &FrozenOracle,
    surface: Surface,
    snapshot_root: &Path,
) -> Result<SurfaceImport, QualificationError> {
    let layout = match surface {
        Surface::AppServer => trial.layout().app_server(),
        Surface::Mcp => trial.layout().mcp(),
    };
    let (database_sha256, database_path, rows) =
        snapshot_and_read(layout.sqlite(), surface, snapshot_root).await?;
    if rows.len() != 2 {
        return Err(invalid(
            "product database must contain exactly two governance receipts",
        ));
    }
    let expected_thread = match surface {
        Surface::AppServer => trial.app_server_thread_id(),
        Surface::Mcp => trial.mcp_thread_id(),
    };
    let expected_turns = (surface == Surface::AppServer).then(|| trial.app_server_turn_ids());
    let http = match surface {
        Surface::AppServer => trial.app_server_http(),
        Surface::Mcp => trial.mcp_http(),
    };
    let expected_calls = http
        .iter()
        .filter(|record| record.post_ordinal() == 1)
        .map(crate::HttpAuditRecord::call_id)
        .collect::<Vec<_>>();
    if expected_calls.len() != 2 {
        return Err(invalid(
            "surface lacks two product function call identities",
        ));
    }
    let mut artifacts = Vec::with_capacity(2);
    let mut failures = Vec::new();
    for (index, row) in rows.iter().enumerate() {
        let ordinal = u8::try_from(index + 1).map_err(|_| invalid("receipt ordinal overflow"))?;
        let expected_turn = expected_turns.and_then(|turns| turns.get(index).map(String::as_str));
        match validate_row(
            row,
            oracle,
            ordinal,
            expected_thread,
            expected_turn,
            expected_calls[index],
        ) {
            Ok(()) => match persist_row(
                trial.completed().run_root(),
                surface,
                ordinal,
                row,
                &database_path,
                &database_sha256,
            ) {
                Ok(artifact) => artifacts.push(artifact),
                Err(error) => failures.push(ImportFailure {
                    artifact: stem(surface, ordinal),
                    reason: error.to_string(),
                }),
            },
            Err(error) => failures.push(ImportFailure {
                artifact: stem(surface, ordinal),
                reason: error.to_string(),
            }),
        }
    }
    Ok(SurfaceImport {
        artifacts,
        failures,
    })
}

pub(crate) fn validate_row(
    row: &ProductReceiptRow,
    oracle: &FrozenOracle,
    ordinal: u8,
    thread_id: &str,
    turn_id: Option<&str>,
    call_id: &str,
) -> Result<(), QualificationError> {
    let bytes = row.payload_json.as_bytes();
    if bytes.len() > MAX_PRODUCT_RECEIPT_BYTES
        || row.seq != i64::from(ordinal)
        || row.schema_version != 1
        || row.thread_id != thread_id
        || turn_id.is_some_and(|expected| row.turn_id != expected)
        || !valid_dynamic_id(&row.turn_id)
        || row.call_id != call_id
        || sha256(bytes) != row.payload_sha256
    {
        return Err(invalid(
            "product receipt row binding differs from trial identity",
        ));
    }
    let value: Value = serde_json::from_slice(bytes)
        .map_err(|error| invalid(format!("invalid product receipt JSON: {error}")))?;
    if canonical_json(&value)? != bytes
        || value.get("receipt_id").and_then(Value::as_str) != Some(&row.receipt_id)
        || value.get("action_id").and_then(Value::as_str) != Some(&row.action_id)
        || value
            .pointer("/admission/decision_id")
            .and_then(Value::as_str)
            != Some(&row.admission_decision_id)
        || value
            .pointer("/authorization/decision_id")
            .and_then(Value::as_str)
            != Some(&row.authorization_decision_id)
    {
        return Err(invalid("product receipt payload differs from indexed row"));
    }
    SemanticVerifier::verify(oracle, bytes)?;
    Ok(())
}

fn persist_row(
    run_root: &Path,
    surface: Surface,
    ordinal: u8,
    row: &ProductReceiptRow,
    database_path: &Path,
    database_sha256: &str,
) -> Result<ProductReceiptArtifact, QualificationError> {
    let stem = stem(surface, ordinal);
    let raw_path = run_root.join(format!("{stem}.product-receipt.json"));
    let import_path = run_root.join(format!("{stem}.product-import.json"));
    let raw_sha256 = sha256(row.payload_json.as_bytes());
    let receipt = ImportReceipt {
        authority: false,
        database_snapshot_sha256: database_sha256,
        enforce: false,
        ordinal,
        outbound: false,
        promotion: false,
        raw_receipt_sha256: &raw_sha256,
        schema: "hepta_shadow_qualification_product_import_v2",
        schema_version: 2,
        surface,
    };
    write_private_new(&raw_path, row.payload_json.as_bytes())?;
    write_private_new(&import_path, &canonical_json(&receipt)?)?;
    Ok(ProductReceiptArtifact {
        database_path: database_path.to_path_buf(),
        database_sha256: database_sha256.to_string(),
        import_path,
        ordinal,
        raw_path,
        raw_sha256,
        surface,
    })
}

#[derive(Serialize)]
struct ImportReceipt<'a> {
    authority: bool,
    database_snapshot_sha256: &'a str,
    enforce: bool,
    ordinal: u8,
    outbound: bool,
    promotion: bool,
    raw_receipt_sha256: &'a str,
    schema: &'static str,
    schema_version: u32,
    surface: Surface,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredImportReceipt {
    authority: bool,
    database_snapshot_sha256: String,
    enforce: bool,
    ordinal: u8,
    outbound: bool,
    promotion: bool,
    raw_receipt_sha256: String,
    schema: String,
    schema_version: u32,
    surface: Surface,
}

fn stem(surface: Surface, ordinal: u8) -> String {
    format!("{}-{ordinal:02}", surface.as_str())
}

fn bounded_reason(mut reason: String) -> String {
    if reason.len() > 1_024 {
        let mut end = 1_024;
        while !reason.is_char_boundary(end) {
            end -= 1;
        }
        reason.truncate(end);
    }
    reason
}

fn error_string(error: impl std::fmt::Display) -> String {
    error.to_string()
}

fn invalid(message: impl Into<String>) -> QualificationError {
    QualificationError::Invalid(message.into())
}
