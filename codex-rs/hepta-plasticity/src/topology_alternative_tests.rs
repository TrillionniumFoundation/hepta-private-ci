use super::*;
use crate::GovernedTopologyProposalV1;
use crate::ProposalWindowV2;
use crate::TopologyChangeV2;
use crate::TopologyGovernanceErrorV1;
use crate::TopologyOperationV2;
use crate::TopologyProposalRequestV2;
use crate::TopologyProposalV2;
use crate::WriterHandoffPlanV1;
use crate::admit_governed_topology_v1;
use crate::build_writer_handoff_plan_v1;
use crate::propose_topology_v2;
use codex_hepta_types::Generation;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

enum HandoffAlternatives {
    Shared,
    Distinct,
}

fn alternatives(mode: HandoffAlternatives) -> (TopologyProposalV2, Vec<WriterHandoffPlanV1>) {
    let plan = |label: &str| {
        build_writer_handoff_plan_v1(
            id("module:alternative"),
            id("owner:old"),
            id("owner:new"),
            12,
            13,
            digest("source-store"),
            digest(&format!("migration:{label}")),
            digest(&format!("rollback:{label}")),
            digest("ack-contract"),
        )
        .expect("handoff")
    };
    let replace = plan("replace");
    let rewire = match mode {
        HandoffAlternatives::Shared => replace.clone(),
        HandoffAlternatives::Distinct => plan("rewire"),
    };
    let change = |operation, handoff: &WriterHandoffPlanV1| TopologyChangeV2 {
        module_id: handoff.module_id.clone(),
        operation,
        predecessor_digest: Some(digest("old-topology")),
        candidate_digest: Some(digest(&format!("candidate:{operation:?}"))),
        capability_typing_digest: digest("capability"),
        compatibility_plan_digest: digest("compatibility"),
        lesion_ablation_digest: digest("ablation"),
        resource_review_digest: digest("resources"),
        security_review_digest: digest("security"),
        migration_digest: handoff.migration_digest,
        rollback_digest: handoff.rollback_digest,
        writer_handoff_digest: handoff.plan_digest,
        evidence_digest: digest("change-evidence"),
    };
    let artifact = digest("artifact");
    let proposal = propose_topology_v2(TopologyProposalRequestV2 {
        proposal_id: id("proposal:alternatives"),
        proposer_id: id("generator:alternatives"),
        evaluator_id: id("evaluator:alternatives"),
        selected_artifact_digest: artifact,
        window: ProposalWindowV2 {
            window_id: id("window:alternatives"),
            window_digest: digest("window"),
        },
        baseline_generation: Generation::new(12).expect("generation"),
        candidate_generation: Generation::new(13).expect("generation"),
        evaluation_digest: digest("evaluation"),
        rollback_predecessor_digest: artifact,
        changes: vec![
            change(TopologyOperationV2::Replace, &replace),
            change(TopologyOperationV2::Rewire, &rewire),
        ],
    })
    .expect("alternative proposal");
    let handoffs = match mode {
        HandoffAlternatives::Shared => vec![replace],
        HandoffAlternatives::Distinct => vec![replace, rewire],
    };
    (proposal, handoffs)
}

fn admit(
    proposal: TopologyProposalV2,
    handoffs: Vec<WriterHandoffPlanV1>,
) -> Result<GovernedTopologyProposalV1, TopologyGovernanceErrorV1> {
    admit_governed_topology_v1(
        proposal,
        handoffs,
        digest("source-auth"),
        digest("eval-auth"),
    )
}

#[test]
fn same_module_alternatives_allow_shared_or_distinct_exact_handoffs() {
    for mode in [HandoffAlternatives::Shared, HandoffAlternatives::Distinct] {
        let (proposal, handoffs) = alternatives(mode);
        let first = admit(proposal.clone(), handoffs.clone()).expect("admission");
        let mut reversed = handoffs;
        reversed.reverse();
        assert_eq!(admit(proposal, reversed), Ok(first));
    }
}

#[test]
fn alternative_handoffs_reject_missing_duplicate_tampered_and_unused_plans() {
    let (proposal, handoffs) = alternatives(HandoffAlternatives::Distinct);
    assert!(matches!(
        admit(proposal.clone(), vec![handoffs[0].clone()]),
        Err(TopologyGovernanceErrorV1::MissingHandoff(_))
    ));
    assert!(matches!(
        admit(
            proposal.clone(),
            vec![handoffs[0].clone(), handoffs[0].clone()]
        ),
        Err(TopologyGovernanceErrorV1::UnexpectedHandoff(_))
    ));
    let mut tampered = handoffs;
    tampered[0].rollback_digest = digest("substituted-rollback");
    assert!(matches!(
        admit(proposal, tampered),
        Err(TopologyGovernanceErrorV1::DigestMismatch(_))
    ));

    let (proposal, mut handoffs) = alternatives(HandoffAlternatives::Shared);
    let (_, distinct) = alternatives(HandoffAlternatives::Distinct);
    handoffs.push(distinct[1].clone());
    assert!(matches!(
        admit(proposal, handoffs),
        Err(TopologyGovernanceErrorV1::UnexpectedHandoff(_))
    ));
}

struct TestFile(PathBuf);

impl TestFile {
    fn create() -> (Self, File) {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "hepta-topology-alternatives-{}-{nonce}.journal",
            std::process::id()
        ));
        let file = OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(&path)
            .expect("create journal");
        (Self(path), file)
    }

    fn reopen(&self) -> File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(&self.0)
            .expect("reopen journal")
    }
}

