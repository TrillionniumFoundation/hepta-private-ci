//! Multi-domain handoff must be complete before route publication.

use super::*;
use crate::DurableWriterHandoffJournalV1;
use crate::WriterHandoffAdvanceV1;
use crate::WriterHandoffPhaseV1;
use crate::WriterHandoffPlanV1;
use codex_hepta_control_plane::RuntimeModuleStateClassV1;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("generation")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn prepared() -> RuntimeModuleSupervisorV1 {
    let mut supervisor = RuntimeModuleSupervisorV1::new();
    let mut abi = RuntimeModuleAbiV1 {
        module_id: id("writer"),
        owner_id: id("owner"),
        generation: generation(1),
        implementation_digest: digest("old"),
        candidate_artifact_digest: digest("old"),
        predecessor_generation: None,
        rollback_predecessor_digest: Digest32::ZERO,
        state_class: RuntimeModuleStateClassV1::Stateful,
        dependencies: Vec::new(),
        input_ports: Vec::new(),
        output_ports: Vec::new(),
        authoritative_domains: [id("data"), id("index")].into_iter().collect(),
        effect_scope: Default::default(),
    };
    supervisor.register_bootstrap(abi.clone()).expect("bootstrap");
    abi.generation = generation(2);
    abi.implementation_digest = digest("new");
    abi.candidate_artifact_digest = digest("new");
    abi.predecessor_generation = Some(generation(1));
    abi.rollback_predecessor_digest = digest("old");
    supervisor
        .register_shadow_for_test(abi, digest("selection"))
        .expect("shadow");
    supervisor
        .enter_canary(&id("writer"), generation(2))
        .expect("canary");
    supervisor
}

fn checkpoint(root: &std::path::Path, domain: &str) -> WriterHandoffCheckpointV1 {
    let file = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(root.join(domain))
        .expect("journal file");
    let mut journal = DurableWriterHandoffJournalV1::create(
        file,
        WriterHandoffPlanV1 {
            operation_id: id(domain),
            domain_id: id(domain),
            source_writer: id("writer"),
            target_writer: id("writer"),
            old_generation: generation(1),
            new_generation: generation(2),
            authority_epoch: 7,
            migration_plan_digest: digest("migration"),
            schema_digest: digest("schema"),
            rollback_predecessor_digest: digest("old"),
        },
    )
    .expect("journal");
    for phase in [
        WriterHandoffPhaseV1::AdmissionStopped,
        WriterHandoffPhaseV1::Drained,
        WriterHandoffPhaseV1::OldWriterFenced,
        WriterHandoffPhaseV1::Snapshotted,
        WriterHandoffPhaseV1::Migrated,
        WriterHandoffPhaseV1::Validated,
        WriterHandoffPhaseV1::NewWriterFenced,
        WriterHandoffPhaseV1::RoutePublished,
    ] {
        journal
            .advance(WriterHandoffAdvanceV1 {
                phase,
                evidence_digest: digest(&format!("{domain}:{phase:?}")),
                outbox_watermark: (phase != WriterHandoffPhaseV1::AdmissionStopped).then_some(9),
                unknown_effect_count: 0,
            })
            .expect("advance");
    }
    journal.checkpoint().clone()
}

#[test]
fn all_domains_must_be_handed_off_before_replacement_becomes_active() {
    let root = tempfile::tempdir().expect("temp");
    let mut supervisor = prepared();
    let old = supervisor.topology();
    let data = checkpoint(root.path(), "data");
    let index = checkpoint(root.path(), "index");
    assert_eq!(
        supervisor.promote_after_writer_handoff(
            &id("writer"),
            generation(2),
            digest("canary"),
            &data
        ),
        Err(RuntimeModuleSupervisorErrorV1::IncompleteWriterHandoff)
    );
    assert_eq!(supervisor.topology(), old);
    assert_eq!(
        supervisor.promote_after_writer_handoffs(
            &id("writer"),
            generation(2),
            digest("canary"),
            &[data.clone(), data.clone()]
        ),
        Err(RuntimeModuleSupervisorErrorV1::HandoffDomainMismatch)
    );
    assert_eq!(supervisor.topology(), old);
    let new = supervisor
        .promote_after_writer_handoffs(
            &id("writer"),
            generation(2),
            digest("canary"),
            &[index, data],
        )
        .expect("all domains ready");
    assert_eq!(new.active[0].generation, generation(2));
}

