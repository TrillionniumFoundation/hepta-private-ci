use std::cell::RefCell;
use std::fs::OpenOptions;
use std::rc::Rc;

use super::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use tempfile::NamedTempFile;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid test id")
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("valid generation")
}

#[test]
fn generator_v3_owns_candidate_construction_and_is_deterministic() {
    let request = ParameterGeneratorRequestV3 {
        proposal_id: id("proposal:generated"),
        learning_rate: FixedQ32::from_raw(2),
        signals: vec![
            ParameterGeneratorSignalV3 {
                layer_id: id("layer:b"),
                parameter_id: id("parameter:b"),
                eligibility: FixedQ32::ONE,
                modulator_broadcast: FixedQ32::ONE,
                lower_bound: FixedQ32::from_raw(-10),
                upper_bound: FixedQ32::from_raw(10),
                evidence_digest: digest(b"evidence-b"),
            },
            ParameterGeneratorSignalV3 {
                layer_id: id("layer:a"),
                parameter_id: id("parameter:a"),
                eligibility: FixedQ32::ONE,
                modulator_broadcast: FixedQ32::ONE,
                lower_bound: FixedQ32::from_raw(-10),
                upper_bound: FixedQ32::from_raw(10),
                evidence_digest: digest(b"evidence-a"),
            },
        ],
    };
    let first = generate_parameter_candidates_v3(request.clone()).expect("generated set");
    let second = generate_parameter_candidates_v3(request.clone()).expect("generated set");
    assert_eq!(first, second);
    assert_eq!(first.input_parameter_count, 2);
    assert_eq!(first.generated_delta_count, 2);
    assert_eq!(first.candidates.len(), 2);
    assert_eq!(first.candidates[0].kind, ParameterCandidateKindV2::NoChange);
    assert_eq!(first.candidates[1].kind, ParameterCandidateKindV2::Update);
    assert_eq!(first.candidates[1].parameter_deltas.len(), 2);
    assert_eq!(
        first.candidates[1].parameter_deltas[0].parameter_id,
        id("parameter:a")
    );
    assert_eq!(first.candidates[1].parameter_deltas[0].delta.raw(), 2);
    verify_generated_parameter_candidates_v3(request, &first).expect("verification");
    assert!(!first.generator_input_digest.is_zero());
    assert!(!first.candidate_set_digest.is_zero());
    assert!(!generator_attestation_payload_v3(&first).is_empty());
}

#[test]
fn generator_v3_never_truncates_or_accepts_duplicate_parameter_identity() {
    let duplicate = ParameterGeneratorSignalV3 {
        layer_id: id("layer:a"),
        parameter_id: id("parameter:a"),
        eligibility: FixedQ32::ONE,
        modulator_broadcast: FixedQ32::ONE,
        lower_bound: FixedQ32::from_raw(-10),
        upper_bound: FixedQ32::from_raw(10),
        evidence_digest: digest(b"evidence"),
    };
    let error = generate_parameter_candidates_v3(ParameterGeneratorRequestV3 {
        proposal_id: id("proposal:duplicate"),
        learning_rate: FixedQ32::ONE,
        signals: vec![duplicate.clone(), duplicate],
    })
    .expect_err("duplicate must reject");
    assert!(matches!(
        error,
        ParameterGeneratorErrorV3::DuplicateParameter(_)
    ));

    let zero = generate_parameter_candidates_v3(ParameterGeneratorRequestV3 {
        proposal_id: id("proposal:zero"),
        learning_rate: FixedQ32::ONE,
        signals: vec![ParameterGeneratorSignalV3 {
            layer_id: id("layer:a"),
            parameter_id: id("parameter:a"),
            eligibility: FixedQ32::ZERO,
            modulator_broadcast: FixedQ32::ONE,
            lower_bound: FixedQ32::from_raw(-10),
            upper_bound: FixedQ32::from_raw(10),
            evidence_digest: digest(b"zero-evidence"),
        }],
    })
    .expect("zero projection is a complete no-change set");
    assert_eq!(zero.candidates.len(), 1);
    assert_eq!(zero.candidates[0].kind, ParameterCandidateKindV2::NoChange);
    assert_eq!(zero.generated_delta_count, 0);
}

#[test]
fn topology_v2_is_exact_successor_bounded_and_authority_free() {
    let selected = digest(b"topology:selected");
    let request = TopologyProposalRequestV2 {
        proposal_id: id("topology:proposal:1"),
        proposer_id: id("topology:generator"),
        evaluator_id: id("topology:evaluator"),
        selected_topology_artifact_digest: selected,
        window: ProposalWindowV2 {
            window_id: id("topology:window:1"),
            window_digest: digest(b"topology-window"),
        },
        baseline_generation: generation(9),
        candidate_generation: generation(10),
        module_id: id("module:adapter"),
        operation: TopologyOperation::Replace,
        predecessor_topology_digest: selected,
        candidate_topology_digest: digest(b"topology:candidate"),
        compatibility_plan_digest: digest(b"compatibility"),
        resource_delta_digest: digest(b"resources"),
        security_review_digest: digest(b"security"),
        lesion_plan_digest: digest(b"lesion"),
        rollback_plan_digest: digest(b"rollback"),
        evaluation_digest: digest(b"evaluation"),
    };
    let proposal = propose_topology_v2(request.clone()).expect("topology proposal");
    verify_topology_proposal_v2(&proposal).expect("topology verification");
    assert_eq!(proposal.operation, TopologyOperation::Replace);
    assert_eq!(proposal.status, ProposalStatus::RequiresIndependentAcceptance);
    assert!(!proposal.authority.grants_any());
    assert!(!proposal.proposal_digest.is_zero());

    let mut stale = request;
    stale.candidate_generation = generation(11);
    assert_eq!(
        propose_topology_v2(stale),
        Err(TopologyProposalErrorV2::GenerationNotExactSuccessor)
    );
}