impl Drop for TestFile {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}

#[test]
fn durable_alternatives_reopen_and_bind_each_canary_to_its_exact_plan() {
    let (proposal, handoffs) = alternatives(HandoffAlternatives::Distinct);
    let governed = admit(proposal, handoffs).expect("governed");
    let proposal_id = governed.proposal.proposal_id.clone();
    let (path, file) = TestFile::create();
    let scope = digest("registry-scope");
    let mut registry = DurableTopologyProposalRegistryV1::bootstrap_empty(file, scope, 8, 4)
        .expect("bootstrap registry");
    registry
        .append(Digest32::ZERO, governed.clone())
        .expect("append");
    let anchor = registry.current_anchor().expect("anchor").expect("head");
    drop(registry);
    let registry =
        DurableTopologyProposalRegistryV1::reopen_anchored(path.reopen(), scope, 8, 4, anchor)
            .expect("reopen registry");
    for candidate in governed
        .proposal
        .candidates
        .iter()
        .filter(|candidate| candidate.kind == TopologyCandidateKindV2::Update)
    {
        let plan = build_structural_canary_plan_v1(
            &registry,
            &proposal_id,
            candidate.candidate_id.clone(),
            digest("health"),
            4,
            1,
            2,
        )
        .expect("candidate canary");
        assert_eq!(
            plan.rollback_plan_digest,
            candidate.changes[0].rollback_digest
        );
        assert_eq!(plan.durable_registry_frame_digest, anchor.frame_digest);
    }
}

#[test]
fn canary_cumulative_regressions_cannot_decrease_or_advance_rejected_observation() {
    let plan = StructuralCanaryPlanV1 {
        topology_admission_digest: digest("admission"),
        durable_registry_scope_digest: digest("registry-scope"),
        durable_registry_writer_fence: 1,
        durable_registry_sequence: 1,
        durable_registry_frame_digest: digest("frame"),
        candidate_id: id("candidate:regressions"),
        rollback_plan_digest: digest("rollback"),
        writer_handoff_set_digest: digest("handoffs"),
        baseline_health_digest: digest("baseline"),
        maximum_steps: 4,
        maximum_regressions: 2,
        minimum_successful_steps: 2,
    };
    let observation = |sequence, regression_count| StructuralCanaryObservationV1 {
        sequence,
        regression_count,
        health_digest: digest("health"),
        evidence_digest: digest("evidence"),
        safety_violation: false,
        lineage_mismatch: false,
        rollback_verified: true,
    };
    let mut actual = StructuralCanaryControllerV1::new(plan.clone()).expect("controller");
    let mut expected = StructuralCanaryControllerV1::new(plan).expect("controller");
    assert_eq!(
        actual.observe(observation(1, 1)),
        expected.observe(observation(1, 1))
    );
    assert_eq!(
        actual.observe(observation(2, 0)),
        Err(StructuralCanaryErrorV1::Observation)
    );
    assert_eq!(
        actual.observe(observation(2, 1)),
        expected.observe(observation(2, 1))
    );
    let aborted = actual.observe(observation(3, 3)).expect("budget abort");
    assert_eq!(aborted.state, StructuralCanaryStateV1::Aborted);
    assert_eq!(actual.finish(), Ok(aborted));
}

#[test]
fn canary_plan_and_receipts_bind_the_registry_scope_and_writer_generation() {
    let (proposal, handoffs) = alternatives(HandoffAlternatives::Distinct);
    let governed = admit(proposal, handoffs).expect("governed");
    let candidate_id = governed
        .proposal
        .candidates
        .iter()
        .find(|candidate| candidate.kind == TopologyCandidateKindV2::Update)
        .expect("candidate")
        .candidate_id
        .clone();
    let mut receipts = Vec::new();
    let mut frames = Vec::new();
    for (scope, fence) in [
        (digest("scope:first"), 8),
        (digest("scope:second"), 8),
        (digest("scope:first"), 9),
    ] {
        let (_path, file) = TestFile::create();
        let mut registry =
            DurableTopologyProposalRegistryV1::bootstrap_empty(file, scope, fence, 4)
                .expect("registry");
        let durable = registry
            .append(Digest32::ZERO, governed.clone())
            .expect("append");
        assert!(!durable.authority.grants_any());
        frames.push(durable.frame_digest);
        let plan = build_structural_canary_plan_v1(
            &registry,
            &governed.proposal.proposal_id,
            candidate_id.clone(),
            digest("health"),
            1,
            0,
            1,
        )
        .expect("plan");
        let mut controller = StructuralCanaryControllerV1::new(plan).expect("controller");
        receipts.push(
            controller
                .observe(StructuralCanaryObservationV1 {
                    sequence: 1,
                    health_digest: digest("health"),
                    evidence_digest: digest("evidence"),
                    regression_count: 0,
                    safety_violation: false,
                    lineage_mismatch: false,
                    rollback_verified: true,
                })
                .expect("observation"),
        );
    }
    assert!(frames.windows(2).all(|pair| pair[0] == pair[1]));
    for left in 0..receipts.len() {
        for right in left + 1..receipts.len() {
            assert_ne!(receipts[left].plan_digest, receipts[right].plan_digest);
            assert_ne!(
                receipts[left].receipt_digest,
                receipts[right].receipt_digest
            );
        }
    }
}
