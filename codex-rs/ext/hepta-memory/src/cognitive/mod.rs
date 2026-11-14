use std::collections::VecDeque;
use std::future::Future;
use std::path::Path;
use std::path::PathBuf;
use std::pin::Pin;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::PoisonError;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_extension_api::EPHEMERAL_MODEL_INPUT_MAX_CONTENT_BYTES;
use codex_extension_api::EPHEMERAL_MODEL_INPUT_MAX_CONTENT_TOKENS;
use codex_extension_api::EPHEMERAL_MODEL_INPUT_SCHEMA_VERSION;
use codex_extension_api::EphemeralModelInputContext;
use codex_extension_api::EphemeralModelInputContributor;
use codex_extension_api::EphemeralModelInputFinalUseGuard;
use codex_extension_api::EphemeralModelInputProposal;
use codex_extension_api::EphemeralModelInputSource;
use codex_extension_api::ExtensionData;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ExtensionMetrics;
use codex_extension_api::ModelProviderPolicyError;
use codex_extension_api::ModelProviderPolicyFuture;
use codex_extension_api::ModelProviderRequestKind;
use codex_extension_api::ModelProviderSha256Digest;
use codex_extension_api::ToolCall;
use codex_extension_api::ToolContributor;
use codex_extension_api::ToolExecutor;
use codex_extension_api::TurnInputContext;
use codex_extension_api::TurnInputContributor;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveRuntime;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::CognitiveStoreError;
use codex_hepta_memory::MAX_RETRIEVAL_QUERY_BYTES;
use codex_hepta_memory::MemoryExplanation;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryRevalidationBinding;
use codex_hepta_memory::MemoryRevisionRecord;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::ProductionCognitiveMutation;
use codex_hepta_memory::RetrievalBatch;
use codex_hepta_memory::RetrievalChannel;
use codex_hepta_memory::RetrievalRequest;
use codex_hepta_memory::RevalidationStatus;
use codex_hepta_memory::SourceRevalidationBinding;
use codex_protocol::user_input::UserInput;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

use crate::extension::HeptaMemoryThreadState;
use crate::framing::digest_many;
use crate::framing::path_identity_bytes;
use crate::framing::workspace_digest;

mod federation;
mod kg_extractor;
mod tools;

pub(crate) use federation::CombinedCognitiveEphemeralContributor;
pub(crate) use federation::FederatedCognitiveExtension;

const COGNITIVE_SOURCE: &str = "hepta_cognitive_plane_v1";
const COGNITIVE_ATTACHMENT_SCHEMA_VERSION: u32 = 2;
const MAX_WITNESSES_PER_THREAD: usize = 16;
const MAX_AUTO_CITATIONS_PER_MEMORY: usize = 8;

type RetrievalFuture<'a> =
    Pin<Box<dyn Future<Output = Result<RetrievalBatch, CognitiveStoreError>> + Send + 'a>>;
type RevalidationFuture<'a> =
    Pin<Box<dyn Future<Output = Result<Vec<RevalidationStatus>, CognitiveStoreError>> + Send + 'a>>;

trait CognitiveRecallBackend: Send + Sync {
    fn retrieve<'a>(
        &'a self,
        access: &'a CognitiveAccess,
        request: &'a RetrievalRequest,
    ) -> RetrievalFuture<'a>;

    fn revalidate_batch<'a>(
        &'a self,
        access: &'a CognitiveAccess,
        bindings: &'a [MemoryRevalidationBinding],
        now_unix_seconds: i64,
    ) -> RevalidationFuture<'a>;
}

