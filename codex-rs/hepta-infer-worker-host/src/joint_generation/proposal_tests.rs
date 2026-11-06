//! Behavioral qualification with explicitly synthetic legal weights, not the
//! unavailable selected trained checkpoint and not a product adoption claim.

use crate::bridge_state::BridgeState;
use crate::codec::Packet;
use crate::codec::Result;
use crate::codec::sha256;
use crate::decoder::Prefixes;
use crate::decoder::TOTAL_UNITS;
use crate::model::Model;
use crate::protocol::Command;
use crate::protocol::EmissionLaw;
use crate::protocol::Reader;
use crate::protocol::Sampler;
use crate::protocol::parse;

#[path = "proposal_test_support.rs"]
mod support;
use support::Fixture;
use support::raw_frame;
use support::request;

fn init() -> Command {
    Command::Init(EmissionLaw {
        seed: 17,
        sampler: Sampler::SplitmixNormal,
    })
}

#[test]
fn real_kernel_partial_prefix_stop_flush_and_replay_are_deterministic() -> Result<()> {
    let fixture = Fixture::new()?;
    let initial = fixture.run(&[], &[], init())?;
    let advanced = fixture.run(&initial.state, &[], Command::Advance(0))?;
    assert_ne!(advanced.state, initial.state);
    assert!(advanced.delta.is_empty());
    let partial = fixture.run(
        &advanced.state,
        &[],
        Command::Commit {
            modality: 1,
            units: 16,
        },
    )?;
    let emitted = Prefixes::read(&partial.delta)?;
    assert_eq!(emitted.cursors, [0, 16, 0, 0]);
    let stopped = fixture.run(&partial.state, &partial.delta, Command::Advance(6))?;
    let replay = fixture.run(&partial.state, &partial.delta, Command::Advance(6))?;
    // Observed wall times vary; numeric successor and unpublished bytes must not.
    assert_eq!(
        (&stopped.state, &stopped.delta, stopped.stopped),
        (&replay.state, &replay.delta, replay.stopped)
    );
    assert!(stopped.stopped);
    let mut prefix = partial.delta;
    prefix.extend(&stopped.delta);
    let complete = Prefixes::read(&prefix)?;
    assert_eq!(complete.cursors, TOTAL_UNITS);
    assert!(complete.bytes[1].starts_with(&emitted.bytes[1]));
    assert!(
        fixture
            .run(
                &stopped.state,
                &prefix,
                Command::Commit {
                    modality: 0,
                    units: 1
                }
            )
            .is_err()
    );
    let model = Model::new(Packet::decode(&fixture.weights)?)?;
    let state = BridgeState::read(
        &stopped.state,
        &model,
        &sha256(&fixture.weights),
        &sha256(&fixture.public),
        &prefix,
    )?;
    assert_eq!(
        state.law,
        EmissionLaw {
            seed: 17,
            sampler: Sampler::SplitmixNormal
        }
    );
    assert_eq!(state.prefixes, complete);
    let encoded = stopped.encode()?;
    let checksum_offset = encoded.len() - 64;
    assert_eq!(
        sha256(&encoded[..checksum_offset]).as_bytes(),
        &encoded[checksum_offset..]
    );
    let mut reader = Reader::new(&encoded[..checksum_offset]);
    assert_eq!(reader.take(8)?, b"HJRESV01");
    assert_eq!(reader.take(32)?, [5; 32].as_slice());
    assert_eq!(reader.byte()?, 1);
    for elapsed in stopped.phase_micros {
        assert_eq!(reader.take(8)?, elapsed.to_le_bytes().as_slice());
    }
    let length = reader.u32()? as usize;
    assert_eq!(reader.take(length)?, stopped.state.as_slice());
    let length = reader.u32()? as usize;
    assert_eq!(reader.take(length)?, stopped.delta.as_slice());
    assert!(reader.is_empty());
    Ok(())
}

#[test]
fn auto_uses_real_actor_mask_and_critic_computation() -> Result<()> {
    let fixture = Fixture::new()?;
    let initial = fixture.run(&[], &[], init())?;
    let auto = fixture.run(&initial.state, &[], Command::Auto(1_000_000))?;
    let shared = fixture.run(&initial.state, &[], Command::Advance(0))?;
    assert_eq!(
        (&auto.state, &auto.delta, auto.stopped),
        (&shared.state, &shared.delta, shared.stopped)
    );
    let stopped = fixture.run(&auto.state, &[], Command::Auto(500_000))?;
    assert!(stopped.stopped);
    assert_eq!(Prefixes::read(&stopped.delta)?.cursors, TOTAL_UNITS);
    let mut weights = support::weights();
    weights
        .tensors
        .get_mut("critic.0.bias")
        .ok_or("missing test critic")?
        .data
        .fill(1.0);
    weights
        .tensors
        .get_mut("critic.2.weight")
        .ok_or("missing test critic")?
        .data
        .fill(1e308);
    let bad_critic = Fixture::from_weights(weights)?;
    let initial = bad_critic.run(&[], &[], init())?;
    assert!(
        bad_critic
            .run(&initial.state, &[], Command::Advance(0))
            .is_ok()
    );
    assert!(
        bad_critic
            .run(&initial.state, &[], Command::Auto(1_000_000))
            .is_err()
    );
    Ok(())
}

