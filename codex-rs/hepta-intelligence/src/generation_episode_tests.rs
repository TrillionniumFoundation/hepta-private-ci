use codex_hepta_learning_ledger::AppendDisposition;
use codex_hepta_learning_ledger::AuthenticatedOutcomeV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::ProductionDecisionV2;
use codex_hepta_learning_ledger::decision_signing_payload_v2;
use codex_hepta_neuron::CellCostTotalV2;
use codex_hepta_neuron::CellGenerationDispositionV2;
use codex_hepta_neuron::CellTaskCostV2;

use super::*;
use crate::generation_episode_test_support::GenerationFixture;
use crate::outcome_credit_v2::tests as ledger_support;
use ledger_support::digest;

fn decision(frozen: &FrozenGenerationEpisodeV1) -> ProductionDecisionV2 {
    let mut request = ledger_support::decision();
    request.record_id = frozen.input().decision_id.clone();
    request.episode_id = frozen.input().episode_id.clone();
    request.run_snapshot_digest = frozen.contract_digest();
    request.objective_digest = frozen.input().objective_digest;
    request.policy_digest = frozen.input().policy_digest;
    request.support_digest = frozen.decision_support_digest();
    request
}

fn append_decision(writer: &mut LedgerWriter, request: ProductionDecisionV2) -> AppendReceipt {
    let payload = decision_signing_payload_v2(&request).expect("decision payload");
    let evidence = ledger_support::sign(
        writer.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &payload,
    );
    writer
        .append_decision(Digest32::ZERO, request, &evidence, /*now*/ 50)
        .expect("decision")
}

fn outcome(
    frozen: &FrozenGenerationEpisodeV1,
    observation: &CellGenerationObservationV1,
) -> AuthenticatedOutcomeV1 {
    let support = frozen
        .outcome_evidence(observation)
        .expect("terminal support");
    let mut value = ledger_support::outcome(
        "generation-observation",
        "generation-quality",
        /*predecessor*/ None,
        /*value*/ 100,
    );
    value.episode_id = frozen.input().episode_id.clone();
    value.unit_profile_digest = frozen.input().evaluation_profile_digest;
    value.support_digest = support.support_digest();
    value
}

fn settled(fixture: &GenerationFixture) -> CellGenerationObservationV1 {
    let mut journal = fixture.open();
    let request = fixture.request(&journal, "stop");
    journal
        .admit(request.clone(), /*now_micros*/ 11)
        .expect("admit");
    journal
        .commit(
            fixture.proposal(&request, CellGenerationDispositionV2::Stopped, &[]),
            /*now_micros*/ 20,
        )
        .expect("settle");
    journal.observe_generation().expect("owner observation")
}

