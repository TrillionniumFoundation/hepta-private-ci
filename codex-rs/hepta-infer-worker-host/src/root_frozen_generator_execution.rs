//! Publish immutable factual inputs for the original exclusive Generator slot.
//! These files are not another dispatcher, mutable journal or signing service.
use std::fs::File;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;

use anyhow::Result;
use anyhow::ensure;
use codex_hepta_agent_components::learning_ledger::NativeFrozenGeneratorRequestV1;
use codex_hepta_agent_components::learning_ledger::ReviewTrustWireV1;
use codex_hepta_agent_components::learning_ledger::read_root_review_input;
use codex_hepta_agentd::AgentdSelfIterationRoundStatusV1;
use codex_hepta_supervisor::RootFleetPeerAdmissionV1;
use codex_hepta_types::Digest32;

use super::configuration::Configuration;
use super::configuration::source;
use super::validation::OriginalGeneratorFacts;

pub(super) struct Execution {
    pub request: PathBuf,
    pub output: PathBuf,
}

pub(super) fn protected_directory(path: &Path) -> Result<()> {
    ensure!(
        path.is_absolute() && path.canonicalize()? == path,
        "noncanonical Generator custody"
    );
    for ancestor in path.ancestors() {
        let metadata = std::fs::symlink_metadata(ancestor)?;
        ensure!(
            metadata.is_dir() && metadata.uid() == 0 && metadata.mode() & 0o022 == 0,
            "Generator custody is not Root protected"
        );
    }
    Ok(())
}

fn publish_complete_source(temporary: &Path, destination: &Path) -> std::io::Result<()> {
    // Atomic no-replace rename preserves
    // the original slot and never exposes an inode with a temporary alias.
    rustix::fs::renameat_with(
        rustix::fs::CWD,
        temporary,
        rustix::fs::CWD,
        destination,
        rustix::fs::RenameFlags::NOREPLACE,
    )
    .map_err(std::io::Error::from)
}

/// Publish complete bytes once. Concurrent identical preparation reads the
/// same original source; a changed or partial source never replaces it.
pub(super) fn immutable(path: &Path, bytes: &[u8], maximum: usize) -> Result<()> {
    ensure!(
        rustix::process::geteuid().as_raw() == 0
            && (1..=codex_hepta_agent_components::intelligence::MAX_PARAMETER_PLASTICITY_MATERIAL_BYTES_V1
                .max(codex_hepta_neuron::MAX_NEURON_OPERATION_OBSERVATION_BYTES_V2))
                .contains(&maximum)
            && !bytes.is_empty()
            && bytes.len() <= maximum,
        "original Generator source bounds"
    );
    let parent = path
        .parent()
        .ok_or_else(|| anyhow::anyhow!("missing source parent"))?;
    protected_directory(parent)?;
    if path.try_exists()? {
        ensure!(
            read_root_review_input(path, maximum as u64)
                .map_err(|error| anyhow::anyhow!("{error}"))?
                == bytes,
            "original Generator source already differs"
        );
        return Ok(());
    }
    // A private temporary cannot expose a partially written approved source.
    // The original output create_new remains the sole execution reservation.
    use std::io::Read;
    let mut random = [0_u8; 32];
    File::open("/dev/urandom")?.read_exact(&mut random)?;
    let temporary = parent.join(format!(".generator-source-{}", Digest32::of_bytes(&random)));
    let result = (|| -> Result<()> {
        let mut file = File::options()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW)
            .open(&temporary)?;
        file.write_all(bytes)?;
        file.set_permissions(std::fs::Permissions::from_mode(0o444))?;
        file.sync_all()?;
        match publish_complete_source(&temporary, path) {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                std::fs::remove_file(&temporary)?;
            }
            Err(error) => return Err(error.into()),
        }
        File::open(parent)?.sync_all()?;
        ensure!(
            read_root_review_input(path, maximum as u64)
                .map_err(|error| anyhow::anyhow!("{error}"))?
                == bytes,
            "concurrent original Generator source differs"
        );
        Ok(())
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&temporary);
    }
    result
}

