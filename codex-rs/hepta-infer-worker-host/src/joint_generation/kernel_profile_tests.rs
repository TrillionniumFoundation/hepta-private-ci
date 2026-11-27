//! Replaceable v4 kernels retain the checkpoint/state binding and media contract.

use super::support;
use crate::codec::Packet;
use crate::codec::Result;
use crate::decoder::Prefixes;
use crate::model::Model;
use crate::observation::OwnerContext;
use crate::proposal::propose;
use crate::protocol::Command;
use crate::protocol::EmissionLaw;
use crate::protocol::Sampler;

#[test]
fn ordinary_v4_delivers_both_modalities_but_cannot_reuse_a_dual_state() -> Result<()> {
    let mut weights = support::observed_weights();
    let dual = support::observed_fixture(weights.clone())?;
    weights.meta.insert("mode".into(), "ordinary".into());
    let ordinary = support::observed_fixture(weights)?;
    let mut owner = OwnerContext {
        required_mask: 9,
        optional_mask: 0,
        budget_total: 1_000_000,
        budget_remaining: 1_000_000,
        task_digest: [7; 32],
    };
    let init = Command::Init(EmissionLaw {
        seed: 19,
        sampler: Sampler::Mean,
    });
    let dual_state = propose(&support::request_observed(&dual, &[], &[], init, &owner))?;
    assert!(
        propose(&support::request_observed(
            &ordinary,
            &dual_state.state,
            &[],
            Command::Advance(/*action*/ 4),
            &owner,
        ))
        .is_err()
    );
    let mut current = propose(&support::request_observed(
        &ordinary,
        &[],
        &[],
        init,
        &owner,
    ))?;
    for action in [4, 1, 6] {
        owner.budget_remaining -= 1000;
        current = propose(&support::request_observed(
            &ordinary,
            &current.state,
            &[],
            Command::Advance(action),
            &owner,
        ))?;
    }
    let model = Model::new(Packet::decode(&ordinary.weights)?)?;
    let prefix = Prefixes::read_for_model(&current.delta, &model)?;
    assert_eq!((current.stopped, prefix.cursors), (true, [16, 0, 0, 128]));
    assert!(prefix.bytes[0].starts_with(b"P6\n16 16\n255\n"));
    assert_eq!(
        std::str::from_utf8(&prefix.bytes[3])
            .map_err(|error| error.to_string())?
            .chars()
            .count(),
        128
    );
    Ok(())
}

#[test]
fn legacy_ordinary_is_not_implicitly_admitted() -> Result<()> {
    let mut weights = support::weights();
    weights.meta.insert("mode".into(), "ordinary".into());
    let fixture = support::Fixture::from_weights(weights)?;
    let result = fixture.run(
        &[],
        &[],
        Command::Init(EmissionLaw {
            seed: 19,
            sampler: Sampler::Mean,
        }),
    );
    assert_eq!(
        result.err().as_deref(),
        Some("bridge requires width32/depth1/direct with dual or v4 ordinary kernel")
    );
    Ok(())
}