impl CognitiveRecallBackend for CognitiveStore {
    fn retrieve<'a>(
        &'a self,
        access: &'a CognitiveAccess,
        request: &'a RetrievalRequest,
    ) -> RetrievalFuture<'a> {
        Box::pin(self.retrieve_memory_candidates(access, request))
    }

    fn revalidate_batch<'a>(
        &'a self,
        access: &'a CognitiveAccess,
        bindings: &'a [MemoryRevalidationBinding],
        now_unix_seconds: i64,
    ) -> RevalidationFuture<'a> {
        Box::pin(self.revalidate_memory_candidates(access, bindings, now_unix_seconds))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) struct ExactDirectiveWitness {
    pub(super) turn_id: String,
    pub(super) workspace: PathBuf,
    pub(super) workspace_sha256: Sha256Digest,
    content_sha256: Sha256Digest,
    content_bytes: usize,
    byte_exact_verification_allowed: bool,
}

impl ExactDirectiveWitness {
    pub(super) fn verifies_content(&self, content: &str) -> bool {
        self.byte_exact_verification_allowed
            && content.len() == self.content_bytes
            && Sha256Digest::for_bytes(content.as_bytes()) == self.content_sha256
    }
}

#[derive(Default)]
struct CognitiveTurnWitnesses {
    values: Mutex<VecDeque<CognitiveTurnWitnessState>>,
}

enum CognitiveTurnWitnessState {
    Valid(ExactDirectiveWitness),
    Poisoned(String),
}

impl CognitiveTurnWitnessState {
    fn turn_id(&self) -> &str {
        match self {
            Self::Valid(witness) => witness.turn_id.as_str(),
            Self::Poisoned(turn_id) => turn_id.as_str(),
        }
    }
}

impl CognitiveTurnWitnesses {
    fn insert(&self, witness: ExactDirectiveWitness) {
        let mut values = self.values.lock().unwrap_or_else(PoisonError::into_inner);
        if let Some(existing) = values
            .iter_mut()
            .find(|existing| existing.turn_id() == witness.turn_id.as_str())
        {
            if matches!(existing, CognitiveTurnWitnessState::Valid(current) if current == &witness)
            {
                return;
            }
            *existing = CognitiveTurnWitnessState::Poisoned(witness.turn_id);
            return;
        }
        values.push_back(CognitiveTurnWitnessState::Valid(witness));
        while values.len() > MAX_WITNESSES_PER_THREAD {
            values.pop_front();
        }
    }

    fn get(&self, turn_id: &str) -> Option<ExactDirectiveWitness> {
        self.values
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .iter()
            .find_map(|state| match state {
                CognitiveTurnWitnessState::Valid(witness) if witness.turn_id == turn_id => {
                    Some(witness.clone())
                }
                CognitiveTurnWitnessState::Valid(_) | CognitiveTurnWitnessState::Poisoned(_) => {
                    None
                }
            })
    }
}

#[derive(Clone)]
struct PreparedCognitiveAttachment {
    thread_id: String,
    turn_id: String,
    workspace: PathBuf,
    query_sha256: Sha256Digest,
    bindings: Vec<PreparedCognitiveBinding>,
    source_binding_sha256: Sha256Digest,
    content_sha256: Sha256Digest,
    claimed_token_count: u32,
}

#[derive(Clone, Serialize)]
struct PreparedCognitiveBinding {
    binding: MemoryRevalidationBinding,
    channels: Vec<RetrievalChannel>,
}

struct RevalidatedAttachmentMemory {
    explanation: MemoryExplanation,
    channels: Vec<RetrievalChannel>,
}

pub(super) struct CognitiveProposalMaterial {
    pub(super) source: &'static str,
    pub(super) source_binding_sha256: Sha256Digest,
    pub(super) content_sha256: Sha256Digest,
    pub(super) content: String,
    pub(super) claimed_token_count: u32,
    pub(super) final_use_guard: Option<Box<dyn EphemeralModelInputFinalUseGuard>>,
}

struct ChainedFinalUseGuard {
    guards: Vec<Box<dyn EphemeralModelInputFinalUseGuard>>,
}

impl EphemeralModelInputFinalUseGuard for ChainedFinalUseGuard {
    fn revalidate(self: Box<Self>) -> ModelProviderPolicyFuture<'static, ()> {
        Box::pin(async move {
            for guard in self.guards {
                guard.revalidate().await?;
            }
            Ok(())
        })
    }
}

