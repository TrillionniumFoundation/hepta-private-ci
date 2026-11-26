use super::*;
use std::fs::OpenOptions;
use std::io::Write;
use std::panic::AssertUnwindSafe;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("valid generation")
}

struct TestPath(PathBuf);

impl TestPath {
    fn new(label: &str, sequence: usize) -> Self {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        Self(std::env::temp_dir().join(format!(
            "hepta-plasticity-adversarial-{label}-{}-{nonce}-{sequence}",
            std::process::id()
        )))
    }
}

impl Drop for TestPath {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}

fn profile() -> ParameterGeneratorProfileV3 {
    let selected_artifact_digest = digest(b"adversarial-artifact");
    let window = ProposalWindowV2 {
        window_id: id("adversarial-window:1"),
        window_digest: digest(b"adversarial-window"),
    };
    let rules = vec![
        ParameterMutationRuleV1 {
            parameter_id: id("parameter:a"),
            layer_id: id("layer:a"),
            surface: ParameterMutationSurfaceV1::LearnableParameter,
            minimum_delta: FixedQ32::from_raw(-(1_i64 << 24)),
            maximum_delta: FixedQ32::from_raw(1_i64 << 24),
        },
        ParameterMutationRuleV1 {
            parameter_id: id("parameter:b"),
            layer_id: id("layer:b"),
            surface: ParameterMutationSurfaceV1::LearnableParameter,
            minimum_delta: FixedQ32::from_raw(-(1_i64 << 24)),
            maximum_delta: FixedQ32::from_raw(1_i64 << 24),
        },
    ];
    ParameterGeneratorProfileV3 {
        selected_artifact_digest,
        window: window.clone(),
        norm_layers: vec![
            LayerNormDenominatorV2 {
                layer_id: id("layer:a"),
                baseline_squared_l2_raw_q64: 1_u128 << 64,
            },
            LayerNormDenominatorV2 {
                layer_id: id("layer:b"),
                baseline_squared_l2_raw_q64: 1_u128 << 64,
            },
        ],
        mutation_policy: build_parameter_mutation_policy_v1(
            id("adversarial-policy:1"),
            digest(b"adversarial-grammar"),
            selected_artifact_digest,
            window,
            rules,
        )
        .expect("policy"),
        update_scales: vec![
            FixedQ32::from_raw(1_i64 << 31),
            FixedQ32::ONE,
        ],
        signals: vec![
            ParameterPlasticitySignalV3 {
                layer_id: id("layer:a"),
                parameter_id: id("parameter:a"),
                eligibility: FixedQ32::ONE,
                modulator: FixedQ32::ONE,
                learning_rate: FixedQ32::from_raw(1_i64 << 20),
                lower_bound: FixedQ32::from_raw(-(1_i64 << 24)),
                upper_bound: FixedQ32::from_raw(1_i64 << 24),
                evidence_digest: digest(b"signal-a"),
            },
            ParameterPlasticitySignalV3 {
                layer_id: id("layer:b"),
                parameter_id: id("parameter:b"),
                eligibility: FixedQ32::ONE,
                modulator: FixedQ32::from_raw(1_i64 << 31),
                learning_rate: FixedQ32::from_raw(1_i64 << 20),
                lower_bound: FixedQ32::from_raw(-(1_i64 << 24)),
                upper_bound: FixedQ32::from_raw(1_i64 << 24),
                evidence_digest: digest(b"signal-b"),
            },
        ],
    }
}

#[test]
fn deterministic_parameter_generation_is_permutation_invariant() {
    let canonical = generate_parameter_candidates_v3(profile()).expect("canonical");
    let mut permuted = profile();
    permuted.norm_layers.reverse();
    permuted.mutation_policy.rules.reverse();
    // Policies are canonical records and must remain canonical after construction;
    // rebuild it from the reversed input to prove construction order is irrelevant.
    permuted.mutation_policy = build_parameter_mutation_policy_v1(
        permuted.mutation_policy.policy_id.clone(),
        permuted.mutation_policy.mutation_grammar_digest,
        permuted.mutation_policy.selected_artifact_digest,
        permuted.mutation_policy.window.clone(),
        permuted.mutation_policy.rules,
    )
    .expect("rebuilt policy");
    permuted.update_scales.reverse();
    permuted.signals.reverse();
    let generated = generate_parameter_candidates_v3(permuted).expect("permuted");
    assert_eq!(generated, canonical);
}

