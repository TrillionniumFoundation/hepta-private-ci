use std::future::Future;
use std::path::Path;
use std::path::PathBuf;
use std::pin::Pin;
use std::sync::Arc;
use std::time::Duration;

use codex_extension_api::ContextualUserFragment;
use codex_extension_api::EPHEMERAL_MODEL_INPUT_SCHEMA_VERSION;
use codex_extension_api::EphemeralModelInputContext;
use codex_extension_api::EphemeralModelInputContributor;
use codex_extension_api::EphemeralModelInputProposal;
use codex_extension_api::EphemeralModelInputSource;
use codex_extension_api::ExtensionData;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ExtensionMetrics;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::ModelProviderPolicyError;
use codex_extension_api::ModelProviderPolicyFuture;
use codex_extension_api::ModelProviderRequestKind;
use codex_extension_api::ModelProviderSha256Digest;
use codex_extension_api::ThreadLifecycleContributor;
use codex_extension_api::ThreadOriginator;
use codex_extension_api::ThreadStartInput;
use codex_extension_api::TurnInputContext;
use codex_extension_api::TurnInputContributor;
use codex_hepta_contracts::MEMORY_CONTRACT_SCHEMA_VERSION;
use codex_hepta_contracts::MemoryId;
use codex_hepta_contracts::MemoryLifecycle;
use codex_hepta_contracts::MemoryProvenance;
use codex_hepta_contracts::MemoryRevision;
use codex_hepta_contracts::MemoryScope;
use codex_hepta_contracts::MemorySourceKind;
use codex_hepta_contracts::RecallAuthority;
use codex_hepta_contracts::RecallLimits;
use codex_hepta_contracts::RecallRequest;
use codex_hepta_contracts::RecallRequestId;
use codex_hepta_contracts::RevisionStamp;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CognitiveRuntime;
use codex_hepta_memory::LocalDevelopmentLifecyclePolicy;
use codex_hepta_memory::RecallObservation;
use codex_hepta_memory::RecallObservationReason;
use codex_hepta_memory::shadow_recall;
use codex_protocol::ThreadId;
use codex_protocol::user_input::UserInput;
use codex_state::Stage1RecallCandidate;
use codex_state::StateRuntime;

use crate::cognitive::CognitiveExtension;
use crate::cognitive::CombinedCognitiveEphemeralContributor;
use crate::cognitive::FederatedCognitiveExtension;
use crate::framing::digest_many;
use crate::framing::domain_digest;
use crate::framing::path_identity_bytes;
use crate::framing::workspace_digest;
use crate::local_lifecycle::LocalTurnLifecycleContributor;
use crate::local_turn_writer::QualificationTurnLifecycleContributor;
use crate::local_turn_writer::QualificationTurnWriterHost;
use crate::observation::ShadowRecallTurnObservation;
use crate::observation::ShadowRecallTurnReason;
use crate::observation::commit_turn_observation;

const RECALL_BACKEND_TIMEOUT: Duration = Duration::from_secs(2);
const HEPTA_MEMORY_SOURCE: &str = "hepta_memory_same_thread_v1";

type RecallBackendFuture<'a> = Pin<
    Box<
        dyn Future<Output = Result<Option<Stage1RecallCandidate>, RecallBackendUnavailable>>
            + Send
            + 'a,
    >,
>;

#[derive(Clone, Copy)]
struct RecallBackendUnavailable;

trait Stage1RecallBackend: Send + Sync {
    fn get_stage1_recall_candidate(
        &self,
        thread_id: ThreadId,
        expected_workspace: PathBuf,
    ) -> RecallBackendFuture<'_>;
}

struct StateRecallBackend {
    state_db: Arc<StateRuntime>,
}

