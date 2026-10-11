use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::path::Path;
use std::path::PathBuf;

use serde::Deserialize;
use serde::Serialize;

use crate::ChildOutcome;
use crate::HttpAuditRecord;
use crate::QualificationError;
use crate::QualificationTrialOutcome;
use crate::Surface;
use crate::digest::framed_digest;
use crate::digest::sha256;
use crate::durable::read_private_bounded;
use crate::durable::verify_private_directory;
use crate::durable::write_private_new;
use crate::request::canonical_json;

const APP_INBOUND_COUNT: u64 = 40;
const APP_OUTBOUND_COUNT: u64 = 5;
const MAX_ARTIFACT_BYTES: usize = 16 * 1024 * 1024;
const MAX_MANIFEST_BYTES: usize = 256 * 1024;
const MAX_TRANSPORT_BYTES: usize = 64 * 1024 * 1024;
const MCP_INBOUND_COUNT: u64 = 53;
const MCP_OUTBOUND_COUNT: u64 = 4;
const TRANSPORT_DOMAIN: &[u8] = b"hepta-shadow-qualification-transport:v1";

pub(crate) struct TransportEvidence {
    artifact_count: usize,
    file_sha256: String,
    run_id: String,
    run_root: PathBuf,
    transport_evidence_sha256: String,
}

impl TransportEvidence {
    pub(crate) fn capture(trial: &QualificationTrialOutcome) -> Result<Self, QualificationError> {
        if trial.app_server_http().len() != 4
            || trial.mcp_http().len() != 4
            || trial.app_server_child().inbound_message_count() != APP_INBOUND_COUNT
            || trial.mcp_child().inbound_message_count() != MCP_INBOUND_COUNT
        {
            return Err(invalid(
                "product transport cardinalities differ from exact trial",
            ));
        }
        let captured = read_artifacts(trial.completed().run_root())?;
        let actual_paths = captured
            .iter()
            .map(|artifact| artifact.entry.path.clone())
            .collect::<BTreeSet<_>>();
        if actual_paths != exact_paths() {
            return Err(invalid(
                "durable transport inventory differs from exact trial",
            ));
        }
        let by_path = captured
            .iter()
            .map(|artifact| (artifact.entry.path.as_str(), artifact))
            .collect::<BTreeMap<_, _>>();
        verify_http(&by_path, Surface::AppServer, trial.app_server_http())?;
        verify_http(&by_path, Surface::Mcp, trial.mcp_http())?;
        verify_protocol(&by_path)?;
        verify_stderr(&by_path, Surface::AppServer, trial.app_server_child())?;
        verify_stderr(&by_path, Surface::Mcp, trial.mcp_child())?;
        Self::write(
            trial.completed().run_id(),
            trial.completed().run_root(),
            captured,
        )
    }

    pub(crate) fn load(run_id: &str, run_root: &Path) -> Result<Self, QualificationError> {
        verify_private_directory(run_root)?;
        let path = run_root.join("transport-manifest.json");
        let bytes = read_private_bounded(&path, MAX_MANIFEST_BYTES)?;
        let manifest: TransportManifest = serde_json::from_slice(&bytes)
            .map_err(|error| QualificationError::Serialization(error.to_string()))?;
        if canonical_json(&manifest)? != bytes
            || manifest.fields.authority
            || manifest.fields.enforce
            || manifest.fields.outbound
            || manifest.fields.promotion
            || manifest.fields.run_id != run_id
            || manifest.fields.schema != "hepta_shadow_qualification_transport_manifest_v1"
            || manifest.fields.schema_version != 1
            || manifest.fields.artifact_count != manifest.fields.artifacts.len()
            || transport_digest(&manifest.fields)? != manifest.transport_evidence_sha256
        {
            return Err(invalid("durable transport manifest binding differs"));
        }
        let current = read_artifacts(run_root)?
            .into_iter()
            .map(|artifact| artifact.entry)
            .collect::<Vec<_>>();
        if current != manifest.fields.artifacts {
            return Err(invalid("durable transport artifacts changed after capture"));
        }
        Ok(Self {
            artifact_count: current.len(),
            file_sha256: sha256(&bytes),
            run_id: run_id.to_string(),
            run_root: run_root.to_path_buf(),
            transport_evidence_sha256: manifest.transport_evidence_sha256,
        })
    }

    #[cfg(test)]
    pub(crate) fn capture_tree(run_id: &str, run_root: &Path) -> Result<Self, QualificationError> {
        let captured = read_artifacts(run_root)?;
        Self::write(run_id, run_root, captured)
    }

    pub(crate) fn verify(&self) -> Result<(), QualificationError> {
        let current = Self::load(&self.run_id, &self.run_root)?;
        if current.artifact_count != self.artifact_count
            || current.file_sha256 != self.file_sha256
            || current.transport_evidence_sha256 != self.transport_evidence_sha256
        {
            return Err(invalid("transport evidence identity changed after capture"));
        }
        Ok(())
    }