pub(super) fn chain_final_use_guards(
    left: Option<Box<dyn EphemeralModelInputFinalUseGuard>>,
    right: Option<Box<dyn EphemeralModelInputFinalUseGuard>>,
) -> Option<Box<dyn EphemeralModelInputFinalUseGuard>> {
    match (left, right) {
        (None, None) => None,
        (Some(guard), None) | (None, Some(guard)) => Some(guard),
        (Some(left), Some(right)) => Some(Box::new(ChainedFinalUseGuard {
            guards: vec![left, right],
        })),
    }
}

impl CognitiveProposalMaterial {
    pub(super) fn into_proposal(
        self,
        input: &EphemeralModelInputContext<'_>,
    ) -> Result<EphemeralModelInputProposal, ModelProviderPolicyError> {
        let proposal = EphemeralModelInputProposal::new(
            EphemeralModelInputSource::parse(self.source)?,
            input.attempt_id,
            input.base_logical_request_sha256.clone(),
            input.thread_id,
            input.turn_id,
            api_digest(&self.source_binding_sha256)?,
            api_digest(&self.content_sha256)?,
            self.content,
            self.claimed_token_count,
        )?;
        Ok(match self.final_use_guard {
            Some(guard) => proposal.with_final_use_guard(guard),
            None => proposal,
        })
    }
}

pub(crate) struct CognitiveExtension {
    runtime: CognitiveRuntime,
    recall: Option<Arc<dyn CognitiveRecallBackend>>,
    production_mutation: Option<Arc<dyn ProductionCognitiveMutation>>,
    qualification_write_enabled: bool,
}

impl CognitiveExtension {
    #[cfg(test)]
    pub(crate) fn new(runtime: CognitiveRuntime) -> Self {
        Self::new_with_mutation(runtime, None, false)
    }

    pub(crate) fn new_with_mutation(
        runtime: CognitiveRuntime,
        production_mutation: Option<Arc<dyn ProductionCognitiveMutation>>,
        qualification_write_enabled: bool,
    ) -> Self {
        let recall = runtime
            .available_store()
            .map(|store| store.clone() as Arc<dyn CognitiveRecallBackend>);
        let production_mutation = production_mutation.filter(|mutation| {
            runtime
                .available_store()
                .is_some_and(|store| mutation.owner_agent_id() == store.owner_agent_id())
        });
        Self {
            runtime,
            recall,
            production_mutation,
            qualification_write_enabled,
        }
    }

    #[cfg(test)]
    fn with_recall(store: Arc<CognitiveStore>, recall: Arc<dyn CognitiveRecallBackend>) -> Self {
        Self {
            runtime: CognitiveRuntime::Available(store),
            recall: Some(recall),
            production_mutation: None,
            qualification_write_enabled: false,
        }
    }

    fn store(&self) -> Option<&Arc<CognitiveStore>> {
        self.runtime.available_store()
    }

    async fn revalidate_bindings(
        &self,
        access: &CognitiveAccess,
        prepared_bindings: &[PreparedCognitiveBinding],
        now_unix_seconds: i64,
    ) -> Option<Vec<RevalidatedAttachmentMemory>> {
        let recall = self.recall.as_ref()?;
        let bindings = prepared_bindings
            .iter()
            .map(|prepared| prepared.binding.clone())
            .collect::<Vec<_>>();
        let statuses = recall
            .revalidate_batch(access, &bindings, now_unix_seconds)
            .await
            .ok()?;
        if statuses.len() != prepared_bindings.len() {
            return None;
        }
        let mut explanations = Vec::with_capacity(prepared_bindings.len());
        for (status, prepared_binding) in statuses.into_iter().zip(prepared_bindings) {
            let RevalidationStatus::Current(explanation) = status else {
                return None;
            };
            if explanation.memory.verification != MemoryVerification::Verified
                || explanation.memory.lifecycle != MemoryLifecycleState::Active
                || secret_like(explanation.memory.content.as_bytes())
                || explanation
                    .citations
                    .iter()
                    .any(|citation| secret_like(&citation.content))
            {
                return None;
            }
            explanations.push(RevalidatedAttachmentMemory {
                explanation: *explanation,
                channels: prepared_binding.channels.clone(),
            });
        }
        Some(explanations)
    }

