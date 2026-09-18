use std::fs::OpenOptions;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use codex_hepta_plasticity::{
    DurableTopologyProposalRegistryV1, GovernedTopologyProposalV1, ProposalWindowV2,
    StructuralCanaryControllerV1, StructuralCanaryObservationV1, StructuralCanaryPlanV1,
    StructuralCanaryStateV1, TopologyChangeV2, TopologyOperationV2, TopologyProposalRequestV2,
    WriterHandoffPlanV1, admit_governed_topology_v1, build_writer_handoff_plan_v1,
    propose_topology_v2,
};
use codex_hepta_types::{Digest32, Generation, StableId};

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
                "hepta-plasticity-{label}-{}-{nonce}.journal",
                std::process::id()
            )),
        }
    }

    fn create(&self) -> std::fs::File {
        OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(&self.path)
            .expect("create qualification registry")
    }

    fn open(&self) -> std::fs::File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(&self.path)
            .expect("open qualification registry")
    }
}

impl Drop for TestFile {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.path);
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).expect("valid id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("valid generation")
}

fn governed_topology() -> (GovernedTopologyProposalV1, WriterHandoffPlanV1) {
    let handoff = build_writer_handoff_plan_v1(
        id("module:adaptive-head"),
        id("owner:current"),
        id("owner:next"),
        12,
        13,
        digest("source-store"),
        digest("migration"),
        digest("rollback"),
        digest("ack-contract"),
    )
    .expect("writer handoff");
    let selected_artifact = digest("selected-artifact");
    let proposal = propose_topology_v2(TopologyProposalRequestV2 {
        proposal_id: id("topology:qualification:1"),
        proposer_id: id("learning.plasticity.generator"),
        evaluator_id: id("learning.eval.independent"),
        selected_artifact_digest: selected_artifact,
        window: ProposalWindowV2 {
            window_id: id("window:qualification:1"),
            window_digest: digest("window"),
        },
        baseline_generation: generation(12),
        candidate_generation: generation(13),
        evaluation_digest: digest("independent-evaluation"),
        rollback_predecessor_digest: selected_artifact,
        changes: vec![TopologyChangeV2 {
            module_id: id("module:adaptive-head"),
            operation: TopologyOperationV2::Rewire,
            predecessor_digest: Some(digest("topology:12")),
            candidate_digest: Some(digest("topology:13")),
            capability_typing_digest: digest("capability-typing"),
            compatibility_plan_digest: digest("compatibility"),
            lesion_ablation_digest: digest("lesion-ablation"),
            resource_review_digest: digest("resource-review"),
            security_review_digest: digest("security-review"),
            migration_digest: handoff.migration_digest,
            rollback_digest: handoff.rollback_digest,
            writer_handoff_digest: handoff.plan_digest,
            evidence_digest: digest("topology-evidence"),
        }],
    })
    .expect("typed topology proposal");
    let governed = admit_governed_topology_v1(
        proposal,
        vec![handoff.clone()],
        digest("observer-authentication"),
        digest("evaluator-authentication"),
    )
    .expect("governed topology");
    (governed, handoff)
}

fn persist_and_reopen(
    fixture: &TestFile,
    governed: GovernedTopologyProposalV1,
) -> GovernedTopologyProposalV1 {
    let scope = digest("topology-registry-scope");
    let anchor = {
        let mut registry =
            DurableTopologyProposalRegistryV1::bootstrap_empty(fixture.create(), scope, 41, 8)
                .expect("bootstrap registry");
        let append = registry
            .append(Digest32::ZERO, governed.clone())
            .expect("append governed topology");
        assert!(!append.authority.grants_any());
        registry
            .current_anchor()
            .expect("anchor read")
            .expect("anchor exists")
    };
    let reopened =
        DurableTopologyProposalRegistryV1::reopen_anchored(fixture.open(), scope, 41, 8, anchor)
            .expect("anchored reopen");
    assert_eq!(reopened.record_count(), Ok(1));
    governed
}

#[test]
fn pls3_governed_topology_persists_then_accepts_bounded_canary() {
    let fixture = TestFile::new("pls3-accept");
    let (governed, handoff) = governed_topology();
    let governed = persist_and_reopen(&fixture, governed);
    let mut controller = StructuralCanaryControllerV1::new(StructuralCanaryPlanV1 {
        topology_admission_digest: governed.admission_digest,
        rollback_plan_digest: handoff.rollback_digest,
        writer_handoff_set_digest: governed.handoff_set_digest,
        baseline_health_digest: digest("baseline-health"),
        maximum_steps: 2,
        maximum_regressions: 0,
        minimum_successful_steps: 2,
    })
    .expect("canary controller");
    for sequence in 1..=2 {
        let receipt = controller
            .observe(StructuralCanaryObservationV1 {
                sequence,
                health_digest: digest(&format!("health:{sequence}")),
                evidence_digest: digest(&format!("evidence:{sequence}")),
                regression_count: 0,
                safety_violation: false,
                lineage_mismatch: false,
                rollback_verified: true,
            })
            .expect("canary observation");
        assert_eq!(receipt.state, StructuralCanaryStateV1::Running);
    }
    let accepted = controller.finish().expect("finish canary");
    assert_eq!(accepted.state, StructuralCanaryStateV1::Accepted);
    assert_eq!(accepted.observed_steps, 2);
    assert!(!accepted.observation_chain_digest.is_zero());
    assert!(!accepted.receipt_digest.is_zero());
}

#[test]
fn pls3_safety_violation_aborts_after_durable_admission() {
    let fixture = TestFile::new("pls3-abort");
    let (governed, handoff) = governed_topology();
    let governed = persist_and_reopen(&fixture, governed);
    let mut controller = StructuralCanaryControllerV1::new(StructuralCanaryPlanV1 {
        topology_admission_digest: governed.admission_digest,
        rollback_plan_digest: handoff.rollback_digest,
        writer_handoff_set_digest: governed.handoff_set_digest,
        baseline_health_digest: digest("baseline-health"),
        maximum_steps: 4,
        maximum_regressions: 0,
        minimum_successful_steps: 2,
    })
    .expect("canary controller");
    let aborted = controller
        .observe(StructuralCanaryObservationV1 {
            sequence: 1,
            health_digest: digest("unsafe-health"),
            evidence_digest: digest("unsafe-evidence"),
            regression_count: 0,
            safety_violation: true,
            lineage_mismatch: false,
            rollback_verified: true,
        })
        .expect("terminal abort receipt");
    assert_eq!(aborted.state, StructuralCanaryStateV1::Aborted);
    assert_eq!(
        controller.finish().expect("finish preserves abort").state,
        StructuralCanaryStateV1::Aborted
    );
}