impl Stage1RecallBackend for StateRecallBackend {
    fn get_stage1_recall_candidate(
        &self,
        thread_id: ThreadId,
        expected_workspace: PathBuf,
    ) -> RecallBackendFuture<'_> {
        Box::pin(async move {
            self.state_db
                .memories()
                .get_stage1_recall_candidate(thread_id, expected_workspace.as_path())
                .await
                .map_err(|_| RecallBackendUnavailable)
        })
    }
}

/// Per-thread limits resolved from trusted product configuration.
///
/// Scope authority is deliberately absent. Installation and principal bindings
/// come from host-frozen thread facts, and the workspace comes from the exact
/// primary turn environment.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HeptaMemoryThreadConfig {
    limits: RecallLimits,
    attachment_proposal_enabled: bool,
    write_enabled: bool,
}

/// Trusted product feature state used to resolve the Memory extension mode.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct HeptaMemoryFeatureFlags {
    pub governance_enabled: bool,
    pub memory_enabled: bool,
    pub read_only_enabled: bool,
    pub write_enabled: bool,
}

impl HeptaMemoryThreadConfig {
    pub fn new(limits: RecallLimits) -> Result<Self, String> {
        limits.validate()?;
        Ok(Self {
            limits,
            attachment_proposal_enabled: false,
            write_enabled: false,
        })
    }

    /// Product-default limits for digest-only same-thread shadow recall.
    pub fn conservative_shadow() -> Self {
        Self {
            limits: RecallLimits::conservative_default(),
            attachment_proposal_enabled: false,
            write_enabled: false,
        }
    }

    /// Product-default limits for a host-witnessed read-only attachment.
    pub fn conservative_read_only_proposal() -> Self {
        Self {
            limits: RecallLimits::conservative_default(),
            attachment_proposal_enabled: true,
            write_enabled: false,
        }
    }

    /// Read-only model attachment requires all three product feature flags.
    /// Memory without the full conjunction remains digest-only shadow mode.
    pub fn for_features(flags: HeptaMemoryFeatureFlags) -> Option<Self> {
        if !flags.memory_enabled {
            return None;
        }
        let mut config = if flags.governance_enabled && flags.read_only_enabled {
            Self::conservative_read_only_proposal()
        } else {
            Self::conservative_shadow()
        };
        config.write_enabled = flags.governance_enabled && flags.write_enabled;
        Some(config)
    }
}

#[derive(Clone)]
pub(crate) struct HeptaMemoryThreadState {
    installation_sha256: Sha256Digest,
    // Host-frozen attribution selector, not an authentication credential. It
    // scopes the request and candidate symmetrically and grants no authority.
    originator_sha256: Sha256Digest,
    pub(crate) limits: RecallLimits,
    pub(crate) attachment_proposal_enabled: bool,
    pub(crate) write_enabled: bool,
}

impl HeptaMemoryThreadState {
    fn scope_for(&self, thread_id: &str, workspace: &Path) -> MemoryScope {
        MemoryScope {
            installation_sha256: self.installation_sha256.clone(),
            workspace_sha256: workspace_digest(workspace),
            thread_sha256: domain_digest(b"hepta-memory:thread:v1", thread_id.as_bytes()),
            principal_sha256: self.originator_sha256.clone(),
        }
    }

    #[cfg(test)]
    pub(crate) fn for_cognitive_test(attachment_proposal_enabled: bool) -> Self {
        Self::for_cognitive_test_with_write(attachment_proposal_enabled, true)
    }

    #[cfg(test)]
    pub(crate) fn for_cognitive_test_with_write(
        attachment_proposal_enabled: bool,
        write_enabled: bool,
    ) -> Self {
        Self {
            installation_sha256: domain_digest(b"hepta-memory:test-installation:v1", b"test"),
            originator_sha256: domain_digest(b"hepta-memory:test-originator:v1", b"test"),
            limits: RecallLimits::conservative_default(),
            attachment_proposal_enabled,
            write_enabled,
        }
    }
}

