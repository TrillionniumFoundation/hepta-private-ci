use std::error::Error as StdError;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_plasticity::DurableProposalRegistry;
use codex_hepta_plasticity::DurableProposalRegistryError;
use codex_hepta_plasticity::LayerNormDenominatorV2;
use codex_hepta_plasticity::ParameterCandidateKindV2;
use codex_hepta_plasticity::ParameterCandidateRequestV2;
use codex_hepta_plasticity::ParameterDeltaV2;
use codex_hepta_plasticity::ParameterGeneratorProfileV3;
use codex_hepta_plasticity::ParameterMutationRuleV1;
use codex_hepta_plasticity::ParameterMutationSurfaceV1;
use codex_hepta_plasticity::ParameterPlasticitySignalV3;
use codex_hepta_plasticity::ParameterProposalRequestV2;
use codex_hepta_plasticity::ProposalWindowV2;
use codex_hepta_plasticity::build_parameter_mutation_policy_v1;
use codex_hepta_plasticity::generate_parameter_candidates_v3;
use codex_hepta_plasticity::propose_v2;
use codex_hepta_plasticity::verify_generated_parameter_candidates_v3;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

struct TestFile {
    path: PathBuf,
}

impl TestFile {
    fn new(label: &str) -> Self {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        Self {
            path: std::env::temp_dir().join(format!(
                "hepta-plasticity-property-{label}-{}-{nonce}.journal",
                std::process::id()
            )),
        }
    }

    fn create(&self) -> Result<File, std::io::Error> {
        OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(&self.path)
    }

    fn open(&self) -> Result<File, std::io::Error> {
        OpenOptions::new().read(true).write(true).open(&self.path)
    }
}

impl Drop for TestFile {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.path);
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("generation")
}

fn profile(reverse: bool, grammar: &[u8]) -> ParameterGeneratorProfileV3 {
    let artifact = digest(b"artifact");
    let window = ProposalWindowV2 {
        window_id: id("window:properties"),
        window_digest: digest(b"window"),
    };
    let mut rules = vec![
        ParameterMutationRuleV1 {
            parameter_id: id("parameter:a"),
            layer_id: id("layer:a"),
            surface: ParameterMutationSurfaceV1::LearnableParameter,
            minimum_delta: FixedQ32::from_raw(-100),
            maximum_delta: FixedQ32::from_raw(100),
        },
        ParameterMutationRuleV1 {
            parameter_id: id("parameter:b"),
            layer_id: id("layer:b"),
            surface: ParameterMutationSurfaceV1::LearnableParameter,
            minimum_delta: FixedQ32::from_raw(-100),
            maximum_delta: FixedQ32::from_raw(100),
        },
    ];
    let mut norm_layers = vec![
        LayerNormDenominatorV2 {
            layer_id: id("layer:a"),
            baseline_squared_l2_raw_q64: 4_000_000,
        },
        LayerNormDenominatorV2 {
            layer_id: id("layer:b"),
            baseline_squared_l2_raw_q64: 9_000_000,
        },
    ];
    let mut signals = vec![
        ParameterPlasticitySignalV3 {
            layer_id: id("layer:a"),
            parameter_id: id("parameter:a"),
            eligibility: FixedQ32::ONE,
            modulator: FixedQ32::ONE,
            learning_rate: FixedQ32::from_raw(2),
            lower_bound: FixedQ32::from_raw(-100),
            upper_bound: FixedQ32::from_raw(100),
            evidence_digest: digest(b"signal-a"),
        },
        ParameterPlasticitySignalV3 {
            layer_id: id("layer:b"),
            parameter_id: id("parameter:b"),
            eligibility: FixedQ32::ONE,
            modulator: FixedQ32::ONE,
            learning_rate: FixedQ32::from_raw(3),
            lower_bound: FixedQ32::from_raw(-100),
            upper_bound: FixedQ32::from_raw(100),
            evidence_digest: digest(b"signal-b"),
        },
    ];
    let mut scales = vec![FixedQ32::ONE, FixedQ32::from_raw(FixedQ32::ONE.raw() / 2)];
    if reverse {
        rules.reverse();
        norm_layers.reverse();
        signals.reverse();
        scales.reverse();
    }
    let policy = build_parameter_mutation_policy_v1(
        id("policy:properties"),
        digest(grammar),
        artifact,
        window.clone(),
        rules,
    )
    .expect("policy");
    ParameterGeneratorProfileV3 {
        selected_artifact_digest: artifact,
        window,
        norm_layers,
        mutation_policy: policy,
        update_scales: scales,
        signals,
    }
}

