//! Durable shutdown composition for the instrumented reference host.
//!
//! This is a thin fail-closed wrapper over the existing single writer. It uses
//! the same `writer/DRAIN.v1` record consumed by `LearningArtifactOwnerService`.
//! An accepted shutdown is not returned until that record is synchronized. On
//! restart, a previously journaled accepted shutdown is reconciled before the
//! owner service opens, so admission cannot silently resume after a crash.

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::io::Read;
#[cfg(unix)]
use std::io::Write;
#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::ArtifactOwnerActionV1;
use super::ArtifactOwnerBootstrapV1;
use super::ArtifactOwnerCommandError;
use super::ArtifactOwnerCommandResultV1;
use super::ArtifactOwnerOperationalMetricsV1;
use super::ArtifactOwnerRuntimePhaseV1;
use super::ArtifactOwnerRuntimeStatusV1;
use super::ArtifactRetentionObservationV1;
use super::InstrumentedLearningArtifactReferenceHostV1;
use super::SignedArtifactOwnerRequestV1;
use super::measurement::ArtifactOwnerStageSampleV1;
use super::operational::ArtifactOperationalObservationError;

const DRAIN_RECORD_NAME: &str = "DRAIN.v1";
const MAX_DRAIN_RECORD_BYTES: u64 = 4096;
const MAX_JOURNAL_RECORD_BYTES: u64 = 2 * 1024 * 1024;
const MAX_JOURNAL_ENTRIES: usize = 4096;
const PREPARED_MAGIC: &str = "HEPTA-ARTIFACT-OWNER-PREPARED-V1";
const RESULT_MAGIC: &str = "HEPTA-ARTIFACT-OWNER-RESULT-V1";

pub struct DurableInstrumentedLearningArtifactReferenceHostV1 {
    inner: InstrumentedLearningArtifactReferenceHostV1,
    drain: OperationalDrainV1,
}

impl std::fmt::Debug for DurableInstrumentedLearningArtifactReferenceHostV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("DurableInstrumentedLearningArtifactReferenceHostV1")
            .field("inner", &self.inner)
            .field("drain_path", &self.drain.path())
            .finish_non_exhaustive()
    }
}

impl DurableInstrumentedLearningArtifactReferenceHostV1 {
    pub fn open(bootstrap: ArtifactOwnerBootstrapV1) -> Result<Self, ArtifactOwnerCommandError> {
        let service = &bootstrap.runtime.service;
        let drain = OperationalDrainV1::new(
            &service.root,
            &service.trust.registry_id,
            service.trust.withdrawal_scope_digest,
            service.storage_binding,
        );
        reconcile_accepted_shutdown(&service.root, &drain)?;
        let inner = InstrumentedLearningArtifactReferenceHostV1::open(bootstrap)?;
        Ok(Self { inner, drain })
    }

    pub fn handle(
        &self,
        request: SignedArtifactOwnerRequestV1,
        now: u64,
    ) -> Result<ArtifactOwnerCommandResultV1, ArtifactOwnerCommandError> {
        let shutdown = request.action == ArtifactOwnerActionV1::Shutdown;
        let result = self.inner.handle(request, now)?;
        if shutdown && result.should_shutdown {
            self.drain.persist()?;
        }
        Ok(result)
    }

    pub fn operational_metrics(
        &self,
        now: u64,
    ) -> Result<ArtifactOwnerOperationalMetricsV1, ArtifactOwnerCommandError> {
        self.inner.operational_metrics(now)
    }

    pub fn status(
        &self,
        now: u64,
        detail: impl Into<String>,
    ) -> Result<ArtifactOwnerRuntimeStatusV1, ArtifactOwnerCommandError> {
        let mut status = self.inner.status(now, detail)?;
        if self.drain.requested()?
            && !matches!(
                status.phase,
                ArtifactOwnerRuntimePhaseV1::Stopped | ArtifactOwnerRuntimePhaseV1::Failed
            )
        {
            status.phase = ArtifactOwnerRuntimePhaseV1::Draining;
            status.detail = "durable shutdown intent is active; new publication is denied".to_owned();
        }
        Ok(status)
    }

    pub fn observe_retention(
        &self,
        observation: ArtifactRetentionObservationV1,
        now: u64,
    ) -> Result<(), ArtifactOperationalObservationError> {
        self.inner.observe_retention(observation, now)
    }