    pub(super) fn has_prepared_attachment(
        &self,
        thread_store: &ExtensionData,
        turn_store: &ExtensionData,
    ) -> bool {
        thread_store
            .get::<HeptaMemoryThreadState>()
            .is_some_and(|state| state.attachment_proposal_enabled)
            && turn_store.get::<PreparedCognitiveAttachment>().is_some()
    }

    pub(super) async fn revalidate_prepared_attachment(
        &self,
        input: &EphemeralModelInputContext<'_>,
    ) -> Option<CognitiveProposalMaterial> {
        if input.schema_version != EPHEMERAL_MODEL_INPUT_SCHEMA_VERSION
            || input.request_kind != ModelProviderRequestKind::Turn
            || !input.generate
            || input.thread_id != input.thread_store.level_id()
            || input.turn_id != input.turn_store.level_id()
            || !input.cwd.is_absolute()
        {
            return None;
        }
        let thread_state = input.thread_store.get::<HeptaMemoryThreadState>()?;
        if !thread_state.attachment_proposal_enabled {
            return None;
        }
        let prepared = input.turn_store.get::<PreparedCognitiveAttachment>()?;
        if prepared.thread_id != input.thread_id
            || prepared.turn_id != input.turn_id
            || path_identity_bytes(prepared.workspace.as_path()) != path_identity_bytes(input.cwd)
        {
            return None;
        }
        let model_context_window = input
            .model_context_window
            .and_then(|value| u64::try_from(value).ok())?;
        let context_budget = model_context_window
            .saturating_mul(u64::from(thread_state.limits.max_context_window_ppm()))
            / 1_000_000;
        if u64::from(prepared.claimed_token_count) > context_budget {
            return None;
        }
        let now = now_unix_seconds()?;
        let store = self.store()?;
        let access = CognitiveAccess::workspace_private(
            store.owner_agent_id().clone(),
            workspace_digest(input.cwd),
        );
        let explanations = self
            .revalidate_bindings(&access, &prepared.bindings, now)
            .await?;
        let content = compile_explanations(&explanations)?;
        let content_sha256 = Sha256Digest::for_bytes(content.as_bytes());
        let source_binding_sha256 = cognitive_source_binding(
            input.thread_id,
            input.turn_id,
            input.cwd,
            &prepared.query_sha256,
            &prepared.bindings,
            &content_sha256,
        );
        let claimed_token_count = u32::try_from(content.len()).ok()?;
        if source_binding_sha256 != prepared.source_binding_sha256
            || content_sha256 != prepared.content_sha256
            || claimed_token_count != prepared.claimed_token_count
            || content.is_empty()
            || content.len() > input.max_content_bytes as usize
            || claimed_token_count > input.max_content_tokens
        {
            return None;
        }
        Some(CognitiveProposalMaterial {
            source: COGNITIVE_SOURCE,
            source_binding_sha256,
            content_sha256,
            content,
            claimed_token_count,
            final_use_guard: None,
        })
    }
}

