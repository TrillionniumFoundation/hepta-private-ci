use codex_hepta_memory_retrieval::EngramDynamicsPolicyV1;
use codex_hepta_memory_retrieval::RetrievalChannelV1;
use codex_hepta_memory_retrieval::RetrievalChannelWeightV1;
use codex_hepta_memory_retrieval::RetrievalPolicyV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::*;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const BODY_GENERATION: u64 = 7;

fn digest(label: &str) -> String {
    Digest32::of_bytes(label.as_bytes()).to_string()
}

fn now_ms() -> u64 {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("current time")
        .as_millis();
    u64::try_from(millis).expect("current time fits u64")
}

fn unsigned_file(revision: u64) -> SignedMemoryRetrievalContextFileV1 {
    let retrieval_policy = RetrievalPolicyV1 {
        policy_id: StableId::new("policy:test-memory-retrieval").expect("policy id"),
        channel_weights: vec![RetrievalChannelWeightV1 {
            channel: RetrievalChannelV1::Lexical,
            weight: FixedQ32::ONE,
            maximum_candidates: 32,
        }],
        maximum_results: 16,
        minimum_total_score: FixedQ32::ZERO,
        maximum_ood: ProbabilityQ32::ONE,
        minimum_distinct_channels: 1,
        abstain_on_contradiction: true,
    };
    retrieval_policy.validate().expect("retrieval policy");
    let dynamics = EngramDynamicsPolicyV1::product_default().expect("dynamics policy");
    let issued_at_unix_ms = now_ms().saturating_sub(1_000);
    SignedMemoryRetrievalContextFileV1 {
        schema_version: FILE_SCHEMA_VERSION,
        agent_id: AGENT_ID.to_string(),
        body_generation: BODY_GENERATION,
        context_revision: revision,
        authority_epoch: revision,
        issued_at_unix_ms,
        expires_at_unix_ms: issued_at_unix_ms + 60_000,
        revoked: false,
        objective_digest: digest("objective"),
        approved_context_digest: digest("approved-context"),
        cue_profile_digest: digest("cue-profile"),
        generation_vector: RetrievalGenerationVectorFileV1 {
            scope_id: "scope:test-memory-retrieval".to_string(),
            purpose_id: "purpose:test-memory-retrieval".to_string(),
            memory_ledger_frontier: 1,
            knowledge_fact_frontier: 1,
            tombstone_frontier: 0,
            source_ledger_frontier: 1,
            knowledge_graph_generation: 1,
            compact_checkpoint_generation: 1,
            prompt_registry_revision: 1,
            retrieval_profile_digest: retrieval_policy.digest().to_string(),
            encoder_preprocessor_digest: digest("encoder-preprocessor"),
            authority_epoch: revision,
            model_digest: digest("model"),
            tokenizer_digest: digest("tokenizer"),
            template_digest: digest("template"),
            tool_schema_digest: digest("tool-schema"),
        },
        retrieval_policy: RetrievalPolicyFileV1 {
            policy_id: retrieval_policy.policy_id.as_str().to_string(),
            channel_weights: vec![RetrievalChannelWeightFileV1 {
                channel: RetrievalChannelFileV1::Lexical,
                weight_raw_q32: FixedQ32::ONE.raw(),
                maximum_candidates: 32,
            }],
            maximum_results: retrieval_policy.maximum_results,
            minimum_total_score_raw_q32: retrieval_policy.minimum_total_score.raw(),
            maximum_ood_raw_q32: retrieval_policy.maximum_ood.raw(),
            minimum_distinct_channels: retrieval_policy.minimum_distinct_channels,
            abstain_on_contradiction: retrieval_policy.abstain_on_contradiction,
        },
        engram_snapshot: EngramSnapshotFileV1 {
            engram_generation_digest: digest("engram-generation"),
            nodes: Vec::new(),
            synapses: Vec::new(),
        },
        dynamics_policy: EngramDynamicsPolicyFileV1 {
            policy_id: dynamics.policy_id.as_str().to_string(),
            maximum_nodes: dynamics.maximum_nodes,
            maximum_synapses: dynamics.maximum_synapses,
            maximum_active_per_population: dynamics.maximum_active_per_population,
            maximum_active_nodes: dynamics.maximum_active_nodes,
            maximum_settling_steps: dynamics.maximum_settling_steps,
            maximum_graph_hops: dynamics.maximum_graph_hops,
            maximum_activation_paths: dynamics.maximum_activation_paths,
            leak_raw_q32: dynamics.leak.raw(),
            lateral_inhibition_raw_q32: dynamics.lateral_inhibition.raw(),
            minimum_activation_raw_q32: dynamics.minimum_activation.raw(),
            contradiction_forces_abstention: dynamics.contradiction_forces_abstention,
        },
        signer_id: "signer:test-memory-retrieval".to_string(),
        signature: Vec::new(),
    }
}

fn sign(
    mut file: SignedMemoryRetrievalContextFileV1,
    key: &SigningKey,
) -> SignedMemoryRetrievalContextFileV1 {
    file.signature = key
        .sign(&memory_retrieval_context_signing_payload_v1(&file).expect("signing payload"))
        .to_bytes()
        .to_vec();
    file
}

