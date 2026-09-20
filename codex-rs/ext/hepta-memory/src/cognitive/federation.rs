use std::path::Path;
use std::sync::Arc;

use codex_extension_api::EPHEMERAL_MODEL_INPUT_MAX_CONTENT_BYTES;
use codex_extension_api::EPHEMERAL_MODEL_INPUT_MAX_CONTENT_TOKENS;
use codex_extension_api::EPHEMERAL_MODEL_INPUT_SCHEMA_VERSION;
use codex_extension_api::EphemeralModelInputContext;
use codex_extension_api::EphemeralModelInputContributor;
use codex_extension_api::EphemeralModelInputProposal;
use codex_extension_api::EphemeralModelInputSource;
use codex_extension_api::ExtensionData;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ExtensionMetrics;
use codex_extension_api::ModelProviderPolicyError;
use codex_extension_api::ModelProviderPolicyFuture;
use codex_extension_api::ModelProviderRequestKind;
use codex_extension_api::ModelProviderSha256Digest;
use codex_extension_api::TurnInputContext;
use codex_extension_api::TurnInputContributor;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::FederatedMemoryExplanation;
use codex_hepta_memory::FederatedMemoryRevalidationBinding;
use codex_hepta_memory::FederatedRecallSet;
use codex_hepta_memory::FederatedRetrievalBatch;
use codex_hepta_memory::FederatedRevalidationStatus;
use codex_hepta_memory::FederationConsumerAccess;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::RetrievalRequest;
use serde::Serialize;
use serde_json::Value;
use serde_json::json;

use super::CognitiveExtension;
use super::CognitiveProposalMaterial;
use super::capture_directive;
use super::now_unix_seconds;
use super::secret_like;
use crate::extension::HeptaMemoryThreadState;
use crate::framing::digest_many;
use crate::framing::path_identity_bytes;
use crate::framing::workspace_digest;

const FEDERATED_COGNITIVE_SOURCE: &str = "hepta_cognitive_federation_v1";
const COMBINED_COGNITIVE_SOURCE: &str = "hepta_cognitive_combined_v1";
const FEDERATED_ATTACHMENT_SCHEMA_VERSION: u32 = 1;
const MAX_AUTO_CITATIONS_PER_MEMORY: usize = 8;
const MAX_COMBINED_CITATIONS_PER_MEMORY: usize = 1;

#[derive(Clone)]
struct PreparedFederatedAttachment {
    thread_id: String,
    turn_id: String,
    workspace: std::path::PathBuf,
    query_sha256: Sha256Digest,
    bindings: Vec<FederatedMemoryRevalidationBinding>,
    source_binding_sha256: Sha256Digest,
    content_sha256: Sha256Digest,
    claimed_token_count: u32,
}

pub(crate) struct FederatedCognitiveExtension {
    federation: Arc<FederatedRecallSet>,
}

impl FederatedCognitiveExtension {
    pub(crate) fn new(federation: Arc<FederatedRecallSet>) -> Self {
        Self { federation }
    }

    fn has_prepared_attachment(
        &self,
        thread_store: &ExtensionData,
        turn_store: &ExtensionData,
    ) -> bool {
        thread_store
            .get::<HeptaMemoryThreadState>()
            .is_some_and(|state| state.attachment_proposal_enabled)
            && turn_store.get::<PreparedFederatedAttachment>().is_some()
    }

    async fn revalidate_prepared_attachment(
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
        let prepared = input.turn_store.get::<PreparedFederatedAttachment>()?;
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
        let access = FederationConsumerAccess::new(
            self.federation.consumer_agent_id().clone(),
            workspace_digest(input.cwd),
        );
        let mut explanations = Vec::with_capacity(prepared.bindings.len());
        for binding in &prepared.bindings {
            let Ok(status) = self.federation.revalidate(&access, binding, now).await else {
                return None;
            };
            let FederatedRevalidationStatus::Current(explanation) = status else {
                return None;
            };
            if explanation.explanation.memory.verification != MemoryVerification::Verified
                || explanation.explanation.memory.lifecycle != MemoryLifecycleState::Active
                || secret_like(explanation.explanation.memory.content.as_bytes())
                || explanation
                    .explanation
                    .citations
                    .iter()
                    .any(|citation| secret_like(&citation.content))
            {
                return None;
            }
            explanations.push(*explanation);
        }
        let content = compile_explanations(&explanations)?;
        let content_sha256 = Sha256Digest::for_bytes(content.as_bytes());
        let source_binding_sha256 = federation_source_binding(
            input.thread_id,
            input.turn_id,
            input.cwd,
            &prepared.query_sha256,
            &prepared.bindings,
            &content_sha256,
        )?;
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
            source: FEDERATED_COGNITIVE_SOURCE,
            source_binding_sha256,
            content_sha256,
            content,
            claimed_token_count,
        })
    }
}

