use crate::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

const HEADER_BYTES: usize = 8 + 2 + 8 + 4 + 32 + 32;

struct TestFile(PathBuf);

impl TestFile {
    fn create() -> (Self, File) {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "hepta-live-registry-{}-{nonce}.journal",
            std::process::id()
        ));
        let file = OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(&path)
            .expect("create registry");
        (Self(path), file)
    }
}

impl Drop for TestFile {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn parameter(label: &str) -> ParameterProposalV2 {
    let artifact = digest("artifact");
    propose_v2(ParameterProposalRequestV2 {
        proposal_id: id(&format!("parameter:proposal:{label}")),
        proposer_id: id("generator:parameters"),
        evaluator_id: id("evaluator:parameters"),
        selected_artifact_digest: artifact,
        window: ProposalWindowV2 {
            window_id: id(&format!("window:{label}")),
            window_digest: digest(label),
        },
        baseline_generation: Generation::new(1).expect("generation"),
        candidate_generation: Generation::new(2).expect("generation"),
        dataset_digest: digest("dataset"),
        update_rule_digest: digest("rule"),
        modulator_digest: digest("modulator"),
        modulator_broadcast_digest: digest("broadcast"),
        eligibility_digest: digest("eligibility"),
        evaluation_digest: digest("evaluation"),
        rollback_predecessor_digest: artifact,
        norm_layers: vec![LayerNormDenominatorV2 {
            layer_id: id("layer:1"),
            baseline_squared_l2_raw_q64: 1_u128 << 64,
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
                    layer_id: id("layer:1"),
                    parameter_id: id("parameter:1"),
                    delta: FixedQ32::from_raw(1),
                    lower_bound: FixedQ32::from_raw(-100),
                    upper_bound: FixedQ32::from_raw(100),
                    evidence_digest: digest("parameter-evidence"),
                }],
            },
        ],
    })
    .expect("parameter proposal")
}

fn topology(label: &str) -> GovernedTopologyProposalV1 {
    let artifact = digest("artifact");
    let handoff = build_writer_handoff_plan_v1(
        id("module:1"),
        id("owner:before"),
        id("owner:after"),
        1,
        2,
        digest("source"),
        digest("migration"),
        digest("rollback"),
        digest("acknowledgement"),
    )
    .expect("handoff");
    let proposal = propose_topology_v2(TopologyProposalRequestV2 {
        proposal_id: id(&format!("topology:proposal:{label}")),
        proposer_id: id("generator:topology"),
        evaluator_id: id("evaluator:topology"),
        selected_artifact_digest: artifact,
        window: ProposalWindowV2 {
            window_id: id(&format!("window:{label}")),
            window_digest: digest(label),
        },
        baseline_generation: Generation::new(1).expect("generation"),
        candidate_generation: Generation::new(2).expect("generation"),
        evaluation_digest: digest("evaluation"),
        rollback_predecessor_digest: artifact,
        changes: vec![TopologyChangeV2 {
            module_id: handoff.module_id.clone(),
            operation: TopologyOperationV2::Replace,
            predecessor_digest: Some(digest("old")),
            candidate_digest: Some(digest(label)),
            capability_typing_digest: digest("capability"),
            compatibility_plan_digest: digest("compatibility"),
            lesion_ablation_digest: digest("ablation"),
            resource_review_digest: digest("resource"),
            security_review_digest: digest("security"),
            migration_digest: handoff.migration_digest,
            rollback_digest: handoff.rollback_digest,
            writer_handoff_digest: handoff.plan_digest,
            evidence_digest: digest("topology-evidence"),
        }],
    })
    .expect("topology proposal");
    admit_governed_topology_v1(
        proposal,
        vec![handoff],
        digest("source-authentication"),
        digest("evaluation-authentication"),
    )
    .expect("governed topology")
}

#[derive(Clone, Copy)]
enum Mutation {
    Header,
    OldBody,
    OldFooter,
    ReauthenticatedOldBody,
    InvalidFrameLength,
    Truncate,
    Grow,
}

const MUTATIONS: [Mutation; 7] = [
    Mutation::Header,
    Mutation::OldBody,
    Mutation::OldFooter,
    Mutation::ReauthenticatedOldBody,
    Mutation::InvalidFrameLength,
    Mutation::Truncate,
    Mutation::Grow,
];

fn image(file: &mut File) -> Vec<u8> {
    file.seek(SeekFrom::Start(0)).expect("seek image");
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes).expect("read image");
    bytes
}

