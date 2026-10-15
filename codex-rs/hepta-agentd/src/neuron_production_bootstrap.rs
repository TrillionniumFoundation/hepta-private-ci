//! One fail-closed construction path for a signed NDU/Final-use Neuron owner,
//! separate durable business-tick intent WAL and persisted Evidence telemetry.
//!
//! This composes already independently provisioned trust and control inputs.
//! It cannot mint signing keys, authorize a model call or mark an untested
//! production route ready solely because source code exists.

use std::io;
#[cfg(any(unix, test))]
use std::path::Component;
use std::path::Path;
#[cfg(unix)]
use std::sync::Arc;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_evidence::metrics_group_commit::MetricsJournalErrorV1;
#[cfg(unix)]
use codex_hepta_evidence::metrics_sink::DurablePhaseMetricSinkV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronRuntime;
use codex_hepta_types::StableId;

use crate::neuron_effect_bootstrap::NeuronEffectBootstrapErrorV1;
#[cfg(unix)]
use crate::neuron_effect_bootstrap::verify_neuron_effect_scope_v1;
use crate::neuron_ndu_read::NduReadVerifierV1;
use crate::neuron_runtime::AgentdNeuronOwner;

#[cfg(unix)]
const METRICS_QUEUE_CAPACITY: usize = 4_096;
#[cfg(unix)]
const METRICS_GROUP_SIZE: usize = 128;
#[cfg(unix)]
const METRICS_FLUSH_INTERVAL_MS: u64 = 250;

#[derive(Debug)]
pub enum NeuronProductionBootstrapErrorV1 {
    InvalidPaths,
    UnsupportedPlatform,
    EffectIntent(NeuronEffectBootstrapErrorV1),
    Metrics(MetricsJournalErrorV1),
    Io(io::Error),
    NotReady,
}