fn window(
    subject: &str,
    materials_digest: Digest32,
    payload_digest: Digest32,
    status: &AgentdSelfIterationRoundStatusV1,
) -> Result<Vec<u8>> {
    use anyhow::Context;
    status.to_json()?;
    Ok(serde_json::to_vec(&serde_json::json!({
        "schema":"hepta.root-frozen-generator-window.v1",
        "subject":subject,
        "round":serde_json::from_slice::<serde_json::Value>(&status.round.canonical_bytes()?)?,
        "materials_digest":materials_digest.to_string(),
        "payload_digest":payload_digest.to_string(),
        "model_request_id":status.generator_request_id.as_ref().context("original model request absent")?.as_str(),
        "model_request_digest":status.generator_model_request_digest.context("original model request preimage absent")?.to_string(),
        "native_run_digest":status.generator_native_run_digest.context("original native record absent")?.to_string(),
        "model_output_digest":status.generator_output_digest.context("original full output absent")?.to_string(),
        "maximum_policy_candidates":status.maximum_policy_candidates,
        "policy_admitted_at_ms":status.policy_admitted_at_ms,
        "policy_deadline_ms":status.policy_deadline_ms,
        "expires_at_ms":status.round.deadline_ms()
    }))?)
}

struct Sources {
    payload: PathBuf,
    window: PathBuf,
    execution: Execution,
}

fn sources(configuration: &Configuration, subject: &str, round_digest: Digest32) -> Sources {
    let identity = Digest32::of_parts(&[
        b"hepta.root-frozen-generator.slot.v1",
        subject.as_bytes(),
        round_digest.as_array(),
    ]);
    let path = |suffix: &str| {
        configuration
            .execution_directory
            .join(format!("{identity}.{suffix}"))
    };
    Sources {
        payload: path("payload"),
        window: path("window.json"),
        execution: Execution {
            request: path("request.json"),
            output: path("evidence.json"),
        },
    }
}

fn native_request(
    configuration: &Configuration,
    sources: &Sources,
    window: &[u8],
    facts: &OriginalGeneratorFacts,
) -> Result<Vec<u8>> {
    let trust: ReviewTrustWireV1 =
        serde_json::from_slice(&source(&configuration.generator_public_trust, 64 * 1024)?)?;
    let native = NativeFrozenGeneratorRequestV1 {
        schema: "hepta.native-frozen-generator-request.v1".into(),
        uid: configuration.generator_uid,
        generator_program_digest: configuration.generator_program.digest.clone(),
        trust,
        principal_id: "native-unprivileged-generator".into(),
        frozen_payload_path: sources.payload.clone(),
        frozen_payload_digest: facts.payload_digest.to_string(),
        window_authorization_path: sources.window.clone(),
        window_authorization_digest: Digest32::of_bytes(window).to_string(),
        private_key_path: configuration.generator_private_key_path.clone(),
        inaccessible_paths: configuration.generator_inaccessible_paths.clone(),
        expires_at_ms: facts.expires_at_ms,
    };
    Ok(serde_json::to_vec(&native)?)
}

pub(super) fn prepare(
    configuration: &Configuration,
    subject: &str,
    materials_digest: Digest32,
    payload: &[u8],
    status: &AgentdSelfIterationRoundStatusV1,
    facts: &OriginalGeneratorFacts,
) -> Result<Execution> {
    protected_directory(&configuration.execution_directory)?;
    let sources = sources(configuration, subject, facts.round_digest);
    let window = window(subject, materials_digest, facts.payload_digest, status)?;
    let request = native_request(configuration, &sources, &window, facts)?;
    immutable(&sources.payload, payload, 512 * 1024)?;
    immutable(&sources.window, &window, 64 * 1024)?;
    // The complete request is published last; it is never an execution reservation.
    immutable(&sources.execution.request, &request, 64 * 1024)?;
    Ok(sources.execution)
}

/// Inspect the same original slot without preparing sources or reserving output.
/// Absent/partial preparation stays pending; changed complete sources are denied.
pub(super) fn observe(
    configuration: &Configuration,
    subject: &str,
    materials_digest: Digest32,
    payload: &[u8],
    status: &AgentdSelfIterationRoundStatusV1,
    facts: &OriginalGeneratorFacts,
) -> Result<Option<Execution>> {
    protected_directory(&configuration.execution_directory)?;
    let sources = sources(configuration, subject, facts.round_digest);
    if !sources.execution.request.try_exists()? {
        return Ok(None);
    }
    let window = window(subject, materials_digest, facts.payload_digest, status)?;
    let request = native_request(configuration, &sources, &window, facts)?;
    ensure!(
        RootFleetPeerAdmissionV1::read_protected_source(
            &sources.payload,
            512 * 1024,
            /*private*/ false
        )? == payload
            && RootFleetPeerAdmissionV1::read_protected_source(
                &sources.window,
                64 * 1024,
                /*private*/ false
            )? == window
            && RootFleetPeerAdmissionV1::read_protected_source(
                &sources.execution.request,
                64 * 1024,
                /*private*/ false
            )? == request,
        "complete original Generator slot differs from current protected composition"
    );
    Ok(Some(sources.execution))
}

#[cfg(test)]
#[path = "root_frozen_generator_execution_tests.rs"]
mod tests;