fn mutate(file: &mut File, mutation: Mutation) {
    let mut bytes = image(file);
    let frame_bytes = u32::from_be_bytes(
        bytes[HEADER_BYTES..HEADER_BYTES + 4]
            .try_into()
            .expect("frame length"),
    ) as usize;
    let body_start = HEADER_BYTES + 4;
    let footer_start = body_start + frame_bytes - 32;
    match mutation {
        Mutation::Header => bytes[0] ^= 1,
        Mutation::OldBody => bytes[body_start + 44] ^= 1,
        Mutation::OldFooter => bytes[footer_start] ^= 1,
        Mutation::ReauthenticatedOldBody => {
            bytes[body_start + 44] ^= 1;
            let replacement = Digest32::of_bytes(&bytes[body_start..footer_start]);
            bytes[footer_start..footer_start + 32].copy_from_slice(replacement.as_array());
        }
        Mutation::InvalidFrameLength => {
            bytes[HEADER_BYTES..HEADER_BYTES + 4].copy_from_slice(&u32::MAX.to_be_bytes());
        }
        Mutation::Truncate => bytes.truncate(HEADER_BYTES),
        Mutation::Grow => bytes.push(0),
    }
    file.set_len(bytes.len() as u64).expect("resize image");
    file.seek(SeekFrom::Start(0)).expect("seek mutation");
    file.write_all(&bytes).expect("write mutation");
    file.sync_all().expect("sync mutation");
}

#[derive(Clone, Copy)]
enum ParameterQuery {
    Retry,
    Append,
    Anchor,
    Read,
    Count,
}

#[test]
fn every_parameter_positive_boundary_rejects_live_corruption_and_stays_poisoned() {
    for mutation in MUTATIONS {
        for query in [
            ParameterQuery::Retry,
            ParameterQuery::Append,
            ParameterQuery::Anchor,
            ParameterQuery::Read,
            ParameterQuery::Count,
        ] {
            let (_fixture, mut file) = TestFile::create();
            let mut registry = DurableProposalRegistry::open_bootstrap_empty(
                file.try_clone().expect("registry clone"),
                digest("scope"),
                17,
                3,
            )
            .expect("registry");
            let first = parameter("first");
            let first_receipt = registry
                .append_v2(Digest32::ZERO, first.clone())
                .expect("first");
            let second_receipt = registry
                .append_v2(first_receipt.frame_digest, parameter("second"))
                .expect("second");
            mutate(&mut file, mutation);
            let before = image(&mut file);
            let result = match query {
                ParameterQuery::Retry => registry
                    .append_v2(second_receipt.frame_digest, first.clone())
                    .map(|_| ()),
                ParameterQuery::Append => registry
                    .append_v2(second_receipt.frame_digest, parameter("third"))
                    .map(|_| ()),
                ParameterQuery::Anchor => registry.current_anchor().map(|_| ()),
                ParameterQuery::Read => registry
                    .get_v2_by_proposal_id(&first.proposal_id)
                    .map(|_| ()),
                ParameterQuery::Count => registry.record_count().map(|_| ()),
            };
            assert_eq!(result, Err(DurableProposalRegistryError::Corrupt));
            assert_eq!(
                registry.current_anchor(),
                Err(DurableProposalRegistryError::Poisoned)
            );
            assert_eq!(
                registry.record_count(),
                Err(DurableProposalRegistryError::Poisoned)
            );
            assert_eq!(
                registry.get_v2_by_proposal_id(&first.proposal_id),
                Err(DurableProposalRegistryError::Poisoned)
            );
            assert_eq!(
                registry.append_v2(second_receipt.frame_digest, first),
                Err(DurableProposalRegistryError::Poisoned)
            );
            assert_eq!(image(&mut file), before);
            drop(registry);
            drop(file);
        }
    }
}

#[derive(Clone, Copy)]
enum TopologyQuery {
    Retry,
    Append,
    Anchor,
    Canary,
    Count,
}