pub(crate) struct CombinedCognitiveEphemeralContributor {
    local: Arc<CognitiveExtension>,
    federated: Arc<FederatedCognitiveExtension>,
}

impl CombinedCognitiveEphemeralContributor {
    pub(crate) fn new(
        local: Arc<CognitiveExtension>,
        federated: Arc<FederatedCognitiveExtension>,
    ) -> Self {
        Self { local, federated }
    }
}

impl EphemeralModelInputContributor for CombinedCognitiveEphemeralContributor {
    fn is_active(&self, thread_store: &ExtensionData, turn_store: &ExtensionData) -> bool {
        self.local.has_prepared_attachment(thread_store, turn_store)
            || self
                .federated
                .has_prepared_attachment(thread_store, turn_store)
    }

    fn contribute<'a>(
        &'a self,
        input: EphemeralModelInputContext<'a>,
    ) -> ModelProviderPolicyFuture<'a, Option<EphemeralModelInputProposal>> {
        Box::pin(async move {
            let local = self.local.revalidate_prepared_attachment(&input).await;
            let federated = self.federated.revalidate_prepared_attachment(&input).await;
            let material = match (local, federated) {
                (Some(local), Some(federated)) => {
                    combine_cognitive_materials(&input, local, federated)
                }
                (Some(local), None) => Some(local),
                (None, Some(federated)) => Some(federated),
                (None, None) => None,
            };
            material
                .map(|material| material.into_proposal(&input))
                .transpose()
        })
    }
}