    pub fn observe_stage(
        &self,
        sample: ArtifactOwnerStageSampleV1,
    ) -> Result<(), ArtifactOperationalObservationError> {
        self.inner.observe_stage(sample)
    }

    #[must_use]
    pub fn shutdown_requested(&self) -> bool {
        self.inner.shutdown_requested()
    }

    pub fn mark_stopped(&self, now: u64) -> Result<(), ArtifactOwnerCommandError> {
        self.inner.mark_stopped(now)
    }

    #[must_use]
    pub const fn inner(&self) -> &InstrumentedLearningArtifactReferenceHostV1 {
        &self.inner
    }
}

#[derive(Debug)]
struct OperationalDrainV1 {
    directory: PathBuf,
    expected: Vec<u8>,
}

impl OperationalDrainV1 {
    fn new(root: &Path, registry_id: &StableId, scope: Digest32, binding: Digest32) -> Self {
        Self {
            directory: root.join("writer"),
            expected: format!("HEPTA-ARTIFACT-DRAIN-V1\n{registry_id}\n{scope}\n{binding}\n")
                .into_bytes(),
        }
    }

    fn path(&self) -> PathBuf {
        self.directory.join(DRAIN_RECORD_NAME)
    }

    fn validated_record(&self) -> io::Result<Option<File>> {
        let path = self.path();
        let metadata = match fs::symlink_metadata(&path) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(error),
        };
        if metadata.file_type().is_symlink()
            || !metadata.is_file()
            || metadata.len() > MAX_DRAIN_RECORD_BYTES
        {
            return Err(invalid_data("invalid durable drain record"));
        }
        let mut file = OpenOptions::new().read(true).write(true).open(path)?;
        let mut bytes = Vec::new();
        (&mut file)
            .take(MAX_DRAIN_RECORD_BYTES + 1)
            .read_to_end(&mut bytes)?;
        if bytes != self.expected {
            return Err(invalid_data("foreign or corrupt durable drain record"));
        }
        Ok(Some(file))
    }

    fn requested(&self) -> io::Result<bool> {
        Ok(self.validated_record()?.is_some())
    }

    fn persist(&self) -> io::Result<()> {
        #[cfg(not(unix))]
        {
            Err(io::Error::new(
                io::ErrorKind::Unsupported,
                "directory durability is not qualified",
            ))
        }
        #[cfg(unix)]
        {
            if !fs::symlink_metadata(&self.directory)?.is_dir() {
                return Err(invalid_data("invalid durable drain directory"));
            }
            let mut options = OpenOptions::new();
            options.write(true).create_new(true).mode(0o600);
            match options.open(self.path()) {
                Ok(mut file) => {
                    file.write_all(&self.expected)?;
                    file.sync_all()?;
                }
                Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
                    let file = self
                        .validated_record()?
                        .ok_or_else(|| invalid_data("durable drain disappeared"))?;
                    file.sync_all()?;
                }
                Err(error) => return Err(error),
            }
            File::open(&self.directory)?.sync_all()?;
            let parent = self
                .directory
                .parent()
                .ok_or_else(|| invalid_data("durable drain has no parent"))?;
            File::open(parent)?.sync_all()
        }
    }
}