impl TurnInputContributor for CognitiveExtension {
    fn contribute<'a>(
        &'a self,
        input: TurnInputContext,
        _extension_metrics: Option<Arc<dyn ExtensionMetrics>>,
        _session_store: &'a ExtensionData,
        thread_store: &'a ExtensionData,
        turn_store: &'a ExtensionData,
        _step_store: &'a ExtensionData,
    ) -> ExtensionFuture<'a, Vec<Box<dyn codex_extension_api::ContextualUserFragment + Send>>> {
        Box::pin(async move {
            turn_store.remove::<PreparedCognitiveAttachment>();
            if input.turn_id != turn_store.level_id() {
                return Vec::new();
            }
            let Some(thread_state) = thread_store.get::<HeptaMemoryThreadState>() else {
                return Vec::new();
            };
            let mut primary_environments = input
                .environments
                .iter()
                .filter(|environment| environment.is_primary);
            let Some(primary) = primary_environments.next() else {
                return Vec::new();
            };
            if primary_environments.next().is_some() {
                return Vec::new();
            }
            let workspace = primary.cwd.to_path_buf();
            if !workspace.is_absolute() {
                return Vec::new();
            }
            let capture = capture_directive(&input.user_input);
            let witness = ExactDirectiveWitness {
                turn_id: input.turn_id.clone(),
                workspace_sha256: workspace_digest(workspace.as_path()),
                workspace: workspace.clone(),
                content_sha256: capture.content_sha256,
                content_bytes: capture.content_bytes,
                byte_exact_verification_allowed: capture.byte_exact_verification_allowed,
            };
            thread_store
                .get_or_init(CognitiveTurnWitnesses::default)
                .insert(witness);

            if !thread_state.attachment_proposal_enabled {
                return Vec::new();
            }
            let Some(query) = capture.query else {
                return Vec::new();
            };
            if secret_like(query.as_bytes()) {
                return Vec::new();
            }
            let Some(now) = now_unix_seconds() else {
                return Vec::new();
            };
            let (Some(store), Some(recall)) = (self.store(), self.recall.as_ref()) else {
                return Vec::new();
            };
            let access = CognitiveAccess::workspace_private(
                store.owner_agent_id().clone(),
                workspace_digest(workspace.as_path()),
            );
            let request = RetrievalRequest::new(query, now);
            let Ok(batch) = recall.retrieve(&access, &request).await else {
                return Vec::new();
            };
            let byte_budget = usize::try_from(
                thread_state
                    .limits
                    .max_total_tokens()
                    .min(EPHEMERAL_MODEL_INPUT_MAX_CONTENT_BYTES),
            )
            .unwrap_or(usize::MAX);
            let item_budget =
                usize::try_from(thread_state.limits.max_item_tokens()).unwrap_or(usize::MAX);
            let Some((bindings, content)) =
                compile_retrieval_batch(&batch, byte_budget, item_budget)
            else {
                return Vec::new();
            };
            let content_sha256 = Sha256Digest::for_bytes(content.as_bytes());
            let source_binding_sha256 = cognitive_source_binding(
                thread_store.level_id(),
                input.turn_id.as_str(),
                workspace.as_path(),
                &batch.query_sha256,
                &bindings,
                &content_sha256,
            );
            let Ok(claimed_token_count) = u32::try_from(content.len()) else {
                return Vec::new();
            };
            turn_store.insert(PreparedCognitiveAttachment {
                thread_id: thread_store.level_id().to_string(),
                turn_id: input.turn_id,
                workspace,
                query_sha256: batch.query_sha256,
                bindings,
                source_binding_sha256,
                content_sha256,
                claimed_token_count,
            });
            Vec::new()
        })
    }
}

impl EphemeralModelInputContributor for CognitiveExtension {
    fn is_active(&self, thread_store: &ExtensionData, turn_store: &ExtensionData) -> bool {
        thread_store
            .get::<HeptaMemoryThreadState>()
            .is_some_and(|state| state.attachment_proposal_enabled)
            && turn_store.get::<PreparedCognitiveAttachment>().is_some()
    }