#[test]
fn every_topology_positive_boundary_rejects_live_corruption_and_stays_poisoned() {
    for mutation in MUTATIONS {
        for query in [
            TopologyQuery::Retry,
            TopologyQuery::Append,
            TopologyQuery::Anchor,
            TopologyQuery::Canary,
            TopologyQuery::Count,
        ] {
            let (_fixture, mut file) = TestFile::create();
            let mut registry = DurableTopologyProposalRegistryV1::bootstrap_empty(
                file.try_clone().expect("registry clone"),
                digest("scope"),
                17,
                3,
            )
            .expect("registry");
            let first = topology("first");
            let candidate_id = first
                .proposal
                .candidates
                .iter()
                .find(|candidate| candidate.kind == TopologyCandidateKindV2::Update)
                .expect("candidate")
                .candidate_id
                .clone();
            let first_receipt = registry
                .append(Digest32::ZERO, first.clone())
                .expect("first");
            let second_receipt = registry
                .append(first_receipt.frame_digest, topology("second"))
                .expect("second");
            mutate(&mut file, mutation);
            let before = image(&mut file);
            match query {
                TopologyQuery::Canary => assert_eq!(
                    build_structural_canary_plan_v1(
                        &registry,
                        &first.proposal.proposal_id,
                        candidate_id,
                        digest("health"),
                        1,
                        0,
                        1
                    )
                    .err(),
                    Some(StructuralCanaryErrorV1::Binding)
                ),
                _ => {
                    let result = match query {
                        TopologyQuery::Retry => registry
                            .append(second_receipt.frame_digest, first.clone())
                            .map(|_| ()),
                        TopologyQuery::Append => registry
                            .append(second_receipt.frame_digest, topology("third"))
                            .map(|_| ()),
                        TopologyQuery::Anchor => registry.current_anchor().map(|_| ()),
                        TopologyQuery::Count => registry.record_count().map(|_| ()),
                        TopologyQuery::Canary => unreachable!(),
                    };
                    assert_eq!(result, Err(DurableTopologyRegistryErrorV1::Corrupt));
                }
            }
            assert_eq!(
                registry.current_anchor(),
                Err(DurableTopologyRegistryErrorV1::Poisoned)
            );
            assert_eq!(
                registry.record_count(),
                Err(DurableTopologyRegistryErrorV1::Poisoned)
            );
            assert_eq!(
                registry.append(second_receipt.frame_digest, first),
                Err(DurableTopologyRegistryErrorV1::Poisoned)
            );
            assert_eq!(image(&mut file), before);
            drop(registry);
            drop(file);
        }
    }
}

#[test]
fn intact_parameter_queries_share_one_serialized_reader_across_threads() {
    let (_fixture, file) = TestFile::create();
    let mut registry = DurableProposalRegistry::open_bootstrap_empty(
        file.try_clone().expect("registry clone"),
        digest("scope"),
        17,
        3,
    )
    .expect("registry");
    let first = parameter("first");
    registry
        .append_v2(Digest32::ZERO, first.clone())
        .expect("append");
    let anchor = registry.current_anchor().expect("anchor");
    let registry = Arc::new(registry);
    std::thread::scope(|scope| {
        for _ in 0..4 {
            scope.spawn(|| {
                for _ in 0..8 {
                    assert_eq!(registry.record_count(), Ok(1));
                    assert_eq!(registry.current_anchor(), Ok(anchor));
                    assert_eq!(
                        registry.get_v2_by_proposal_id(&first.proposal_id),
                        Ok(Some(&first))
                    );
                }
            });
        }
    });
    drop(registry);
    drop(file);
}

#[test]
fn intact_topology_queries_share_one_serialized_reader_across_threads() {
    let (_fixture, file) = TestFile::create();
    let mut registry = DurableTopologyProposalRegistryV1::bootstrap_empty(
        file.try_clone().expect("registry clone"),
        digest("scope"),
        17,
        3,
    )
    .expect("registry");
    let first = topology("first");
    let candidate_id = first
        .proposal
        .candidates
        .iter()
        .find(|candidate| candidate.kind == TopologyCandidateKindV2::Update)
        .expect("candidate")
        .candidate_id
        .clone();
    registry
        .append(Digest32::ZERO, first.clone())
        .expect("append");
    let anchor = registry.current_anchor().expect("anchor");
    let registry = Arc::new(registry);
    std::thread::scope(|scope| {
        for _ in 0..4 {
            scope.spawn(|| {
                for _ in 0..8 {
                    assert_eq!(registry.record_count(), Ok(1));
                    assert_eq!(registry.current_anchor(), Ok(anchor));
                    assert!(
                        build_structural_canary_plan_v1(
                            &registry,
                            &first.proposal.proposal_id,
                            candidate_id.clone(),
                            digest("health"),
                            1,
                            0,
                            1
                        )
                        .is_ok()
                    );
                }
            });
        }
    });
    drop(registry);
    drop(file);
}

#[path = "registry_final_admission_tests.rs"]
mod final_admission_tests;
