//! Multi-domain handoff and transactional topology publication regressions.

use codex_hepta_control_plane::RuntimeModuleStateClassV1;
use codex_hepta_types::RuntimeTopologyDeltaV1;

use super::*;
use crate::DurableWriterHandoffJournalV1;
use crate::WriterHandoffAdvanceV1;
use crate::WriterHandoffPhaseV1;
use crate::WriterHandoffPlanV1;

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
        rollback_predecessor_digest: predecessor.map_or(Digest32::ZERO, |(_, value)| digest(value)),
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
fn projected_topology_rejects_unmaterialized_dependency() {
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
    let candidate_digest = digest("dangling-candidate");
    let extension = stateless_abi(
        "extension",
        2,
        "extension-v1",
        candidate_digest,
        None,
        &["missing.module"],
    );
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
    assert_eq!(
        validate_projected_dependency_graph(&baseline, &candidate, &[extension]),
        Err(RuntimeModuleSupervisorErrorV1::TopologyDependencyMissing {
            module_id: id("extension"),
            dependency_id: id("missing.module"),
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

// These fixtures isolate host publication from independent-token issuance,
// which is covered by the selection/evolution integration tests. They do not
// assert that fixture digests constitute independent production authority.
fn pending_extension(supervisor: &mut RuntimeModuleSupervisorV1) -> Digest32 {
    let candidate_digest = digest("pending-extension");
    let baseline = supervisor.topology();
    supervisor
        .register_shadow_for_test(
            stateless_abi("extension", 2, "extension-v1", candidate_digest, None, &[]),
            digest("selection"),
        )
        .expect("shadow");
    supervisor.pending_topologies.insert(
        candidate_digest,
        topology_candidate(
            candidate_digest,
            baseline.digest,
            vec![RuntimeTopologyDeltaV1 {
                module_id: id("extension"),
                operation: RuntimeTopologyOperationV1::Add,
                related_module_ids: Vec::new(),
                predecessor_digest: Digest32::ZERO,
                candidate_digest: digest("extension-v1"),
                evidence_digest: digest("evidence"),
            }],
        ),
    );
    candidate_digest
}

fn retirement_witness() -> RuntimeModuleRetirementWitnessV1 {
    RuntimeModuleRetirementWitnessV1 {
        drain_digest: digest("drained"),
        reconciliation_digest: digest("reconciled"),
        unknown_effect_count: 0,
    }
}

#[test]
fn finalization_rechecks_the_exact_selected_baseline_without_consuming_evidence() {
    let mut supervisor = RuntimeModuleSupervisorV1::new();
    let candidate_digest = pending_extension(&mut supervisor);
    supervisor.enter_topology_canary(candidate_digest).unwrap();
    supervisor
        .promote_stateless(&id("extension"), generation(2), digest("canary"))
        .unwrap();
    supervisor
        .register_bootstrap(stateless_abi(
            "unrelated",
            1,
            "unrelated-v1",
            digest("unrelated-v1"),
            None,
            &[],
        ))
        .unwrap();
    let before = supervisor.topology();
    let selections = supervisor.selections.clone();
    let promotions = supervisor.pending_promotions.clone();
    assert_eq!(
        supervisor.finalize_topology_candidate(candidate_digest),
        Err(RuntimeModuleSupervisorErrorV1::TopologyBaselineMismatch)
    );
    assert_eq!(supervisor.topology(), before);
    assert_eq!(supervisor.selections, selections);
    assert_eq!(supervisor.pending_promotions, promotions);
    assert!(supervisor.pending_topologies.contains_key(&candidate_digest));
}

#[test]
fn shadow_only_candidate_cannot_preload_canary_promotion_evidence() {
    let mut supervisor = RuntimeModuleSupervisorV1::new();
    pending_extension(&mut supervisor);
    let before = supervisor.topology();
    assert_eq!(
        supervisor.promote_stateless(&id("extension"), generation(2), digest("canary")),
        Err(RuntimeModuleSupervisorErrorV1::Registry(
            RuntimeModuleRegistryError::InvalidLifecycleTransition
        ))
    );
    assert_eq!(supervisor.topology(), before);
    assert!(supervisor.pending_promotions.is_empty());
}

#[test]
fn single_module_publication_cannot_bypass_dependency_validation() {
    let mut supervisor = RuntimeModuleSupervisorV1::new();
    supervisor
        .register_shadow_for_test(
            stateless_abi(
                "consumer",
                1,
                "consumer-v1",
                digest("consumer-v1"),
                None,
                &["missing"],
            ),
            digest("selection"),
        )
        .unwrap();
    supervisor.enter_canary(&id("consumer"), generation(1)).unwrap();
    let before = supervisor.topology();
    assert_eq!(
        supervisor.promote_stateless(&id("consumer"), generation(1), digest("canary")),
        Err(RuntimeModuleSupervisorErrorV1::TopologyDependencyMissing {
            module_id: id("consumer"),
            dependency_id: id("missing"),
        })
    );
    assert_eq!(supervisor.topology(), before);
    assert_eq!(
        supervisor.registry.record(&id("consumer"), generation(1)).unwrap().lifecycle,
        RuntimeModuleLifecycleV1::Canary
    );
}

#[test]
fn single_module_replacement_cannot_publish_a_dependency_cycle() {
    let mut supervisor = RuntimeModuleSupervisorV1::new();
    for (module, dependencies) in [("alpha", Vec::new()), ("beta", vec!["alpha"])] {
        supervisor
            .register_bootstrap(stateless_abi(
                module, 1, module, digest(module), None, &dependencies,
            ))
            .unwrap();
    }
    supervisor
        .register_shadow_for_test(
            stateless_abi(
                "alpha", 2, "alpha-v2", digest("alpha-v2"), Some((1, "alpha")), &["beta"],
            ),
            digest("selection"),
        )
        .unwrap();
    supervisor.enter_canary(&id("alpha"), generation(2)).unwrap();
    let before = supervisor.topology();
    assert!(matches!(
        supervisor.promote_stateless(&id("alpha"), generation(2), digest("canary")),
        Err(RuntimeModuleSupervisorErrorV1::TopologyDependencyCycle(_))
    ));
    assert_eq!(supervisor.topology(), before);
    assert_eq!(supervisor.registry.active_generation(&id("alpha")), Some(generation(1)));
}

#[test]
fn discarded_candidate_releases_work_but_cannot_be_promoted_or_replayed() {
    let mut supervisor = RuntimeModuleSupervisorV1::new();
    let candidate_digest = pending_extension(&mut supervisor);
    supervisor.enter_topology_canary(candidate_digest).unwrap();
    supervisor
        .promote_stateless(&id("extension"), generation(2), digest("canary"))
        .unwrap();
    let before = supervisor.topology();
    supervisor.discard_topology_candidate(candidate_digest).unwrap();
    assert_eq!(supervisor.topology(), before);
    assert!(supervisor.selections.is_empty());
    assert!(supervisor.pending_promotions.is_empty());
    assert!(supervisor.pending_topologies.is_empty());
    assert_eq!(
        supervisor.promote_stateless(&id("extension"), generation(2), digest("canary")),
        Err(RuntimeModuleSupervisorErrorV1::MissingVerifiedSelection)
    );
    assert!(
        supervisor
            .registry
            .register_candidate(stateless_abi(
                "extension", 2, "extension-v1", candidate_digest, None, &[],
            ))
            .is_err()
    );
}

#[test]
fn thousand_upgrades_keep_supervisor_selection_and_retirement_metadata_bounded() {
    let mut supervisor = RuntimeModuleSupervisorV1::new();
    supervisor
        .register_bootstrap(stateless_abi("module", 1, "v1", digest("v1"), None, &[]))
        .unwrap();
    for epoch in 2..=1_001 {
        let implementation = format!("v{epoch}");
        let predecessor = format!("v{}", epoch - 1);
        supervisor
            .record_retirement_ready(&id("module"), generation(epoch - 1), retirement_witness())
            .unwrap();
        supervisor
            .register_shadow_for_test(
                stateless_abi(
                    "module",
                    epoch,
                    &implementation,
                    digest(&implementation),
                    Some((epoch - 1, &predecessor)),
                    &[],
                ),
                digest("selection"),
            )
            .unwrap();
        supervisor.enter_canary(&id("module"), generation(epoch)).unwrap();
        let snapshot = supervisor
            .promote_stateless(&id("module"), generation(epoch), digest("canary"))
            .unwrap();
        assert_eq!(snapshot.active.len(), 1);
        assert_eq!(snapshot.active[0].generation, generation(epoch));
        assert_eq!(supervisor.selections.len(), 1);
        assert!(supervisor.retirement_ready.is_empty());
    }
}

#[test]
fn retire_only_proposals_have_a_reusable_pending_budget() {
    let mut supervisor = RuntimeModuleSupervisorV1::new();
    let baseline = supervisor.topology().digest;
    for index in 0..MAX_PENDING_TOPOLOGIES {
        supervisor.ensure_topology_capacity().unwrap();
        let proposal = digest(&format!("proposal-{index}"));
        supervisor.pending_topologies.insert(
            proposal,
            topology_candidate(
                proposal,
                baseline,
                vec![RuntimeTopologyDeltaV1 {
                    module_id: id("retiring"),
                    operation: RuntimeTopologyOperationV1::Retire,
                    related_module_ids: Vec::new(),
                    predecessor_digest: digest("retiring-v1"),
                    candidate_digest: Digest32::ZERO,
                    evidence_digest: digest("evidence"),
                }],
            ),
        );
    }
    assert_eq!(
        supervisor.ensure_topology_capacity(),
        Err(RuntimeModuleSupervisorErrorV1::PendingTopologyCapacity)
    );
    supervisor.discard_topology_candidate(digest("proposal-0")).unwrap();
    supervisor.ensure_topology_capacity().unwrap();
    assert_eq!(supervisor.pending_topologies.len(), MAX_PENDING_TOPOLOGIES - 1);
    assert!(supervisor.selections.is_empty());
}

#[test]
fn blocked_retirement_does_not_leave_a_ready_marker() {
    let mut supervisor = RuntimeModuleSupervisorV1::new();
    for (module, dependencies) in [("foundation", Vec::new()), ("consumer", vec!["foundation"])] {
        supervisor
            .register_bootstrap(stateless_abi(
                module, 1, module, digest(module), None, &dependencies,
            ))
            .unwrap();
    }
    let before = supervisor.topology();
    assert!(matches!(
        supervisor.retire_after_reconciliation(&id("foundation"), generation(1), retirement_witness()),
        Err(RuntimeModuleSupervisorErrorV1::Registry(
            RuntimeModuleRegistryError::SelectedDependent(_)
        ))
    ));
    assert_eq!(supervisor.topology(), before);
    assert!(supervisor.retirement_ready.is_empty());
}

#[test]
fn topology_retires_dependents_before_providers_regardless_of_delta_order() {
    let mut supervisor = RuntimeModuleSupervisorV1::new();
    let mut deltas = Vec::new();
    for (module, dependencies) in [("alpha", Vec::new()), ("zeta", vec!["alpha"])] {
        supervisor
            .register_bootstrap(stateless_abi(
                module, 1, module, digest(module), None, &dependencies,
            ))
            .unwrap();
        supervisor
            .record_retirement_ready(&id(module), generation(1), retirement_witness())
            .unwrap();
        deltas.push(RuntimeTopologyDeltaV1 {
            module_id: id(module),
            operation: RuntimeTopologyOperationV1::Retire,
            related_module_ids: Vec::new(),
            predecessor_digest: digest(module),
            candidate_digest: Digest32::ZERO,
            evidence_digest: digest("retire"),
        });
    }
    let candidate_digest = digest("retire-chain");
    supervisor.pending_topologies.insert(
        candidate_digest,
        topology_candidate(candidate_digest, supervisor.topology().digest, deltas),
    );
    let result = supervisor.finalize_topology_candidate(candidate_digest).unwrap();
    assert!(result.active.is_empty());
    assert!(supervisor.pending_topologies.is_empty());
    assert!(supervisor.retirement_ready.is_empty());
}

#[test]
fn topology_can_rewire_a_consumer_and_retire_its_old_provider_atomically() {
    let mut supervisor = RuntimeModuleSupervisorV1::new();
    for (module, dependencies) in [("foundation", Vec::new()), ("consumer", vec!["foundation"])] {
        supervisor
            .register_bootstrap(stateless_abi(
                module, 1, module, digest(module), None, &dependencies,
            ))
            .unwrap();
    }
    let before = supervisor.topology();
    let candidate_digest = digest("rewire-and-retire");
    supervisor
        .register_shadow_for_test(
            stateless_abi(
                "consumer", 2, "consumer-v2", candidate_digest, Some((1, "consumer")), &[],
            ),
            digest("selection"),
        )
        .unwrap();
    supervisor.enter_canary(&id("consumer"), generation(2)).unwrap();
    supervisor.pending_topologies.insert(
        candidate_digest,
        topology_candidate(
            candidate_digest,
            before.digest,
            vec![
                RuntimeTopologyDeltaV1 {
                    module_id: id("foundation"),
                    operation: RuntimeTopologyOperationV1::Retire,
                    related_module_ids: Vec::new(),
                    predecessor_digest: digest("foundation"),
                    candidate_digest: Digest32::ZERO,
                    evidence_digest: digest("retire"),
                },
                RuntimeTopologyDeltaV1 {
                    module_id: id("consumer"),
                    operation: RuntimeTopologyOperationV1::Rewire,
                    related_module_ids: Vec::new(),
                    predecessor_digest: digest("consumer"),
                    candidate_digest: digest("consumer-v2"),
                    evidence_digest: digest("rewire"),
                },
            ],
        ),
    );
    supervisor
        .record_retirement_ready(&id("foundation"), generation(1), retirement_witness())
        .unwrap();
    let staged = supervisor
        .promote_stateless(&id("consumer"), generation(2), digest("canary"))
        .unwrap();
    assert_eq!(staged, before);
    let result = supervisor.finalize_topology_candidate(candidate_digest).unwrap();
    assert_eq!(result.active.len(), 1);
    assert_eq!(result.active[0].module_id, id("consumer"));
    assert_eq!(result.active[0].generation, generation(2));
    assert!(result.active[0].dependencies.is_empty());
}