    fn contribute<'a>(
        &'a self,
        input: EphemeralModelInputContext<'a>,
    ) -> ModelProviderPolicyFuture<'a, Option<EphemeralModelInputProposal>> {
        Box::pin(async move {
            // Automatic recall is deliberately fail-open. Every rejected scope,
            // backend failure, stale binding, or retry-time drift simply removes
            // the optional context from this physical send.
            if input.schema_version != EPHEMERAL_MODEL_INPUT_SCHEMA_VERSION
                || input.request_kind != ModelProviderRequestKind::Turn
                || !input.generate
                || input.thread_id != input.thread_store.level_id()
                || input.turn_id != input.turn_store.level_id()
                || !input.cwd.is_absolute()
            {
                return Ok(None);
            }
            let Some(thread_state) = input.thread_store.get::<HeptaMemoryThreadState>() else {
                return Ok(None);
            };
            if !thread_state.attachment_proposal_enabled {
                return Ok(None);
            }
            let Some(prepared) = input.turn_store.get::<PreparedCognitiveAttachment>() else {
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
            let Some(now) = now_unix_seconds() else {
                return Ok(None);
            };
            let Some(store) = self.store() else {
                return Ok(None);
            };
            let access = CognitiveAccess::workspace_private(
                store.owner_agent_id().clone(),
                workspace_digest(input.cwd),
            );
            let Some(explanations) = self
                .revalidate_bindings(&access, &prepared.bindings, now)
                .await
            else {
                return Ok(None);
            };
            let Some(content) = compile_explanations(&explanations) else {
                return Ok(None);
            };
            let content_sha256 = Sha256Digest::for_bytes(content.as_bytes());
            let source_binding_sha256 = cognitive_source_binding(
                input.thread_id,
                input.turn_id,
                input.cwd,
                &prepared.query_sha256,
                &prepared.bindings,
                &content_sha256,
            );
            let Ok(claimed_token_count) = u32::try_from(content.len()) else {
                return Ok(None);
            };
            if source_binding_sha256 != prepared.source_binding_sha256
                || content_sha256 != prepared.content_sha256
                || claimed_token_count != prepared.claimed_token_count
                || content.is_empty()
                || content.len() > input.max_content_bytes as usize
                || claimed_token_count > input.max_content_tokens
            {
                return Ok(None);
            }
            Ok(Some(EphemeralModelInputProposal::new(
                EphemeralModelInputSource::parse(COGNITIVE_SOURCE)?,
                input.attempt_id,
                input.base_logical_request_sha256.clone(),
                input.thread_id,
                input.turn_id,
                api_digest(&source_binding_sha256)?,
                api_digest(&content_sha256)?,
                content,
                claimed_token_count,
            )?))
        })
    }
}

impl ToolContributor for CognitiveExtension {
    fn tools(
        &self,
        _session_store: &ExtensionData,
        _thread_store: &ExtensionData,
    ) -> Vec<Arc<dyn ToolExecutor<ToolCall>>> {
        Vec::new()
    }

    fn tools_for_step(
        &self,
        _session_store: &ExtensionData,
        thread_store: &ExtensionData,
        step_store: &ExtensionData,
    ) -> Vec<Arc<dyn ToolExecutor<ToolCall>>> {
        let Some(thread_state) = thread_store.get::<HeptaMemoryThreadState>() else {
            return Vec::new();
        };
        let witnesses = thread_store.get_or_init(CognitiveTurnWitnesses::default);
        tools::deferred_cognitive_tools(
            self.runtime.clone(),
            thread_store.level_id().to_string(),
            step_store.level_id().to_string(),
            witnesses,
            thread_state.write_enabled
                && self.qualification_write_enabled
                && self.store().is_some(),
            if thread_state.write_enabled {
                self.production_mutation.clone()
            } else {
                None
            },
        )
    }
}

pub(super) struct DirectiveCapture {
    pub(super) content_sha256: Sha256Digest,
    pub(super) content_bytes: usize,
    pub(super) byte_exact_verification_allowed: bool,
    pub(super) query: Option<String>,
}