#[test]
fn owner_terminal_and_delivery_cut_precedes_independently_signed_outcome() {
    let fixture = GenerationFixture::new();
    let mut journal = fixture.open();
    let request = fixture.request(&journal, "stop-and-deliver");
    journal
        .admit(request.clone(), /*now_micros*/ 11)
        .expect("admit");
    assert!(
        fixture
            .frozen
            .outcome_evidence(&journal.observe_generation().expect("pending"))
            .is_err()
    );
    journal
        .commit(
            fixture.proposal(
                &request,
                CellGenerationDispositionV2::Stopped,
                b"immutable prefix",
            ),
            /*now_micros*/ 20,
        )
        .expect("settle");
    assert!(
        fixture
            .frozen
            .outcome_evidence(&journal.observe_generation().expect("outbox"))
            .is_err()
    );
    let chunk = journal
        .pending_output()
        .expect("outbox")
        .cloned()
        .expect("chunk");
    let delivery_cost =
        CellTaskCostV2::new(journal.task_cost().expect("cost").identity()).expect("delivery cost");
    journal
        .acknowledge(chunk, digest("delivery ack").into_array(), delivery_cost)
        .expect("ack");
    let observed = journal.observe_generation().expect("delivered terminal");
    let support = fixture
        .frozen
        .outcome_evidence(&observed)
        .expect("bound evidence");
    assert_eq!(support.complete_metrics(), None);
    assert_eq!(
        observed.cost().summary().expect("meter summary").cpu_micros,
        CellCostTotalV2 {
            known_sum: 0,
            unknown_entries: 1
        }
    );

    let ledger_fixture = ledger_support::Fixture::new();
    let mut writer = ledger_fixture.writer();
    let decision = append_decision(&mut writer, decision(&fixture.frozen));
    let request = ledger_support::observed_request(
        &writer,
        decision.chain_digest,
        outcome(&fixture.frozen, &observed),
    );
    let receipt = append_generation_outcome_v1(
        &mut writer,
        &fixture.frozen,
        &observed,
        request.clone(),
        /*now*/ 50,
    )
    .expect("independent outcome");
    assert_eq!(receipt.disposition, AppendDisposition::Appended);
    drop(journal);
    let reopened = fixture.open();
    let recovered = reopened
        .observe_generation()
        .expect("recovered observation");
    assert_eq!(recovered, observed);
    let replay = append_generation_outcome_v1(
        &mut writer,
        &fixture.frozen,
        &recovered,
        request,
        /*now*/ 50,
    )
    .expect("exact outcome replay");
    assert_eq!(replay.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(replay.chain_digest, receipt.chain_digest);
}

#[test]
fn frozen_versions_and_actual_owner_initial_state_cannot_be_substituted() {
    let fixture = GenerationFixture::new();
    let observed = settled(&fixture);
    let changes: [fn(&mut FrozenGenerationEpisodeInputV1); 9] = [
        |value| value.objective_digest = digest("other objective"),
        |value| value.policy_digest = digest("other policy"),
        |value| value.evaluation_profile_digest = digest("other evaluator"),
        |value| value.sampler_digest = digest("other sampler"),
        |value| value.source_frontier = digest("other sources"),
        |value| value.initial.manifest_digest = digest("other model").into_array(),
        |value| value.initial.generation += 1,
        |value| value.initial.writer_epoch += 1,
        |value| value.initial.state.push(1),
    ];
    for change in changes {
        let mut input = fixture.frozen.input().clone();
        change(&mut input);
        let changed = FrozenGenerationEpisodeV1::new(input).expect("changed valid contract");
        assert!(changed.validate_observation(&observed).is_err());
    }
    // Keeping the declared task identity cannot hide different real owner state.
    let mut substituted = GenerationFixture::new();
    substituted.config.initial.state = b"unbound encoder state".to_vec();
    let owner = substituted.open();
    assert!(
        substituted
            .frozen
            .validate_observation(&owner.observe_generation().expect("owner"))
            .is_err()
    );
}

#[test]
fn signed_decision_must_bind_the_exact_frozen_contract() {
    let fixture = GenerationFixture::new();
    let observed = settled(&fixture);
    let changes: [fn(&mut ProductionDecisionV2); 3] = [
        |value| value.run_snapshot_digest = digest("unrelated run snapshot"),
        |value| value.policy_digest = digest("unrelated policy"),
        |value| value.support_digest = digest("unrelated decision support"),
    ];
    for change in changes {
        let ledger_fixture = ledger_support::Fixture::new();
        let mut writer = ledger_fixture.writer();
        let mut request = decision(&fixture.frozen);
        change(&mut request);
        let decision = append_decision(&mut writer, request);
        let before = writer.snapshot().expect("ledger before");
        let request = ledger_support::observed_request(
            &writer,
            decision.chain_digest,
            outcome(&fixture.frozen, &observed),
        );
        assert!(matches!(
            append_generation_outcome_v1(
                &mut writer,
                &fixture.frozen,
                &observed,
                request,
                /*now*/ 50,
            ),
            Err(GenerationEpisodeErrorV1::Binding(
                "generation decision contract"
            ))
        ));
        assert_eq!(writer.snapshot().expect("ledger after"), before);
    }
}

#[test]
fn signed_outcome_must_bind_the_owner_cut_evaluator_and_observer() {
    let fixture = GenerationFixture::new();
    let observed = settled(&fixture);
    let ledger_fixture = ledger_support::Fixture::new();
    let mut writer = ledger_fixture.writer();
    let decision = append_decision(&mut writer, decision(&fixture.frozen));
    let before = writer.snapshot().expect("ledger before");
    let changes: [fn(&mut AuthenticatedOutcomeV1); 3] = [
        |value| value.support_digest = digest("different owner cut"),
        |value| value.unit_profile_digest = digest("different evaluator"),
        |value| value.observer = ledger_support::principal("generator"),
    ];
    for change in changes {
        let mut value = outcome(&fixture.frozen, &observed);
        change(&mut value);
        let request = ledger_support::observed_request(&writer, decision.chain_digest, value);
        assert!(
            append_generation_outcome_v1(
                &mut writer,
                &fixture.frozen,
                &observed,
                request,
                /*now*/ 50,
            )
            .is_err()
        );
        assert_eq!(writer.snapshot().expect("ledger after"), before);
    }
    let mut request = ledger_support::observed_request(
        &writer,
        decision.chain_digest,
        outcome(&fixture.frozen, &observed),
    );
    request.evidence.signature[0] ^= 1;
    assert!(matches!(
        append_generation_outcome_v1(
            &mut writer,
            &fixture.frozen,
            &observed,
            request,
            /*now*/ 50,
        ),
        Err(GenerationEpisodeErrorV1::Outcome(_))
    ));
    assert_eq!(
        writer.snapshot().expect("ledger after bad signature"),
        before
    );
}
