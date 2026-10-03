//! Actual Unix clock through durable ledger, root activation and final-use fitting.
use super::*;

fn wall_micros() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_micros()
        .try_into()
        .unwrap()
}

#[test]
fn real_wall_clock_millisecond_authority_reaches_microsecond_final_use_fit_and_reload() {
    let now = wall_micros() / 1_000;
    let fixture = Fixture::with_candidates_and_expiry_at(
        vec![id("action"), id("abstain")],
        now + 90_000,
        now,
    );
    let (receipt, freeze) = fixture.dataset_at(wall_micros() / 1_000, now + 60_000);
    let profile = crate::TrainingProfileV1::new(
        hash("objective"),
        hash("sensors"),
        receipt.snapshot.eligible_frontier,
        1,
        FixedQ32::ONE,
        crate::OperatorResourceBudgetV1::qualification_default(),
    )
    .unwrap();
    let mut input = plan(&receipt);
    input.training_profile_digest = profile.digest();
    let row = sign_at(
        &fixture.owner,
        "observer",
        2,
        LearningEvidenceRoleV1::Observer,
        &tabular_training_signing_payload_v2(&input, &receipt, &fixture.owner).unwrap(),
        now,
        now + 60_000,
    );
    let request = crate::TabularTrainingRequestV1::new(
        input.artifact_id,
        input.producer_id,
        input.generation,
        profile,
        input.sensor_ids,
        input.action_ids,
        input.samples,
    )
    .unwrap();
    let observed = wall_micros();
    let generation = Generation::new(1).unwrap();
    let fence = crate::FinalUseFenceV1::new(
        receipt.snapshot.ledger_head_digest,
        receipt.snapshot.eligible_frontier,
        generation,
        7,
        3,
        observed + 30_000_000,
    )
    .unwrap();
    let witness = crate::FinalUseWitnessV1::new(
        observed,
        receipt.snapshot.ledger_head_digest,
        receipt.snapshot.eligible_frontier,
        generation,
        7,
        3,
        false,
    )
    .unwrap();
    let capability = crate::issue_tabular_final_use_capability_v1(
        &fixture.owner,
        &receipt,
        &freeze,
        &row,
        request,
        fence,
        crate::WorkControlV1::new(),
        &witness,
    )
    .unwrap();
    let candidate = crate::fit_tabular_final_use_v1(capability, &witness, &witness).unwrap();
    let publication = candidate.publication_view();
    assert!(publication.published_at_unix_micros() >= observed);
    assert_eq!(
        publication.dataset_digest(),
        receipt.snapshot.dataset_digest
    );
    let selection = crate::SelectionCurrentnessV1::new(
        candidate.artifact_digest(),
        hash("host-selection"),
        publication.runtime_profile_digest(),
        publication.trust_digest(),
        hash("current-owner-registry"),
        receipt.snapshot.ledger_head_digest,
        generation,
        7,
        3,
        wall_micros().max(publication.published_at_unix_micros()),
        observed + 20_000_000,
        false,
    )
    .unwrap();
    let selected = candidate.pin_for_selection(selection).unwrap();
    let loaded = selected.load(wall_micros()).unwrap();
    let prediction = loaded
        .predict(&id("sensor"), &id("action"), wall_micros())
        .unwrap();
    assert_eq!(prediction.value, FixedQ32::from_raw(20));
    assert!(!prediction.authority.grants_any());
}
