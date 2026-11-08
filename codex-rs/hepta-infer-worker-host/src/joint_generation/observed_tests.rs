//! Integration tests use synthetic tensors to prove wiring, never model quality.

use super::support;
use crate::bridge_state::BridgeState;
use crate::codec::Packet;
use crate::codec::Result;
use crate::codec::sha256;
use crate::decoder::Prefixes;
use crate::decoder::commit_chunk;
use crate::model::Model;
use crate::observation::DeliveryObservation;
use crate::observation::OwnerContext;
use crate::protocol::Command;
use crate::protocol::EmissionLaw;
use crate::protocol::Sampler;
use crate::state::State;

fn owner() -> OwnerContext {
    OwnerContext {
        required_mask: 8,
        optional_mask: 1,
        budget_total: 1_000_000,
        budget_remaining: 1_000_000,
        task_digest: [7; 32],
    }
}

fn set(packet: &mut Packet, name: &str, index: usize, value: f64) -> Result<()> {
    *packet
        .tensors
        .get_mut(name)
        .ok_or("missing fixture tensor")?
        .data
        .get_mut(index)
        .ok_or("fixture index")? = value;
    Ok(())
}

#[test]
fn actor_and_both_critics_consume_actual_committed_bytes() -> Result<()> {
    let mut weights = support::observed_weights();
    for name in ["actor", "critic", "delivery_critic"] {
        set(&mut weights, &format!("{name}.0.weight"), 69 + 48 + 15, 1.0)?;
        set(&mut weights, &format!("{name}.2.weight"), 0, 1.0)?;
    }
    let fixture = support::observed_fixture(weights)?;
    let model = Model::new(Packet::decode(&fixture.weights)?)?;
    let state = model.encode(&Packet::decode(&fixture.public)?)?;
    let mut a = Prefixes::for_model(&model);
    a.frame(/*modality*/ 3, /*units*/ 1, b"a")?;
    let mut b = Prefixes::for_model(&model);
    b.frame(/*modality*/ 3, /*units*/ 1, b"b")?;
    let oa = DeliveryObservation::new(&owner(), &a, model.total_units())?;
    let ob = DeliveryObservation::new(&owner(), &b, model.total_units())?;
    let ia = model.inspect_observed(&state, &oa)?;
    let ib = model.inspect_observed(&state, &ob)?;
    for name in ["actor.logits", "critic", "delivery_critic"] {
        assert_ne!(ia.get(name)?, ib.get(name)?);
    }
    let probabilities = ia.get("policy.probabilities")?;
    assert_eq!(&probabilities[2..4], &[0.0, 0.0]);
    assert!(model.inspect(&state, /*remaining*/ 1.0).is_err());
    Ok(())
}

#[test]
fn ordered_text_and_core_persistence_survive_state_roundtrip() -> Result<()> {
    let mut weights = support::observed_weights();
    for channel in 0..32 {
        set(&mut weights, "token_encoder.weight", 97 * 32 + channel, 0.2)?;
        set(
            &mut weights,
            "token_encoder.weight",
            98 * 32 + channel,
            -0.4,
        )?;
        set(
            &mut weights,
            "text_recurrent.weight",
            channel * 32 + channel,
            0.5,
        )?;
        set(
            &mut weights,
            "encoder_fusion.0.weight",
            channel * 128 + 96 + channel,
            1.0,
        )?;
        set(
            &mut weights,
            "core.layers.0.output.weight",
            channel * 32 + channel,
            1.0,
        )?;
    }
    let fixture = support::observed_fixture(weights.clone())?;
    let model = Model::new(weights.clone())?;
    let mut public = Packet::decode(&fixture.public)?;
    public
        .tensors
        .get_mut("tokens")
        .ok_or("fixture tokens")?
        .shape = vec![1, 2];
    public
        .tensors
        .get_mut("tokens")
        .ok_or("fixture tokens")?
        .data = vec![97.0, 98.0];
    let first = model.encode(&public)?;
    public
        .tensors
        .get_mut("tokens")
        .ok_or("fixture tokens")?
        .data
        .reverse();
    let reversed = model.encode(&public)?;
    assert_ne!(first.context, reversed.context);
    let once = model.advance(&reversed, "shared", &public)?;
    let restored = State::read(&Packet::decode(&once.packet().encode()?)?, &model)?;
    assert_eq!(
        model.advance(&once, "shared", &public)?,
        model.advance(&restored, "shared", &public)?
    );
    weights
        .meta
        .insert("core_state_profile".into(), "reset-each-action-v1".into());
    let reset = Model::new(weights)?;
    let reset_once = reset.advance(&reset.encode(&public)?, "shared", &public)?;
    let reset_twice = reset.advance(&reset_once, "shared", &public)?;
    assert_ne!(
        model.advance(&once, "shared", &public)?.core,
        reset_twice.core
    );
    Ok(())
}