    pub(crate) fn artifact_count(&self) -> usize {
        self.artifact_count
    }

    pub(crate) fn file_sha256(&self) -> &str {
        &self.file_sha256
    }

    pub(crate) fn transport_evidence_sha256(&self) -> &str {
        &self.transport_evidence_sha256
    }

    fn write(
        run_id: &str,
        run_root: &Path,
        captured: Vec<CapturedArtifact>,
    ) -> Result<Self, QualificationError> {
        let artifacts = captured
            .into_iter()
            .map(|artifact| artifact.entry)
            .collect::<Vec<_>>();
        let fields = TransportFields {
            artifact_count: artifacts.len(),
            artifacts,
            authority: false,
            enforce: false,
            outbound: false,
            promotion: false,
            run_id: run_id.to_string(),
            schema: "hepta_shadow_qualification_transport_manifest_v1".to_string(),
            schema_version: 1,
        };
        let transport_evidence_sha256 = transport_digest(&fields)?;
        let manifest = TransportManifest {
            fields,
            transport_evidence_sha256: transport_evidence_sha256.clone(),
        };
        let bytes = canonical_json(&manifest)?;
        write_private_new(&run_root.join("transport-manifest.json"), &bytes)?;
        Ok(Self {
            artifact_count: manifest.fields.artifact_count,
            file_sha256: sha256(&bytes),
            run_id: run_id.to_string(),
            run_root: run_root.to_path_buf(),
            transport_evidence_sha256,
        })
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct TransportArtifact {
    path: String,
    sha256: String,
    size_bytes: usize,
}

struct CapturedArtifact {
    bytes: Vec<u8>,
    entry: TransportArtifact,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct TransportManifest {
    fields: TransportFields,
    transport_evidence_sha256: String,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct TransportFields {
    artifact_count: usize,
    artifacts: Vec<TransportArtifact>,
    authority: bool,
    enforce: bool,
    outbound: bool,
    promotion: bool,
    run_id: String,
    schema: String,
    schema_version: u32,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredProtocolReceipt {
    authority: bool,
    direction: String,
    enforce: bool,
    outbound: bool,
    promotion: bool,
    raw_sha256: String,
    raw_size_bytes: usize,
    schema: String,
    schema_version: u32,
    sequence: u64,
    surface: Surface,
}

fn read_artifacts(run_root: &Path) -> Result<Vec<CapturedArtifact>, QualificationError> {
    let mut captured = Vec::new();
    let mut total_bytes = 0_usize;
    for directory in ["http", "protocol"] {
        let root = run_root.join(directory);
        verify_private_directory(&root)?;
        for entry in std::fs::read_dir(root)? {
            let entry = entry?;
            let metadata = std::fs::symlink_metadata(entry.path())?;
            let name = entry
                .file_name()
                .into_string()
                .map_err(|_| invalid("transport artifact name is not UTF-8"))?;
            if metadata.file_type().is_symlink() || !metadata.is_file() {
                return Err(invalid("transport tree contains a non-regular artifact"));
            }
            let bytes = read_private_bounded(&entry.path(), MAX_ARTIFACT_BYTES)?;
            total_bytes = total_bytes.saturating_add(bytes.len());
            if total_bytes > MAX_TRANSPORT_BYTES {
                return Err(invalid("transport evidence exceeds its aggregate bound"));
            }
            captured.push(CapturedArtifact {
                entry: TransportArtifact {
                    path: format!("{directory}/{name}"),
                    sha256: sha256(&bytes),
                    size_bytes: bytes.len(),
                },
                bytes,
            });
        }
    }
    captured.sort_by(|left, right| left.entry.path.cmp(&right.entry.path));
    Ok(captured)
}

fn exact_paths() -> BTreeSet<String> {
    let mut paths = BTreeSet::new();
    for surface in [Surface::AppServer, Surface::Mcp] {
        for sample in 1..=2 {
            for post in 1..=2 {
                let prefix = format!("http/{}-{sample:02}-{post:02}", surface.as_str());
                for suffix in [
                    "request-body.json",
                    "request.http",
                    "response.http",
                    "response.sse",
                ] {
                    paths.insert(format!("{prefix}-{suffix}"));
                }
            }
        }
        let (inbound, outbound) = match surface {
            Surface::AppServer => (APP_INBOUND_COUNT, APP_OUTBOUND_COUNT),
            Surface::Mcp => (MCP_INBOUND_COUNT, MCP_OUTBOUND_COUNT),
        };
        for sequence in 1..=inbound {
            let prefix = format!("protocol/{}-inbound-{sequence:06}", surface.as_str());
            paths.insert(format!("{prefix}.raw.jsonl"));
            paths.insert(format!("{prefix}.receipt.json"));
        }
        for sequence in 1..=outbound {
            let prefix = format!("protocol/{}-outbound-{sequence:03}", surface.as_str());
            paths.insert(format!("{prefix}.raw.jsonl"));
            paths.insert(format!("{prefix}.receipt.json"));
        }
        paths.insert(format!("protocol/{}-stderr.log", surface.as_str()));
    }
    paths
}

fn verify_http(
    artifacts: &BTreeMap<&str, &CapturedArtifact>,
    surface: Surface,
    records: &[HttpAuditRecord],
) -> Result<(), QualificationError> {
    for (index, record) in records.iter().enumerate() {
        let sequence = u8::try_from(index).map_err(|_| invalid("HTTP sequence overflow"))?;
        let sample = sequence / 2 + 1;
        let post = sequence % 2 + 1;
        if record.surface() != surface
            || record.sample_ordinal() != sample
            || record.post_ordinal() != post
        {
            return Err(invalid("HTTP audit record ordering differs"));
        }
        let prefix = format!("http/{}-{sample:02}-{post:02}", surface.as_str());
        for (suffix, expected) in [
            ("request-body.json", record.request_body_sha256()),
            ("request.http", record.request_wire_sha256()),
            ("response.http", record.response_wire_sha256()),
            ("response.sse", record.response_body_sha256()),
        ] {
            if artifacts
                .get(format!("{prefix}-{suffix}").as_str())
                .map(|artifact| artifact.entry.sha256.as_str())
                != Some(expected)
            {
                return Err(invalid("HTTP audit digest differs from durable artifact"));
            }
        }
    }
    Ok(())
}

fn verify_protocol(
    artifacts: &BTreeMap<&str, &CapturedArtifact>,
) -> Result<(), QualificationError> {
    for surface in [Surface::AppServer, Surface::Mcp] {
        let (inbound, outbound) = match surface {
            Surface::AppServer => (APP_INBOUND_COUNT, APP_OUTBOUND_COUNT),
            Surface::Mcp => (MCP_INBOUND_COUNT, MCP_OUTBOUND_COUNT),
        };
        for sequence in 1..=inbound {
            verify_protocol_pair(artifacts, surface, "inbound", sequence, /*width*/ 6)?;
        }
        for sequence in 1..=outbound {
            verify_protocol_pair(artifacts, surface, "outbound", sequence, /*width*/ 3)?;
        }
    }
    Ok(())
}

fn verify_protocol_pair(
    artifacts: &BTreeMap<&str, &CapturedArtifact>,
    surface: Surface,
    direction: &str,
    sequence: u64,
    width: usize,
) -> Result<(), QualificationError> {
    let prefix = format!(
        "protocol/{}-{direction}-{sequence:0width$}",
        surface.as_str()
    );
    let raw = artifacts
        .get(format!("{prefix}.raw.jsonl").as_str())
        .ok_or_else(|| invalid("protocol raw artifact is missing"))?;
    let receipt = artifacts
        .get(format!("{prefix}.receipt.json").as_str())
        .ok_or_else(|| invalid("protocol receipt artifact is missing"))?;
    let stored: StoredProtocolReceipt = serde_json::from_slice(&receipt.bytes)
        .map_err(|error| QualificationError::Serialization(error.to_string()))?;
    if canonical_json(&stored)? != receipt.bytes
        || stored.authority
        || stored.enforce
        || stored.outbound
        || stored.promotion
        || stored.direction
            != format!("{direction}_pre_send").replace("inbound_pre_send", "inbound_post_receive")
        || stored.raw_sha256 != raw.entry.sha256
        || stored.raw_size_bytes != raw.entry.size_bytes
        || stored.schema != "hepta_shadow_qualification_protocol_artifact_v2"
        || stored.schema_version != 2
        || stored.sequence != sequence
        || stored.surface != surface
        || raw.bytes.len() < 2
        || raw.bytes.last() != Some(&b'\n')
        || raw.bytes[..raw.bytes.len() - 1]
            .iter()
            .any(|byte| matches!(byte, b'\n' | b'\r'))
    {
        return Err(invalid(
            "protocol receipt differs from durable raw artifact",
        ));
    }
    Ok(())
}

fn verify_stderr(
    artifacts: &BTreeMap<&str, &CapturedArtifact>,
    surface: Surface,
    outcome: &ChildOutcome,
) -> Result<(), QualificationError> {
    let artifact = artifacts
        .get(format!("protocol/{}-stderr.log", surface.as_str()).as_str())
        .ok_or_else(|| invalid("product stderr artifact is missing"))?;
    if outcome.stderr_truncated()
        || outcome.stderr_size_bytes() != artifact.entry.size_bytes as u64
        || outcome.stderr_sha256() != artifact.entry.sha256
    {
        return Err(invalid(
            "product stderr digest differs from durable artifact",
        ));
    }
    Ok(())
}

fn transport_digest(fields: &TransportFields) -> Result<String, QualificationError> {
    let bytes = canonical_json(fields)?;
    Ok(framed_digest(TRANSPORT_DOMAIN, [bytes.as_slice()]))
}

fn invalid(message: impl Into<String>) -> QualificationError {
    QualificationError::Invalid(message.into())
}