#[test]
fn foreign_source_writer_or_unknown_effect_leaves_topology_unchanged() {
    let root = tempfile::tempdir().expect("temp");
    let mut supervisor = prepared();
    let old = supervisor.topology();
    let data = checkpoint(root.path(), "data");
    let index = checkpoint(root.path(), "index");
    let mut foreign = data.clone();
    foreign.plan.source_writer = id("unrelated-writer");
    assert_eq!(
        supervisor.promote_after_writer_handoffs(
            &id("writer"),
            generation(2),
            digest("canary"),
            &[foreign, index.clone()]
        ),
        Err(RuntimeModuleSupervisorErrorV1::ModuleMismatch)
    );
    let mut uncertain = data;
    uncertain.unknown_effect_count = 1;
    assert_eq!(
        supervisor.promote_after_writer_handoffs(
            &id("writer"),
            generation(2),
            digest("canary"),
            &[uncertain, index]
        ),
        Err(RuntimeModuleSupervisorErrorV1::HandoffNotTerminal)
    );
    assert_eq!(supervisor.topology(), old);
}


fn stateless_abi(
    module: &str,
    epoch: u64,
    implementation: &str,
    candidate_artifact_digest: Digest32,
    predecessor: Option<(u64, &str)>,
    dependencies: &[&str],
) -> RuntimeModuleAbiV1 {
    RuntimeModuleAbiV1 {
        module_id: id(module),
        owner_id: id("owner"),
        generation: generation(epoch),
        implementation_digest: digest(implementation),
        candidate_artifact_digest,
        predecessor_generation: predecessor.map(|(value, _)| generation(value)),
        rollback_predecessor_digest: predecessor
            .map_or(Digest32::ZERO, |(_, value)| digest(value)),
        state_class: RuntimeModuleStateClassV1::Stateless,
        dependencies: dependencies.iter().map(|value| id(value)).collect(),
        input_ports: Vec::new(),
        output_ports: Vec::new(),
        authoritative_domains: Default::default(),
        effect_scope: Default::default(),
    }
}

fn topology_candidate(
    candidate_digest: Digest32,
    selected_topology_digest: Digest32,
    deltas: Vec<RuntimeTopologyDeltaV1>,
) -> RuntimeTopologyCandidateV1 {
    RuntimeTopologyCandidateV1 {
        proposal_digest: digest("proposal"),
        candidate_id: id("candidate"),
        candidate_digest,
        baseline_generation: generation(1),
        candidate_generation: generation(2),
        selected_topology_digest,
        evaluation_digest: digest("evaluation"),
        rollback_predecessor_digest: selected_topology_digest,
        changed: true,
        deltas,
    }
}

#[test]
fn projected_topology_rejects_retiring_a_still_required_dependency() {
    let mut supervisor = RuntimeModuleSupervisorV1::new();
    supervisor
        .register_bootstrap(stateless_abi(
            "foundation",
            1,
            "foundation-v1",
            digest("foundation-v1"),
            None,
            &[],
        ))
        .expect("foundation");
    supervisor
        .register_bootstrap(stateless_abi(
            "consumer",
            1,
            "consumer-v1",
            digest("consumer-v1"),
            None,
            &["foundation"],
        ))
        .expect("consumer");
    let baseline = supervisor.topology();
    let candidate = topology_candidate(
        digest("retire-foundation"),
        baseline.digest,
        vec![RuntimeTopologyDeltaV1 {
            module_id: id("foundation"),
            operation: RuntimeTopologyOperationV1::Retire,
            related_module_ids: Vec::new(),
            predecessor_digest: digest("foundation-v1"),
            candidate_digest: Digest32::ZERO,
            evidence_digest: digest("retirement-evidence"),
        }],
    );
    assert_eq!(
        validate_projected_dependency_graph(&baseline, &candidate, &[]),
        Err(RuntimeModuleSupervisorErrorV1::TopologyDependencyMissing {
            module_id: id("consumer"),
            dependency_id: id("foundation"),
        })
    );
}