pub(super) fn capture_directive(input: &[UserInput]) -> DirectiveCapture {
    let mut hasher = Sha256::new();
    let mut content_bytes = 0usize;
    let mut has_text = false;
    let mut exact = true;
    let mut query = Vec::with_capacity(MAX_RETRIEVAL_QUERY_BYTES.min(1024));
    let mut query_bounded = true;
    for item in input {
        let UserInput::Text {
            text,
            text_elements,
        } = item
        else {
            exact = false;
            continue;
        };
        if !text_elements.is_empty() {
            exact = false;
        }
        if text.is_empty() {
            continue;
        }
        if has_text {
            hasher.update(b"\n");
            content_bytes = content_bytes.saturating_add(1);
            if query_bounded && query.len() < MAX_RETRIEVAL_QUERY_BYTES {
                query.push(b'\n');
            } else {
                query_bounded = false;
                query.clear();
            }
        }
        has_text = true;
        hasher.update(text.as_bytes());
        content_bytes = content_bytes.saturating_add(text.len());
        if query_bounded
            && query
                .len()
                .checked_add(text.len())
                .is_some_and(|length| length <= MAX_RETRIEVAL_QUERY_BYTES)
        {
            query.extend_from_slice(text.as_bytes());
        } else {
            query_bounded = false;
            query.clear();
        }
    }
    if !has_text {
        exact = false;
    }
    let content_sha256 = Sha256Digest::from_sha256_output(hasher.finalize());
    let query = if query_bounded {
        String::from_utf8(query)
            .ok()
            .filter(|query| !query.trim().is_empty())
    } else {
        None
    };
    DirectiveCapture {
        content_sha256,
        content_bytes,
        byte_exact_verification_allowed: exact,
        query,
    }
}

#[derive(Serialize)]
struct CognitiveAttachment<'a> {
    schema_version: u32,
    source: &'static str,
    memories: &'a [AttachmentMemory],
}

#[derive(Clone, Serialize)]
struct AttachmentMemory {
    memory_id: String,
    revision: u64,
    content: String,
    content_sha256: String,
    channels: Vec<RetrievalChannel>,
    citations: Vec<AttachmentCitation>,
}

#[derive(Clone, Serialize)]
struct AttachmentCitation {
    source_id: String,
    revision: u64,
    content_sha256: String,
}

fn compile_retrieval_batch(
    batch: &RetrievalBatch,
    max_bytes: usize,
    max_item_bytes: usize,
) -> Option<(Vec<PreparedCognitiveBinding>, String)> {
    let max_bytes = max_bytes
        .min(EPHEMERAL_MODEL_INPUT_MAX_CONTENT_BYTES as usize)
        .min(EPHEMERAL_MODEL_INPUT_MAX_CONTENT_TOKENS as usize);
    let mut selected_bindings = Vec::new();
    let mut selected_memories = Vec::new();
    for candidate in &batch.candidates {
        if candidate.memory.verification != MemoryVerification::Verified
            || candidate.memory.lifecycle != MemoryLifecycleState::Active
            || candidate.memory.content.len() > max_item_bytes
            || secret_like(candidate.memory.content.as_bytes())
        {
            continue;
        }
        let channels = canonical_channels(&candidate.channels);
        let record = attachment_record(
            &candidate.memory,
            &candidate.revalidation.citations,
            &channels,
        );
        let mut proposed = selected_memories.clone();
        proposed.push(record);
        let Ok(content) = serialize_attachment(&proposed) else {
            continue;
        };
        if content.len() > max_bytes {
            continue;
        }
        selected_memories = proposed;
        selected_bindings.push(PreparedCognitiveBinding {
            binding: candidate.revalidation.clone(),
            channels,
        });
    }
    if selected_bindings.is_empty() {
        return None;
    }
    let content = serialize_attachment(&selected_memories).ok()?;
    Some((selected_bindings, content))
}

fn compile_explanations(explanations: &[RevalidatedAttachmentMemory]) -> Option<String> {
    let memories = explanations
        .iter()
        .map(|revalidated| {
            let explanation = &revalidated.explanation;
            let citations = explanation
                .citations
                .iter()
                .map(|citation| SourceRevalidationBinding {
                    id: citation.id.clone(),
                    scope: citation.scope.clone(),
                    content_sha256: citation.content_sha256.clone(),
                })
                .collect::<Vec<_>>();
            attachment_record(&explanation.memory, &citations, &revalidated.channels)
        })
        .collect::<Vec<_>>();
    serialize_attachment(&memories).ok()
}

fn serialize_attachment(memories: &[AttachmentMemory]) -> Result<String, serde_json::Error> {
    serde_json::to_string(&CognitiveAttachment {
        schema_version: COGNITIVE_ATTACHMENT_SCHEMA_VERSION,
        source: "verified_versioned_memory",
        memories,
    })
}