#[test]
fn canonical_generation_is_permutation_invariant_and_tamper_evident() {
    let canonical = generate_parameter_candidates_v3(profile(false, b"grammar-a"))
        .expect("canonical generation");
    let permuted = generate_parameter_candidates_v3(profile(true, b"grammar-a"))
        .expect("permuted generation");
    assert_eq!(canonical, permuted);

    let mut reordered = canonical.clone();
    reordered.candidates.reverse();
    assert!(verify_generated_parameter_candidates_v3(
        profile(false, b"grammar-a"),
        &reordered
    )
    .is_err());

    let mut changed_evidence = canonical.clone();
    let update = changed_evidence
        .candidates
        .iter_mut()
        .find(|candidate| candidate.kind == ParameterCandidateKindV2::Update)
        .expect("update candidate");
    update.parameter_deltas[0].evidence_digest = digest(b"changed-evidence");
    assert!(verify_generated_parameter_candidates_v3(
        profile(false, b"grammar-a"),
        &changed_evidence
    )
    .is_err());

    let changed_grammar = generate_parameter_candidates_v3(profile(false, b"grammar-b"))
        .expect("changed grammar");
    assert_ne!(canonical.generator_digest, changed_grammar.generator_digest);
}

fn proposal(proposal_id: &str, window_id: &str, window_material: &[u8]) -> codex_hepta_plasticity::ParameterProposalV2 {
    let selected = digest(b"selected-artifact");
    propose_v2(ParameterProposalRequestV2 {
        proposal_id: id(proposal_id),
        proposer_id: id("proposer:properties"),
        evaluator_id: id("evaluator:properties"),
        selected_artifact_digest: selected,
        window: ProposalWindowV2 {
            window_id: id(window_id),
            window_digest: digest(window_material),
        },
        baseline_generation: generation(1),
        candidate_generation: generation(2),
        dataset_digest: digest(b"dataset"),
        update_rule_digest: digest(b"update-rule"),
        modulator_digest: digest(b"modulator"),
        modulator_broadcast_digest: digest(b"broadcast"),
        eligibility_digest: digest(b"eligibility"),
        evaluation_digest: digest(b"evaluation"),
        rollback_predecessor_digest: selected,
        norm_layers: vec![LayerNormDenominatorV2 {
            layer_id: id("layer:properties"),
            baseline_squared_l2_raw_q64: 1_000_000,
        }],
        candidates: vec![
            ParameterCandidateRequestV2 {
                candidate_id: id("candidate:no-change"),
                kind: ParameterCandidateKindV2::NoChange,
                parameter_deltas: Vec::new(),
            },
            ParameterCandidateRequestV2 {
                candidate_id: id("candidate:update"),
                kind: ParameterCandidateKindV2::Update,
                parameter_deltas: vec![ParameterDeltaV2 {
                    layer_id: id("layer:properties"),
                    parameter_id: id("parameter:properties"),
                    delta: FixedQ32::from_raw(1),
                    lower_bound: FixedQ32::from_raw(-10),
                    upper_bound: FixedQ32::from_raw(10),
                    evidence_digest: digest(b"delta-evidence"),
                }],
            },
        ],
    })
    .expect("proposal")
}

#[test]
fn recovery_repairs_only_incomplete_crash_tails() -> Result<(), Box<dyn StdError>> {
    for tail in [&[0_u8][..], &[0, 0, 0][..], &[0, 0, 1, 0, 7][..]] {
        let fixture = TestFile::new("crash-tail");
        let scope = digest(b"scope");
        let anchor = {
            let mut registry =
                DurableProposalRegistry::open_bootstrap_empty(fixture.create()?, scope, 7, 4)?;
            registry.append_v2(
                Digest32::ZERO,
                proposal("proposal:tail", "window:tail", b"window"),
            )?;
            registry.current_anchor()?.expect("anchor")
        };
        let valid = std::fs::read(&fixture.path)?;
        let mut file = OpenOptions::new().append(true).open(&fixture.path)?;
        file.write_all(tail)?;
        file.sync_all()?;
        drop(file);

        let reopened = DurableProposalRegistry::open_anchored(
            fixture.open()?,
            scope,
            7,
            4,
            anchor,
        )?;
        assert_eq!(reopened.current_anchor()?, Some(anchor));
        drop(reopened);
        assert_eq!(std::fs::read(&fixture.path)?, valid);
    }
    Ok(())
}

#[test]
fn complete_corruption_and_second_writer_fail_closed() -> Result<(), Box<dyn StdError>> {
    let fixture = TestFile::new("corrupt");
    let scope = digest(b"scope");
    let anchor = {
        let mut registry =
            DurableProposalRegistry::open_bootstrap_empty(fixture.create()?, scope, 11, 4)?;
        assert!(matches!(
            DurableProposalRegistry::open(fixture.open()?, scope, 11, 4),
            Err(DurableProposalRegistryError::Busy)
        ));
        registry.append_v2(
            Digest32::ZERO,
            proposal("proposal:corrupt", "window:corrupt", b"window"),
        )?;
        registry.current_anchor()?.expect("anchor")
    };

    let mut bytes = std::fs::read(&fixture.path)?;
    bytes.extend_from_slice(&76_u32.to_be_bytes());
    bytes.extend_from_slice(&[0_u8; 76]);
    std::fs::write(&fixture.path, &bytes)?;
    let before = std::fs::read(&fixture.path)?;
    assert!(matches!(
        DurableProposalRegistry::open_anchored(fixture.open()?, scope, 11, 4, anchor),
        Err(DurableProposalRegistryError::Corrupt)
    ));
    assert_eq!(std::fs::read(&fixture.path)?, before);
    Ok(())
}
