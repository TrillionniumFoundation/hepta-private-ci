//! Fixed unsigned wire data. Parsing never authenticates a job or owner.
use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

use super::JointTextTrainingErrorV1 as Error;

pub(super) const PROFILE: &str = "joint-v4-verified-memory-text-sgd-v1";
pub(super) const REQUEST_SCHEMA: &str = "hepta.joint-text-worker.request.v1";
pub(super) const MAX_JSON_BYTES: usize = 65_536;
pub(super) const MAX_PACKET_BYTES: usize = 8 * 1024 * 1024;
pub(super) const MAX_STEPS: u64 = 64;
pub(super) const MAX_WALL_MS: u64 = 300_000;
pub(super) const PROFILE_BYTES: &[u8] = concat!(
    "hepta.joint-text-worker.profile.v1\0",
    "width32;depth1;dual;direct;persistent-v1;cpu;fp64;threads1;",
    "one-memory-revision;prefix4096bytes;continuation128scalars;",
    "fresh-encode/shared/text/text_loss;sgd;momentum0;weight_decay0;",
    "maxsteps64;cooperative-wall-cap300000ms;packet-cap8388608bytes;",
    "exact-predecessor-export-roundtrip;unsigned;no-ndu-training",
)
.as_bytes();
const REQUEST_DOMAIN: &[u8] = b"hepta.joint-text-worker.request-binding.v1\0";
const UPDATE_DOMAIN: &[u8] = b"hepta.joint-text-worker.update-rule.v1\0";
const SOURCE_DOMAIN: &[u8] = b"hepta.joint-text-worker.execution-sources.v1\0";
pub(super) const SOURCE_PATHS: [&str; 7] = [
    "scripts/joint_text_training_contract.py",
    "scripts/joint_text_training_io.py",
    "scripts/joint_text_training_compute.py",
    "scripts/joint_generation_v4_text_worker.py",
    "scripts/joint_generation_v4_model.py",
    "scripts/joint_generation_v4_io.py",
    "experiments/multimodal_output_portfolio/joint_hepta_20261029/hepta_core.py",
];
pub(super) const ABSENT_PATHS: [&str; 4] = [
    "scripts/__init__.py",
    "experiments/__init__.py",
    "experiments/multimodal_output_portfolio/__init__.py",
    "experiments/multimodal_output_portfolio/joint_hepta_20261029/__init__.py",
];

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct RequestWire {
    pub(super) schema: String,
    pub(super) profile: String,
    pub(super) principal_id: String,
    pub(super) agent_id: String,
    pub(super) cell_id: String,
    pub(super) operation_id: String,
    pub(super) source_run_id: String,
    pub(super) completed_task_receipt: String,
    pub(super) iteration_head: String,
    pub(super) selected_bundle_digest: String,
    pub(super) selected_generation: u64,
    pub(super) candidate_artifact_id: String,
    pub(super) evaluation_profile: String,
    pub(super) dataset_digest: String,
    pub(super) dataset_observed_rows: u64,
    pub(super) dataset_observed_bytes: u64,
    pub(super) source_record_count: u64,
    pub(super) materialization_digest: String,
    pub(super) materialization_profile_digest: String,
    pub(super) source_support_digest: String,
    pub(super) source_content_sha256: String,
    pub(super) source_revision: u64,
    pub(super) source_policy_revision: u64,
    pub(super) predecessor_sha256: String,
    pub(super) predecessor_bytes: u64,
    pub(super) execution_source_digest: String,
    pub(super) prefix: String,
    pub(super) continuation: String,
    pub(super) steps: u64,
    pub(super) learning_rate_f64_be: String,
    pub(super) maximum_dataset_rows: u64,
    pub(super) maximum_dataset_bytes: u64,
    pub(super) maximum_training_steps: u64,
    pub(super) maximum_training_milliseconds: u64,
    pub(super) maximum_artifact_bytes: u64,
}