#[test]
fn byte_decoder_is_autoregressive_and_chunk_partition_invariant() -> Result<()> {
    let mut weights = support::observed_weights();
    set(&mut weights, "token_encoder.weight", 65 * 32, 1.0)?;
    set(&mut weights, "emissions.text.bias", 65, 1.0)?;
    set(&mut weights, "emissions.text.weight", 66 * 64 + 32, 2.0)?;
    let fixture = support::observed_fixture(weights)?;
    let model = Model::new(Packet::decode(&fixture.weights)?)?;
    let initial = model.encode(&Packet::decode(&fixture.public)?)?;
    let law = EmissionLaw {
        seed: 19,
        sampler: Sampler::Mean,
    };
    let mut whole = initial.clone();
    let all = commit_chunk(
        &model, &mut whole, /*modality*/ 3, /*start*/ 0, /*units*/ 8, law,
    )?;
    assert_eq!(all, b"ABABABAB");
    let mut split = initial;
    let mut pieces = commit_chunk(
        &model, &mut split, /*modality*/ 3, /*start*/ 0, /*units*/ 3, law,
    )?;
    split = State::read(&Packet::decode(&split.packet().encode()?)?, &model)?;
    pieces.extend(commit_chunk(
        &model, &mut split, /*modality*/ 3, /*start*/ 3, /*units*/ 5, law,
    )?);
    assert_eq!((pieces, split.clone()), (all, whole));
    assert!(
        commit_chunk(
            &model, &mut split, /*modality*/ 3, /*start*/ 0, /*units*/ 1, law
        )
        .is_err()
    );
    Ok(())
}

#[test]
fn open_utf8_sampling_resumes_and_has_no_label_vocabulary() -> Result<()> {
    let fixture = support::observed_fixture(support::observed_weights())?;
    let model = Model::new(Packet::decode(&fixture.weights)?)?;
    let mut one = model.encode(&Packet::decode(&fixture.public)?)?;
    let mut two = one.clone();
    let law = EmissionLaw {
        seed: 811,
        sampler: Sampler::SplitmixNormal,
    };
    let all = commit_chunk(
        &model, &mut one, /*modality*/ 3, /*start*/ 0, /*units*/ 128, law,
    )?;
    let mut part = commit_chunk(
        &model, &mut two, /*modality*/ 3, /*start*/ 0, /*units*/ 64, law,
    )?;
    part.extend(commit_chunk(
        &model, &mut two, /*modality*/ 3, /*start*/ 64, /*units*/ 64, law,
    )?);
    assert_eq!((all.clone(), one), (part, two));
    let decoded = std::str::from_utf8(&all).map_err(|error| error.to_string())?;
    assert_eq!(decoded.chars().count(), 128);
    assert!(!decoded.is_ascii());
    Ok(())
}