fn reconcile_accepted_shutdown(root: &Path, drain: &OperationalDrainV1) -> io::Result<()> {
    if drain.requested()? {
        drain.persist()?;
        return Ok(());
    }
    let requests = root.join("host/requests");
    let entries = match fs::read_dir(&requests) {
        Ok(entries) => entries,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(()),
        Err(error) => return Err(error),
    };
    let mut seen = 0usize;
    for entry in entries {
        seen = seen.saturating_add(1);
        if seen > MAX_JOURNAL_ENTRIES {
            return Err(invalid_data("shutdown journal exceeds bounded inventory"));
        }
        let entry = entry?;
        let metadata = fs::symlink_metadata(entry.path())?;
        if metadata.file_type().is_symlink()
            || !metadata.is_file()
            || metadata.len() > MAX_JOURNAL_RECORD_BYTES
        {
            return Err(invalid_data("invalid shutdown request journal entry"));
        }
        let prepared = read_bounded(&entry.path())?;
        let text = std::str::from_utf8(&prepared)
            .map_err(|_| invalid_data("non-UTF8 shutdown request journal"))?;
        let lines: Vec<_> = text.lines().collect();
        if lines.len() != 5 || lines[0] != PREPARED_MAGIC || !text.ends_with('\n') {
            return Err(invalid_data("corrupt shutdown request journal"));
        }
        if lines[4] != "shutdown" {
            continue;
        }
        let request_id = StableId::new(lines[1].to_owned())
            .map_err(|_| invalid_data("invalid shutdown request identity"))?;
        let result_path = root
            .join("host/results")
            .join(format!("{request_id}.result"));
        let result = match fs::symlink_metadata(&result_path) {
            Ok(metadata) => {
                if metadata.file_type().is_symlink()
                    || !metadata.is_file()
                    || metadata.len() > MAX_JOURNAL_RECORD_BYTES
                {
                    return Err(invalid_data("invalid shutdown result journal entry"));
                }
                read_bounded(&result_path)?
            }
            Err(error) if error.kind() == io::ErrorKind::NotFound => continue,
            Err(error) => return Err(error),
        };
        let response = decode_result_response(&result)?;
        if contains(&response, b"hepta.learning-artifactd.shutdown.v1")
            && contains(&response, b"\"accepted\":true")
        {
            drain.persist()?;
            return Ok(());
        }
    }
    Ok(())
}

fn decode_result_response(bytes: &[u8]) -> io::Result<Vec<u8>> {
    let text = std::str::from_utf8(bytes)
        .map_err(|_| invalid_data("non-UTF8 shutdown result journal"))?;
    let lines: Vec<_> = text.lines().collect();
    if lines.len() != 4 || lines[0] != RESULT_MAGIC || !text.ends_with('\n') {
        return Err(invalid_data("corrupt shutdown result journal"));
    }
    let expected = lines[2]
        .parse::<usize>()
        .map_err(|_| invalid_data("invalid shutdown response length"))?;
    let response = decode_hex(lines[3])?;
    if response.len() != expected {
        return Err(invalid_data("shutdown response length mismatch"));
    }
    Ok(response)
}

fn read_bounded(path: &Path) -> io::Result<Vec<u8>> {
    let mut bytes = Vec::new();
    File::open(path)?
        .take(MAX_JOURNAL_RECORD_BYTES + 1)
        .read_to_end(&mut bytes)?;
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_JOURNAL_RECORD_BYTES {
        return Err(invalid_data("journal entry exceeds bound"));
    }
    Ok(bytes)
}

fn decode_hex(value: &str) -> io::Result<Vec<u8>> {
    if !value.len().is_multiple_of(2) {
        return Err(invalid_data("invalid result hex length"));
    }
    let mut output = Vec::with_capacity(value.len() / 2);
    for pair in value.as_bytes().chunks_exact(2) {
        let high = decode_nibble(pair[0]).ok_or_else(|| invalid_data("invalid result hex"))?;
        let low = decode_nibble(pair[1]).ok_or_else(|| invalid_data("invalid result hex"))?;
        output.push((high << 4) | low);
    }
    Ok(output)
}

const fn decode_nibble(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'a'..=b'f' => Some(value - b'a' + 10),
        _ => None,
    }
}

fn contains(haystack: &[u8], needle: &[u8]) -> bool {
    haystack.windows(needle.len()).any(|window| window == needle)
}

fn invalid_data(message: &'static str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn result_decoder_rejects_length_drift() {
        let bytes = b"HEPTA-ARTIFACT-OWNER-RESULT-V1\n0000000000000000000000000000000000000000000000000000000000000000\n2\n61\n";
        assert!(decode_result_response(bytes).is_err());
    }

    #[test]
    fn drain_record_is_scope_and_binding_specific() {
        let first = OperationalDrainV1::new(
            Path::new("/tmp/one"),
            &StableId::new("registry".to_owned()).expect("id"),
            Digest32::of_bytes(b"scope"),
            Digest32::of_bytes(b"binding"),
        );
        let second = OperationalDrainV1::new(
            Path::new("/tmp/one"),
            &StableId::new("registry".to_owned()).expect("id"),
            Digest32::of_bytes(b"other-scope"),
            Digest32::of_bytes(b"binding"),
        );
        assert_ne!(first.expected, second.expected);
    }
}
