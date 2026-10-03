//! Physical generation construction uses the installed control owner unchanged.
use super::*;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use std::sync::Mutex;

pub struct CpuNeuronParameterCompilerOwnersV1 {
    pub control: Arc<Mutex<DurableInferenceControl>>,
    pub clock: Arc<dyn AuthorityClock>,
    pub generator: AgentdSelfIterationLocalSignerV1,
}

/// The installed Root role bridge verifies the fixed window and original
/// physical facts before issuing Generator evidence. This is not a raw signing
/// oracle; implementations must reject facts outside that installed purpose.
#[cfg(target_os = "linux")]
pub trait CpuNeuronGeneratorIssuancePortV2: Send + Sync {
    fn principal_id(&self) -> &StableId;
    fn issue<'a>(
        &'a self,
        candidate: &'a AgentdSelfIterationCandidateV1,
    ) -> std::pin::Pin<
        Box<
            dyn std::future::Future<
                    Output = Result<
                        codex_hepta_agent_components::learning_ledger::SignedLearningEvidenceV1,
                        AgentdError,
                    >,
                > + Send
                + 'a,
        >,
    >;
}

#[cfg(target_os = "linux")]
pub struct CpuNeuronParameterCompilerOwnersV2 {
    pub resources: Arc<crate::FleetWorkerResourcePortV2>,
    pub control: Arc<tokio::sync::Mutex<DurableInferenceControl>>,
    pub clock: Arc<dyn AuthorityClock>,
    pub generator: Arc<dyn CpuNeuronGeneratorIssuancePortV2>,
}

#[derive(Clone)]
pub(super) enum Control {
    Legacy(Arc<Mutex<DurableInferenceControl>>),
    #[cfg(target_os = "linux")]
    Current(Arc<tokio::sync::Mutex<DurableInferenceControl>>),
}

#[derive(Clone)]
pub(super) enum Worker {
    Legacy(CpuNeuronControlConfigV1),
    #[cfg(target_os = "linux")]
    Current(crate::CpuNeuronControlConfigV2),
}
impl Worker {
    pub(super) fn generation(&self) -> u64 {
        match self {
            Self::Legacy(worker) => worker.generation,
            #[cfg(target_os = "linux")]
            Self::Current(worker) => worker.model_generation.get(),
        }
    }
}

#[derive(Clone)]
pub(super) enum Generator {
    Legacy(Arc<AgentdSelfIterationLocalSignerV1>),
    #[cfg(target_os = "linux")]
    Protected(Arc<dyn CpuNeuronGeneratorIssuancePortV2>),
}
impl Generator {
    pub(super) fn principal_id(&self) -> &StableId {
        match self {
            Self::Legacy(signer) => signer.principal_id(),
            #[cfg(target_os = "linux")]
            Self::Protected(issuer) => issuer.principal_id(),
        }
    }
    pub(super) async fn issue(
        &self,
        candidate: &AgentdSelfIterationCandidateV1,
        frozen_payload: &[u8],
        now: u64,
        expires: u64,
    ) -> Result<codex_hepta_agent_components::learning_ledger::SignedLearningEvidenceV1, AgentdError>
    {
        match self {
            Self::Legacy(signer) => signer.sign_payload(frozen_payload, now, expires),
            #[cfg(target_os = "linux")]
            Self::Protected(issuer) => issuer.issue(candidate).await,
        }
    }
}

pub(super) struct Owners {
    pub control: Control,
    pub clock: Arc<dyn AuthorityClock>,
    pub generator: Generator,
    #[cfg(target_os = "linux")]
    pub resources: Option<Arc<crate::FleetWorkerResourcePortV2>>,
}

pub(super) struct Materialized {
    pub successor: AgentdNeuronHandleV2,
    pub rollback: AgentdNeuronHandleV2,
    pub canary_tick: NeuronTickInputV1,
    pub canary_port: CanonicalPortInputV1,
}

pub(super) fn map_workers<W, V>(
    plan: CpuNeuronParameterCompilerPlanV1<W>,
    mut map: impl FnMut(W) -> V,
) -> CpuNeuronParameterCompilerPlanV1<V> {
    CpuNeuronParameterCompilerPlanV1 {
        envelope: plan.envelope,
        baseline: plan.baseline,
        baseline_runtime: plan.baseline_runtime,
        baseline_native: plan.baseline_native,
        baseline_body: plan.baseline_body,
        baseline_candidate_id: plan.baseline_candidate_id,
        request: plan.request,
        test_plan_digest: plan.test_plan_digest,
        candidates: plan
            .candidates
            .into_iter()
            .map(|candidate| CpuNeuronParameterCandidatePlanV1 {
                candidate_id: candidate.candidate_id,
                generation: candidate.generation,
                worker: map(candidate.worker),
                admission: candidate.admission,
                canary_tick: candidate.canary_tick,
                canary_port: candidate.canary_port,
            })
            .collect(),
        rollback: plan.rollback,
        rollback_worker: map(plan.rollback_worker),
        rollback_admission: plan.rollback_admission,
    }
}