/// Digest-only exact-turn preparation retained until a physical provider send.
///
/// Raw summary content is deliberately absent. Every physical send must reread
/// and revalidate the exact state row before proposing ephemeral input.
#[derive(Clone)]
struct PreparedMemoryAttachment {
    thread_id: String,
    turn_id: String,
    workspace: PathBuf,
    request_id: RecallRequestId,
    revision: MemoryRevision,
    source_binding_sha256: Sha256Digest,
    claimed_token_count: u32,
}

pub struct HeptaMemoryExtension<F> {
    resolve_thread: F,
    backend: Option<Arc<dyn Stage1RecallBackend>>,
    legacy_attachment_enabled: bool,
}

impl<F> HeptaMemoryExtension<F> {
    pub fn new(
        resolve_thread: F,
        state_db: Option<Arc<StateRuntime>>,
        legacy_attachment_enabled: bool,
    ) -> Self {
        let backend = state_db.map(|state_db| {
            Arc::new(StateRecallBackend { state_db }) as Arc<dyn Stage1RecallBackend>
        });
        Self {
            resolve_thread,
            backend,
            legacy_attachment_enabled,
        }
    }

    #[cfg(test)]
    fn with_backend(resolve_thread: F, backend: Option<Arc<dyn Stage1RecallBackend>>) -> Self {
        Self {
            resolve_thread,
            backend,
            legacy_attachment_enabled: true,
        }
    }
}

impl<C, F> ThreadLifecycleContributor<C> for HeptaMemoryExtension<F>
where
    C: Sync,
    F: Fn(&C) -> Option<HeptaMemoryThreadConfig> + Send + Sync,
{
    fn on_thread_start<'a>(&'a self, input: ThreadStartInput<'a, C>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            let Some(config) = (self.resolve_thread)(input.config) else {
                input.thread_store.remove::<HeptaMemoryThreadState>();
                return;
            };
            let Some(originator) = input.thread_store.get::<ThreadOriginator>() else {
                input.thread_store.remove::<HeptaMemoryThreadState>();
                return;
            };
            if input.installation_id.trim().is_empty() || originator.0.trim().is_empty() {
                input.thread_store.remove::<HeptaMemoryThreadState>();
                return;
            }
            input.thread_store.insert(HeptaMemoryThreadState {
                installation_sha256: domain_digest(
                    b"hepta-memory:installation:v1",
                    input.installation_id.as_bytes(),
                ),
                originator_sha256: domain_digest(
                    b"hepta-memory:principal:v1",
                    originator.0.as_bytes(),
                ),
                limits: config.limits,
                attachment_proposal_enabled: config.attachment_proposal_enabled,
                write_enabled: config.write_enabled,
            });
        })
    }
}

