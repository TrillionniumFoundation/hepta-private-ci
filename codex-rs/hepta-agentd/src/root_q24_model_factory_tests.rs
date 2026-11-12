//! Client reply validation cannot turn a stale/foreign Root response into a
//! creation permit. These are protocol controls, not deployed authority tests.

use super::*;

#[test]
fn factory_client_refuses_replayed_create_and_changed_live_frontier() -> anyhow::Result<()> {
    let revocations = Digest32::of_bytes(b"live-head").to_string();
    let material = Digest32::of_bytes(b"actual-material").to_string();
    let reserved = FactoryLease {
        epoch: 1,
        material: None,
        revocations: revocations.clone(),
    };
    let bound = FactoryLease {
        epoch: 2,
        material: Some(material.clone()),
        revocations,
    };
    let first = Command::Bind {
        expected: reserved,
        material: material.clone(),
    };
    validate_reply(
        &first,
        &Reply {
            lease: bound.clone(),
            newly_bound: true,
        },
    )?;
    assert!(
        validate_reply(
            &Command::Bind {
                expected: bound.clone(),
                material
            },
            &Reply {
                lease: bound.clone(),
                newly_bound: true
            }
        )
        .is_err()
    );
    assert!(
        validate_reply(
            &Command::Observe,
            &Reply {
                lease: bound.clone(),
                newly_bound: true
            }
        )
        .is_err()
    );
    let mut changed = bound.clone();
    changed.revocations = Digest32::of_bytes(b"revoked-head").to_string();
    assert!(
        validate_reply(
            &Command::Confirm {
                expected: bound.clone()
            },
            &Reply {
                lease: changed,
                newly_bound: false
            }
        )
        .is_err()
    );
    validate_reply(
        &Command::Confirm {
            expected: bound.clone(),
        },
        &Reply {
            lease: bound,
            newly_bound: false,
        },
    )?;
    Ok(())
}

#[test]
fn factory_client_refuses_noncanonical_or_missing_material_binding() {
    for (epoch, material) in [
        (0, None),
        (1, Some(Digest32::of_bytes(b"material").to_string())),
        (2, None),
        (2, Some(Digest32::ZERO.to_string())),
    ] {
        let reply = Reply {
            lease: FactoryLease {
                epoch,
                material,
                revocations: Digest32::of_bytes(b"live-head").to_string(),
            },
            newly_bound: false,
        };
        assert!(validate_reply(&Command::Observe, &reply).is_err());
    }
}

#[path = "root_q24_model_same_actor_tests.rs"]
mod same_actor_tests;
