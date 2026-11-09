//! Signed supervisor inventory and the original seven-file Joint worker closure.
//! These bounded observations are not a filesystem transaction. The deployment
//! owner must preserve the admitted source tree throughout worker execution.

use std::collections::BTreeMap;
use std::fs;
use std::io;
use std::path::Path;

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use crate::automation_joint_text_inputs::JointTextRecordedSourceV1;
use crate::automation_joint_text_inputs::JointTextReservationV1;

use super::hcsn_source::HcsnSourceManifest;
use super::hcsn_source::read_source_digest;

const MAX_WORKER_SOURCE_BYTES: u64 = 256 * 1024;
const HC_FILES: [&str; 10] = [
    "qualification/hcsn_training/__init__.py",
    "qualification/hcsn_training/joint_protocol.py",
    "qualification/hcsn_training/joint_store.py",
    "qualification/hcsn_training/joint_process.py",
    "qualification/hcsn_training/joint_sources.py",
    "qualification/hcsn_training/joint_outputs.py",
    "qualification/hcsn_training/joint_lifecycle.py",
    "qualification/hcsn_training/joint_runner.py",
    "qualification/hcsn_training/joint_worker_adapter.py",
    "qualification/hcsn_training/joint_supervisor.py",
];
const ABSENT_INITIALIZERS: [&str; 4] = [
    "scripts/__init__.py",
    "experiments/__init__.py",
    "experiments/multimodal_output_portfolio/__init__.py",
    "experiments/multimodal_output_portfolio/joint_hepta_20261029/__init__.py",
];

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct WorkerFile {
    bytes: u64,
    sha256: Sha256Digest,
}

/// Named fields keep the seven paths fixed and reject duplicate JSON keys.
/// A task cannot extend this inventory or choose a different Python module.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct WorkerSources {
    contract: WorkerFile,
    custody: WorkerFile,
    compute: WorkerFile,
    entry: WorkerFile,
    model: WorkerFile,
    packet: WorkerFile,
    core: WorkerFile,
}