#[test]
fn state_inventory_and_actual_prefix_are_both_required() -> Result<()> {
    let fixture = Fixture::new()?;
    let initial = fixture.run(&[], &[], init())?;
    let partial = fixture.run(
        &initial.state,
        &[],
        Command::Commit {
            modality: 0,
            units: 1,
        },
    )?;
    let model = Model::new(Packet::decode(&fixture.weights)?)?;
    let weights_hash = sha256(&fixture.weights);
    let public_hash = sha256(&fixture.public);
    let packet = Packet::decode(&partial.state)?;
    let mutations: [fn(&mut Packet); 4] = [
        |packet| {
            packet.meta.insert("extra".into(), "value".into());
        },
        |packet| {
            packet.meta.insert("cursor.image".into(), "0".into());
        },
        |packet| {
            packet.vector("extra", vec![0.0]);
        },
        |packet| {
            if let Some(tensor) = packet.tensors.get_mut("prefix.image") {
                tensor.shape = vec![1, 48];
            }
        },
    ];
    for mutate in mutations {
        let mut changed = packet.clone();
        mutate(&mut changed);
        assert!(
            BridgeState::read(
                &changed.encode()?,
                &model,
                &weights_hash,
                &public_hash,
                &partial.delta
            )
            .is_err()
        );
    }
    let mut forged_prefix = partial.delta.clone();
    *forged_prefix.last_mut().ok_or("missing frame payload")? ^= 1;
    let mut forged_state = packet;
    forged_state
        .meta
        .insert("bridge.prefix_sha256".into(), sha256(&forged_prefix));
    assert!(
        BridgeState::read(
            &forged_state.encode()?,
            &model,
            &weights_hash,
            &public_hash,
            &forged_prefix
        )
        .is_err()
    );
    assert!(
        BridgeState::read(
            &partial.state,
            &model,
            &"a".repeat(64),
            &public_hash,
            &partial.delta
        )
        .is_err()
    );
    Ok(())
}

#[test]
fn malformed_framing_domains_and_request_bounds_are_rejected() -> Result<()> {
    let valid = raw_frame(
        /*modality*/ 0, /*start*/ 0, /*units*/ 1, &[128; 48],
    );
    assert_eq!(Prefixes::read(&valid)?.cursors, [1, 0, 0, 0]);
    let mut duplicate = valid.clone();
    duplicate.extend(&valid);
    for prefix in [
        duplicate,
        raw_frame(
            /*modality*/ 0, /*start*/ 1, /*units*/ 1, &[128; 48],
        ),
        raw_frame(/*modality*/ 0, /*start*/ 0, /*units*/ 0, &[]),
        raw_frame(
            /*modality*/ 1,
            /*start*/ 0,
            /*units*/ 1,
            &[0],
        ),
        raw_frame(
            /*modality*/ 3,
            /*start*/ 0,
            /*units*/ 2,
            b"action=63;sound=0\n",
        ),
        raw_frame(
            /*modality*/ 3,
            /*start*/ 0,
            /*units*/ 2,
            b"action=0;sound=17\n",
        ),
        raw_frame(
            /*modality*/ 3,
            /*start*/ 0,
            /*units*/ 1,
            b"action=00;",
        ),
        raw_frame(
            /*modality*/ 4,
            /*start*/ 0,
            /*units*/ 1,
            &[0],
        ),
    ] {
        assert!(Prefixes::read(&prefix).is_err());
    }
    let text = raw_frame(
        /*modality*/ 3,
        /*start*/ 0,
        /*units*/ 2,
        b"action=62;sound=16\n",
    );
    assert_eq!(Prefixes::read(&text)?.cursors, [0, 0, 0, 2]);
    let valid = request(b"weights", b"public", &[], &[], init());
    assert!(parse(&valid).is_ok());
    let mut trailing = valid.clone();
    trailing.push(0);
    let mut zero_digest = valid.clone();
    zero_digest[8..40].fill(0);
    let mut oversized = valid.clone();
    oversized[40..44].copy_from_slice(&(8 * 1024 * 1024 + 1_u32).to_le_bytes());
    let mut bad_sampler = valid.clone();
    *bad_sampler.last_mut().ok_or("missing sampler")? = 2;
    for bytes in [
        trailing,
        zero_digest,
        oversized,
        bad_sampler,
        valid[..valid.len() - 1].to_vec(),
        request(b"w", b"p", &[], &[], Command::Auto(1_000_001)),
    ] {
        assert!(parse(&bytes).is_err());
    }
    Ok(())
}
