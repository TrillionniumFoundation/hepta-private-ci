//! Signed, file-backed current HNMF retrieval context for the ordinary Agentd binary.
//!
//! The file is an externally published current-view artifact. Agentd verifies
//! the configured signer, exact Agent/body generation, validity window and
//! monotonic context/authority epochs every time the context is used. It never
//! edits the file, manufactures an engram or silently falls back to an older
//! generation.

use std::io::Read;
use std::path::Path;
use std::path::PathBuf;
use std::str::FromStr;
use std::sync::Mutex;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_memory::RetrievalExecutionContextV1;
use codex_hepta_memory_retrieval::EngramDynamicsPolicyV1;
use codex_hepta_memory_retrieval::EngramNodeV1;
use codex_hepta_memory_retrieval::EngramPopulationV1;
use codex_hepta_memory_retrieval::EngramSnapshotV1;
use codex_hepta_memory_retrieval::EngramSupportV1;
use codex_hepta_memory_retrieval::RetrievalChannelV1;
use codex_hepta_memory_retrieval::RetrievalChannelWeightV1;
use codex_hepta_memory_retrieval::RetrievalPolicyV1;
use codex_hepta_memory_retrieval::SynapseRelationV1;
use codex_hepta_memory_retrieval::SynapseV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::Verifier;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;

use crate::CurrentMemoryRetrievalContext;