impl std::fmt::Display for NeuronProductionBootstrapErrorV1 {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for NeuronProductionBootstrapErrorV1 {}

impl From<NeuronEffectBootstrapErrorV1> for NeuronProductionBootstrapErrorV1 {
    fn from(value: NeuronEffectBootstrapErrorV1) -> Self {
        Self::EffectIntent(value)
    }
}
impl From<MetricsJournalErrorV1> for NeuronProductionBootstrapErrorV1 {
    fn from(value: MetricsJournalErrorV1) -> Self {
        Self::Metrics(value)
    }
}
impl From<io::Error> for NeuronProductionBootstrapErrorV1 {
    fn from(value: io::Error) -> Self {
        Self::Io(value)
    }
}

/// Both journals must be distinct filenames in the same, already provisioned
/// protected directory. Disallow lexical aliases before either journal is
/// created, so a failed composition cannot mutate an arbitrary file.
#[cfg(any(unix, test))]
fn validate_production_paths(
    effect_intent_path: &Path,
    metrics_path: &Path,
) -> Result<(), NeuronProductionBootstrapErrorV1> {
    if !effect_intent_path.is_absolute()
        || !metrics_path.is_absolute()
        || effect_intent_path == metrics_path
        || effect_intent_path.parent().is_none()
        || effect_intent_path.parent() != metrics_path.parent()
        || [effect_intent_path, metrics_path].iter().any(|path| {
            path.file_name().is_none()
                || path
                    .components()
                    .any(|component| matches!(component, Component::CurDir | Component::ParentDir))
        })
    {
        return Err(NeuronProductionBootstrapErrorV1::InvalidPaths);
    }
    Ok(())
}

/// An original signed Neuron effect and its terminal Evidence belong to two
/// independent WAL owners. Losing EITHER history must never be interpreted as
/// permission to bootstrap a fresh, empty companion journal after restart.
/// This preflight is deliberately read-only; both original open/replay owners
/// still validate their real WAL contents and pinned inode identities.
#[cfg(unix)]
fn require_existing_effect_metrics_v1(
    effect_intent_path: &Path,
    metrics_path: &Path,
) -> Result<(), NeuronProductionBootstrapErrorV1> {
    use std::fs;
    use std::os::unix::fs::MetadataExt;

    let parent = effect_intent_path
        .parent()
        .ok_or(NeuronProductionBootstrapErrorV1::InvalidPaths)?;
    // A symlinked parent or an ancestor alias can silently switch the pair
    // onto different history. Reject it before either open() creates bytes.
    let directory = fs::symlink_metadata(parent)?;
    if !directory.file_type().is_dir() || fs::canonicalize(parent)? != parent {
        return Err(NeuronProductionBootstrapErrorV1::InvalidPaths);
    }

    let probe = |path: &Path| -> Result<Option<u64>, NeuronProductionBootstrapErrorV1> {
        match fs::symlink_metadata(path) {
            Ok(metadata) if metadata.is_file() && metadata.nlink() == 1 => {
                Ok(Some(metadata.len()))
            }
            Ok(_) => Err(NeuronProductionBootstrapErrorV1::InvalidPaths),
            Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(None),
            Err(error) => Err(NeuronProductionBootstrapErrorV1::Io(error)),
        }
    };
    let intent = probe(effect_intent_path)?;
    let evidence = probe(metrics_path)?;
    match (intent, evidence) {
        (None, None) | (Some(0), Some(0)) => Ok(()),
        (Some(intent_bytes), Some(evidence_bytes))
            if intent_bytes > 0 && evidence_bytes > 0 =>
        {
            Ok(())
        }
        // Partial startup, truncated companion, lost original ledger, or a
        // namespace replacement all fail before the first new WAL write.
        _ => Err(NeuronProductionBootstrapErrorV1::NotReady),
    }
}

/// Returns a Neuron owner only after independently recovering the exact
/// scope/generation effect-intent WAL and durable Evidence telemetry sink.
/// Callers must still independently initialize and verify both signed
/// authorities, the NDU live frontier and the actual inference backend.
#[cfg(unix)]
#[allow(clippy::too_many_arguments)]
pub fn bootstrap_neuron_production_owner_v1<W, P>(
    runtime: NeuronRuntime<W>,
    inference_control: P,
    neuron_owner_id: StableId,
    final_use: FinalUseAuthority,
    ndu_read_verifier: NduReadVerifierV1,
    effect_intent_path: &Path,
    metrics_path: &Path,
    scope: JournalScope,
    max_records: usize,
) -> Result<AgentdNeuronOwner<W, P>, NeuronProductionBootstrapErrorV1>
where
    W: AnchorWitnessStore,
    P: NeuronInferenceControlPort,
{
    validate_production_paths(effect_intent_path, metrics_path)?;
    // The signed runtime's actual journal is the source of scope/generation
    // identity; refuse a caller-provided mismatch before creating files.
    verify_neuron_effect_scope_v1(runtime.journal_scope(), scope)?;
    // Check before either owner creates a new file; a recovered effect history
    // cannot silently replace a deleted/zero-byte Evidence journal.
    require_existing_effect_metrics_v1(effect_intent_path, metrics_path)?;
    let owner = AgentdNeuronOwner::new_authorized_durable_from_path(
        runtime,
        inference_control,
        neuron_owner_id,
        final_use,
        ndu_read_verifier,
        effect_intent_path,
        max_records,
    )?;
    let sink = Arc::new(DurablePhaseMetricSinkV1::open(
        metrics_path,
        /* capacity */ METRICS_QUEUE_CAPACITY,
        /* group_size */ METRICS_GROUP_SIZE,
        /* flush_interval_ms */ METRICS_FLUSH_INTERVAL_MS,
    )?);
    // The parent fsync makes both journal names durable before effects.
    // A failed sync aborts construction; a model call cannot have occurred.
    let parent = effect_intent_path
        .parent()
        .ok_or(NeuronProductionBootstrapErrorV1::InvalidPaths)?;
    std::fs::File::open(parent)?.sync_all()?;
    let owner = owner.with_original_evidence_sink(sink);
    if !owner.flush_production_metrics() {
        return Err(NeuronProductionBootstrapErrorV1::NotReady);
    }
    Ok(owner)
}

/// No audited owner-only ACL and directory-fsync contract for these journals
/// exists on unsupported platforms. Do not pretend Windows is production-ready.
#[cfg(not(unix))]
#[allow(clippy::too_many_arguments)]
pub fn bootstrap_neuron_production_owner_v1<W, P>(
    _runtime: NeuronRuntime<W>,
    _inference_control: P,
    _neuron_owner_id: StableId,
    _final_use: FinalUseAuthority,
    _ndu_read_verifier: NduReadVerifierV1,
    _effect_intent_path: &Path,
    _metrics_path: &Path,
    _scope: JournalScope,
    _max_records: usize,
) -> Result<AgentdNeuronOwner<W, P>, NeuronProductionBootstrapErrorV1>
where
    W: AnchorWitnessStore,
    P: NeuronInferenceControlPort,
{
    Err(NeuronProductionBootstrapErrorV1::UnsupportedPlatform)
}

#[cfg(test)]
#[path = "neuron_production_bootstrap_tests.rs"]
mod tests;