impl RequestWire {
    pub(super) fn validate(&self) -> Result<(), Error> {
        if self.schema != REQUEST_SCHEMA || self.profile != PROFILE {
            return Err(Error::Binding("request profile"));
        }
        for value in [
            &self.principal_id,
            &self.agent_id,
            &self.cell_id,
            &self.operation_id,
            &self.source_run_id,
            &self.candidate_artifact_id,
        ] {
            if value.is_empty()
                || value.len() > 128
                || !value.bytes().all(|byte| {
                    byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b':' | b'-')
                })
            {
                return Err(Error::Binding("worker identifier profile"));
            }
        }
        for value in [
            &self.completed_task_receipt,
            &self.iteration_head,
            &self.selected_bundle_digest,
            &self.evaluation_profile,
            &self.dataset_digest,
            &self.materialization_digest,
            &self.materialization_profile_digest,
            &self.source_support_digest,
            &self.source_content_sha256,
            &self.predecessor_sha256,
            &self.execution_source_digest,
        ] {
            digest(value)?;
        }
        let positive = [
            self.dataset_observed_rows,
            self.dataset_observed_bytes,
            self.source_record_count,
            self.predecessor_bytes,
            self.steps,
            self.maximum_dataset_rows,
            self.maximum_dataset_bytes,
            self.maximum_training_steps,
            self.maximum_training_milliseconds,
            self.maximum_artifact_bytes,
        ];
        if positive.contains(&0)
            || self.dataset_observed_rows > self.maximum_dataset_rows
            || self.dataset_observed_bytes > self.maximum_dataset_bytes
            || self.steps > self.maximum_training_steps.min(MAX_STEPS)
            || self.predecessor_bytes > self.maximum_artifact_bytes.min(MAX_PACKET_BYTES as u64)
        {
            return Err(Error::Capacity);
        }
        let rate = finite_f64(&self.learning_rate_f64_be)?;
        let text_bytes = self.prefix.len() + self.continuation.len();
        if !(0.0 < rate && rate <= 1.0)
            || self.prefix.len() > 4096
            || self.continuation.is_empty()
            || self.continuation.chars().count() > 128
            || text_bytes > 4608
            || text_bytes as u64 > self.maximum_dataset_bytes
        {
            return Err(Error::Binding("text or optimizer profile"));
        }
        let mut text = Sha256::new();
        text.update(self.prefix.as_bytes());
        text.update(self.continuation.as_bytes());
        if Digest32::from_array(text.finalize().into()) != digest(&self.source_content_sha256)? {
            return Err(Error::Binding("complete original text"));
        }
        Ok(())
    }

    pub(super) fn encode(&self) -> Result<Vec<u8>, Error> {
        self.validate()?;
        let mut bytes = serde_json::to_vec(self).map_err(|_| Error::Encoding)?;
        bytes.push(b'\n');
        if bytes.len() > MAX_JSON_BYTES {
            return Err(Error::Capacity);
        }
        Ok(bytes)
    }

    pub(super) fn binding_digest(&self) -> Result<Digest32, Error> {
        self.validate()?;
        let mut hash = Sha256::new();
        hash.update(REQUEST_DOMAIN);
        field(&mut hash, b"schema", self.schema.as_bytes());
        field(&mut hash, b"profile", self.profile.as_bytes());
        field(&mut hash, b"principal_id", self.principal_id.as_bytes());
        field(&mut hash, b"agent_id", self.agent_id.as_bytes());
        field(&mut hash, b"cell_id", self.cell_id.as_bytes());
        field(&mut hash, b"operation_id", self.operation_id.as_bytes());
        field(&mut hash, b"source_run_id", self.source_run_id.as_bytes());
        field(
            &mut hash,
            b"completed_task_receipt",
            &hex_bytes::<32>(&self.completed_task_receipt)?,
        );
        field(
            &mut hash,
            b"iteration_head",
            &hex_bytes::<32>(&self.iteration_head)?,
        );
        field(
            &mut hash,
            b"selected_bundle_digest",
            &hex_bytes::<32>(&self.selected_bundle_digest)?,
        );
        field(
            &mut hash,
            b"selected_generation",
            &self.selected_generation.to_be_bytes(),
        );
        field(
            &mut hash,
            b"candidate_artifact_id",
            self.candidate_artifact_id.as_bytes(),
        );
        field(
            &mut hash,
            b"evaluation_profile",
            &hex_bytes::<32>(&self.evaluation_profile)?,
        );
        field(
            &mut hash,
            b"dataset_digest",
            &hex_bytes::<32>(&self.dataset_digest)?,
        );
        field(
            &mut hash,
            b"dataset_observed_rows",
            &self.dataset_observed_rows.to_be_bytes(),
        );
        field(
            &mut hash,
            b"dataset_observed_bytes",
            &self.dataset_observed_bytes.to_be_bytes(),
        );
        field(
            &mut hash,
            b"source_record_count",
            &self.source_record_count.to_be_bytes(),
        );
        field(
            &mut hash,
            b"materialization_digest",
            &hex_bytes::<32>(&self.materialization_digest)?,
        );
        field(
            &mut hash,
            b"materialization_profile_digest",
            &hex_bytes::<32>(&self.materialization_profile_digest)?,
        );
        field(
            &mut hash,
            b"source_support_digest",
            &hex_bytes::<32>(&self.source_support_digest)?,
        );
        field(
            &mut hash,
            b"source_content_sha256",
            &hex_bytes::<32>(&self.source_content_sha256)?,
        );
        field(
            &mut hash,
            b"source_revision",
            &self.source_revision.to_be_bytes(),
        );
        field(
            &mut hash,
            b"source_policy_revision",
            &self.source_policy_revision.to_be_bytes(),
        );
        field(
            &mut hash,
            b"predecessor_sha256",
            &hex_bytes::<32>(&self.predecessor_sha256)?,
        );
        field(
            &mut hash,
            b"predecessor_bytes",
            &self.predecessor_bytes.to_be_bytes(),
        );
        field(
            &mut hash,
            b"execution_source_digest",
            &hex_bytes::<32>(&self.execution_source_digest)?,
        );
        field(&mut hash, b"prefix", self.prefix.as_bytes());
        field(&mut hash, b"continuation", self.continuation.as_bytes());
        field(&mut hash, b"steps", &self.steps.to_be_bytes());
        field(
            &mut hash,
            b"learning_rate_f64_be",
            &hex_bytes::<8>(&self.learning_rate_f64_be)?,
        );
        field(
            &mut hash,
            b"maximum_dataset_rows",
            &self.maximum_dataset_rows.to_be_bytes(),
        );
        field(
            &mut hash,
            b"maximum_dataset_bytes",
            &self.maximum_dataset_bytes.to_be_bytes(),
        );
        field(
            &mut hash,
            b"maximum_training_steps",
            &self.maximum_training_steps.to_be_bytes(),
        );
        field(
            &mut hash,
            b"maximum_training_milliseconds",
            &self.maximum_training_milliseconds.to_be_bytes(),
        );
        field(
            &mut hash,
            b"maximum_artifact_bytes",
            &self.maximum_artifact_bytes.to_be_bytes(),
        );
        Ok(Digest32::from_array(hash.finalize().into()))
    }

    pub(super) fn update_rule(&self) -> Result<Digest32, Error> {
        self.validate()?;
        let mut hash = Sha256::new();
        hash.update(UPDATE_DOMAIN);
        frame(&mut hash, Digest32::of_bytes(PROFILE_BYTES).as_array());
        frame(&mut hash, digest(&self.execution_source_digest)?.as_array());
        frame(&mut hash, &self.steps.to_be_bytes());
        frame(&mut hash, &hex_bytes::<8>(&self.learning_rate_f64_be)?);
        Ok(Digest32::from_array(hash.finalize().into()))
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct SourceFileWire {
    pub(super) path: String,
    pub(super) bytes: u64,
    pub(super) sha256: String,
}

pub(super) fn source_digest(
    files: &[SourceFileWire],
    absent: &[String],
) -> Result<Digest32, Error> {
    if files.len() != SOURCE_PATHS.len() || absent.len() != ABSENT_PATHS.len() {
        return Err(Error::Binding("execution source inventory"));
    }
    if absent.windows(2).any(|pair| pair[0] >= pair[1]) {
        return Err(Error::Binding("canonical absent source order"));
    }
    let mut rows = BTreeMap::new();
    for file in files {
        if !SOURCE_PATHS.contains(&file.path.as_str()) || file.bytes == 0 {
            return Err(Error::Binding("execution source path"));
        }
        let mut value = vec![1];
        value.extend_from_slice(&file.bytes.to_be_bytes());
        value.extend_from_slice(digest(&file.sha256)?.as_array());
        if rows.insert(file.path.as_str(), value).is_some() {
            return Err(Error::Binding("duplicate execution source"));
        }
    }
    let mut absent_set = BTreeSet::new();
    for path in absent {
        if !ABSENT_PATHS.contains(&path.as_str())
            || !absent_set.insert(path.as_str())
            || rows.insert(path.as_str(), vec![0]).is_some()
        {
            return Err(Error::Binding("unexpected package initializer"));
        }
    }
    let mut hash = Sha256::new();
    hash.update(SOURCE_DOMAIN);
    for (path, value) in rows {
        frame(&mut hash, path.as_bytes());
        frame(&mut hash, &value);
    }
    Ok(Digest32::from_array(hash.finalize().into()))
}

pub(super) fn parse_json<T: serde::de::DeserializeOwned>(raw: &[u8]) -> Result<T, Error> {
    if raw.is_empty() || raw.len() > MAX_JSON_BYTES {
        return Err(Error::Capacity);
    }
    serde_json::from_slice(raw).map_err(|_| Error::Encoding)
}

pub(super) fn digest(text: &str) -> Result<Digest32, Error> {
    let value = Digest32::from_array(hex_bytes::<32>(text)?);
    if value.is_zero() {
        return Err(Error::Binding("zero digest"));
    }
    Ok(value)
}

pub(super) fn finite_f64(text: &str) -> Result<f64, Error> {
    let value = f64::from_be_bytes(hex_bytes::<8>(text)?);
    if !value.is_finite() {
        return Err(Error::Binding("nonfinite metric"));
    }
    Ok(value)
}

pub(super) fn hex(value: Digest32) -> String {
    value
        .as_array()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn hex_bytes<const N: usize>(text: &str) -> Result<[u8; N], Error> {
    if text.len() != 2 * N
        || !text
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(Error::Binding("canonical hexadecimal"));
    }
    let mut bytes = [0; N];
    for (index, byte) in bytes.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&text[index * 2..index * 2 + 2], /*radix*/ 16)
            .map_err(|_| Error::Encoding)?;
    }
    Ok(bytes)
}

fn field(hash: &mut Sha256, name: &[u8], value: &[u8]) {
    frame(hash, name);
    frame(hash, value);
}

fn frame(hash: &mut Sha256, value: &[u8]) {
    hash.update((value.len() as u64).to_be_bytes());
    hash.update(value);
}
