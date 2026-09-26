use super::*;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::DatasetFreezeRequestV1;
use codex_hepta_learning_ledger::freeze_dataset_receipt_v3;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;

use crate::TabularOperatorSampleV1;

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).expect("valid id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn actor() -> AuthenticatedPrincipalV1 {
    AuthenticatedPrincipalV1 {
        principal_id: id("dataset-owner"),
        credential_chain_digest: digest("dataset-owner-credential"),
        signing_key_digest: digest("dataset-owner-key"),
        scope_digest: digest("scope"),
        authority_epoch: 9,
        authenticated_at: 10,
        expires_at: 100,
    }
}

fn receipt(records: Vec<Digest32>) -> DatasetSnapshotReceiptV3 {
    freeze_dataset_receipt_v3(
        DatasetFreezeRequestV1 {
            snapshot_id: id("dataset-snapshot"),
            producer: actor(),
            ledger_head_digest: digest("ledger-head"),
            objective_digest: digest("objective"),
            eligible_frontier: 7,
            outcome_watermark: 50,
            correction_cut_digest: digest("correction-cut"),
            revocation_cut_digest: digest("revocation-cut"),
            inclusion_policy_digest: digest("inclusion-policy"),
            source_record_digests: records,
            pending_outcomes: 0,
            censored_outcomes: 0,
        },
        50,
    )
    .expect("valid dataset receipt")
}

fn tabular_plan(dataset_digest: Digest32, evidence: [Digest32; 2]) -> TabularOperatorPlanV1 {
    TabularOperatorPlanV1 {
        artifact_id: id("artifact"),
        producer_id: id("trainer"),
        generation: Generation::new(1).expect("generation"),
        objective_digest: digest("objective"),
        dataset_digest,
        sensor_core_digest: digest("sensor-core"),
        training_profile_digest: digest("profile"),
        minimum_samples_per_cell: 2,
        sensor_ids: vec![id("sensor")],
        action_ids: vec![id("action")],
        samples: vec![
            TabularOperatorSampleV1 {
                sample_id: id("sample-a"),
                sensor_id: id("sensor"),
                action_id: id("action"),
                target: FixedQ32::from_raw(10),
                evidence_digest: evidence[0],
            },
            TabularOperatorSampleV1 {
                sample_id: id("sample-b"),
                sensor_id: id("sensor"),
                action_id: id("action"),
                target: FixedQ32::from_raw(20),
                evidence_digest: evidence[1],
            },
        ],
    }
}

#[test]
fn op_06_tabular_fit_requires_exact_frozen_dataset_evidence() {
    let records = [digest("record-a"), digest("record-b")];
    let receipt = receipt(vec![records[0], records[1]]);
    let verified = verify_tabular_operator_plan_v2(
        tabular_plan(receipt.snapshot.dataset_digest, records),
        &receipt,
        50,
    )
    .expect("exact receipt binds plan");
    let artifact = fit_tabular_operator_verified_v2(verified).expect("fit");
    assert_eq!(artifact.dataset_digest, receipt.snapshot.dataset_digest);

    let mismatch = tabular_plan(
        receipt.snapshot.dataset_digest,
        [records[0], digest("other-record")],
    );
    assert!(matches!(
        verify_tabular_operator_plan_v2(mismatch, &receipt, 50),
        Err(OperatorDatasetBindingError::EvidenceSetMismatch)
    ));
}

#[test]
fn op_06_world_model_requires_exact_frozen_dataset_evidence() {
    let records = [digest("record-a"), digest("record-b")];
    let extra_support = receipt(vec![records[0], records[1], digest("support-record")]);
    let receipt = receipt(vec![records[0], records[1]]);
    let rows = vec![
        WorldModelSampleV1 {
            sample_id: id("sample-a"),
            state_id: id("state"),
            action_id: id("action"),
            next_state_id: id("next-a"),
            outcome: FixedQ32::from_raw(10),
            evidence_digest: records[0],
        },
        WorldModelSampleV1 {
            sample_id: id("sample-b"),
            state_id: id("state"),
            action_id: id("action"),
            next_state_id: id("next-b"),
            outcome: FixedQ32::from_raw(20),
            evidence_digest: records[1],
        },
    ];
    assert!(matches!(
        verify_world_model_dataset_v2(id("world-model"), rows.clone(), &extra_support, 50),
        Err(OperatorDatasetBindingError::EvidenceSetMismatch)
    ));
    let verified =
        verify_world_model_dataset_v2(id("world-model"), rows, &receipt, 50).expect("bind rows");
    let model = fit_transition_model_verified_v2(verified).expect("fit");
    assert_eq!(model.dataset_digest, receipt.snapshot.dataset_digest);
}

#[test]
fn op_07_row_semantics_payload_binds_every_tabular_field() {
    let records = [digest("record-a"), digest("record-b")];
    let receipt = receipt(records.to_vec());
    let mut plan = tabular_plan(receipt.snapshot.dataset_digest, records);
    let baseline = canonical_tabular_row_semantics_v1(&plan, &receipt).expect("canonical");

    plan.samples[0].target = FixedQ32::from_raw(11);
    let changed_target = canonical_tabular_row_semantics_v1(&plan, &receipt).expect("canonical");
    assert_ne!(Digest32::of_bytes(&baseline), Digest32::of_bytes(&changed_target));

    plan.samples[0].target = FixedQ32::from_raw(10);
    plan.samples[0].action_id = id("changed-action");
    let changed_action = canonical_tabular_row_semantics_v1(&plan, &receipt).expect("canonical");
    assert_ne!(Digest32::of_bytes(&baseline), Digest32::of_bytes(&changed_action));
}

#[test]
fn op_07_world_model_payload_binds_transition_semantics() {
    let records = [digest("record-a")];
    let receipt = receipt(records.to_vec());
    let mut rows = vec![WorldModelSampleV1 {
        sample_id: id("sample-a"),
        state_id: id("state"),
        action_id: id("action"),
        next_state_id: id("next"),
        outcome: FixedQ32::from_raw(10),
        evidence_digest: records[0],
    }];
    let baseline = canonical_world_model_row_semantics_v1(&id("model"), &rows, &receipt)
        .expect("canonical");
    rows[0].next_state_id = id("changed-next");
    let changed = canonical_world_model_row_semantics_v1(&id("model"), &rows, &receipt)
        .expect("canonical");
    assert_ne!(Digest32::of_bytes(&baseline), Digest32::of_bytes(&changed));
}