#[derive(Clone, Default)]
struct MemoryAnchorStore {
    shared: Rc<RefCell<Option<DurableRegistryAnchorV1>>>,
    fail_commit: bool,
}

impl DurableProposalAnchorStoreV1 for MemoryAnchorStore {
    fn load_anchor(
        &mut self,
        _registry_scope_digest: Digest32,
        _writer_fence: u64,
    ) -> Result<Option<DurableRegistryAnchorV1>, ProductionAnchorStoreErrorV1> {
        Ok(*self.shared.borrow())
    }

    fn compare_and_store_anchor(
        &mut self,
        _registry_scope_digest: Digest32,
        _writer_fence: u64,
        expected: Option<DurableRegistryAnchorV1>,
        next: DurableRegistryAnchorV1,
    ) -> Result<(), ProductionAnchorStoreErrorV1> {
        if self.fail_commit {
            return Err(ProductionAnchorStoreErrorV1::Unavailable);
        }
        if *self.shared.borrow() != expected {
            return Err(ProductionAnchorStoreErrorV1::Conflict);
        }
        *self.shared.borrow_mut() = Some(next);
        Ok(())
    }
}

fn valid_v2_proposal(name: &str) -> ParameterProposalV2 {
    let selected = digest(b"artifact:production");
    propose_v2(ParameterProposalRequestV2 {
        proposal_id: id(name),
        proposer_id: id("proposer:production"),
        evaluator_id: id("evaluator:production"),
        selected_artifact_digest: selected,
        window: ProposalWindowV2 {
            window_id: id(name.replace("proposal", "window").as_str()),
            window_digest: digest(name.as_bytes()),
        },
        baseline_generation: generation(1),
        candidate_generation: generation(2),
        dataset_digest: digest(b"dataset:production"),
        update_rule_digest: digest(b"rule:production"),
        modulator_digest: digest(b"modulator:production"),
        modulator_broadcast_digest: digest(b"broadcast:production"),
        eligibility_digest: digest(b"eligibility:production"),
        evaluation_digest: digest(b"evaluation:production"),
        rollback_predecessor_digest: selected,
        norm_layers: vec![LayerNormDenominatorV2 {
            layer_id: id("layer:production"),
            baseline_squared_l2_raw_q64: 1_000_000,
        }],
        candidates: vec![ParameterCandidateRequestV2 {
            candidate_id: id("candidate:no-change:production"),
            kind: ParameterCandidateKindV2::NoChange,
            parameter_deltas: Vec::new(),
        }],
    })
    .expect("valid v2 proposal")
}

#[test]
fn production_registry_requires_and_advances_external_anchor() {
    let file = NamedTempFile::new().expect("temp file");
    let path = file.path().to_owned();
    drop(file);
    let shared = Rc::new(RefCell::new(None));
    let store = MemoryAnchorStore {
        shared: shared.clone(),
        fail_commit: false,
    };
    let scope = digest(b"production-scope");
    let handle = OpenOptions::new()
        .read(true)
        .write(true)
        .open(&path)
        .expect("open proposal file");
    let mut registry = ProductionProposalRegistryV1::open(handle, scope, 7, 16, store)
        .expect("bootstrap production registry");
    let receipt = registry
        .append_v2(valid_v2_proposal("proposal:production:1"))
        .expect("anchored append");
    assert_eq!(registry.current_anchor().expect("anchor"), Some(receipt.acknowledged_anchor));
    assert_eq!(*shared.borrow(), Some(receipt.acknowledged_anchor));
    drop(registry);

    let handle = OpenOptions::new()
        .read(true)
        .write(true)
        .open(&path)
        .expect("reopen proposal file");
    ProductionProposalRegistryV1::open(
        handle,
        scope,
        7,
        16,
        MemoryAnchorStore {
            shared: shared.clone(),
            fail_commit: false,
        },
    )
    .expect("anchored reopen");

    let handle = OpenOptions::new()
        .read(true)
        .write(true)
        .open(&path)
        .expect("reopen without anchor");
    let error = ProductionProposalRegistryV1::open(
        handle,
        scope,
        7,
        16,
        MemoryAnchorStore::default(),
    )
    .expect_err("existing history without independent anchor must reject");
    assert!(matches!(
        error,
        ProductionProposalRegistryErrorV1::AnchorRequiredForExistingHistory
    ));
}

#[test]
fn production_registry_poisoned_when_anchor_commit_is_indeterminate() {
    let file = NamedTempFile::new().expect("temp file");
    let path = file.path().to_owned();
    drop(file);
    let handle = OpenOptions::new()
        .read(true)
        .write(true)
        .open(&path)
        .expect("open proposal file");
    let store = MemoryAnchorStore {
        shared: Rc::new(RefCell::new(None)),
        fail_commit: true,
    };
    let mut registry = ProductionProposalRegistryV1::open(
        handle,
        digest(b"poison-scope"),
        11,
        16,
        store,
    )
    .expect("bootstrap registry");
    assert!(matches!(
        registry.append_v2(valid_v2_proposal("proposal:production:poison")),
        Err(ProductionProposalRegistryErrorV1::AnchorCommitIndeterminate)
    ));
    assert!(registry.is_poisoned());
    assert!(matches!(
        registry.record_count(),
        Err(ProductionProposalRegistryErrorV1::Poisoned)
    ));
}
