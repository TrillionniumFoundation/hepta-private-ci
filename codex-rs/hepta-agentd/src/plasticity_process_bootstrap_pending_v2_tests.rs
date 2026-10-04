use super::*;
use codex_hepta_agent_components::learning_ledger::CandidateSetCompleteness;
use codex_hepta_agent_components::learning_ledger::EpisodeDecision;
use codex_hepta_agent_components::learning_ledger::LedgerEvent;
use codex_hepta_agent_components::plasticity::ProposalWindowV2;
use codex_hepta_agent_components::types::ProbabilityQ32;
use serde_json::json;

fn descriptor(root: &Path) -> serde_json::Value {
    let digest = Digest32::of_bytes(b"original test binding").to_string();
    json!({
        "schema":SCHEMA,"agent_id":"018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12",
        "spawn_generation":1,"queue_capacity":4,"objective_digest":digest,
        "artifacts":{"path":root.join("snapshot"),"receipt":{
            "binding":digest,"head_digest":digest,"file_digest":digest,"records":3,"encoded_bytes":128},
            "observed_at":1,"expires_at":100,"update_rule_artifact_id":"policy:update-rule",
            "mutation_policy_artifact_id":"policy:mutation","broadcast_artifact_id":"policy:broadcast"},
        "ledger":{"path":root.join("ledger"),"binding":digest,"max_records":8,
            "anchor_sequence":0,"anchor_chain_digest":Digest32::ZERO.to_string()},
        "trust":{"scope_digest":digest,"objective_digest":digest,"authority_epoch":1,"signers":[]},
        "owner_policy":{"dataset_owner_id":"owner:dataset","update_rule_owner_id":"owner:update-rule",
            "modulator_owner_id":"owner:modulator","modulator_broadcast_owner_id":"owner:broadcast",
            "eligibility_owner_id":"owner:neuron","parameter_signal_owner_id":"owner:neuron",
            "mutation_policy_owner_id":"owner:mutation"},
        "parameter_registry":{"mode":"bootstrap_new","registry_path":root.join("parameter"),
            "anchor_path":root.join("parameter-anchor"),"scope_digest":digest,"maximum_records":8},
        "topology_registry":{"mode":"bootstrap_new","registry_path":root.join("topology"),
            "anchor_path":root.join("topology-anchor"),"scope_digest":digest,"maximum_records":8}
    })
}

#[test]
fn pending_schema_has_no_legacy_neuron_or_unsigned_dataset_surface() {
    let directory = tempfile::tempdir().expect("original independent paths");
    let value = descriptor(directory.path());
    let pending: PendingV2Descriptor =
        serde_json::from_value(value.clone()).expect("pending schema");
    assert!(pending.input_context.is_none());
    for (field, data) in [
        ("neuron", json!({"journal_path":"/fake-v1"})),
        ("dataset", json!({"snapshot":"unsigned"})),
        ("ndu", json!({"path":"/old-projection"})),
    ] {
        let mut changed = value.clone();
        changed[field] = data;
        assert!(
            serde_json::from_value::<PendingV2Descriptor>(changed).is_err(),
            "{field}"
        );
    }
}