impl<F> TurnInputContributor for HeptaMemoryExtension<F>
where
    F: Send + Sync,
{
    fn contribute<'a>(
        &'a self,
        input: TurnInputContext,
        _extension_metrics: Option<Arc<dyn ExtensionMetrics>>,
        _session_store: &'a ExtensionData,
        thread_store: &'a ExtensionData,
        turn_store: &'a ExtensionData,
        _step_store: &'a ExtensionData,
    ) -> ExtensionFuture<'a, Vec<Box<dyn ContextualUserFragment + Send>>> {
        Box::pin(async move {
            turn_store.remove::<PreparedMemoryAttachment>();
            // The turn store is created by admission and is the authority for
            // the exact parent turn. Same-thread lookup alone is insufficient.
            if input.turn_id != turn_store.level_id() {
                return Vec::new();
            }
            let Some(thread_state) = thread_store.get::<HeptaMemoryThreadState>() else {
                return Vec::new();
            };
            let mut primary_environments = input.environments.iter().filter(|item| item.is_primary);
            let Some(primary_environment) = primary_environments.next() else {
                return Vec::new();
            };
            if primary_environments.next().is_some() {
                return Vec::new();
            }
            let workspace = primary_environment.cwd.to_path_buf();
            if !workspace.is_absolute() {
                return Vec::new();
            }
            let Some(query) = bounded_turn_query(&input, thread_state.limits.max_query_bytes())
            else {
                return Vec::new();
            };
            // A Cognitive Plane owns cross-thread attachment when present.
            // Stage-1 remains a compatibility fallback only; allowing both to
            // claim one physical send would fail the host's single-claimant
            // invariant.
            if !self.legacy_attachment_enabled {
                return Vec::new();
            }

            let source_thread = thread_store.level_id();
            let Ok(source_thread_id) = ThreadId::try_from(source_thread) else {
                return Vec::new();
            };
            let scope = thread_state.scope_for(source_thread, workspace.as_path());
            let Ok(request) = RecallRequest::new(
                input.turn_id.as_str(),
                scope,
                RecallAuthority::SameThread,
                query.as_bytes(),
                thread_state.limits.clone(),
            ) else {
                return Vec::new();
            };

            let preflight =
                shadow_recall(&request, query.as_str(), &[], /*now_unix_seconds*/ 0);
            if preflight.reason == RecallObservationReason::SecretLikeQuery {
                commit_turn_observation(
                    turn_store,
                    ShadowRecallTurnObservation::from_recall(preflight),
                );
                return Vec::new();
            }

            let Some(backend) = self.backend.as_ref() else {
                commit_turn_observation(
                    turn_store,
                    ShadowRecallTurnObservation::failure(
                        &request,
                        ShadowRecallTurnReason::BackendMissing,
                    ),
                );
                return Vec::new();
            };
            let stage1_candidate =
                match read_stage1_candidate(backend.as_ref(), source_thread_id, workspace.clone())
                    .await
                {
                    Ok(candidate) => candidate,
                    Err(reason) => {
                        commit_turn_observation(
                            turn_store,
                            ShadowRecallTurnObservation::failure(&request, reason),
                        );
                        return Vec::new();
                    }
                };

            let mut revisions = Vec::new();
            if let Some(candidate) = stage1_candidate.as_ref() {
                match stage1_revision(
                    candidate,
                    &thread_state,
                    workspace.as_path(),
                    source_thread_id,
                ) {
                    Ok(revision) => revisions.push(revision),
                    Err(Stage1BindingError::SourceThreadMismatch) => {
                        commit_turn_observation(
                            turn_store,
                            ShadowRecallTurnObservation::failure(
                                &request,
                                ShadowRecallTurnReason::SourceBindingMismatch,
                            ),
                        );
                        return Vec::new();
                    }
                    Err(Stage1BindingError::InvalidSourceTime) => {
                        commit_turn_observation(
                            turn_store,
                            ShadowRecallTurnObservation::failure(
                                &request,
                                ShadowRecallTurnReason::InvalidSourceTime,
                            ),
                        );
                        return Vec::new();
                    }
                }
            }
            let recall_candidates = stage1_candidate
                .iter()
                .zip(revisions.iter())
                .map(|(candidate, revision)| {
                    codex_hepta_memory::RecallCandidate::new(
                        revision,
                        candidate.rollout_summary.as_str(),
                        candidate.source_updated_at.timestamp(),
                        conservative_token_count(candidate.rollout_summary.as_str()),
                    )
                })
                .collect::<Vec<_>>();
            let observation = shadow_recall(
                &request,
                query.as_str(),
                &recall_candidates,
                /*now_unix_seconds*/ 0,
            );
            let prepared_attachment = prepare_memory_attachment(
                &thread_state,
                &request,
                &observation,
                stage1_candidate.as_ref(),
                revisions.first(),
                source_thread,
                input.turn_id.as_str(),
                workspace.as_path(),
            );
            commit_turn_observation(
                turn_store,
                ShadowRecallTurnObservation::from_recall(observation),
            );
            if let Some(prepared_attachment) = prepared_attachment {
                turn_store.insert(prepared_attachment);
            }
            Vec::new()
        })
    }
}

