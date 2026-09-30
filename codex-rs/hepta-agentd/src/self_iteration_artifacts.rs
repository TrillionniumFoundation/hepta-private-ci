//! Installer-owned input inventory. A verified checksum proves file identity;
//! it does not certify a model, release holdout data or authorize activation.

use std::fs::File;
use std::io::Read;
use std::path::Component;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_agent_components::types::AuthorityPosture;
use serde::Deserialize;
use serde::Serialize;

use super::*;

const MAX_MANIFEST_BYTES: u64 = 64 * 1024;
const MAX_ARTIFACT_BYTES: u64 = 16 * 1024 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AgentdSelfIterationArtifactKindV1 {
    ModelWeights,
    FeatureEncoder,
    OodCalibration,
    IndependentHoldout,
    GenerationConfiguration,
    QualificationEvidence,
}
impl AgentdSelfIterationArtifactKindV1 {
    const REQUIRED: [Self; 6] = [
        Self::ModelWeights,
        Self::FeatureEncoder,
        Self::OodCalibration,
        Self::IndependentHoldout,
        Self::GenerationConfiguration,
        Self::QualificationEvidence,
    ];
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AgentdSelfIterationArtifactFileV1 {
    pub kind: AgentdSelfIterationArtifactKindV1,
    /// One filename inside the trusted input directory. No path traversal or
    /// external lookup is permitted by this descriptor.
    pub filename: String,
    pub byte_length: u64,
    #[serde(with = "super::codec::digest")]
    pub digest: Digest32,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AgentdSelfIterationArtifactManifestV1 {
    pub version: u32,
    #[serde(with = "super::codec::digest")]
    pub objective_digest: Digest32,
    pub candidate_generation: u64,
    pub artifacts: Vec<AgentdSelfIterationArtifactFileV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AgentdSelfIterationArtifactReadinessV1 {
    PendingInputs {
        descriptor_digest: Option<Digest32>,
        manifest_missing: bool,
        missing: Vec<AgentdSelfIterationArtifactKindV1>,
    },
    /// The generation compiler and independent Eval owner must still parse,
    /// validate, qualify and bind every input to their actual durable owners.
    InputsVerifiedAwaitingOwnerQualification {
        descriptor_digest: Digest32,
        manifest: AgentdSelfIterationArtifactManifestV1,
    },
}
impl AgentdSelfIterationArtifactReadinessV1 {
    pub fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

/// The installer freezes the expected manifest digest in its host config. A
/// missing manifest/file is explicit pending input; changed or unsafe material
/// is an error. This function never substitutes repository fixtures or chats.
pub fn inspect_self_iteration_artifacts_v1(
    trusted_directory: &Path,
    manifest_filename: &str,
    expected_manifest_digest: Digest32,
    objective_digest: Digest32,
    candidate_generation: u64,
    budget: Duration,
) -> Result<AgentdSelfIterationArtifactReadinessV1, AgentdError> {
    if !trusted_directory.is_absolute()
        || trusted_directory.canonicalize()? != trusted_directory
        || expected_manifest_digest.is_zero()
        || objective_digest.is_zero()
        || candidate_generation == 0
        || budget.is_zero()
        || budget > Duration::from_secs(300)
    {
        return Err(invalid("artifact inventory host binding or budget"));
    }
    let metadata = std::fs::symlink_metadata(trusted_directory)?;
    if !metadata.is_dir() || metadata.file_type().is_symlink() {
        return Err(invalid("artifact inventory directory"));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if metadata.mode() & 0o077 != 0 || metadata.uid() != unsafe { libc::geteuid() } {
            return Err(invalid(
                "artifact inventory directory must be private and host-owned",
            ));
        }
    }
    validate_filename(manifest_filename)?;
    let deadline = Instant::now()
        .checked_add(budget)
        .ok_or_else(|| invalid("inventory deadline"))?;
    let Some(mut file) = open_private_file(
        &trusted_directory.join(manifest_filename),
        MAX_MANIFEST_BYTES,
    )?
    else {
        return Ok(AgentdSelfIterationArtifactReadinessV1::PendingInputs {
            descriptor_digest: None,
            manifest_missing: true,
            missing: AgentdSelfIterationArtifactKindV1::REQUIRED.to_vec(),
        });
    };
    let mut bytes = Vec::new();
    file.by_ref()
        .take(MAX_MANIFEST_BYTES + 1)
        .read_to_end(&mut bytes)?;
    let descriptor_digest = Digest32::of_bytes(&bytes);
    if descriptor_digest != expected_manifest_digest {
        return Err(invalid("artifact manifest differs from installed digest"));
    }
    let manifest: AgentdSelfIterationArtifactManifestV1 = serde_json::from_slice(&bytes)
        .map_err(|error| invalid(format!("artifact manifest: {error}")))?;
    if manifest.version != 1
        || manifest.objective_digest != objective_digest
        || manifest.candidate_generation != candidate_generation
        || manifest.artifacts.len() > 6
    {
        return Err(invalid("artifact manifest objective or generation binding"));
    }
    let mut kinds = std::collections::BTreeSet::new();
    let mut names = std::collections::BTreeSet::new();
    let mut missing = Vec::new();
    for artifact in &manifest.artifacts {
        validate_filename(&artifact.filename)?;
        if artifact.filename == manifest_filename
            || !kinds.insert(artifact.kind)
            || !names.insert(&artifact.filename)
            || artifact.byte_length == 0
            || artifact.byte_length > MAX_ARTIFACT_BYTES
            || artifact.digest.is_zero()
        {
            return Err(invalid("artifact descriptor duplicate or size"));
        }
        let Some(file) = open_private_file(
            &trusted_directory.join(&artifact.filename),
            artifact.byte_length,
        )?
        else {
            missing.push(artifact.kind);
            continue;
        };
        if file.metadata()?.len() != artifact.byte_length {
            return Err(invalid("artifact byte length changed"));
        }
        let digest = Digest32::of_reader(DeadlineReader { file, deadline }, artifact.byte_length)?;
        if digest != artifact.digest {
            return Err(invalid("artifact digest differs from installed descriptor"));
        }
    }
    missing.extend(
        AgentdSelfIterationArtifactKindV1::REQUIRED
            .into_iter()
            .filter(|kind| !kinds.contains(kind)),
    );
    missing.sort();
    if !missing.is_empty() {
        return Ok(AgentdSelfIterationArtifactReadinessV1::PendingInputs {
            descriptor_digest: Some(descriptor_digest),
            manifest_missing: false,
            missing,
        });
    }
    Ok(
        AgentdSelfIterationArtifactReadinessV1::InputsVerifiedAwaitingOwnerQualification {
            descriptor_digest,
            manifest,
        },
    )
}

fn validate_filename(value: &str) -> Result<(), AgentdError> {
    let mut components = Path::new(value).components();
    if value.is_empty()
        || value.len() > 255
        || !matches!(components.next(), Some(Component::Normal(_)))
        || components.next().is_some()
    {
        return Err(invalid(
            "artifact filename must be one directory-local name",
        ));
    }
    Ok(())
}

fn open_private_file(path: &Path, limit: u64) -> Result<Option<File>, AgentdError> {
    let metadata = match std::fs::symlink_metadata(path) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        result => result?,
    };
    if !metadata.is_file() || metadata.file_type().is_symlink() || metadata.len() > limit {
        return Err(invalid("artifact must be a bounded regular file"));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if metadata.mode() & 0o077 != 0
            || metadata.nlink() != 1
            || metadata.uid() != unsafe { libc::geteuid() }
        {
            return Err(invalid("artifact must be private, host-owned and unlinked"));
        }
    }
    let file = File::open(path)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        let opened = file.metadata()?;
        if opened.dev() != metadata.dev() || opened.ino() != metadata.ino() {
            return Err(invalid("artifact file identity changed"));
        }
    }
    Ok(Some(file))
}

struct DeadlineReader {
    file: File,
    deadline: Instant,
}
impl Read for DeadlineReader {
    fn read(&mut self, bytes: &mut [u8]) -> std::io::Result<usize> {
        if Instant::now() >= self.deadline {
            return Err(std::io::Error::new(
                std::io::ErrorKind::TimedOut,
                "artifact inventory deadline",
            ));
        }
        self.file.read(bytes)
    }
}

#[cfg(test)]
#[path = "self_iteration_artifacts_tests.rs"]
mod tests;