#[test]
fn v4_bridge_restores_owner_text_prefix_and_rejects_contract_drift() -> Result<()> {
    let fixture = support::observed_fixture(support::observed_weights())?;
    let model = Model::new(Packet::decode(&fixture.weights)?)?;
    let mut contract = owner();
    let init = Command::Init(EmissionLaw {
        seed: 5,
        sampler: Sampler::Mean,
    });
    let initial = crate::proposal::propose(&support::request_observed(
        &fixture,
        &[],
        &[],
        init,
        &contract,
    ))?;
    contract.budget_remaining -= 1000;
    let partial = crate::proposal::propose(&support::request_observed(
        &fixture,
        &initial.state,
        &[],
        Command::Commit {
            modality: 3,
            units: 7,
        },
        &contract,
    ))?;
    let restored = BridgeState::read(
        &partial.state,
        &model,
        &sha256(&fixture.weights),
        &sha256(&fixture.public),
        &partial.delta,
    )?;
    assert_eq!(restored.owner, Some(contract.clone()));
    assert_eq!(restored.prefixes.cursors, [0, 0, 0, 7]);
    assert_eq!(restored.model.text.as_ref().ok_or("missing text")?.units, 7);
    let mut invalid_unit = Packet::decode(&partial.state)?;
    invalid_unit
        .meta
        .insert("owner.budget_unit".into(), "tokens".into());
    assert!(
        BridgeState::read(
            &invalid_unit.encode()?,
            &model,
            &sha256(&fixture.weights),
            &sha256(&fixture.public),
            &partial.delta
        )
        .is_err()
    );
    let mut forged = contract.clone();
    forged.budget_remaining += 1;
    assert!(
        crate::proposal::propose(&support::request_observed(
            &fixture,
            &partial.state,
            &partial.delta,
            Command::Advance(0),
            &forged,
        ))
        .is_err()
    );
    forged = contract.clone();
    forged.required_mask = 1;
    forged.optional_mask = 8;
    assert!(
        crate::proposal::propose(&support::request_observed(
            &fixture,
            &partial.state,
            &partial.delta,
            Command::Advance(0),
            &forged,
        ))
        .is_err()
    );
    assert!(
        crate::proposal::propose(&support::request_observed(
            &fixture,
            &partial.state,
            &partial.delta,
            Command::Commit {
                modality: 1,
                units: 1
            },
            &contract,
        ))
        .is_err()
    );
    let mismatch = support::request_observed(
        &fixture,
        &partial.state,
        &partial.delta,
        Command::Auto(1_000_000),
        &contract,
    );
    assert!(crate::protocol::parse(&mismatch).is_err());
    Ok(())
}

#[test]
fn explicit_advance_uses_the_same_completed_modality_mask_as_auto() -> Result<()> {
    let fixture = support::observed_fixture(support::observed_weights())?;
    let contract = owner();
    let init = Command::Init(EmissionLaw {
        seed: 5,
        sampler: Sampler::Mean,
    });
    let initial = crate::proposal::propose(&support::request_observed(
        &fixture,
        &[],
        &[],
        init,
        &contract,
    ))?;
    let complete = crate::proposal::propose(&support::request_observed(
        &fixture,
        &initial.state,
        &[],
        Command::Commit {
            modality: 3,
            units: 128,
        },
        &contract,
    ))?;
    assert!(
        crate::proposal::propose(&support::request_observed(
            &fixture,
            &complete.state,
            &complete.delta,
            Command::Advance(4),
            &contract
        ))
        .is_err()
    );
    Ok(())
}

#[test]
fn canonical_stopped_state_requires_actual_required_delivery() -> Result<()> {
    let fixture = support::observed_fixture(support::observed_weights())?;
    let model = Model::new(Packet::decode(&fixture.weights)?)?;
    let contract = owner();
    let initial = crate::proposal::propose(&support::request_observed(
        &fixture,
        &[],
        &[],
        Command::Init(EmissionLaw {
            seed: 5,
            sampler: Sampler::Mean,
        }),
        &contract,
    ))?;
    let mut state = BridgeState::read(
        &initial.state,
        &model,
        &sha256(&fixture.weights),
        &sha256(&fixture.public),
        &[],
    )?;
    state.model.stopped = true;
    assert!(
        state
            .encode(&sha256(&fixture.weights), &sha256(&fixture.public), &[])
            .is_err()
    );
    let advanced = crate::proposal::propose(&support::request_observed(
        &fixture,
        &initial.state,
        &[],
        Command::Advance(0),
        &contract,
    ))?;
    let stopped = crate::proposal::propose(&support::request_observed(
        &fixture,
        &advanced.state,
        &[],
        Command::Advance(6),
        &contract,
    ))?;
    assert!(stopped.stopped);
    let restored = BridgeState::read(
        &stopped.state,
        &model,
        &sha256(&fixture.weights),
        &sha256(&fixture.public),
        &stopped.delta,
    )?;
    assert_eq!(restored.prefixes.cursors, [0, 0, 0, 128]);
    Ok(())
}
