use super::support;
use crate::codec::Packet;
use crate::codec::Result;
use crate::decoder::Prefixes;
use crate::model::Model;
use crate::observation::OwnerContext;
use crate::planner;
use crate::protocol::Command;
use crate::protocol::EmissionLaw;
use crate::protocol::Sampler;

fn owner() -> OwnerContext {
    OwnerContext {
        required_mask: 8,
        optional_mask: 1,
        budget_total: 1_000_000,
        budget_remaining: 1_000_000,
        task_digest: [9; 32],
    }
}

#[test]
fn recursive_value_selects_delivery_against_actor_argmax_and_retains_receipt() -> Result<()> {
    let mut weights = support::observed_weights();
    weights
        .meta
        .insert("allow_initial_stop".into(), "true".into());
    weights
        .tensors
        .get_mut("actor.2.bias")
        .ok_or("actor bias")?
        .data = vec![5.0, 0.0, 0.0, 0.0, 0.0, 0.0, -5.0];
    let fixture = support::observed_fixture(weights.clone())?;
    let model = Model::new(weights.clone())?;
    let public = Packet::decode(&fixture.public)?;
    let state = model.encode(&public)?;
    let law = EmissionLaw {
        seed: 3,
        sampler: Sampler::Mean,
    };
    let receipt = planner::choose(
        &model,
        &state,
        &Prefixes::for_model(&model),
        &owner(),
        &public,
        law,
    )?;
    assert_eq!(receipt.action, 6);
    assert!(receipt.forecasts <= 32 && receipt.forecasts > 1);
    assert!(receipt.scores[6] > receipt.scores[0]);
    weights
        .meta
        .insert("inference_profile".into(), planner::ACTOR_PROFILE.into());
    let actor_model = Model::new(weights)?;
    let actor = planner::choose(
        &actor_model,
        &state,
        &Prefixes::for_model(&actor_model),
        &owner(),
        &public,
        law,
    )?;
    assert_eq!(actor.action, 0);
    let mut actor_packet = Packet::default();
    actor.write_packet(&mut actor_packet);
    assert_eq!(
        actor_packet.text("planning.objective")?,
        "actor-probability-argmax-v1"
    );
    assert_eq!(planner::PlanningReceipt::read(&actor_packet)?, Some(actor));
    let initial = crate::proposal::propose(&support::request_observed(
        &fixture,
        &[],
        &[],
        Command::Init(law),
        &owner(),
    ))?;
    let output = crate::proposal::propose(&support::request_observed(
        &fixture,
        &initial.state,
        &[],
        Command::Auto(1_000_000),
        &owner(),
    ))?;
    let packet = Packet::decode(&output.state)?;
    let retained =
        planner::PlanningReceipt::read(&packet)?.ok_or("missing retained planner receipt")?;
    assert_eq!(retained, receipt);
    assert!(output.stopped);
    // Optional image was never started: STOP must not produce it gratuitously.
    assert_eq!(
        Prefixes::read_for_model(&output.delta, &model)?.cursors,
        [0, 0, 0, 128]
    );
    Ok(())
}

#[test]
fn planner_enforces_forecast_and_duration_budgets() -> Result<()> {
    let mut weights = support::observed_weights();
    weights.meta.insert("ndu.horizon".into(), "4".into());
    weights.meta.insert("ndu.max_forecasts".into(), "7".into());
    let fixture = support::observed_fixture(weights.clone())?;
    let model = Model::new(weights)?;
    let public = Packet::decode(&fixture.public)?;
    let state = model.encode(&public)?;
    let law = EmissionLaw {
        seed: 11,
        sampler: Sampler::Mean,
    };
    let receipt = planner::choose(
        &model,
        &state,
        &Prefixes::for_model(&model),
        &owner(),
        &public,
        law,
    )?;
    assert!(receipt.forecasts <= 7);
    assert!(receipt.exhausted);
    let mut insufficient = owner();
    insufficient.budget_remaining = 999;
    assert!(
        planner::choose(
            &model,
            &state,
            &Prefixes::for_model(&model),
            &insufficient,
            &public,
            law
        )
        .is_err()
    );
    Ok(())
}

#[test]
fn changed_inference_profile_cannot_silently_become_an_ndu_solver() -> Result<()> {
    let mut weights = support::observed_weights();
    weights
        .meta
        .insert("inference_profile".into(), "undocumented-policy".into());
    let fixture = support::observed_fixture(weights)?;
    let law = EmissionLaw {
        seed: 3,
        sampler: Sampler::Mean,
    };
    assert!(
        crate::proposal::propose(&support::request_observed(
            &fixture,
            &[],
            &[],
            Command::Init(law),
            &owner()
        ))
        .is_err()
    );
    Ok(())
}

#[test]
fn deterministic_risk_parameter_is_retained_without_claiming_a_risk_effect() -> Result<()> {
    let fixture = support::observed_fixture(support::observed_weights())?;
    let public = Packet::decode(&fixture.public)?;
    let law = EmissionLaw {
        seed: 3,
        sampler: Sampler::Mean,
    };
    let mut reference = None;
    for risk in [0.0, 0.25, 10.0] {
        let mut weights = support::observed_weights();
        weights.meta.insert("ndu.risk".into(), risk.to_string());
        let model = Model::new(weights)?;
        let receipt = planner::choose(
            &model,
            &model.encode(&public)?,
            &Prefixes::for_model(&model),
            &owner(),
            &public,
            law,
        )?;
        assert_eq!(
            receipt.risk_evidence,
            planner::RiskEvidence::InactiveSingleParticle(risk)
        );
        let decision = (
            receipt.action,
            receipt.scores,
            receipt.scored,
            receipt.forecasts,
        );
        if let Some(expected) = reference {
            assert_eq!(decision, expected);
        } else {
            reference = Some(decision);
        }
        let mut packet = Packet::default();
        receipt.write_packet(&mut packet);
        assert_eq!(
            planner::PlanningReceipt::read(&packet)?,
            Some(receipt.clone())
        );
        packet
            .meta
            .insert("planning.risk_semantics".into(), "risk-sensitive".into());
        assert!(planner::PlanningReceipt::read(&packet).is_err());
        packet.meta.insert(
            "planning.risk_semantics".into(),
            "inactive-single-particle".into(),
        );
        packet
            .meta
            .insert("planning.support_particles".into(), "4".into());
        assert!(planner::PlanningReceipt::read(&packet).is_err());
        for key in ["risk_semantics", "risk_parameter", "support_particles"] {
            packet.meta.remove(&format!("planning.{key}"));
        }
        let legacy = planner::PlanningReceipt::read(&packet)?.ok_or("legacy receipt")?;
        let mut expected = receipt;
        expected.risk_evidence = planner::RiskEvidence::LegacyUnrecorded;
        assert_eq!(legacy, expected);
    }
    Ok(())
}