impl<F> EphemeralModelInputContributor for HeptaMemoryExtension<F>
where
    F: Send + Sync,
{
    fn is_active(&self, thread_store: &ExtensionData, turn_store: &ExtensionData) -> bool {
        self.legacy_attachment_enabled
            && thread_store
                .get::<HeptaMemoryThreadState>()
                .is_some_and(|state| state.attachment_proposal_enabled)
            && turn_store.get::<PreparedMemoryAttachment>().is_some()
    }

    fn contribute<'a>(
        &'a self,
        input: EphemeralModelInputContext<'a>,
    ) -> ModelProviderPolicyFuture<'a, Option<EphemeralModelInputProposal>> {
        Box::pin(async move {
            if !self.legacy_attachment_enabled {
                return Ok(None);
            }
            // Rebind the admitted thread/turn stores to this exact physical
            // attempt before rereading any raw summary from state.
            if input.schema_version != EPHEMERAL_MODEL_INPUT_SCHEMA_VERSION
                || input.request_kind != ModelProviderRequestKind::Turn
                || !input.generate
                || input.thread_id != input.thread_store.level_id()
                || input.turn_id != input.turn_store.level_id()
                || !input.cwd.is_absolute()
            {
                return Err(ephemeral_error(
                    "hepta_memory_ephemeral_scope_mismatch",
                    "Memory proposal scope does not match the exact physical send",
                ));
            }
            let Some(thread_state) = input.thread_store.get::<HeptaMemoryThreadState>() else {
                return Ok(None);
            };
            if !thread_state.attachment_proposal_enabled {
                return Ok(None);
            }
            let Some(prepared) = input.turn_store.get::<PreparedMemoryAttachment>() else {
                return Ok(None);
            };
            if prepared.thread_id != input.thread_id
                || prepared.turn_id != input.turn_id
                || path_identity_bytes(prepared.workspace.as_path())
                    != path_identity_bytes(input.cwd)
            {
                return Ok(None);
            }
            let Some(model_context_window) = input
                .model_context_window
                .and_then(|value| u64::try_from(value).ok())
            else {
                return Ok(None);
            };
            let context_budget = model_context_window
                .saturating_mul(u64::from(thread_state.limits.max_context_window_ppm()))
                / 1_000_000;
            if u64::from(prepared.claimed_token_count) > context_budget {
                return Ok(None);
            }
            let Some(backend) = self.backend.as_ref() else {
                return Ok(None);
            };
            let Ok(source_thread_id) = ThreadId::try_from(prepared.thread_id.as_str()) else {
                return Ok(None);
            };
            let candidate = match read_stage1_candidate(
                backend.as_ref(),
                source_thread_id,
                input.cwd.to_path_buf(),
            )
            .await
            {
                Ok(Some(candidate)) => candidate,
                Ok(None) | Err(_) => return Ok(None),
            };
            let Ok(revision) =
                stage1_revision(&candidate, &thread_state, input.cwd, source_thread_id)
            else {
                return Ok(None);
            };
            let claimed_token_count = conservative_token_count(candidate.rollout_summary.as_str());
            let source_binding_sha256 = memory_attachment_source_binding(
                prepared.thread_id.as_str(),
                prepared.turn_id.as_str(),
                input.cwd,
                &prepared.request_id,
                &revision,
            );
            if revision != prepared.revision
                || claimed_token_count != prepared.claimed_token_count
                || source_binding_sha256 != prepared.source_binding_sha256
                || candidate.rollout_summary.is_empty()
                || candidate.rollout_summary.len() > input.max_content_bytes as usize
                || claimed_token_count > input.max_content_tokens
            {
                return Ok(None);
            }

            Ok(Some(EphemeralModelInputProposal::new(
                EphemeralModelInputSource::parse(HEPTA_MEMORY_SOURCE)?,
                input.attempt_id,
                input.base_logical_request_sha256.clone(),
                input.thread_id,
                input.turn_id,
                api_digest(&prepared.source_binding_sha256)?,
                api_digest(&prepared.revision.revision.content_sha256)?,
                candidate.rollout_summary,
                claimed_token_count,
            )?))
        })
    }
}

