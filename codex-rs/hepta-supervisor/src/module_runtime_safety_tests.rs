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