fn write_file(path: &Path, file: &SignedMemoryRetrievalContextFileV1) {
    std::fs::write(path, serde_json::to_vec(file).expect("serialize context"))
        .expect("write context");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))
            .expect("protect context");
    }
}

// The production reader rejects group-writable owner roots. Tempfile uses
// the process umask unless explicit permissions are requested; a shared umask
// must not make signature/revocation tests fail before reaching that boundary.
fn private_owner_directory() -> tempfile::TempDir {
    let temp = tempfile::tempdir().expect("temporary owner root");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(temp.path(), std::fs::Permissions::from_mode(0o700))
            .expect("protect owner directory");
    }
    temp
}

fn provider(root: &Path, path: &Path, key: &SigningKey) -> FileCurrentMemoryRetrievalContextV1 {
    FileCurrentMemoryRetrievalContextV1::new(
        path.to_path_buf(),
        AgentId::parse(AGENT_ID).expect("agent id"),
        BODY_GENERATION,
        root.to_path_buf(),
        MemoryRetrievalContextVerifierV1 {
            signer_id: "signer:test-memory-retrieval".to_string(),
            verifying_key: key.verifying_key().to_bytes(),
        },
    )
    .expect("provider")
}

#[test]
fn signed_provider_reloads_and_rejects_revocation() {
    let temp = private_owner_directory();
    let root = temp.path().canonicalize().expect("canonical owner root");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700))
            .expect("protect owner root");
    }
    let path = root.join("memory-retrieval-context.json");
    let key = SigningKey::from_bytes(&[7_u8; 32]);
    write_file(&path, &sign(unsigned_file(1), &key));
    let provider = provider(&root, &path, &key);
    provider
        .current(
            &AgentId::parse(AGENT_ID).expect("agent id"),
            BODY_GENERATION,
        )
        .expect("current context");

    let mut revoked = unsigned_file(2);
    revoked.revoked = true;
    write_file(&path, &sign(revoked, &key));
    assert!(
        provider
            .current(
                &AgentId::parse(AGENT_ID).expect("agent id"),
                BODY_GENERATION,
            )
            .is_err()
    );
}

#[test]
fn signed_provider_rejects_rollback_and_same_revision_fork() {
    let temp = private_owner_directory();
    let root = temp.path().canonicalize().expect("canonical owner root");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700))
            .expect("protect owner root");
    }
    let path = root.join("memory-retrieval-context.json");
    let key = SigningKey::from_bytes(&[9_u8; 32]);
    write_file(&path, &sign(unsigned_file(1), &key));
    let provider = provider(&root, &path, &key);

    let revision_two = sign(unsigned_file(2), &key);
    write_file(&path, &revision_two);
    provider
        .current(
            &AgentId::parse(AGENT_ID).expect("agent id"),
            BODY_GENERATION,
        )
        .expect("advanced context");

    write_file(&path, &sign(unsigned_file(1), &key));
    assert!(
        provider
            .current(
                &AgentId::parse(AGENT_ID).expect("agent id"),
                BODY_GENERATION,
            )
            .is_err()
    );

    let mut fork = unsigned_file(2);
    fork.objective_digest = digest("forked-objective");
    write_file(&path, &sign(fork, &key));
    assert!(
        provider
            .current(
                &AgentId::parse(AGENT_ID).expect("agent id"),
                BODY_GENERATION,
            )
            .is_err()
    );
}

#[test]
fn signed_provider_rejects_wrong_generation_and_bad_signature() {
    let temp = private_owner_directory();
    let root = temp.path().canonicalize().expect("canonical owner root");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700))
            .expect("protect owner root");
    }
    let path = root.join("memory-retrieval-context.json");
    let key = SigningKey::from_bytes(&[11_u8; 32]);
    let mut wrong_generation = unsigned_file(1);
    wrong_generation.body_generation = BODY_GENERATION + 1;
    write_file(&path, &sign(wrong_generation, &key));
    assert!(
        FileCurrentMemoryRetrievalContextV1::new(
            path.clone(),
            AgentId::parse(AGENT_ID).expect("agent id"),
            BODY_GENERATION,
            root.clone(),
            MemoryRetrievalContextVerifierV1 {
                signer_id: "signer:test-memory-retrieval".to_string(),
                verifying_key: key.verifying_key().to_bytes(),
            },
        )
        .is_err()
    );

    let mut bad_signature = sign(unsigned_file(1), &key);
    bad_signature.signature[0] ^= 1;
    write_file(&path, &bad_signature);
    assert!(
        FileCurrentMemoryRetrievalContextV1::new(
            path,
            AgentId::parse(AGENT_ID).expect("agent id"),
            BODY_GENERATION,
            root,
            MemoryRetrievalContextVerifierV1 {
                signer_id: "signer:test-memory-retrieval".to_string(),
                verifying_key: key.verifying_key().to_bytes(),
            },
        )
        .is_err()
    );
}