#[allow(clippy::too_many_arguments)]
fn prepare_memory_attachment(
    thread_state: &HeptaMemoryThreadState,
    request: &RecallRequest,
    observation: &RecallObservation,
    candidate: Option<&Stage1RecallCandidate>,
    revision: Option<&MemoryRevision>,
    thread_id: &str,
    turn_id: &str,
    workspace: &Path,
) -> Option<PreparedMemoryAttachment> {
    if !thread_state.attachment_proposal_enabled
        || observation.reason != RecallObservationReason::Ranked
    {
        return None;
    }
    let (Some(candidate), Some(revision), [ranked]) =
        (candidate, revision, observation.ranked.as_slice())
    else {
        return None;
    };
    if ranked.memory_id != revision.memory_id || ranked.revision != revision.revision {
        return None;
    }
    let claimed_token_count = conservative_token_count(candidate.rollout_summary.as_str());
    if candidate.rollout_summary.is_empty()
        || claimed_token_count > thread_state.limits.max_item_tokens()
        || claimed_token_count > thread_state.limits.max_total_tokens()
    {
        return None;
    }
    Some(PreparedMemoryAttachment {
        thread_id: thread_id.to_string(),
        turn_id: turn_id.to_string(),
        workspace: workspace.to_path_buf(),
        request_id: request.request_id.clone(),
        revision: revision.clone(),
        source_binding_sha256: memory_attachment_source_binding(
            thread_id,
            turn_id,
            workspace,
            &request.request_id,
            revision,
        ),
        claimed_token_count,
    })
}

fn memory_attachment_source_binding(
    thread_id: &str,
    turn_id: &str,
    workspace: &Path,
    request_id: &RecallRequestId,
    revision: &MemoryRevision,
) -> Sha256Digest {
    digest_many(
        b"hepta-memory:ephemeral-source-binding:v2",
        &[
            thread_id.as_bytes(),
            turn_id.as_bytes(),
            path_identity_bytes(workspace).as_slice(),
            request_id.as_str().as_bytes(),
            revision.memory_id.as_str().as_bytes(),
            &revision.revision.revision.to_be_bytes(),
            revision.revision.content_sha256.as_str().as_bytes(),
            revision.provenance.source_id_sha256.as_str().as_bytes(),
            revision.scope.installation_sha256.as_str().as_bytes(),
            revision.scope.workspace_sha256.as_str().as_bytes(),
            revision.scope.thread_sha256.as_str().as_bytes(),
            revision.scope.principal_sha256.as_str().as_bytes(),
        ],
    )
}

fn api_digest(
    digest: &Sha256Digest,
) -> Result<ModelProviderSha256Digest, ModelProviderPolicyError> {
    ModelProviderSha256Digest::parse(digest.as_str())
}

fn ephemeral_error(reason_code: &'static str, detail: &'static str) -> ModelProviderPolicyError {
    ModelProviderPolicyError::new(reason_code, detail)
}

async fn read_stage1_candidate(
    backend: &dyn Stage1RecallBackend,
    source_thread_id: ThreadId,
    workspace: PathBuf,
) -> Result<Option<Stage1RecallCandidate>, ShadowRecallTurnReason> {
    let read = backend.get_stage1_recall_candidate(source_thread_id, workspace);
    match tokio::time::timeout(RECALL_BACKEND_TIMEOUT, read).await {
        Err(_) => Err(ShadowRecallTurnReason::BackendTimeout),
        Ok(Err(_)) => Err(ShadowRecallTurnReason::BackendUnavailable),
        Ok(Ok(candidate)) => Ok(candidate),
    }
}

