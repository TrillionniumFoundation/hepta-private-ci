use std::fs::OpenOptions;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use codex_hepta_plasticity::{
    DurableTopologyProposalRegistryV2, ProposalWindowV2, TopologyChangeV2, TopologyOperationV2,
    TopologyProposalRequestV2, TopologyWriterHandoffV1, bind_topology_writer_handoff_v1,
    propose_topology_v2, verify_topology_writer_handoffs_v1,
};
use codex_hepta_types::{Digest32, Generation, StableId};

struct TestFile {
    path: PathBuf,
}
impl TestFile {
    fn new() -> Self {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        Self {
            path: std::env::temp_dir().join(format!(
                "hepta-plasticity-structural-canary-{}-{nonce}.journal",
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
            .expect("create canary registry")
    }
    fn open(&self) -> std::fs::File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(&self.path)
            .expect("open canary registry")
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

fn proposal_and_handoff() -> (
    codex_hepta_plasticity::TopologyProposalV2,
    TopologyWriterHandoffV1,
) {
    let handoff = bind_topology_writer_handoff_v1(TopologyWriterHandoffV1 {
        module_id: id("module:adaptive-head"),
        operation: TopologyOperationV2::Rewire,
        source_writer_id: id("writer:current"),
        destination_writer_id: id("writer:next"),
        source_domain_digest: digest("domain:current"),
        destination_domain_digest: digest("domain:next"),
        baseline_generation: generation(12),
        candidate_generation: generation(13),
        migration_digest: digest("migration-plan"),
        rollback_digest: digest("rollback-plan"),
        handoff_digest: Digest32::ZERO,
    })
    .expect("typed writer handoff");
    let selected = digest("selected-artifact");
    let proposal = propose_topology_v2(TopologyProposalRequestV2 {
        proposal_id: id("topology:canary:1"),
        proposer_id: id("learning.plasticity.generator"),
        evaluator_id: id("learning.eval.independent"),
        selected_artifact_digest: selected,
        window: ProposalWindowV2 {
            window_id: id("window:canary:1"),
            window_digest: digest("window:canary"),
        },
        baseline_generation: generation(12),
        candidate_generation: generation(13),
        evaluation_digest: digest("independent-evaluation"),
        rollback_predecessor_digest: selected,
        changes: vec![TopologyChangeV2 {
            module_id: id("module:adaptive-head"),
            operation: TopologyOperationV2::Rewire,
            predecessor_digest: Some(digest("topology:12")),
            candidate_digest: Some(digest("topology:13")),
            migration_digest: handoff.migration_digest,
            rollback_digest: handoff.rollback_digest,
            writer_handoff_digest: handoff.handoff_digest,
            evidence_digest: digest("lesion-ablation-security-evidence"),
        }],
    })
    .expect("bounded topology proposal");
    (proposal, handoff)
}

#[test]
fn pls3_structural_canary_persists_candidate_without_runtime_mutation() {
    let (proposal, handoff) = proposal_and_handoff();
    let handoff_set =
        verify_topology_writer_handoffs_v1(&proposal, &[handoff]).expect("handoff set verifies");
    assert!(!handoff_set.is_zero());
    assert!(!proposal.authority.grants_any());
    assert_eq!(
        proposal.rollback_predecessor_digest,
        proposal.selected_artifact_digest
    );

    let fixture = TestFile::new();
    let scope = digest("topology-registry-scope");
    let anchor = {
        let mut registry = DurableTopologyProposalRegistryV2::open(fixture.create(), scope, 41, 8)
            .expect("open topology registry");
        let receipt = registry
            .append_v2(Digest32::ZERO, proposal.clone())
            .expect("append candidate");
        assert!(!receipt.authority.grants_any());
        registry
            .current_anchor()
            .expect("anchor read")
            .expect("anchor exists")
    };

    let reopened =
        DurableTopologyProposalRegistryV2::open_anchored(fixture.open(), scope, 41, 8, anchor)
            .expect("anchored reopen");
    assert_eq!(reopened.record_count(), Ok(1));
    assert_eq!(reopened.get(&proposal.proposal_id), Ok(Some(&proposal)));
}

#[test]
fn pls3_canary_abort_rejects_writer_handoff_drift_before_persistence() {
    let (proposal, mut handoff) = proposal_and_handoff();
    handoff.rollback_digest = digest("drifted-rollback");
    assert!(verify_topology_writer_handoffs_v1(&proposal, &[handoff]).is_err());

    // The canary has no apply API and no registry append is attempted after the
    // handoff gate fails. The current selected artifact therefore remains the
    // exact rollback predecessor named by the proposal.
    assert_eq!(
        proposal.rollback_predecessor_digest,
        proposal.selected_artifact_digest
    );
    assert!(!proposal.authority.grants_any());
}