const FILE_SCHEMA_VERSION: u32 = 1;
const MAX_CONTEXT_FILE_BYTES: u64 = 4 * 1024 * 1024;
const MAX_CONTEXT_VALIDITY_MS: u64 = 300_000;
const SIGNING_DOMAIN: &str = "hepta.agentd.memory-retrieval-context.v1";

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RetrievalGenerationVectorFileV1 {
    pub scope_id: String,
    pub purpose_id: String,
    pub memory_ledger_frontier: u64,
    pub knowledge_fact_frontier: u64,
    pub tombstone_frontier: u64,
    pub source_ledger_frontier: u64,
    pub knowledge_graph_generation: u64,
    pub compact_checkpoint_generation: u64,
    pub prompt_registry_revision: u64,
    pub retrieval_profile_digest: String,
    pub encoder_preprocessor_digest: String,
    pub authority_epoch: u64,
    pub model_digest: String,
    pub tokenizer_digest: String,
    pub template_digest: String,
    pub tool_schema_digest: String,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RetrievalChannelFileV1 {
    Lexical,
    Vector,
    Entity,
    Temporal,
    Causal,
    Procedural,
    ContradictionSupport,
    Graph,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RetrievalChannelWeightFileV1 {
    pub channel: RetrievalChannelFileV1,
    pub weight_raw_q32: i64,
    pub maximum_candidates: u32,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RetrievalPolicyFileV1 {
    pub policy_id: String,
    pub channel_weights: Vec<RetrievalChannelWeightFileV1>,
    pub maximum_results: u32,
    pub minimum_total_score_raw_q32: i64,
    pub maximum_ood_raw_q32: u64,
    pub minimum_distinct_channels: u32,
    pub abstain_on_contradiction: bool,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EngramPopulationFileV1 {
    SensoryTrace,
    EpisodicBinding,
    SemanticConcept,
    ProceduralSkill,
    PredictiveWorld,
    UtilitySalience,
    MetaMemory,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SynapseRelationFileV1 {
    Associative,
    Temporal,
    Causal,
    Procedural,
    Predictive,
    Supports,
    Inhibitory,
    Contradicts,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EngramSupportFileV1 {
    pub record_id: String,
    pub record_revision: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EngramNodeFileV1 {
    pub node_id: String,
    pub population: EngramPopulationFileV1,
    pub support: Vec<EngramSupportFileV1>,
    pub threshold_raw_q32: i64,
    pub confidence_raw_q32: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SynapseFileV1 {
    pub source_node_id: String,
    pub target_node_id: String,
    pub relation: SynapseRelationFileV1,
    pub weight_raw_q32: i64,
    pub support_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EngramSnapshotFileV1 {
    pub engram_generation_digest: String,
    pub nodes: Vec<EngramNodeFileV1>,
    pub synapses: Vec<SynapseFileV1>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EngramDynamicsPolicyFileV1 {
    pub policy_id: String,
    pub maximum_nodes: u32,
    pub maximum_synapses: u32,
    pub maximum_active_per_population: u32,
    pub maximum_active_nodes: u32,
    pub maximum_settling_steps: u8,
    pub maximum_graph_hops: u8,
    pub maximum_activation_paths: u32,
    pub leak_raw_q32: i64,
    pub lateral_inhibition_raw_q32: i64,
    pub minimum_activation_raw_q32: i64,
    pub contradiction_forces_abstention: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SignedMemoryRetrievalContextFileV1 {
    pub schema_version: u32,
    pub agent_id: String,
    pub body_generation: u64,
    pub context_revision: u64,
    pub authority_epoch: u64,
    pub issued_at_unix_ms: u64,
    pub expires_at_unix_ms: u64,
    pub revoked: bool,
    pub objective_digest: String,
    pub approved_context_digest: String,
    pub cue_profile_digest: String,
    pub generation_vector: RetrievalGenerationVectorFileV1,
    pub retrieval_policy: RetrievalPolicyFileV1,
    pub engram_snapshot: EngramSnapshotFileV1,
    pub dynamics_policy: EngramDynamicsPolicyFileV1,
    pub signer_id: String,
    pub signature: Vec<u8>,
}

#[derive(Serialize)]
struct MemoryRetrievalContextSigningPayloadV1<'a> {
    domain: &'static str,
    schema_version: u32,
    agent_id: &'a str,
    body_generation: u64,
    context_revision: u64,
    authority_epoch: u64,
    issued_at_unix_ms: u64,
    expires_at_unix_ms: u64,
    revoked: bool,
    objective_digest: &'a str,
    approved_context_digest: &'a str,
    cue_profile_digest: &'a str,
    generation_vector: &'a RetrievalGenerationVectorFileV1,
    retrieval_policy: &'a RetrievalPolicyFileV1,
    engram_snapshot: &'a EngramSnapshotFileV1,
    dynamics_policy: &'a EngramDynamicsPolicyFileV1,
    signer_id: &'a str,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryRetrievalContextVerifierV1 {
    pub signer_id: String,
    pub verifying_key: [u8; 32],
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct AcceptedFrontierV1 {
    context_revision: u64,
    authority_epoch: u64,
    context_digest: Digest32,
    signed_payload_digest: Digest32,
}

pub struct FileCurrentMemoryRetrievalContextV1 {
    path: PathBuf,
    owner: AgentId,
    body_generation: u64,
    owner_root: PathBuf,
    verifier: MemoryRetrievalContextVerifierV1,
    accepted: Mutex<Option<AcceptedFrontierV1>>,
}

impl FileCurrentMemoryRetrievalContextV1 {
    pub fn new(
        path: PathBuf,
        owner: AgentId,
        body_generation: u64,
        owner_root: PathBuf,
        verifier: MemoryRetrievalContextVerifierV1,
    ) -> Result<Self, String> {
        if body_generation == 0 || verifier.signer_id.is_empty() {
            return Err(
                "retrieval context body generation and signer identity must be non-zero"
                    .to_string(),
            );
        }
        let value = Self {
            path,
            owner,
            body_generation,
            owner_root,
            verifier,
            accepted: Mutex::new(None),
        };
        value.current(&value.owner, value.body_generation)?;
        Ok(value)
    }

    fn load(
        &self,
    ) -> Result<
        (
            SignedMemoryRetrievalContextFileV1,
            RetrievalExecutionContextV1,
            Digest32,
        ),
        String,
    > {
        let bytes = read_owner_file(&self.path, &self.owner_root)?;
        let file: SignedMemoryRetrievalContextFileV1 = serde_json::from_slice(&bytes)
            .map_err(|error| format!("invalid retrieval context JSON: {error}"))?;
        let signed_payload = memory_retrieval_context_signing_payload_v1(&file)?;
        self.verify_file(&file, &signed_payload)?;
        let context = decode_context(&file)?;
        context
            .validate()
            .map_err(|error| format!("invalid retrieval execution context: {error}"))?;
        Ok((file, context, Digest32::of_bytes(&signed_payload)))
    }

    fn verify_file(
        &self,
        file: &SignedMemoryRetrievalContextFileV1,
        signed_payload: &[u8],
    ) -> Result<(), String> {
        if file.schema_version != FILE_SCHEMA_VERSION
            || file.agent_id != self.owner.as_str()
            || file.body_generation != self.body_generation
            || file.context_revision == 0
            || file.authority_epoch == 0
            || file.revoked
            || file.signer_id != self.verifier.signer_id
            || file.signature.len() != 64
        {
            return Err(
                "retrieval context identity, schema, revision or revocation state is invalid"
                    .to_string(),
            );
        }
        let now = wall_clock_ms()?;
        let validity = file
            .expires_at_unix_ms
            .checked_sub(file.issued_at_unix_ms)
            .ok_or_else(|| "retrieval context validity window regressed".to_string())?;
        if file.issued_at_unix_ms == 0
            || validity == 0
            || validity > MAX_CONTEXT_VALIDITY_MS
            || now < file.issued_at_unix_ms
            || now >= file.expires_at_unix_ms
        {
            return Err("retrieval context validity window is not current".to_string());
        }
        if file.generation_vector.authority_epoch != file.authority_epoch {
            return Err(
                "retrieval context authority epoch differs from its generation vector".to_string(),
            );
        }
        let key = VerifyingKey::from_bytes(&self.verifier.verifying_key)
            .map_err(|_| "invalid retrieval context verifying key".to_string())?;
        let signature_bytes: [u8; 64] = file
            .signature
            .as_slice()
            .try_into()
            .map_err(|_| "invalid retrieval context signature length".to_string())?;
        key.verify(signed_payload, &Signature::from_bytes(&signature_bytes))
            .map_err(|_| "retrieval context signature verification failed".to_string())
    }

    fn advance_frontier(
        &self,
        file: &SignedMemoryRetrievalContextFileV1,
        context: &RetrievalExecutionContextV1,
        signed_payload_digest: Digest32,
    ) -> Result<(), String> {
        let next = AcceptedFrontierV1 {
            context_revision: file.context_revision,
            authority_epoch: file.authority_epoch,
            context_digest: context.binding_digest(),
            signed_payload_digest,
        };
        let mut accepted = self
            .accepted
            .lock()
            .map_err(|_| "retrieval context frontier lock poisoned".to_string())?;
        if let Some(previous) = *accepted
            && (next.context_revision < previous.context_revision
                || next.authority_epoch < previous.authority_epoch
                || (next.context_revision == previous.context_revision
                    && (next.authority_epoch != previous.authority_epoch
                        || next.context_digest != previous.context_digest
                        || next.signed_payload_digest != previous.signed_payload_digest)))
        {
            return Err("retrieval context regressed, forked or changed in place".to_string());
        }
        *accepted = Some(next);
        Ok(())
    }
}

impl CurrentMemoryRetrievalContext for FileCurrentMemoryRetrievalContextV1 {
    fn current(
        &self,
        owner: &AgentId,
        body_generation: u64,
    ) -> Result<RetrievalExecutionContextV1, String> {
        if owner != &self.owner || body_generation != self.body_generation {
            return Err("retrieval context requested for another Agent generation".to_string());
        }
        let (file, context, signed_payload_digest) = self.load()?;
        self.advance_frontier(&file, &context, signed_payload_digest)?;
        Ok(context)
    }
}

pub fn memory_retrieval_context_signing_payload_v1(
    file: &SignedMemoryRetrievalContextFileV1,
) -> Result<Vec<u8>, String> {
    serde_json::to_vec(&MemoryRetrievalContextSigningPayloadV1 {
        domain: SIGNING_DOMAIN,
        schema_version: file.schema_version,
        agent_id: &file.agent_id,
        body_generation: file.body_generation,
        context_revision: file.context_revision,
        authority_epoch: file.authority_epoch,
        issued_at_unix_ms: file.issued_at_unix_ms,
        expires_at_unix_ms: file.expires_at_unix_ms,
        revoked: file.revoked,
        objective_digest: &file.objective_digest,
        approved_context_digest: &file.approved_context_digest,
        cue_profile_digest: &file.cue_profile_digest,
        generation_vector: &file.generation_vector,
        retrieval_policy: &file.retrieval_policy,
        engram_snapshot: &file.engram_snapshot,
        dynamics_policy: &file.dynamics_policy,
        signer_id: &file.signer_id,
    })
    .map_err(|error| format!("retrieval context signing payload failed: {error}"))
}

fn decode_context(
    file: &SignedMemoryRetrievalContextFileV1,
) -> Result<RetrievalExecutionContextV1, String> {
    let vector = &file.generation_vector;
    let generation_vector = LaneCGenerationVectorV1 {
        scope_id: stable_id(&vector.scope_id, "scope_id")?,
        purpose_id: stable_id(&vector.purpose_id, "purpose_id")?,
        memory_ledger_frontier: vector.memory_ledger_frontier,
        knowledge_fact_frontier: vector.knowledge_fact_frontier,
        tombstone_frontier: vector.tombstone_frontier,
        source_ledger_frontier: vector.source_ledger_frontier,
        knowledge_graph_generation: Generation::new(vector.knowledge_graph_generation)
            .map_err(|error| format!("invalid knowledge_graph_generation: {error}"))?,
        compact_checkpoint_generation: Generation::new(vector.compact_checkpoint_generation)
            .map_err(|error| format!("invalid compact_checkpoint_generation: {error}"))?,
        prompt_registry_revision: Revision::new(vector.prompt_registry_revision)
            .map_err(|error| format!("invalid prompt_registry_revision: {error}"))?,
        retrieval_profile_digest: digest(
            &vector.retrieval_profile_digest,
            "retrieval_profile_digest",
        )?,
        encoder_preprocessor_digest: digest(
            &vector.encoder_preprocessor_digest,
            "encoder_preprocessor_digest",
        )?,
        authority_epoch: vector.authority_epoch,
        model_digest: digest(&vector.model_digest, "model_digest")?,
        tokenizer_digest: digest(&vector.tokenizer_digest, "tokenizer_digest")?,
        template_digest: digest(&vector.template_digest, "template_digest")?,
        tool_schema_digest: digest(&vector.tool_schema_digest, "tool_schema_digest")?,
    };
    let retrieval_policy = RetrievalPolicyV1 {
        policy_id: stable_id(&file.retrieval_policy.policy_id, "retrieval policy_id")?,
        channel_weights: file
            .retrieval_policy
            .channel_weights
            .iter()
            .map(|row| RetrievalChannelWeightV1 {
                channel: row.channel.into(),
                weight: FixedQ32::from_raw(row.weight_raw_q32),
                maximum_candidates: row.maximum_candidates,
            })
            .collect(),
        maximum_results: file.retrieval_policy.maximum_results,
        minimum_total_score: FixedQ32::from_raw(file.retrieval_policy.minimum_total_score_raw_q32),
        maximum_ood: ProbabilityQ32::from_raw(file.retrieval_policy.maximum_ood_raw_q32)
            .map_err(|error| format!("invalid maximum_ood_raw_q32: {error}"))?,
        minimum_distinct_channels: file.retrieval_policy.minimum_distinct_channels,
        abstain_on_contradiction: file.retrieval_policy.abstain_on_contradiction,
    };
    let generation_vector_digest = generation_vector.digest();
    let nodes = file
        .engram_snapshot
        .nodes
        .iter()
        .map(|node| {
            Ok(EngramNodeV1 {
                node_id: stable_id(&node.node_id, "engram node_id")?,
                population: node.population.into(),
                support: node
                    .support
                    .iter()
                    .map(|support| {
                        Ok(EngramSupportV1 {
                            record_id: stable_id(&support.record_id, "engram support record_id")?,
                            record_revision: Revision::new(support.record_revision).map_err(
                                |error| format!("invalid engram support revision: {error}"),
                            )?,
                        })
                    })
                    .collect::<Result<Vec<_>, String>>()?,
                threshold: FixedQ32::from_raw(node.threshold_raw_q32),
                confidence: ProbabilityQ32::from_raw(node.confidence_raw_q32)
                    .map_err(|error| format!("invalid engram confidence: {error}"))?,
                generation_vector_digest,
            })
        })
        .collect::<Result<Vec<_>, String>>()?;
    let synapses = file
        .engram_snapshot
        .synapses
        .iter()
        .map(|synapse| {
            Ok(SynapseV1 {
                source_node_id: stable_id(&synapse.source_node_id, "synapse source_node_id")?,
                target_node_id: stable_id(&synapse.target_node_id, "synapse target_node_id")?,
                relation: synapse.relation.into(),
                weight: FixedQ32::from_raw(synapse.weight_raw_q32),
                support_digest: digest(&synapse.support_digest, "synapse support_digest")?,
                generation_vector_digest,
            })
        })
        .collect::<Result<Vec<_>, String>>()?;
    let engram_snapshot = EngramSnapshotV1::new(
        generation_vector_digest,
        digest(
            &file.engram_snapshot.engram_generation_digest,
            "engram_generation_digest",
        )?,
        nodes,
        synapses,
    )
    .map_err(|error| format!("invalid engram snapshot: {error}"))?;
    let dynamics = &file.dynamics_policy;
    let dynamics_policy = EngramDynamicsPolicyV1 {
        policy_id: stable_id(&dynamics.policy_id, "dynamics policy_id")?,
        maximum_nodes: dynamics.maximum_nodes,
        maximum_synapses: dynamics.maximum_synapses,
        maximum_active_per_population: dynamics.maximum_active_per_population,
        maximum_active_nodes: dynamics.maximum_active_nodes,
        maximum_settling_steps: dynamics.maximum_settling_steps,
        maximum_graph_hops: dynamics.maximum_graph_hops,
        maximum_activation_paths: dynamics.maximum_activation_paths,
        leak: FixedQ32::from_raw(dynamics.leak_raw_q32),
        lateral_inhibition: FixedQ32::from_raw(dynamics.lateral_inhibition_raw_q32),
        minimum_activation: FixedQ32::from_raw(dynamics.minimum_activation_raw_q32),
        contradiction_forces_abstention: dynamics.contradiction_forces_abstention,
    };
    Ok(RetrievalExecutionContextV1 {
        generation_vector,
        objective_digest: digest(&file.objective_digest, "objective_digest")?,
        approved_context_digest: digest(&file.approved_context_digest, "approved_context_digest")?,
        cue_profile_digest: digest(&file.cue_profile_digest, "cue_profile_digest")?,
        retrieval_policy,
        engram_snapshot,
        dynamics_policy,
    })
}

fn stable_id(value: &str, label: &str) -> Result<StableId, String> {
    StableId::new(value.to_string()).map_err(|error| format!("invalid {label}: {error}"))
}

fn digest(value: &str, label: &str) -> Result<Digest32, String> {
    let value = Digest32::from_str(value).map_err(|error| format!("invalid {label}: {error}"))?;
    if value.is_zero() {
        return Err(format!("invalid {label}: zero digest"));
    }
    Ok(value)
}

impl From<RetrievalChannelFileV1> for RetrievalChannelV1 {
    fn from(value: RetrievalChannelFileV1) -> Self {
        match value {
            RetrievalChannelFileV1::Lexical => Self::Lexical,
            RetrievalChannelFileV1::Vector => Self::Vector,
            RetrievalChannelFileV1::Entity => Self::Entity,
            RetrievalChannelFileV1::Temporal => Self::Temporal,
            RetrievalChannelFileV1::Causal => Self::Causal,
            RetrievalChannelFileV1::Procedural => Self::Procedural,
            RetrievalChannelFileV1::ContradictionSupport => Self::ContradictionSupport,
            RetrievalChannelFileV1::Graph => Self::Graph,
        }
    }
}

impl From<EngramPopulationFileV1> for EngramPopulationV1 {
    fn from(value: EngramPopulationFileV1) -> Self {
        match value {
            EngramPopulationFileV1::SensoryTrace => Self::SensoryTrace,
            EngramPopulationFileV1::EpisodicBinding => Self::EpisodicBinding,
            EngramPopulationFileV1::SemanticConcept => Self::SemanticConcept,
            EngramPopulationFileV1::ProceduralSkill => Self::ProceduralSkill,
            EngramPopulationFileV1::PredictiveWorld => Self::PredictiveWorld,
            EngramPopulationFileV1::UtilitySalience => Self::UtilitySalience,
            EngramPopulationFileV1::MetaMemory => Self::MetaMemory,
        }
    }
}

impl From<SynapseRelationFileV1> for SynapseRelationV1 {
    fn from(value: SynapseRelationFileV1) -> Self {
        match value {
            SynapseRelationFileV1::Associative => Self::Associative,
            SynapseRelationFileV1::Temporal => Self::Temporal,
            SynapseRelationFileV1::Causal => Self::Causal,
            SynapseRelationFileV1::Procedural => Self::Procedural,
            SynapseRelationFileV1::Predictive => Self::Predictive,
            SynapseRelationFileV1::Supports => Self::Supports,
            SynapseRelationFileV1::Inhibitory => Self::Inhibitory,
            SynapseRelationFileV1::Contradicts => Self::Contradicts,
        }
    }
}

#[cfg(unix)]
fn read_owner_file(path: &Path, owner_root: &Path) -> Result<Vec<u8>, String> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;

    if !path.is_absolute()
        || path.parent() != Some(owner_root)
        || owner_root
            .canonicalize()
            .map_err(|error| error.to_string())?
            != owner_root
    {
        return Err(
            "retrieval context file must be a direct child of the canonical owner root".to_string(),
        );
    }
    let root = std::fs::metadata(owner_root).map_err(|error| error.to_string())?;
    let before = std::fs::symlink_metadata(path).map_err(|error| error.to_string())?;
    if !root.is_dir()
        || root.mode() & 0o022 != 0
        || !before.is_file()
        || before.file_type().is_symlink()
        || before.nlink() != 1
        || before.uid() != root.uid()
        || before.mode() & 0o022 != 0
        || before.len() == 0
        || before.len() > MAX_CONTEXT_FILE_BYTES
    {
        return Err(
            "retrieval context file must be a bounded owner-controlled regular file".to_string(),
        );
    }
    let mut file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
        .open(path)
        .map_err(|error| error.to_string())?;
    let opened = file.metadata().map_err(|error| error.to_string())?;
    let identity = |metadata: &std::fs::Metadata| {
        (
            metadata.dev(),
            metadata.ino(),
            metadata.len(),
            metadata.mtime(),
            metadata.mtime_nsec(),
            metadata.ctime(),
            metadata.ctime_nsec(),
        )
    };
    if identity(&opened) != identity(&before) {
        return Err("retrieval context file changed while opening".to_string());
    }
    let mut bytes = Vec::new();
    file.by_ref()
        .take(MAX_CONTEXT_FILE_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|error| error.to_string())?;
    let after = std::fs::symlink_metadata(path).map_err(|error| error.to_string())?;
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_CONTEXT_FILE_BYTES
        || identity(&after) != identity(&before)
        || identity(&file.metadata().map_err(|error| error.to_string())?) != identity(&before)
    {
        return Err("retrieval context file changed while reading".to_string());
    }
    Ok(bytes)
}

#[cfg(not(unix))]
fn read_owner_file(path: &Path, owner_root: &Path) -> Result<Vec<u8>, String> {
    if !path.is_absolute() || path.parent() != Some(owner_root) {
        return Err("retrieval context file must be a direct child of the owner root".to_string());
    }
    let metadata = std::fs::metadata(path).map_err(|error| error.to_string())?;
    if !metadata.is_file() || metadata.len() == 0 || metadata.len() > MAX_CONTEXT_FILE_BYTES {
        return Err("retrieval context file must be a bounded regular file".to_string());
    }
    std::fs::read(path).map_err(|error| error.to_string())
}

fn wall_clock_ms() -> Result<u64, String> {
    let value = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| "retrieval context clock is before the Unix epoch".to_string())?
        .as_millis();
    u64::try_from(value).map_err(|_| "retrieval context clock overflow".to_string())
}

#[cfg(test)]
#[path = "cognitive_retrieval_context_file_tests.rs"]
mod tests;