#[test]
fn projected_topology_rejects_new_dependency_cycles() {
    let mut supervisor = RuntimeModuleSupervisorV1::new();
    supervisor
        .register_bootstrap(stateless_abi(
            "alpha",
            1,
            "alpha-v1",
            digest("alpha-v1"),
            None,
            &[],
        ))
        .expect("alpha");
    let baseline = supervisor.topology();
    let candidate_digest = digest("cycle-candidate");
    let alpha = stateless_abi(
        "alpha",
        2,
        "alpha-v2",
        candidate_digest,
        Some((1, "alpha-v1")),
        &["beta"],
    );
    let beta = stateless_abi(
        "beta",
        2,
        "beta-v1",
        candidate_digest,
        None,
        &["alpha"],
    );
    let candidate = topology_candidate(
        candidate_digest,
        baseline.digest,
        vec![
            RuntimeTopologyDeltaV1 {
                module_id: id("alpha"),
                operation: RuntimeTopologyOperationV1::Replace,
                related_module_ids: Vec::new(),
                predecessor_digest: digest("alpha-v1"),
                candidate_digest: digest("alpha-v2"),
                evidence_digest: digest("alpha-evidence"),
            },
            RuntimeTopologyDeltaV1 {
                module_id: id("beta"),
                operation: RuntimeTopologyOperationV1::Add,
                related_module_ids: Vec::new(),
                predecessor_digest: Digest32::ZERO,
                candidate_digest: digest("beta-v1"),
                evidence_digest: digest("beta-evidence"),
            },
        ],
    );
    assert!(matches!(
        validate_projected_dependency_graph(&baseline, &candidate, &[alpha, beta]),
        Err(RuntimeModuleSupervisorErrorV1::TopologyDependencyCycle(_))
    ));
}

#[test]
fn topology_candidate_is_not_serving_until_atomic_finalize() {
    let mut supervisor = RuntimeModuleSupervisorV1::new();
    supervisor
        .register_bootstrap(stateless_abi(
            "foundation",
            1,
            "foundation-v1",
            digest("foundation-v1"),
            None,
            &[],
        ))
        .expect("foundation");
    let baseline = supervisor.topology();
    let candidate_digest = digest("atomic-candidate");
    let extension = stateless_abi(
        "extension",
        2,
        "extension-v1",
        candidate_digest,
        None,
        &["foundation"],
    );
    supervisor
        .register_shadow_for_test(extension, digest("selection"))
        .expect("shadow");
    supervisor
        .enter_canary(&id("extension"), generation(2))
        .expect("canary");
    let candidate = topology_candidate(
        candidate_digest,
        baseline.digest,
        vec![RuntimeTopologyDeltaV1 {
            module_id: id("extension"),
            operation: RuntimeTopologyOperationV1::Add,
            related_module_ids: Vec::new(),
            predecessor_digest: Digest32::ZERO,
            candidate_digest: digest("extension-v1"),
            evidence_digest: digest("extension-evidence"),
        }],
    );
    supervisor
        .pending_topologies
        .insert(candidate_digest, candidate);

    let staged = supervisor
        .promote_stateless(&id("extension"), generation(2), digest("canary"))
        .expect("promotion evidence staged");
    assert_eq!(staged, baseline);
    assert_eq!(supervisor.topology(), baseline);

    let committed = supervisor
        .finalize_topology_candidate(candidate_digest)
        .expect("atomic finalize");
    assert_eq!(committed.active.len(), 2);
    assert!(
        committed
            .active
            .iter()
            .any(|module| module.module_id == id("extension"))
    );
}