impl WorkerSources {
    fn files(&self) -> [(&str, &WorkerFile); 7] {
        [
            ("scripts/joint_text_training_contract.py", &self.contract),
            ("scripts/joint_text_training_io.py", &self.custody),
            ("scripts/joint_text_training_compute.py", &self.compute),
            ("scripts/joint_generation_v4_text_worker.py", &self.entry),
            ("scripts/joint_generation_v4_model.py", &self.model),
            ("scripts/joint_generation_v4_io.py", &self.packet),
            (
                "experiments/multimodal_output_portfolio/joint_hepta_20261029/hepta_core.py",
                &self.core,
            ),
        ]
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct JointTextSourceManifestV1 {
    supervisor: HcsnSourceManifest,
    worker: WorkerSources,
    worker_execution_source_digest: Sha256Digest,
}

impl JointTextSourceManifestV1 {
    pub(super) fn execution_digest(&self) -> &Sha256Digest {
        &self.worker_execution_source_digest
    }

    pub(super) fn verify(&self, repository: &Path) -> io::Result<()> {
        self.supervisor.verify(repository)?;
        require_absent_initializers(repository)?;
        for relative in HC_FILES {
            let expected = self
                .supervisor
                .expected_digest(relative)
                .ok_or_else(|| io::Error::other("Joint fixed supervisor source is not signed"))?;
            let (actual, _) =
                read_source_digest(&repository.join(relative), MAX_WORKER_SOURCE_BYTES)?;
            if &actual != expected {
                return invalid("Joint fixed supervisor source differs from its signed deployment");
            }
        }
        let mut rows = BTreeMap::new();
        for (relative, expected) in self.worker.files() {
            if expected.bytes == 0 || expected.bytes > MAX_WORKER_SOURCE_BYTES {
                return invalid("Joint worker source exceeds its original fixed file bound");
            }
            let (digest, bytes) = read_source_digest(&repository.join(relative), expected.bytes)?;
            if digest != expected.sha256 || bytes != expected.bytes {
                return invalid("Joint worker source differs from its signed deployment");
            }
            let mut value = vec![1];
            value.extend_from_slice(&bytes.to_be_bytes());
            value.extend_from_slice(&decode_digest(&digest)?);
            rows.insert(relative, value);
        }
        for relative in ABSENT_INITIALIZERS {
            rows.insert(relative, vec![0]);
        }
        let mut material = b"hepta.joint-text-worker.execution-sources.v1\0".to_vec();
        for (relative, value) in rows {
            frame(&mut material, relative.as_bytes());
            frame(&mut material, &value);
        }
        if Sha256Digest::for_bytes(&material) != self.worker_execution_source_digest {
            return invalid("Joint worker source framing differs from the original H request");
        }
        require_absent_initializers(repository)?;
        self.supervisor.verify(repository)
    }

    /// Compare the retained pre-spawn capture to this exact deployment. A
    /// current source check alone would not establish the job's original code.
    pub(super) fn verify_reservation(
        &self,
        repository: &Path,
        python: &Path,
        python_sha256: &Sha256Digest,
        reservation: &JointTextReservationV1,
    ) -> io::Result<()> {
        self.verify(repository)?;
        let mut expected = Vec::new();
        for relative in HC_FILES {
            let (sha256, bytes) =
                read_source_digest(&repository.join(relative), MAX_WORKER_SOURCE_BYTES)?;
            if self.supervisor.expected_digest(relative) != Some(&sha256) {
                return invalid(
                    "Joint retained supervisor capture is not the signed source version",
                );
            }
            expected.push(JointTextRecordedSourceV1 {
                path: relative.to_string(),
                bytes,
                sha256,
            });
        }
        for (relative, file) in self.worker.files() {
            expected.push(JointTextRecordedSourceV1 {
                path: relative.to_string(),
                bytes: file.bytes,
                sha256: file.sha256.clone(),
            });
        }
        expected.sort_by(|left, right| left.path.cmp(&right.path));
        let mut absent: Vec<_> = ABSENT_INITIALIZERS
            .iter()
            .map(|name| (*name).to_string())
            .collect();
        absent.push("qualification/__init__.py".to_string());
        absent.sort();
        let resolved = python.canonicalize()?;
        let (digest, bytes) = read_source_digest(&resolved, 128 * 1024 * 1024)?;
        if reservation.sources != expected
            || reservation.absent_sources != absent
            || reservation.python.path != python
            || reservation.python.resolved_path != resolved
            || reservation.python.bytes != bytes
            || &reservation.python.sha256 != python_sha256
            || &digest != python_sha256
        {
            return invalid("Joint original executable capture differs from its signed deployment");
        }
        self.verify(repository)
    }
}

fn require_absent_initializers(repository: &Path) -> io::Result<()> {
    for relative in ABSENT_INITIALIZERS
        .into_iter()
        .chain(["qualification/__init__.py"])
    {
        let path = repository.join(relative);
        let parent = path
            .parent()
            .ok_or_else(|| io::Error::other("missing source parent"))?;
        if parent.canonicalize()? != parent {
            return invalid("Joint source initializer parent is not canonical");
        }
        match fs::symlink_metadata(path) {
            Err(error) if error.kind() == io::ErrorKind::NotFound => {}
            Err(error) => return Err(error),
            Ok(_) => return invalid("Joint worker package initializer must be absent"),
        }
    }
    Ok(())
}

fn decode_digest(digest: &Sha256Digest) -> io::Result<[u8; 32]> {
    let text = digest.as_str();
    Sha256Digest::parse(text).map_err(io::Error::other)?;
    let mut bytes = [0; 32];
    for (index, value) in bytes.iter_mut().enumerate() {
        *value =
            u8::from_str_radix(&text[index * 2..index * 2 + 2], 16).map_err(io::Error::other)?;
    }
    Ok(bytes)
}

fn frame(material: &mut Vec<u8>, value: &[u8]) {
    material.extend_from_slice(&(value.len() as u64).to_be_bytes());
    material.extend_from_slice(value);
}

fn invalid<T>(message: &str) -> io::Result<T> {
    Err(io::Error::new(io::ErrorKind::InvalidData, message))
}

#[cfg(test)]
#[path = "automation_joint_text_source_tests.rs"]
mod tests;