#[test]
fn coverage_digest_rejects_each_bound_frontier_or_set_mutation() {
    let profile = profile();
    let generated = generate_parameter_candidates_v3(profile.clone()).expect("generate");
    let draft = build_generator_coverage_draft_v1(
        &profile,
        &generated,
        vec![id("parameter:a"), id("parameter:b")],
        Vec::new(),
        GeneratorCoverageFrontierV1 {
            artifact_registry_head_digest: digest(b"artifact-head"),
            qualification_evidence_head_digest: digest(b"evidence-head"),
            owner_evidence_set_digest: digest(b"owner-set"),
        },
    )
    .expect("draft");

    let mut mutations: Vec<Box<dyn Fn(&mut GeneratorCoverageDraftV1)>> = vec![
        Box::new(|value| value.selected_artifact_digest = digest(b"other-artifact")),
        Box::new(|value| value.window.window_digest = digest(b"other-window")),
        Box::new(|value| value.mutation_grammar_digest = digest(b"other-grammar")),
        Box::new(|value| {
            value.frontier.artifact_registry_head_digest = digest(b"other-artifact-head")
        }),
        Box::new(|value| {
            value.frontier.qualification_evidence_head_digest = digest(b"other-evidence-head")
        }),
        Box::new(|value| value.frontier.owner_evidence_set_digest = digest(b"other-owner-set")),
    ];
    for mutate in mutations.drain(..) {
        let mut changed = draft.clone();
        mutate(&mut changed);
        assert_eq!(
            verify_generator_coverage_draft_v1(&changed),
            Err(GeneratorCoverageErrorV1::DigestMismatch)
        );
    }
}

fn topology_change(module: &str, old: &[u8], new: &[u8]) -> TopologyChangeV2 {
    TopologyChangeV2 {
        module_id: id(module),
        operation: TopologyOperationV2::Replace,
        predecessor_digest: Some(digest(old)),
        candidate_digest: Some(digest(new)),
        capability_typing_digest: digest(format!("{module}:capability").as_bytes()),
        compatibility_plan_digest: digest(format!("{module}:compatibility").as_bytes()),
        lesion_ablation_digest: digest(format!("{module}:ablation").as_bytes()),
        resource_review_digest: digest(format!("{module}:resource").as_bytes()),
        security_review_digest: digest(format!("{module}:security").as_bytes()),
        migration_digest: digest(format!("{module}:migration").as_bytes()),
        rollback_digest: digest(format!("{module}:rollback").as_bytes()),
        writer_handoff_digest: digest(format!("{module}:handoff").as_bytes()),
        evidence_digest: digest(format!("{module}:evidence").as_bytes()),
    }
}

#[test]
fn deterministic_topology_proposal_is_change_order_invariant() {
    let artifact = digest(b"topology-artifact");
    let first = topology_change("module:a", b"a-old", b"a-new");
    let second = topology_change("module:b", b"b-old", b"b-new");
    let request = |changes| TopologyProposalRequestV2 {
        proposal_id: id("topology:adversarial:1"),
        proposer_id: id("generator:adversarial"),
        evaluator_id: id("evaluator:adversarial"),
        selected_artifact_digest: artifact,
        window: ProposalWindowV2 {
            window_id: id("topology-window:1"),
            window_digest: digest(b"topology-window"),
        },
        baseline_generation: generation(9),
        candidate_generation: generation(10),
        evaluation_digest: digest(b"topology-evaluation"),
        rollback_predecessor_digest: artifact,
        changes,
    };
    let canonical = propose_topology_v2(request(vec![first.clone(), second.clone()]))
        .expect("canonical");
    let reversed = propose_topology_v2(request(vec![second, first])).expect("reversed");
    assert_eq!(canonical, reversed);
}

#[test]
fn malformed_registry_frames_never_panic() {
    let mut state = 0x9e37_79b9_7f4a_7c15_u64;
    for sequence in 0..256 {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        let length = (state as usize % 1024) + 1;
        let mut bytes = Vec::with_capacity(length);
        for index in 0..length {
            state ^= state << 13;
            state ^= state >> 7;
            state ^= state << 17;
            bytes.push((state ^ index as u64) as u8);
        }
        let path = TestPath::new("decoder", sequence);
        let mut file = OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(&path.0)
            .expect("create fuzz file");
        file.write_all(&bytes).expect("write fuzz bytes");
        file.sync_all().expect("sync fuzz bytes");
        drop(file);
        let result = std::panic::catch_unwind(AssertUnwindSafe(|| {
            let file = OpenOptions::new()
                .read(true)
                .write(true)
                .open(&path.0)
                .expect("reopen fuzz file");
            DurableProposalRegistry::open(file, digest(b"fuzz-scope"), 17, 16)
        }));
        assert!(result.is_ok(), "decoder panicked for sequence {sequence}");
    }
}
