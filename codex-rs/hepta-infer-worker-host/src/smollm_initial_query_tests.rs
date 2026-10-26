//! Proposed real pinned-model controls; NOT_RUN and no product qualification.
//! Uses the original publication/selector and controlled Unix issuer fixtures.
use super::*;
use codex_hepta_agentd::NeuralCognitiveExecutionV1;
use codex_hepta_infer_core::durable_control::RequestState;
use std::time::Duration;
use std::time::Instant;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires the original pinned model configuration with canonical selected gen1 zero material"]
async fn real_selected_initial_query_actual_forward_then_withdrawal_is_sticky() -> TestResult<()> {
    let (input, worker, bytes) = input_and_worker("initial-query-forward")?;
    let mut fixture = Fixture::new(input.output.join("query-owner"), &bytes)?;
    let (material, current) = fixture.selected(/*revoked_at*/ None)?;
    let (inputs, issuer, authority) = inputs(
        worker,
        &input.output.join("query-effects"),
        /*expected_claims*/ 2,
    )
    .await?;
    let owner = prepare_selected_initial_smollm_v1(
        fixture.config("query-body")?,
        material,
        current,
        inputs,
    )
    .await?;
    let (mut owner, actual) = tokio::task::spawn_blocking(move || {
        let mut owner = owner;
        let actual = owner.with_current_initial_read(
            "Reply yes or no: is two plus two four?",
            &[id("native-answer-no"), id("native-answer-yes")],
            &NeuralCognitiveExecutionV1::bounded_read(),
            |proof| {
                let load = proof.measured_load();
                let forward = proof.measured_forward();
                std::assert_eq!(load.generation(), 1);
                std::assert_eq!(forward.ready_digest(), load.ready_digest());
                std::assert_eq!(proof.scores_q32().map(<[i64]>::len), Some(2));
                assert!(!proof.selection_digest().is_zero());
                assert!(!forward.response_digest().is_zero());
                assert!(!forward.input_digest().is_zero());
                let (request, reservation) = forward.control_ids();
                std::assert_eq!(reservation, format!("reservation-{request}"));
                Ok((
                    proof.selection_digest(),
                    load.ready_digest(),
                    forward.response_digest(),
                ))
            },
        );
        (owner, actual)
    })
    .await?;
    let actual = actual?;
    let selected = owner.with_current_initial_load(|proof| {
        Ok((proof.selection_digest(), proof.measured().ready_digest()))
    })?;
    std::assert_eq!((actual.0, actual.1), selected);
    fixture.withdraw()?;
    let (mut owner, refused) = tokio::task::spawn_blocking(move || {
        let refused = owner.with_current_initial_read::<()>(
            "withdrawn query must not execute",
            &[id("native-answer-no")],
            &NeuralCognitiveExecutionV1::bounded_read(),
            |_| panic!("withdrawn query reached its consumer"),
        );
        (owner, refused)
    })
    .await?;
    assert!(refused.is_err());
    assert!(
        owner
            .with_current_initial_load::<()>(|_| panic!("closed owner revived"))
            .is_err()
    );
    owner.shutdown().await?;
    issuer.await?.map_err(issuer_error)?;
    archive_authority(&authority, &input.output)?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires the original pinned model configuration with canonical selected gen1 zero material"]
async fn real_selected_initial_query_refuses_before_claim_and_keeps_cleanup() -> TestResult<()> {
    for name in ["expired", "cancelled", "overlong", "association"] {
        let (input, worker, bytes) = input_and_worker(&format!("query-preclaim-{name}"))?;
        let fixture = Fixture::new(input.output.join(format!("query-owner-{name}")), &bytes)?;
        let (material, current) = fixture.selected(/*revoked_at*/ None)?;
        let (inputs, issuer, authority) = inputs(
            worker,
            &input.output.join(format!("query-effects-{name}")),
            /*expected_claims*/ 1,
        )
        .await?;
        let journal = inputs.inference_journal.clone();
        let mut owner = prepare_selected_initial_smollm_v1(
            fixture.config("query-preclaim-body")?,
            material,
            current,
            inputs,
        )
        .await?;
        let journal_before = fs::read(&journal)?;
        let cancellation = CancellationToken::new();
        let deadline = match name {
            "expired" => Instant::now(),
            "cancelled" | "association" => Instant::now() + Duration::from_secs(2),
            "overlong" => Instant::now() + Duration::from_secs(3),
            _ => unreachable!(),
        };
        if name == "cancelled" {
            cancellation.cancel();
        }
        if name == "association" {
            owner.association.as_mut().unwrap().0 = digest("other Ready");
        }
        let execution = NeuralCognitiveExecutionV1::with_deadline(deadline, cancellation);
        let (mut owner, refused) = tokio::task::spawn_blocking(move || {
            let refused = owner.with_current_initial_read::<()>(
                "preclaim refusal",
                &[id("native-answer-no")],
                &execution,
                |_| panic!("rejected query reached its consumer"),
            );
            (owner, refused)
        })
        .await?;
        assert!(refused.is_err(), "{name}");
        std::assert_eq!(fs::read(&journal)?, journal_before);
        assert!(
            owner
                .with_current_initial_load::<()>(|_| panic!("closed query revived"))
                .is_err()
        );
        owner.shutdown().await?;
        issuer.await?.map_err(issuer_error)?;
        archive_authority(&authority, &input.output)?;
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires the original pinned model configuration with canonical selected gen1 zero material"]
async fn real_selected_initial_query_outer_error_closes_owner_and_keeps_completed() -> TestResult<()>
{
    let (input, worker, bytes) = input_and_worker("query-late-cancel")?;
    let fixture = Fixture::new(input.output.join("query-late-owner"), &bytes)?;
    let (material, current) = fixture.selected(/*revoked_at*/ None)?;
    let (inputs, issuer, authority) = inputs(
        worker,
        &input.output.join("query-late-effects"),
        /*expected_claims*/ 2,
    )
    .await?;
    let journal = inputs.inference_journal.clone();
    let owner = prepare_selected_initial_smollm_v1(
        fixture.config("query-late-body")?,
        material,
        current,
        inputs,
    )
    .await?;
    let (mut owner, refused, completed_id) = tokio::task::spawn_blocking(move || {
        let mut owner = owner;
        let mut completed_id = None;
        let cancellation = CancellationToken::new();
        let execution = NeuralCognitiveExecutionV1::with_deadline(
            Instant::now() + Duration::from_secs(2),
            cancellation.clone(),
        );
        let refused = owner.with_current_initial_read(
            "Reply yes or no: is two plus two four?",
            &[id("native-answer-no")],
            &execution,
            |proof| {
                assert!(!proof.measured_forward().response_digest().is_zero());
                completed_id = Some(proof.measured_forward().control_ids().0.to_owned());
                cancellation.cancel();
                Ok(())
            },
        );
        (owner, refused, completed_id)
    })
    .await?;
    assert!(refused.is_err());
    assert!(
        owner
            .with_current_initial_load::<()>(|_| panic!("late query revived"))
            .is_err()
    );
    owner.shutdown().await?;
    drop(owner);
    let completed_id = completed_id.ok_or("no actual completed forward observed")?;
    let cold = DurableInferenceControl::open(&journal, /*capacity*/ 8)?;
    let completed = cold
        .get(&completed_id)
        .ok_or("completed original read missing")?;
    std::assert_eq!(completed.state, RequestState::Completed);
    assert!(completed.terminal_observation_digest.is_some());
    issuer.await?.map_err(issuer_error)?;
    archive_authority(&authority, &input.output)?;
    Ok(())
}