#[test]
fn original_anchored_writers_reopen_without_a_round_and_never_fall_back_after_corruption() {
    let directory = tempfile::tempdir().expect("original writer paths");
    let mut pending: PendingV2Descriptor =
        serde_json::from_value(descriptor(directory.path())).expect("descriptor");
    let mut ledger = DurableLedger::create(
        create_new_rw(&pending.ledger.path, "original learning ledger").expect("new original file"),
        digest(&pending.ledger.binding, "binding").expect("binding"),
        pending.ledger.max_records,
    )
    .expect("original ledger initialization");
    let receipt = ledger
        .append_qualification(
            Digest32::ZERO,
            LedgerEvent::Decision(EpisodeDecision {
                record_id: StableId::new("decision.pending-startup").expect("id"),
                episode_id: StableId::new("episode.pending-startup").expect("id"),
                objective_digest: digest(&pending.objective_digest, "objective")
                    .expect("objective"),
                policy_id: StableId::new("policy.pending-startup").expect("id"),
                candidate_ids: vec![
                    StableId::new("candidate.pending-startup").expect("id"),
                    StableId::new("abstain").expect("original mandatory candidate"),
                ],
                selected_candidate_id: StableId::new("candidate.pending-startup").expect("id"),
                selected_propensity: ProbabilityQ32::ONE,
                completeness: CandidateSetCompleteness::Complete,
                support_digest: Digest32::of_bytes(b"original decision support"),
            }),
        )
        .expect("original durable qualification receipt, not independent custody");
    pending.ledger.anchor_sequence = receipt.sequence.get();
    pending.ledger.anchor_chain_digest = receipt.chain_digest.to_string();
    drop(ledger);
    let ledger = load_ledger(&pending.ledger).expect("actual original nonempty acknowledged head");
    assert_eq!(
        ledger.snapshot().expect("original snapshot").head_digest,
        receipt.chain_digest
    );
    drop(ledger);
    let parameter = open_parameter_writer(&pending.parameter_registry)
        .expect("initialize original parameter owners");
    let topology = open_topology_writer(&pending.topology_registry)
        .expect("initialize original topology owners");
    drop((parameter, topology));
    let paths = [
        &pending.ledger.path,
        &pending.parameter_registry.registry_path,
        &pending.parameter_registry.anchor_path,
        &pending.topology_registry.registry_path,
        &pending.topology_registry.anchor_path,
    ];
    let before = paths
        .iter()
        .map(std::fs::read)
        .collect::<Result<Vec<_>, _>>()
        .expect("whole original stores");
    pending.parameter_registry.mode = RegistryOpenModeV1::ReopenAnchored;
    pending.topology_registry.mode = RegistryOpenModeV1::ReopenAnchored;
    // Header-only registries have no acknowledged proposal. The anchored mode
    // must reject them rather than invent an anchor at startup.
    assert!(open_parameter_writer(&pending.parameter_registry).is_err());
    assert!(open_topology_writer(&pending.topology_registry).is_err());
    pending.parameter_registry.mode = RegistryOpenModeV1::ResumeUnacknowledged;
    pending.topology_registry.mode = RegistryOpenModeV1::ResumeUnacknowledged;
    drop(open_parameter_writer(&pending.parameter_registry).expect("cold parameter owner"));
    drop(open_topology_writer(&pending.topology_registry).expect("cold topology owner"));
    assert_eq!(
        paths
            .iter()
            .map(std::fs::read)
            .collect::<Result<Vec<_>, _>>()
            .expect("cold stores"),
        before
    );
    std::fs::write(
        &pending.parameter_registry.registry_path,
        b"broken original history",
    )
    .expect("counterexample");
    let corrupted =
        std::fs::read(&pending.parameter_registry.registry_path).expect("corrupt bytes");
    assert!(open_parameter_writer(&pending.parameter_registry).is_err());
    assert_eq!(
        std::fs::read(&pending.parameter_registry.registry_path).expect("no fresh fallback"),
        corrupted
    );
    pending.ledger.anchor_sequence = receipt.sequence.get();
    pending.ledger.anchor_chain_digest =
        Digest32::of_bytes(b"invented acknowledgement").to_string();
    assert!(load_ledger(&pending.ledger).is_err());
    assert_eq!(
        std::fs::read(&pending.ledger.path).expect("unchanged original ledger"),
        before[0]
    );
}

#[test]
fn pending_resolver_cannot_turn_any_advice_into_owner_evidence() {
    let query = PlasticityOwnerEvidenceQueryV1 {
        kind: PlasticityOwnerEvidenceKindV1::Dataset,
        evidence_digest: Digest32::of_bytes(b"unsigned dataset"),
        objective_digest: Digest32::of_bytes(b"training"),
        selected_artifact_digest: Digest32::of_bytes(b"native head"),
        artifact_registry_head_digest: Digest32::of_bytes(b"registry"),
        qualification_evidence_head_digest: Digest32::of_bytes(b"ledger"),
        window: ProposalWindowV2 {
            window_id: StableId::new("window.pending").expect("id"),
            window_digest: Digest32::of_bytes(b"window"),
        },
        dataset_digest: Digest32::of_bytes(b"dataset"),
        baseline_generation: Generation::new(1).expect("generation"),
        layer_id: None,
        parameter_id: None,
        signal_eligibility: None,
        signal_modulator: None,
        signal_learning_rate: None,
        signal_lower_bound: None,
        signal_upper_bound: None,
        now: 50,
    };
    for kind in [
        PlasticityOwnerEvidenceKindV1::Dataset,
        PlasticityOwnerEvidenceKindV1::Eligibility,
        PlasticityOwnerEvidenceKindV1::ParameterSignal,
    ] {
        let query = PlasticityOwnerEvidenceQueryV1 {
            kind,
            ..query.clone()
        };
        assert_eq!(
            PendingV2Resolver.resolve(&query),
            Err(PlasticityOwnerEvidenceErrorV1::Missing)
        );
    }
}

#[cfg(unix)]
#[test]
fn same_inode_across_ledger_and_native_proposal_owners_is_rejected() {
    let directory = tempfile::tempdir().expect("original mutable paths");
    let pending: PendingV2Descriptor =
        serde_json::from_value(descriptor(directory.path())).expect("descriptor");
    std::fs::write(&pending.ledger.path, b"original ledger").expect("ledger");
    std::fs::hard_link(
        &pending.ledger.path,
        &pending.parameter_registry.registry_path,
    )
    .expect("foreign alias");
    assert!(
        validate_mutable_owner_paths(&[
            &pending.ledger.path,
            &pending.parameter_registry.registry_path
        ])
        .is_err()
    );
}
