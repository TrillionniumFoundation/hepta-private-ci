//! Read the original immutable model observations without opening an issuer,
//! touching credentials or turning missing evidence into permission to retry.
use std::fs::Metadata;
use std::os::unix::fs::MetadataExt;
use std::path::Path;

use anyhow::ensure;

use super::RootModelAssessmentBindingV1;
use super::RootModelOutcomeReceiptV1;
use super::RootModelTerminalReceiptV1;
use super::original_identity;
use super::store;

// A complete 32KiB native prompt can require six JSON bytes per original byte.
// The original intent and terminal are separately bounded; neither is clipped.
const MAX_ORIGINAL_MODEL_FACT_BYTES: usize = 256 * 1024;

impl RootModelOutcomeReceiptV1 {
    /// Read one original Root-custodied intent and its immutable outcome.
    /// Missing, partial or corrupt files return an error, never a retry grant.
    /// Completion is a provider fact; consumers still verify native release.
    pub fn read_original_protected(
        directory: &Path,
        subject: &str,
        request_id: &str,
    ) -> anyhow::Result<Self> {
        Self::read_original_protected_with_bytes(directory, subject, request_id)
            .map(|(outcome, _bytes)| outcome)
    }

    /// Retain the complete original terminal publication for a bounded factual
    /// transport. Validation and the stable two-publication read are identical
    /// to `read_original_protected`; the bytes are never reconstructed.
    pub fn read_original_protected_with_bytes(
        directory: &Path,
        subject: &str,
        request_id: &str,
    ) -> anyhow::Result<(Self, Vec<u8>)> {
        ensure!(
            rustix::process::geteuid().as_raw() == 0,
            "original model facts require the actual Root reader"
        );
        ensure!(
            directory.is_absolute() && directory.canonicalize()? == directory,
            "original model fact directory must be canonical"
        );
        store::protected_directory(directory)?;
        let identity = original_identity(subject, request_id)?;
        let intent_path = directory.join(format!("{identity}.intent.json"));
        let terminal_path = directory.join(format!("{identity}.terminal.json"));
        let intent_bytes = read_fact(&intent_path)?;
        let intent: RootModelTerminalReceiptV1 = serde_json::from_slice(&intent_bytes)?;
        ensure!(
            intent.schema == "hepta.root-model-terminal.v1"
                && intent.subject == subject
                && intent.binding.request_id == request_id
                && intent.admitted_at_ms > 0
                && intent.native_prompt.len() <= 32 * 1024
                && RootModelAssessmentBindingV1::parse(
                    &intent.native_prompt,
                    intent.admitted_at_ms,
                )? == Some(intent.binding.clone())
                && intent.completed_at_ms == 0
                && intent.response_id.is_empty()
                && intent.stream_sha256 == [0; 32]
                && intent.model_output_sha256 == [0; 32]
                && intent.model_output_bytes == 0,
            "original model intent is incomplete or has another identity"
        );
        let terminal_bytes = read_fact(&terminal_path)?;
        let outcome: Self = serde_json::from_slice(&terminal_bytes)?;
        match &outcome {
            Self::Completed { receipt } => {
                let mut admission = receipt.clone();
                admission.completed_at_ms = 0;
                admission.response_id.clear();
                admission.stream_sha256 = [0; 32];
                admission.model_output_sha256 = [0; 32];
                admission.model_output_bytes = 0;
                ensure!(
                    admission == intent
                        && receipt.completed_at_ms >= intent.admitted_at_ms
                        && !receipt.response_id.is_empty()
                        && receipt.response_id.len() <= 1024
                        && receipt.stream_sha256 != [0; 32]
                        && receipt.model_output_sha256 != [0; 32]
                        && receipt.model_output_bytes > 0
                        && receipt.model_output_bytes
                            <= intent.binding.maximum_response_bytes as usize,
                    "original completed model fact differs from its whole admission"
                );
            }
            Self::Failed {
                admission,
                observed_at_ms,
                stream_sha256,
                ..
            } => {
                ensure!(
                    admission == &intent
                        && *observed_at_ms >= intent.admitted_at_ms
                        && *stream_sha256 != [0; 32],
                    "original failed model fact differs from its whole admission"
                );
            }
        }
        // The two original publications must form one stable read; no file is
        // repaired, sealed, retried or overwritten by this projection.
        ensure!(
            read_fact(&intent_path)? == intent_bytes
                && read_fact(&terminal_path)? == terminal_bytes,
            "original model publications changed during observation"
        );
        Ok((outcome, terminal_bytes))
    }
}

fn read_fact(path: &Path) -> anyhow::Result<Vec<u8>> {
    let before = std::fs::symlink_metadata(path)?;
    ensure!(
        before.is_file()
            && before.uid() == 0
            && before.nlink() == 1
            && before.mode() & 0o7777 == 0o600,
        "original model fact must be a private Root file with one link"
    );
    let bytes = store::read_protected(path, MAX_ORIGINAL_MODEL_FACT_BYTES, /*private*/ true)?;
    let after = std::fs::symlink_metadata(path)?;
    ensure!(
        same_file(&before, &after) && bytes.len() as u64 == after.len(),
        "original model fact changed during observation"
    );
    Ok(bytes)
}

fn same_file(before: &Metadata, after: &Metadata) -> bool {
    before.dev() == after.dev()
        && before.ino() == after.ino()
        && before.uid() == after.uid()
        && before.nlink() == after.nlink()
        && before.mode() == after.mode()
        && before.len() == after.len()
        && before.mtime() == after.mtime()
        && before.mtime_nsec() == after.mtime_nsec()
        && before.ctime() == after.ctime()
        && before.ctime_nsec() == after.ctime_nsec()
}

#[cfg(test)]
#[path = "local_model_relay_witness_reader_tests.rs"]
mod tests;