impl TurnInputContributor for FederatedCognitiveExtension {
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
            turn_store.remove::<PreparedFederatedAttachment>();
            if input.turn_id != turn_store.level_id() {
                return Vec::new();
            }
            let Some(thread_state) = thread_store.get::<HeptaMemoryThreadState>() else {
                return Vec::new();
            };
            if !thread_state.attachment_proposal_enabled {
                return Vec::new();
            }
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
            let Some(query) = capture.query else {
                return Vec::new();
            };
            if secret_like(query.as_bytes()) {
                return Vec::new();
            }
            let Some(now) = now_unix_seconds() else {
                return Vec::new();
            };
            let access = FederationConsumerAccess::new(
                self.federation.consumer_agent_id().clone(),
                workspace_digest(workspace.as_path()),
            );
            let Ok(batch) = self
                .federation
                .retrieve(&access, &RetrievalRequest::new(query, now))
                .await
            else {
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
            let Some(source_binding_sha256) = federation_source_binding(
                thread_store.level_id(),
                input.turn_id.as_str(),
                workspace.as_path(),
                &batch.query_sha256,
                &bindings,
                &content_sha256,
            ) else {
                return Vec::new();
            };
            let Ok(claimed_token_count) = u32::try_from(content.len()) else {
                return Vec::new();
            };
            turn_store.insert(PreparedFederatedAttachment {
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

impl EphemeralModelInputContributor for FederatedCognitiveExtension {
    fn is_active(&self, thread_store: &ExtensionData, turn_store: &ExtensionData) -> bool {
        thread_store
            .get::<HeptaMemoryThreadState>()
            .is_some_and(|state| state.attachment_proposal_enabled)
            && turn_store.get::<PreparedFederatedAttachment>().is_some()
    }

    fn contribute<'a>(
        &'a self,
        input: EphemeralModelInputContext<'a>,
    ) -> ModelProviderPolicyFuture<'a, Option<EphemeralModelInputProposal>> {
        Box::pin(async move {
            // Federation is optional context. A revoked/expired/corrupt owner
            // capability removes the whole proposal and never blocks the turn.
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
            let Some(prepared) = input.turn_store.get::<PreparedFederatedAttachment>() else {
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
            let access = FederationConsumerAccess::new(
                self.federation.consumer_agent_id().clone(),
                workspace_digest(input.cwd),
            );
            let mut explanations = Vec::with_capacity(prepared.bindings.len());
            for binding in &prepared.bindings {
                let Ok(status) = self.federation.revalidate(&access, binding, now).await else {
                    return Ok(None);
                };
                let FederatedRevalidationStatus::Current(explanation) = status else {
                    return Ok(None);
                };
                if explanation.explanation.memory.verification != MemoryVerification::Verified
                    || explanation.explanation.memory.lifecycle != MemoryLifecycleState::Active
                    || secret_like(explanation.explanation.memory.content.as_bytes())
                    || explanation
                        .explanation
                        .citations
                        .iter()
                        .any(|citation| secret_like(&citation.content))
                {
                    return Ok(None);
                }
                explanations.push(*explanation);
            }
            let Some(content) = compile_explanations(&explanations) else {
                return Ok(None);
            };
            let content_sha256 = Sha256Digest::for_bytes(content.as_bytes());
            let Some(source_binding_sha256) = federation_source_binding(
                input.thread_id,
                input.turn_id,
                input.cwd,
                &prepared.query_sha256,
                &prepared.bindings,
                &content_sha256,
            ) else {
                return Ok(None);
            };
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
                EphemeralModelInputSource::parse(FEDERATED_COGNITIVE_SOURCE)?,
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

#[derive(Serialize)]
struct FederatedAttachment<'a> {
    schema_version: u32,
    source: &'static str,
    memories: &'a [FederatedAttachmentMemory],
}

#[derive(Clone, Serialize)]
struct FederatedAttachmentMemory {
    source_agent_id: AgentId,
    capability_id: String,
    capability_generation: u64,
    capability_revision: u64,
    memory_id: String,
    revision: u64,
    content: String,
    content_sha256: String,
    citations: Vec<FederatedAttachmentCitation>,
}

#[derive(Clone, Serialize)]
struct FederatedAttachmentCitation {
    source_agent_id: AgentId,
    source_id: String,
    revision: u64,
    content_sha256: String,
}

fn combine_cognitive_materials(
    input: &EphemeralModelInputContext<'_>,
    local: CognitiveProposalMaterial,
    federated: CognitiveProposalMaterial,
) -> Option<CognitiveProposalMaterial> {
    let local_value = serde_json::from_str::<Value>(&local.content).ok()?;
    let federated_value = serde_json::from_str::<Value>(&federated.content).ok()?;
    let local_memory = compact_local_memory(local_value.get("memories")?.as_array()?.first()?)?;
    let federated_memory =
        compact_federated_memory(federated_value.get("memories")?.as_array()?.first()?)?;
    let content = serde_json::to_string(&json!({
        "s": "verified_cognitive_v1",
        "m": [local_memory, federated_memory],
    }))
    .ok()?;
    let claimed_token_count = u32::try_from(content.len()).ok()?;
    let thread_state = input.thread_store.get::<HeptaMemoryThreadState>()?;
    let model_context_window = input
        .model_context_window
        .and_then(|value| u64::try_from(value).ok())?;
    let context_budget = model_context_window
        .saturating_mul(u64::from(thread_state.limits.max_context_window_ppm()))
        / 1_000_000;
    if content.len() > input.max_content_bytes as usize
        || claimed_token_count > input.max_content_tokens
        || u64::from(claimed_token_count) > context_budget
    {
        return Some(local);
    }
    let content_sha256 = Sha256Digest::for_bytes(content.as_bytes());
    let source_binding_sha256 = digest_many(
        b"hepta:cognitive:combined-ephemeral-source-binding:v1",
        &[
            input.thread_id.as_bytes(),
            input.turn_id.as_bytes(),
            path_identity_bytes(input.cwd).as_slice(),
            local.source_binding_sha256.as_str().as_bytes(),
            local.content_sha256.as_str().as_bytes(),
            federated.source_binding_sha256.as_str().as_bytes(),
            federated.content_sha256.as_str().as_bytes(),
            content_sha256.as_str().as_bytes(),
        ],
    );
    Some(CognitiveProposalMaterial {
        source: COMBINED_COGNITIVE_SOURCE,
        source_binding_sha256,
        content_sha256,
        content,
        claimed_token_count,
    })
}

fn compact_local_memory(memory: &Value) -> Option<Value> {
    let citations = memory
        .get("citations")?
        .as_array()?
        .iter()
        .take(MAX_COMBINED_CITATIONS_PER_MEMORY)
        .map(compact_local_citation)
        .collect::<Option<Vec<_>>>()?;
    Some(json!({
        "m": memory.get("memory_id")?,
        "r": memory.get("revision")?,
        "c": memory.get("content")?,
        "h": memory.get("content_sha256")?,
        "q": citations,
    }))
}

fn compact_federated_memory(memory: &Value) -> Option<Value> {
    let citations = memory
        .get("citations")?
        .as_array()?
        .iter()
        .take(MAX_COMBINED_CITATIONS_PER_MEMORY)
        .map(compact_federated_citation)
        .collect::<Option<Vec<_>>>()?;
    Some(json!({
        "a": memory.get("source_agent_id")?,
        "p": memory.get("capability_id")?,
        "g": memory.get("capability_generation")?,
        "v": memory.get("capability_revision")?,
        "m": memory.get("memory_id")?,
        "r": memory.get("revision")?,
        "c": memory.get("content")?,
        "h": memory.get("content_sha256")?,
        "q": citations,
    }))
}

fn compact_local_citation(citation: &Value) -> Option<Value> {
    Some(json!({
        "s": citation.get("source_id")?,
        "r": citation.get("revision")?,
        "h": citation.get("content_sha256")?,
    }))
}

fn compact_federated_citation(citation: &Value) -> Option<Value> {
    Some(json!({
        "s": citation.get("source_id")?,
        "r": citation.get("revision")?,
        "h": citation.get("content_sha256")?,
    }))
}

fn compile_retrieval_batch(
    batch: &FederatedRetrievalBatch,
    max_bytes: usize,
    max_item_bytes: usize,
) -> Option<(Vec<FederatedMemoryRevalidationBinding>, String)> {
    let max_bytes = max_bytes
        .min(EPHEMERAL_MODEL_INPUT_MAX_CONTENT_BYTES as usize)
        .min(EPHEMERAL_MODEL_INPUT_MAX_CONTENT_TOKENS as usize);
    let mut selected_bindings = Vec::new();
    let mut selected_memories = Vec::new();
    for candidate in &batch.candidates {
        let memory = &candidate.candidate.memory;
        if memory.verification != MemoryVerification::Verified
            || memory.lifecycle != MemoryLifecycleState::Active
            || memory.content.len() > max_item_bytes
            || secret_like(memory.content.as_bytes())
        {
            continue;
        }
        let record = attachment_record(
            &candidate.source_agent_id,
            &candidate.revalidation,
            &candidate.candidate.memory,
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
        selected_bindings.push(candidate.revalidation.clone());
    }
    if selected_bindings.is_empty() {
        return None;
    }
    let content = serialize_attachment(&selected_memories).ok()?;
    Some((selected_bindings, content))
}

fn compile_explanations(explanations: &[FederatedMemoryExplanation]) -> Option<String> {
    let memories = explanations
        .iter()
        .map(|explanation| {
            let binding = FederatedMemoryRevalidationBinding {
                source_agent_id: explanation.source_agent_id.clone(),
                capability: explanation.capability.clone(),
                memory: codex_hepta_memory::MemoryRevalidationBinding {
                    memory: explanation.explanation.memory.id.clone(),
                    scope: explanation.explanation.memory.scope.clone(),
                    content_sha256: explanation.explanation.memory.content_sha256.clone(),
                    verification: explanation.explanation.memory.verification,
                    lifecycle: explanation.explanation.memory.lifecycle.clone(),
                    valid_from_unix_seconds: explanation.explanation.memory.valid_from_unix_seconds,
                    valid_to_unix_seconds: explanation.explanation.memory.valid_to_unix_seconds,
                    citations: explanation
                        .explanation
                        .citations
                        .iter()
                        .map(|citation| codex_hepta_memory::SourceRevalidationBinding {
                            id: citation.id.clone(),
                            scope: citation.scope.clone(),
                            content_sha256: citation.content_sha256.clone(),
                        })
                        .collect(),
                    kg_projection_generation: explanation.explanation.kg_projection_generation,
                },
            };
            attachment_record(
                &explanation.source_agent_id,
                &binding,
                &explanation.explanation.memory,
            )
        })
        .collect::<Vec<_>>();
    serialize_attachment(&memories).ok()
}

fn attachment_record(
    source_agent_id: &AgentId,
    binding: &FederatedMemoryRevalidationBinding,
    memory: &codex_hepta_memory::MemoryRevisionRecord,
) -> FederatedAttachmentMemory {
    FederatedAttachmentMemory {
        source_agent_id: source_agent_id.clone(),
        capability_id: binding.capability.id().as_str().to_string(),
        capability_generation: binding.capability.generation(),
        capability_revision: binding.capability.revision(),
        memory_id: memory.id.memory_id.as_str().to_string(),
        revision: memory.id.revision,
        content: memory.content.clone(),
        content_sha256: memory.content_sha256.as_str().to_string(),
        citations: binding
            .memory
            .citations
            .iter()
            .take(MAX_AUTO_CITATIONS_PER_MEMORY)
            .map(|citation| FederatedAttachmentCitation {
                source_agent_id: source_agent_id.clone(),
                source_id: citation.id.source_id.as_str().to_string(),
                revision: citation.id.revision,
                content_sha256: citation.content_sha256.as_str().to_string(),
            })
            .collect(),
    }
}

fn serialize_attachment(
    memories: &[FederatedAttachmentMemory],
) -> Result<String, serde_json::Error> {
    serde_json::to_string(&FederatedAttachment {
        schema_version: FEDERATED_ATTACHMENT_SCHEMA_VERSION,
        source: "explicit_federated_verified_memory",
        memories,
    })
}

fn federation_source_binding(
    thread_id: &str,
    turn_id: &str,
    workspace: &Path,
    query_sha256: &Sha256Digest,
    bindings: &[FederatedMemoryRevalidationBinding],
    content_sha256: &Sha256Digest,
) -> Option<Sha256Digest> {
    let serialized = serde_json::to_vec(bindings).ok()?;
    Some(digest_many(
        b"hepta:cognitive:federated-ephemeral-source-binding:v1",
        &[
            thread_id.as_bytes(),
            turn_id.as_bytes(),
            path_identity_bytes(workspace).as_slice(),
            query_sha256.as_str().as_bytes(),
            serialized.as_slice(),
            content_sha256.as_str().as_bytes(),
        ],
    ))
}

fn api_digest(
    digest: &Sha256Digest,
) -> Result<ModelProviderSha256Digest, ModelProviderPolicyError> {
    ModelProviderSha256Digest::parse(digest.as_str())
}

#[cfg(test)]
mod tests {
    use codex_extension_api::EPHEMERAL_MODEL_INPUT_MAX_CONTENT_BYTES;
    use codex_extension_api::EPHEMERAL_MODEL_INPUT_MAX_CONTENT_TOKENS;
    use codex_extension_api::EPHEMERAL_MODEL_INPUT_SCHEMA_VERSION;
    use codex_extension_api::EphemeralModelInputContext;
    use codex_extension_api::EphemeralModelInputContributor;
    use codex_extension_api::ExtensionData;
    use codex_extension_api::ModelProviderRequestKind;
    use codex_extension_api::ModelProviderSha256Digest;
    use codex_extension_api::ModelProviderTransport;
    use codex_extension_api::TurnInputContributor;
    use codex_extension_api::TurnInputEnvironment;
    use codex_hepta_contracts::AgentId;
    use codex_hepta_contracts::Sha256Digest;
    use codex_hepta_memory::CognitiveAccess;
    use codex_hepta_memory::CognitiveScope;
    use codex_hepta_memory::CognitiveStore;
    use codex_hepta_memory::FederatedMemoryReader;
    use codex_hepta_memory::FederatedRecallSet;
    use codex_hepta_memory::FederationGrantRequest;
    use codex_hepta_memory::FederationGrantScope;
    use codex_hepta_memory::LedgerSourceKind;
    use codex_hepta_memory::MemoryDraft;
    use codex_hepta_memory::MemoryLifecycleState;
    use codex_hepta_memory::MemoryRevisionDraft;
    use codex_hepta_memory::MemoryVerification;
    use codex_hepta_memory::SourceDraft;
    use codex_hepta_paths::HeptaFleetRoot;
    use codex_protocol::user_input::UserInput;
    use codex_utils_path_uri::PathUri;

    use super::COMBINED_COGNITIVE_SOURCE;
    use super::FEDERATED_COGNITIVE_SOURCE;
    use super::FederatedCognitiveExtension;
    use super::combine_cognitive_materials;
    use super::now_unix_seconds;
    use crate::cognitive::CognitiveProposalMaterial;
    use crate::extension::HeptaMemoryThreadState;
    use crate::framing::workspace_digest;

    const THREAD_ID: &str = "00000000-0000-4000-8000-000000000711";
    const OWNER_ID: &str = "00000000-0000-4000-8000-000000000712";
    const CONSUMER_ID: &str = "00000000-0000-4000-8000-000000000713";

    #[test]
    fn combined_proposal_is_exact_bounded_and_owner_capability_sensitive() {
        let temp = tempfile::tempdir().expect("tempdir");
        let workspace = temp.path().canonicalize().expect("workspace");
        let session_store = ExtensionData::new("combined-session");
        let thread_store = ExtensionData::new(THREAD_ID);
        thread_store.insert(HeptaMemoryThreadState::for_cognitive_test(true));
        let turn_store = ExtensionData::new("combined-turn");
        let base_logical_request_sha256 =
            ModelProviderSha256Digest::parse("11".repeat(32)).expect("base digest");
        let input = EphemeralModelInputContext {
            schema_version: EPHEMERAL_MODEL_INPUT_SCHEMA_VERSION,
            session_store: &session_store,
            thread_store: &thread_store,
            turn_store: &turn_store,
            attempt_id: "combined-attempt",
            base_logical_request_sha256: &base_logical_request_sha256,
            thread_id: thread_store.level_id(),
            turn_id: turn_store.level_id(),
            cwd: &workspace,
            request_kind: ModelProviderRequestKind::Turn,
            provider_id: "provider",
            model: "model",
            transport: ModelProviderTransport::Http,
            generate: true,
            model_context_window: Some(100_000),
            max_content_bytes: EPHEMERAL_MODEL_INPUT_MAX_CONTENT_BYTES,
            max_content_tokens: EPHEMERAL_MODEL_INPUT_MAX_CONTENT_TOKENS,
        };

        let mut boundary = None;
        for padding in 0..=700 {
            let combined = combine_cognitive_materials(
                &input,
                local_material(padding),
                federated_material(
                    OWNER_ID,
                    "federation:v1:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    padding,
                ),
            )
            .expect("combined material");
            if combined.source == COMBINED_COGNITIVE_SOURCE {
                boundary = Some((padding, combined));
            }
        }
        let (padding, boundary) = boundary.expect("at least one combined proposal fits");
        assert!(EPHEMERAL_MODEL_INPUT_MAX_CONTENT_BYTES as usize - boundary.content.len() <= 2);
        assert!(boundary.content.len() <= EPHEMERAL_MODEL_INPUT_MAX_CONTENT_BYTES as usize);
        assert_eq!(
            boundary.claimed_token_count as usize,
            boundary.content.len()
        );
        assert_eq!(
            boundary.content_sha256,
            Sha256Digest::for_bytes(boundary.content.as_bytes())
        );
        let payload =
            serde_json::from_str::<serde_json::Value>(&boundary.content).expect("combined payload");
        let memories = payload["m"].as_array().expect("combined memories");
        assert_eq!(memories.len(), 2);
        assert_eq!(memories[0]["h"], "22".repeat(32));
        assert_eq!(
            memories[0]["q"].as_array().expect("local citations").len(),
            1
        );
        assert_eq!(memories[0]["q"][0]["h"], "33".repeat(32));
        assert_eq!(memories[1]["h"], "44".repeat(32));
        assert_eq!(
            memories[1]["q"]
                .as_array()
                .expect("federated citations")
                .len(),
            1
        );
        assert_eq!(memories[1]["q"][0]["h"], "55".repeat(32));

        let changed = combine_cognitive_materials(
            &input,
            local_material(padding),
            federated_material(
                "00000000-0000-4000-8000-000000000799",
                "federation:v1:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                padding,
            ),
        )
        .expect("changed combined material");
        assert_eq!(changed.source, COMBINED_COGNITIVE_SOURCE);
        assert_ne!(
            changed.source_binding_sha256,
            boundary.source_binding_sha256
        );
        assert!(
            changed
                .content
                .contains("00000000-0000-4000-8000-000000000799")
        );
        assert!(changed.content.contains("federation:v1:bbbb"));
    }

    fn local_material(padding: usize) -> CognitiveProposalMaterial {
        let content = serde_json::to_string(&serde_json::json!({
            "schema_version": 1,
            "source": "verified_versioned_memory",
            "memories": [{
                "memory_id": "00000000-0000-4000-8000-000000000701",
                "revision": 7,
                "content": "l".repeat(padding),
                "content_sha256": "22".repeat(32),
                "citations": [{
                    "source_id": "00000000-0000-4000-8000-000000000702",
                    "revision": 3,
                    "content_sha256": "33".repeat(32),
                }, {
                    "source_id": "00000000-0000-4000-8000-000000000705",
                    "revision": 2,
                    "content_sha256": "66".repeat(32),
                }],
            }],
        }))
        .expect("local content");
        CognitiveProposalMaterial {
            source: "hepta_cognitive_plane_v1",
            source_binding_sha256: Sha256Digest::for_bytes(b"local-binding"),
            content_sha256: Sha256Digest::for_bytes(content.as_bytes()),
            claimed_token_count: u32::try_from(content.len()).expect("local length"),
            content,
        }
    }

    fn federated_material(
        owner_agent_id: &str,
        capability_id: &str,
        padding: usize,
    ) -> CognitiveProposalMaterial {
        let content = serde_json::to_string(&serde_json::json!({
            "schema_version": 1,
            "source": "explicit_federated_verified_memory",
            "memories": [{
                "source_agent_id": owner_agent_id,
                "capability_id": capability_id,
                "capability_generation": 11,
                "capability_revision": 12,
                "memory_id": "00000000-0000-4000-8000-000000000703",
                "revision": 9,
                "content": "f".repeat(padding),
                "content_sha256": "44".repeat(32),
                "citations": [{
                    "source_agent_id": owner_agent_id,
                    "source_id": "00000000-0000-4000-8000-000000000704",
                    "revision": 4,
                    "content_sha256": "55".repeat(32),
                }, {
                    "source_agent_id": owner_agent_id,
                    "source_id": "00000000-0000-4000-8000-000000000706",
                    "revision": 1,
                    "content_sha256": "77".repeat(32),
                }],
            }],
        }))
        .expect("federated content");
        CognitiveProposalMaterial {
            source: FEDERATED_COGNITIVE_SOURCE,
            source_binding_sha256: Sha256Digest::for_bytes(
                format!("federated-binding:{owner_agent_id}:{capability_id}").as_bytes(),
            ),
            content_sha256: Sha256Digest::for_bytes(content.as_bytes()),
            claimed_token_count: u32::try_from(content.len()).expect("federated length"),
            content,
        }
    }

    #[tokio::test]
    async fn revoke_removes_prepared_federated_context_from_next_physical_send() {
        let temp = tempfile::tempdir().expect("tempdir");
        let fleet_root = temp.path().join("fleet");
        std::fs::create_dir_all(&fleet_root).expect("fleet root");
        let fleet = HeptaFleetRoot::parse(fleet_root).expect("fleet").layout();
        let owner_id = AgentId::parse(OWNER_ID).expect("owner id");
        let consumer_id = AgentId::parse(CONSUMER_ID).expect("consumer id");
        let owner_layout = fleet.agent(&owner_id);
        let owner = CognitiveStore::open(&owner_layout)
            .await
            .expect("owner store");
        let owner_access = CognitiveAccess::agent_private(owner_id.clone());
        let now = now_unix_seconds().expect("time");
        let citation = owner
            .append_source(
                &owner_access,
                &SourceDraft {
                    scope: CognitiveScope::AgentPrivate,
                    kind: LedgerSourceKind::ExplicitMemoryDirective,
                    event_key: "federated-physical-send-source".to_string(),
                    content: b"federated physical send must revalidate".to_vec(),
                    observed_at_unix_seconds: now,
                },
            )
            .await
            .expect("source");
        owner
            .remember_memory(
                &owner_access,
                &MemoryDraft {
                    stable_key: "federated-physical-send-memory".to_string(),
                    revision: MemoryRevisionDraft {
                        scope: CognitiveScope::AgentPrivate,
                        content: "federated physical send must revalidate".to_string(),
                        verification: MemoryVerification::Verified,
                        lifecycle: MemoryLifecycleState::Active,
                        valid_from_unix_seconds: now - 1,
                        valid_to_unix_seconds: None,
                        citations: vec![citation],
                    },
                },
            )
            .await
            .expect("memory");
        let workspace = temp.path().join("consumer-workspace");
        std::fs::create_dir_all(&workspace).expect("consumer workspace");
        let workspace = workspace.canonicalize().expect("canonical workspace");
        let capability = owner
            .grant_federated_recall(
                &owner_access,
                &FederationGrantRequest {
                    consumer_agent_id: consumer_id.clone(),
                    scope: FederationGrantScope::new(
                        CognitiveScope::AgentPrivate,
                        workspace_digest(&workspace),
                    ),
                    effective_at_unix_seconds: now - 1,
                    expires_at_unix_seconds: now + 3_600,
                },
            )
            .await
            .expect("grant");
        let readers = FederatedMemoryReader::discover(&owner_layout, &consumer_id, now)
            .await
            .expect("discover");
        let extension = FederatedCognitiveExtension::new(std::sync::Arc::new(
            FederatedRecallSet::new(consumer_id, readers).expect("recall set"),
        ));
        let session_store = ExtensionData::new("session-federation");
        let thread_store = ExtensionData::new(THREAD_ID);
        thread_store.insert(HeptaMemoryThreadState::for_cognitive_test(true));
        let turn_store = ExtensionData::new("turn-federation-revoke");
        let step_store = ExtensionData::new(turn_store.level_id());
        let fragments = TurnInputContributor::contribute(
            &extension,
            codex_extension_api::TurnInputContext {
                turn_id: turn_store.level_id().to_string(),
                user_input: vec![UserInput::Text {
                    text: "federated physical send".to_string(),
                    text_elements: Vec::new(),
                }],
                environments: vec![TurnInputEnvironment {
                    environment_id: "primary".to_string(),
                    cwd: PathUri::from_host_native_path(&workspace).expect("workspace uri"),
                    is_primary: true,
                }],
            },
            None,
            &session_store,
            &thread_store,
            &turn_store,
            &step_store,
        )
        .await;
        assert!(fragments.is_empty());
        assert!(EphemeralModelInputContributor::is_active(
            &extension,
            &thread_store,
            &turn_store,
        ));
        let base = ModelProviderSha256Digest::parse("2".repeat(64)).expect("base digest");
        let input = |attempt_id| EphemeralModelInputContext {
            schema_version: EPHEMERAL_MODEL_INPUT_SCHEMA_VERSION,
            session_store: &session_store,
            thread_store: &thread_store,
            turn_store: &turn_store,
            attempt_id,
            base_logical_request_sha256: &base,
            thread_id: THREAD_ID,
            turn_id: turn_store.level_id(),
            cwd: &workspace,
            request_kind: ModelProviderRequestKind::Turn,
            provider_id: "provider-federation",
            model: "model-federation",
            transport: ModelProviderTransport::Http,
            generate: true,
            model_context_window: Some(128_000),
            max_content_bytes: EPHEMERAL_MODEL_INPUT_MAX_CONTENT_BYTES,
            max_content_tokens: EPHEMERAL_MODEL_INPUT_MAX_CONTENT_TOKENS,
        };
        let first = EphemeralModelInputContributor::contribute(
            &extension,
            input("model-provider-attempt:v1:before-revoke"),
        )
        .await
        .expect("contributor")
        .expect("proposal before revoke");
        assert_eq!(first.source().as_str(), FEDERATED_COGNITIVE_SOURCE);
        assert!(first.into_content().contains(OWNER_ID));

        owner
            .revoke_federated_recall(&owner_access, &capability, now)
            .await
            .expect("revoke");
        let next = EphemeralModelInputContributor::contribute(
            &extension,
            input("model-provider-attempt:v1:after-revoke"),
        )
        .await
        .expect("fail-open contributor");
        assert!(next.is_none());
    }
}
