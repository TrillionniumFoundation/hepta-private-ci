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
    let owner = AgentdNeuronOwner::new_authorized_durable_from_path(
        runtime,
        inference_control,
        neuron_owner_id,
        final_use,
        ndu_read_verifier,
        effect_intent_path,
        scope,
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
    let owner = owner.with_metric_sink(sink);
    if !owner.production_metrics_ready() {
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