/// Registers Memory lifecycle, digest-only shadow recall, and optional
/// physical-send ephemeral input on the host's existing registry.
pub fn install<C, F>(
    builder: &mut ExtensionRegistryBuilder<C>,
    state_db: Option<Arc<StateRuntime>>,
    cognitive_runtime: CognitiveRuntime,
    local_turn_lifecycle_enabled: bool,
    local_development_policy: Option<LocalDevelopmentLifecyclePolicy>,
    resolve_thread: F,
) -> Arc<HeptaMemoryExtension<F>>
where
    C: Sync,
    F: Fn(&C) -> Option<HeptaMemoryThreadConfig> + Send + Sync + 'static,
{
    install_with_turn_writer(
        builder,
        state_db,
        cognitive_runtime,
        local_turn_lifecycle_enabled,
        local_development_policy,
        /*qualification_turn_writer_enabled*/ false,
        /*qualification_turn_writer*/ None,
        resolve_thread,
    )
}

/// Install the extension with an explicit qualification turn-writer gate.
///
/// The writer is registered only when all three inputs are positive: the
/// embedding's explicit flag, a validated qualification-only policy, and an
/// available CognitiveRuntime plus host capability.  Ordinary `install`
/// callers retain the historical no-writer behavior.
#[expect(
    clippy::too_many_arguments,
    reason = "the extension installation boundary carries independent runtime capabilities explicitly"
)]
pub fn install_with_turn_writer<C, F>(
    builder: &mut ExtensionRegistryBuilder<C>,
    state_db: Option<Arc<StateRuntime>>,
    cognitive_runtime: CognitiveRuntime,
    local_turn_lifecycle_enabled: bool,
    local_development_policy: Option<LocalDevelopmentLifecyclePolicy>,
    qualification_turn_writer_enabled: bool,
    qualification_turn_writer: Option<QualificationTurnWriterHost>,
    resolve_thread: F,
) -> Arc<HeptaMemoryExtension<F>>
where
    C: Sync,
    F: Fn(&C) -> Option<HeptaMemoryThreadConfig> + Send + Sync + 'static,
{
    // The legacy H9 turn callback is deliberately separate from the E17
    // explicit host-owned witness policy.  A policy value is a positive gate
    // for a host call, but its canonical `automatic_lifecycle_registration`
    // bit is false; accepting both here would silently install a callback and
    // create an unbound legacy lease before the host can supply a bound
    // lease/checkpoint pair.  Keep the old callback available only to direct
    // legacy embeddings that do not opt into the policy seam.
    let local_lifecycle_store = (local_turn_lifecycle_enabled
        && local_development_policy.is_none())
    .then(|| cognitive_runtime.available_store().cloned())
    .flatten();
    let qualification_writer_profile = qualification_turn_writer_enabled
        && local_development_policy
            .as_ref()
            .is_some_and(|policy| policy.validate().is_ok())
        && cognitive_runtime.available_store().is_some()
        && qualification_turn_writer.is_some();
    let legacy_attachment_enabled = matches!(&cognitive_runtime, CognitiveRuntime::Absent);
    let extension = Arc::new(HeptaMemoryExtension::new(
        resolve_thread,
        state_db,
        legacy_attachment_enabled,
    ));
    builder.thread_lifecycle_contributor(extension.clone());
    builder.turn_input_contributor(extension.clone());
    builder.ephemeral_model_input_contributor(extension.clone());
    if !matches!(&cognitive_runtime, CognitiveRuntime::Absent) {
        let federation = cognitive_runtime.federation().cloned();
        let cognitive = Arc::new(CognitiveExtension::new(cognitive_runtime));
        builder.turn_input_contributor(cognitive.clone());
        builder.tool_contributor(cognitive.clone());
        if let Some(federation) = federation {
            let federated = Arc::new(FederatedCognitiveExtension::new(federation));
            builder.turn_input_contributor(federated.clone());
            builder.ephemeral_model_input_contributor(Arc::new(
                CombinedCognitiveEphemeralContributor::new(cognitive, federated),
            ));
        } else {
            builder.ephemeral_model_input_contributor(cognitive);
        }
    }
    // This is an explicit legacy embedding capability, never inferred from an
    // environment variable or from a non-absent CognitiveRuntime.  Policy-
    // gated embeddings use the host-owned writer above instead of this
    // callback.  The contributor only records local-development journal rows
    // and has no dispatch, KG, routing, or production authority.
    if let Some(store) = local_lifecycle_store {
        builder.turn_lifecycle_contributor(Arc::new(LocalTurnLifecycleContributor::new(store)));
    }
    if qualification_writer_profile && let Some(host) = qualification_turn_writer {
        builder.turn_lifecycle_contributor(Arc::new(
            QualificationTurnLifecycleContributor::with_host(host),
        ));
    }
    extension
}