pub(super) fn open_generation(
    plan: CpuNeuronGenerationPlanV1,
    control: Control,
    clock: Arc<dyn AuthorityClock>,
    worker: Worker,
    admission: AgentdNeuronArtifactAdmissionV1,
) -> Result<AgentdNeuronHandleV2, AgentdError> {
    match (control, worker) {
        (Control::Legacy(control), Worker::Legacy(worker)) => {
            crate::open_installed_cpu_neuron_generation_v1(
                plan,
                CpuNeuronGenerationOpenModeV1::Create,
                control,
                clock,
                worker,
                admission,
            )
        }
        #[cfg(target_os = "linux")]
        (Control::Current(control), Worker::Current(worker)) => {
            let mode = existing_generation_mode([
                &plan.generation_store,
                &plan.runtime_index,
                &plan.witness,
            ])?;
            crate::local_cpu_generation::open_guarded_cpu_neuron_generation_v2(
                plan, mode, control, clock, worker, admission,
            )
        }
        #[cfg(target_os = "linux")]
        _ => Err(error(
            "CPU compiler worker does not belong to its control owner",
        )),
    }
}

#[cfg(target_os = "linux")]
fn existing_generation_mode(
    paths: [&std::path::Path; 3],
) -> Result<CpuNeuronGenerationOpenModeV1, AgentdError> {
    use std::os::unix::fs::MetadataExt;
    let mut present = 0;
    for path in paths {
        match std::fs::symlink_metadata(path) {
            Ok(meta)
                if meta.is_file()
                    && !meta.file_type().is_symlink()
                    && meta.uid() == rustix::process::geteuid().as_raw()
                    && meta.nlink() == 1
                    && meta.mode() & 0o077 == 0 =>
            {
                present += 1
            }
            Ok(_) => return Err(error("original sparse generation store identity changed")),
            Err(value) if value.kind() == std::io::ErrorKind::NotFound => (),
            Err(value) => return Err(error(value.to_string())),
        }
    }
    match present {
        0 => Ok(CpuNeuronGenerationOpenModeV1::Create),
        3 => Ok(CpuNeuronGenerationOpenModeV1::Recover),
        _ => Err(error(
            "partial original sparse stores require owner reconciliation",
        )),
    }
}

pub(super) struct Issuance {
    task: Option<JoinHandle<Result<AgentdSelfIterationCandidateV1, AgentdError>>>,
    completed: Option<AgentdSelfIterationCandidateV1>,
    failed: bool,
}
impl Issuance {
    pub(super) fn start(
        generator: Generator,
        mut candidate: AgentdSelfIterationCandidateV1,
        clock: Arc<dyn AuthorityClock>,
    ) -> Result<Self, AgentdError> {
        let payload = self_iteration_frozen_candidate_payload_v1(&candidate)?;
        let now = clock
            .now_unix_ms()
            .map_err(|value| error(value.to_string()))?;
        // Recovery returns the original immutable publication. Its signed time
        // is bounded by the original admitted round, not this process restart.
        let issued_not_before = candidate
            .round
            .as_ref()
            .map_or(now, AgentdSelfIterationRoundV1::admitted_at_ms);
        if now < issued_not_before {
            return Err(error("original Generator issuance clock rolled back"));
        }
        let expiry = candidate
            .envelope
            .expiry_unix_seconds
            .checked_mul(1000)
            .ok_or_else(|| error("sparse issuance expiry overflow"))?;
        let expected = candidate.generator_attestation.clone();
        Ok(Self {
            task: Some(tokio::spawn(async move {
                candidate.generator_attestation =
                    generator.issue(&candidate, &payload, now, expiry).await?;
                validation::validate_generator_issuance(
                    &candidate.generator_attestation,
                    &expected,
                    &payload,
                    issued_not_before,
                    expiry,
                    clock.as_ref(),
                    candidate.round.as_ref(),
                )?;
                Ok(candidate)
            })),
            completed: None,
            failed: false,
        })
    }
    pub(super) async fn observe(&mut self) -> Result<AgentdSelfIterationCandidateV1, AgentdError> {
        if let Some(candidate) = &self.completed {
            return Ok(candidate.clone());
        }
        if self.failed {
            return Err(error(
                "original Generator issuance requires owner reconciliation",
            ));
        }
        let task = self
            .task
            .as_mut()
            .ok_or_else(|| error("original issuance task missing"))?;
        let result = task.await;
        self.task = None;
        self.failed = true;
        let candidate = result.map_err(|value| error(value.to_string()))??;
        self.completed = Some(candidate.clone());
        self.failed = false;
        Ok(candidate)
    }
}

#[cfg(all(test, target_os = "linux"))]
#[path = "local_cpu_parameter_owners_tests.rs"]
mod tests;

pub(super) fn start_generation(
    selected: CpuNeuronParameterCandidatePlanV1<Worker>,
    rollback: CpuNeuronGenerationPlanV1,
    rollback_worker: Worker,
    control: Control,
    clock: Arc<dyn AuthorityClock>,
    rollback_admission: AgentdNeuronArtifactAdmissionV1,
) -> JoinHandle<Result<Materialized, AgentdError>> {
    tokio::task::spawn_blocking(move || {
        let successor = open_generation(
            selected.generation,
            control.clone(),
            Arc::clone(&clock),
            selected.worker,
            selected.admission,
        )?;
        let rollback = open_generation(
            rollback,
            control,
            clock,
            rollback_worker,
            rollback_admission,
        )?;
        Ok(Materialized {
            successor,
            rollback,
            canary_tick: selected.canary_tick,
            canary_port: selected.canary_port,
        })
    })
}
