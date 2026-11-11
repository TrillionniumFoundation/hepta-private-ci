//! Native fixture qualification only: no product adoption or independent B claim.

use std::sync::atomic::Ordering;

use codex_hepta_learning_ledger::OutcomeTerminalityV1;

use super::test_support::*;
use super::*;

#[tokio::test]
async fn authentic_terminal_source_materializes_exact_batch_without_executing_again()
-> anyhow::Result<()> {
    let mut fixture = Fixture::new(Q / 2).await?;
    fixture.terminal((1_i64 << 32) + 128)?;
    let before = fixture.bytes()?;
    let material = fixture.freeze()?;
    let expected = CellQ24TrainingBatchV1::new(
        material.dataset().snapshot.dataset_digest,
        vec![CellQ24TrainingSampleV1 {
            input: vec![Q, Q / 2],
            target: Q,
        }],
    )?;
    pretty_assertions::assert_eq!(material.batch().encoded(), expected.encoded());
    material.revalidate(
        &fixture.writer,
        &fixture.source.readback(),
        &fixture.identity,
    )?;
    pretty_assertions::assert_eq!(fixture.bytes()?, before);
    pretty_assertions::assert_eq!(fixture.calls.load(Ordering::SeqCst), 1);
    // The excluded episode has neither ledger labels nor a Circuit source.
    // Successful construction is only a training partition, never independent B.
    pretty_assertions::assert_eq!(material.batch().rows(), 1);
    Ok(())
}

#[tokio::test]
async fn withdrawn_source_rejects_an_existing_material_without_new_work() -> anyhow::Result<()> {
    let mut fixture = Fixture::new(Q / 2).await?;
    fixture.terminal(1_i64 << 32)?;
    let material = fixture.freeze()?;
    let run =
        circuit_learning_run_id_v1(&fixture.writer, &fixture.identity.agent_id, &id("train-A"))?;
    fixture.source.withdraw_source(&run)?;
    let after_withdrawal = fixture.bytes()?;
    assert!(
        material
            .revalidate(
                &fixture.writer,
                &fixture.source.readback(),
                &fixture.identity
            )
            .is_err()
    );
    pretty_assertions::assert_eq!(fixture.bytes()?, after_withdrawal);
    pretty_assertions::assert_eq!(fixture.calls.load(Ordering::SeqCst), 1);
    Ok(())
}

#[tokio::test]
async fn changed_original_input_cannot_replace_the_sealed_training_source() -> anyhow::Result<()> {
    let mut fixture = Fixture::new(Q / 2).await?;
    fixture.terminal(1_i64 << 32)?;
    let material = fixture.freeze()?;
    let replacement = Fixture::new(-Q / 2).await?;
    assert!(
        material
            .revalidate(
                &fixture.writer,
                &replacement.source.readback(),
                &replacement.identity
            )
            .is_err()
    );
    material.revalidate(
        &fixture.writer,
        &fixture.source.readback(),
        &fixture.identity,
    )?;
    pretty_assertions::assert_eq!(
        (
            fixture.calls.load(Ordering::SeqCst),
            replacement.calls.load(Ordering::SeqCst)
        ),
        (1, 1)
    );
    Ok(())
}

#[tokio::test]
async fn corrected_original_outcome_invalidates_old_material() -> anyhow::Result<()> {
    let mut fixture = Fixture::new(Q / 2).await?;
    fixture.terminal(1_i64 << 32)?;
    let material = fixture.freeze()?;
    fixture.correct(2_i64 << 32)?;
    assert!(
        material
            .revalidate(
                &fixture.writer,
                &fixture.source.readback(),
                &fixture.identity
            )
            .is_err()
    );
    let corrected = fixture.freeze()?;
    let expected = CellQ24TrainingBatchV1::new(
        corrected.dataset().snapshot.dataset_digest,
        vec![CellQ24TrainingSampleV1 {
            input: vec![Q, Q / 2],
            target: 2 * Q,
        }],
    )?;
    pretty_assertions::assert_eq!(corrected.batch().encoded(), expected.encoded());
    Ok(())
}

#[tokio::test]
async fn wrong_frozen_identities_and_duplicate_or_overlapping_splits_reject() -> anyhow::Result<()>
{
    let mut fixture = Fixture::new(Q / 2).await?;
    fixture.terminal(1_i64 << 32)?;
    let original = fixture.profile.clone();
    let mutations: &[fn(&mut CellQ24DatasetProfileV1)] = &[
        |p| p.principal_digest = d("other-principal"),
        |p| p.cell_id = id("other-cell"),
        |p| {
            p.agent_id =
                AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13").expect("fixture agent")
        },
        |p| p.ledger_binding = d("other-ledger"),
        |p| p.evidence_trust_digest = d("other-trust"),
        |p| p.objective_digest = d("other-objective"),
        |p| p.selected_bundle = d("other-bundle"),
        |p| p.outcome_unit_profile = d("other-unit"),
        |p| p.input_width = 1,
        |p| p.training_episodes[0].run_snapshot_digest = d("other-snapshot"),
        |p| p.training_episodes[0].decision_support_digest = d("other-support"),
        |p| p.training_episodes.push(p.training_episodes[0].clone()),
        |p| p.training_episodes[0].episode_id = id("different-episode"),
        |p| p.excluded_episodes = vec![id("train-A")],
    ];
    let before = fixture.bytes()?;
    for (index, mutate) in mutations.iter().enumerate() {
        fixture.profile = original.clone();
        mutate(&mut fixture.profile);
        assert!(
            fixture.freeze().is_err(),
            "mutation {index} unexpectedly admitted"
        );
    }
    fixture.profile = original;
    fixture.freeze()?;
    pretty_assertions::assert_eq!(fixture.bytes()?, before);
    Ok(())
}

#[tokio::test]
async fn missing_pending_censored_and_unbound_outcomes_are_errors() -> anyhow::Result<()> {
    let fixture = Fixture::new(Q / 2).await?;
    assert!(fixture.freeze().is_err());
    for terminality in [
        OutcomeTerminalityV1::Pending,
        OutcomeTerminalityV1::Censored,
    ] {
        let mut fixture = Fixture::new(Q / 2).await?;
        fixture.append_outcome(None, terminality, None, d("terminal-unit"), d("support"))?;
        assert!(fixture.freeze().is_err());
    }
    let mut unbound = Fixture::new(Q / 2).await?;
    unbound.append_outcome(
        Some(1_i64 << 32),
        OutcomeTerminalityV1::Terminal,
        None,
        d("terminal-unit"),
        d("different-publication"),
    )?;
    assert!(unbound.freeze().is_err());
    let mut outside = Fixture::new(Q / 2).await?;
    outside.terminal((8_i64 << 32) + 1)?;
    assert!(outside.freeze().is_err());
    let mut outside_input = Fixture::new(8 * Q + 1).await?;
    outside_input.terminal(1_i64 << 32)?;
    assert!(outside_input.freeze().is_err());
    Ok(())
}

#[test]
fn q32_targets_round_toward_zero_and_reject_range_before_rounding() -> anyhow::Result<()> {
    let input = [-257, -255, 0, 255, 257, -(8_i64 << 32), 8_i64 << 32];
    let actual = input
        .into_iter()
        .map(target_q24)
        .collect::<Result<Vec<_>, _>>()?;
    pretty_assertions::assert_eq!(actual, vec![-1, 0, 0, 0, 1, -8 * Q, 8 * Q]);
    assert!(target_q24((8_i64 << 32) + 1).is_err());
    assert!(target_q24(-(8_i64 << 32) - 1).is_err());
    Ok(())
}