fn bounded_turn_query(input: &TurnInputContext, max_query_bytes: u32) -> Option<String> {
    let max_query_bytes = max_query_bytes as usize;
    let mut query = String::with_capacity(max_query_bytes.min(1024));
    for item in &input.user_input {
        let UserInput::Text { text, .. } = item else {
            continue;
        };
        if text.is_empty() {
            continue;
        }
        let separator_bytes = usize::from(!query.is_empty());
        let next_len = query
            .len()
            .checked_add(separator_bytes)?
            .checked_add(text.len())?;
        if next_len > max_query_bytes {
            return None;
        }
        if separator_bytes == 1 {
            query.push('\n');
        }
        query.push_str(text);
    }
    (!query.trim().is_empty()).then_some(query)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Stage1BindingError {
    SourceThreadMismatch,
    InvalidSourceTime,
}

fn stage1_revision(
    candidate: &Stage1RecallCandidate,
    thread_state: &HeptaMemoryThreadState,
    workspace: &Path,
    expected_source_thread_id: ThreadId,
) -> Result<MemoryRevision, Stage1BindingError> {
    if candidate.thread_id != expected_source_thread_id {
        return Err(Stage1BindingError::SourceThreadMismatch);
    }
    let source_updated_at = candidate.source_updated_at.timestamp();
    let generated_at = candidate.generated_at.timestamp();
    if source_updated_at < 0 || generated_at < 0 || generated_at < source_updated_at {
        return Err(Stage1BindingError::InvalidSourceTime);
    }
    let source_thread_id = candidate.thread_id.to_string();
    let scope = thread_state.scope_for(source_thread_id.as_str(), workspace);
    let content = candidate.rollout_summary.as_bytes();
    let revision_number =
        u64::try_from(source_updated_at).map_err(|_| Stage1BindingError::InvalidSourceTime)?;
    let source_revision = RevisionStamp::new(revision_number, content);
    let source_id_sha256 = digest_many(
        b"hepta-memory:stage1-source:v2",
        &[
            source_thread_id.as_bytes(),
            &source_updated_at.to_be_bytes(),
            &generated_at.to_be_bytes(),
            source_revision.content_sha256.as_str().as_bytes(),
        ],
    );
    Ok(MemoryRevision {
        schema_version: MEMORY_CONTRACT_SCHEMA_VERSION,
        memory_id: MemoryId::for_content(&scope, content),
        revision: source_revision.clone(),
        scope,
        provenance: MemoryProvenance {
            source_kind: MemorySourceKind::CodexStage1Summary,
            source_id_sha256,
            source_revision,
            observed_at_unix_seconds: generated_at,
        },
        lifecycle: MemoryLifecycle::Active,
        valid_until_unix_seconds: None,
    })
}

fn conservative_token_count(summary: &str) -> u32 {
    u32::try_from(summary.len()).unwrap_or(u32::MAX)
}

#[cfg(test)]
#[path = "extension_tests.rs"]
mod tests;
