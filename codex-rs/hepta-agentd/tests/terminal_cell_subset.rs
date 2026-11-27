#![allow(
    clippy::unwrap_used,
    reason = "integration assertions and fixture setup must fail the test immediately"
)]

use codex_hepta_bellman_operator::*;
use codex_hepta_learning_ledger::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;

#[path = "support/terminal_cell_owner.rs"]
mod support;
use support::Fixture;
use support::decision;
use support::digest;
use support::id;
use support::outcome;
use support::sign;

fn observed(selected: &[&str]) -> (Fixture, LedgerWriter, DatasetSnapshotReceiptV3) {
    let fixture = Fixture::new();
    let mut owner = fixture.writer();
    let now = 50;
    for (index, action) in selected.iter().enumerate() {
        let mut request = decision();
        request.record_id = id(&format!("subset-{index}.decision"));
        request.episode_id = id(&format!("subset-{index}.episode"));
        request.selected_candidate_id = id(action);
        let episode = request.episode_id.clone();
        let signed = sign(
            owner.verifier(),
            "generator",
            LearningEvidenceRoleV1::Generator,
            &decision_signing_payload_v2(&request).unwrap(),
        );
        let head = owner.witness_frontier().unwrap().anchor.chain_digest;
        let receipt = owner.append_decision(head, request, &signed, now).unwrap();
        let value = (index as i64) * FixedQ32::ONE.raw();
        let mut terminal = outcome(
            &format!("subset-{index}.record"),
            &format!("subset-{index}.result"),
            /*predecessor*/ None,
            value,
        );
        terminal.episode_id = episode;
        let signed = sign(
            owner.verifier(),
            "observer",
            LearningEvidenceRoleV1::Observer,
            &outcome_signing_payload_v2(&terminal),
        );
        owner
            .append_outcome(receipt.chain_digest, terminal, &signed, now)
            .unwrap();
    }
    let plan = DatasetFreezePlanV2 {
        snapshot_id: id("supported-owner-dataset"),
        objective_digest: digest("objective"),
        inclusion_policy_digest: digest("all-authenticated-owner-records"),
    };
    let signed = sign(
        owner.verifier(),
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        &dataset_freeze_signing_payload_v2(&owner.snapshot().unwrap(), &plan).unwrap(),
    );
    let dataset = owner.freeze_dataset(plan, &signed, now).unwrap();
    (fixture, owner, dataset)
}

fn profile() -> TerminalSupportedCellProfileV1 {
    let generation = 1;
    TerminalSupportedCellProfileV1 {
        cells: TerminalCellProfileV1 {
            artifact_id: id("supported-owner-model"),
            producer_id: id("owner"),
            generation: Generation::new(generation).unwrap(),
            sensor_id: id("one-state"),
            objective_digest: digest("objective"),
            run_snapshot_digest: digest("run-snapshot"),
            unit_profile_digest: digest("reward-units"),
            action_ids: vec![id("read")],
            minimum_samples_per_action: 1,
        },
        candidate_ids: vec![id("abstain"), id("read")],
    }
}

#[test]
fn observed_subset_keeps_complete_grammar_without_inventing_abstain_target() {
    let (_fixture, owner, data) = observed(&["read", "read"]);
    let now = 50;
    let profile = profile();
    // Existing V1 still rejects an action set smaller than the admitted set.
    assert!(freeze_terminal_cell_from_owner_v1(&owner, &data, profile.cells.clone(), now).is_err());
    let mut complete = profile.cells.clone();
    complete.action_ids = profile.candidate_ids.clone();
    let legacy = freeze_terminal_cell_from_owner_v1(&owner, &data, complete, now).unwrap();
    assert!(fit_terminal_cell_from_owner_v1(&owner, legacy, now).is_err());
    let frozen =
        freeze_supported_terminal_cells_from_owner_v1(&owner, &data, profile.clone(), now).unwrap();
    assert_eq!(frozen.sample_count(), 2);
    let trained = fit_terminal_cell_from_owner_v1(&owner, frozen, now).unwrap();
    assert_eq!(trained.cells.len(), 1);
    assert_eq!(
        (
            trained.cells[0].action_id.clone(),
            trained.cells[0].sample_count,
            trained.cells[0].mean_target
        ),
        (id("read"), 2, FixedQ32::from_raw(FixedQ32::ONE.raw() / 2))
    );
    let bytes = encode_tabular_payload_v1(&trained).unwrap();
    let pin = TabularPayloadPinV1 {
        payload_digest: Digest32::of_bytes(&bytes),
        artifact_digest: trained.artifact_digest,
        objective_digest: trained.objective_digest,
        dataset_digest: trained.dataset_digest,
        sensor_core_digest: trained.sensor_core_digest,
        training_profile_digest: trained.training_profile_digest,
        generation: trained.generation,
    };
    let loaded = LoadedTabularOperatorV1::from_pinned_payload(&bytes, &pin).unwrap();
    assert_eq!(
        loaded
            .predict(&profile.cells.sensor_id, &id("read"))
            .unwrap()
            .value,
        FixedQ32::from_raw(FixedQ32::ONE.raw() / 2)
    );
    assert!(
        loaded
            .predict(&profile.cells.sensor_id, &id("abstain"))
            .is_err()
    );
}

#[test]
fn subset_rejects_missing_support_bad_grammar_and_omitted_observed_actions() {
    let (_fixture, owner, data) = observed(&["read"]);
    let mut variants = Vec::new();
    let mut changed = profile();
    changed.cells.action_ids.clear();
    variants.push(changed);
    let mut changed = profile();
    changed.cells.action_ids.push(id("read"));
    variants.push(changed);
    let mut changed = profile();
    changed.cells.action_ids.push(id("abstain"));
    variants.push(changed);
    let mut changed = profile();
    changed.cells.action_ids.push(id("unregistered"));
    variants.push(changed);
    let mut changed = profile();
    changed.cells.minimum_samples_per_action = 2;
    variants.push(changed);
    let mut changed = profile();
    changed.candidate_ids.push(id("read"));
    variants.push(changed);
    let mut changed = profile();
    changed.candidate_ids.push(id("unobserved"));
    variants.push(changed);
    let mut changed = profile();
    changed.candidate_ids.retain(|id| id.as_str() != "abstain");
    variants.push(changed);
    for changed in variants {
        assert!(
            freeze_supported_terminal_cells_from_owner_v1(&owner, &data, changed, /*now*/ 50)
                .is_err()
        );
    }
    let (_other_fixture, other, other_data) = observed(&["read", "abstain"]);
    // An actually observed abstain cannot disappear through subset selection.
    assert!(
        freeze_supported_terminal_cells_from_owner_v1(
            &other,
            &other_data,
            profile(),
            /*now*/ 50
        )
        .is_err()
    );
}