fn attachment_record(
    memory: &MemoryRevisionRecord,
    citations: &[SourceRevalidationBinding],
    channels: &[RetrievalChannel],
) -> AttachmentMemory {
    AttachmentMemory {
        memory_id: memory.id.memory_id.as_str().to_string(),
        revision: memory.id.revision,
        content: memory.content.clone(),
        content_sha256: memory.content_sha256.as_str().to_string(),
        channels: channels.to_vec(),
        citations: citations
            .iter()
            .take(MAX_AUTO_CITATIONS_PER_MEMORY)
            .map(|citation| AttachmentCitation {
                source_id: citation.id.source_id.as_str().to_string(),
                revision: citation.id.revision,
                content_sha256: citation.content_sha256.as_str().to_string(),
            })
            .collect(),
    }
}

fn canonical_channels(channels: &[RetrievalChannel]) -> Vec<RetrievalChannel> {
    let mut channels = channels.to_vec();
    channels.sort_unstable();
    channels.dedup();
    channels
}

fn cognitive_source_binding(
    thread_id: &str,
    turn_id: &str,
    workspace: &Path,
    query_sha256: &Sha256Digest,
    bindings: &[PreparedCognitiveBinding],
    content_sha256: &Sha256Digest,
) -> Sha256Digest {
    let serialized = serde_json::to_vec(bindings).unwrap_or_default();
    digest_many(
        b"hepta:cognitive:ephemeral-source-binding:v2",
        &[
            thread_id.as_bytes(),
            turn_id.as_bytes(),
            path_identity_bytes(workspace).as_slice(),
            query_sha256.as_str().as_bytes(),
            serialized.as_slice(),
            content_sha256.as_str().as_bytes(),
        ],
    )
}

fn api_digest(
    digest: &Sha256Digest,
) -> Result<ModelProviderSha256Digest, ModelProviderPolicyError> {
    ModelProviderSha256Digest::parse(digest.as_str())
}

pub(super) fn now_unix_seconds() -> Option<i64> {
    let seconds = SystemTime::now().duration_since(UNIX_EPOCH).ok()?.as_secs();
    i64::try_from(seconds).ok()
}

pub(super) fn secret_like(bytes: &[u8]) -> bool {
    let text = String::from_utf8_lossy(bytes).to_ascii_lowercase();
    let compact = text
        .chars()
        .filter(|character| !character.is_whitespace())
        .collect::<String>();
    [
        "api_key=",
        "apikey=",
        "access_token=",
        "refresh_token=",
        "password=",
        "passwd=",
        "client_secret=",
        "authorization:bearer",
        "-----beginprivatekey-----",
        "-----beginrsaprivatekey-----",
        "-----beginecprivatekey-----",
        "github_pat_",
        "ghp_",
    ]
    .iter()
    .any(|marker| compact.contains(marker))
        || contains_aws_access_key(compact.as_bytes())
        || contains_openai_style_key(compact.as_bytes())
        || contains_jwt(compact.as_bytes())
}

fn contains_aws_access_key(bytes: &[u8]) -> bool {
    bytes.windows(20).any(|window| {
        matches!(&window[..4], b"akia" | b"asia")
            && window[4..]
                .iter()
                .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit())
    })
}

fn contains_openai_style_key(bytes: &[u8]) -> bool {
    bytes.windows(20).any(|window| {
        window.starts_with(b"sk-")
            && window[3..]
                .iter()
                .all(|byte| byte.is_ascii_alphanumeric() || *byte == b'-' || *byte == b'_')
    })
}

fn contains_jwt(bytes: &[u8]) -> bool {
    bytes
        .split(|byte| !(byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.')))
        .any(|token| {
            token.starts_with(b"eyj")
                && token.len() >= 32
                && token.iter().filter(|byte| **byte == b'.').count() == 2
        })
}

#[cfg(test)]
#[path = "tests.rs"]
mod tests;
