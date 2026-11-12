//! State-transition and lost-ack controls. No test record is a Root capability.

use super::*;
use pretty_assertions::assert_eq;

fn fixture() -> anyhow::Result<(tempfile::TempDir, FactoryRecord, FactoryLease)> {
    let (directory, _, _, _, profile) = super::super::profile::tests::fixture()?;
    let record = FactoryRecord {
        profile,
        epoch: 1,
        material: None,
    };
    let lease = FactoryLease {
        epoch: 1,
        material: None,
        revocations: Digest32::of_bytes(b"original-live-root-head").to_string(),
    };
    Ok((directory, record, lease))
}

#[test]
fn factory_bind_is_durable_once_and_lost_ack_reopens_without_genesis() -> anyhow::Result<()> {
    let (_directory, original, lease) = fixture()?;
    let material = Digest32::of_bytes(b"qualified-original-material").to_string();
    let (bound, acknowledgement) = transition(
        &original,
        lease.clone(),
        Command::Bind {
            expected: lease,
            material: material.clone(),
        },
        /*now*/ 50,
    )?;
    assert_eq!(
        bound,
        FactoryRecord {
            profile: original.profile,
            epoch: 2,
            material: Some(material.clone())
        }
    );
    assert!(acknowledgement.newly_bound);
    // A lost first ACK leaves a persisted Bound record. A reopened request is
    // explicitly recover-only, including after the original work deadline.
    let reopened: FactoryRecord = serde_json::from_slice(&serde_json::to_vec(&bound)?)?;
    let (read, repeated) = transition(
        &reopened,
        acknowledgement.lease.clone(),
        Command::Bind {
            expected: acknowledgement.lease.clone(),
            material,
        },
        /*now*/ 101,
    )?;
    assert_eq!(read, bound);
    assert_eq!(repeated.lease, acknowledgement.lease);
    assert!(!repeated.newly_bound);
    Ok(())
}

#[test]
fn factory_refuses_material_rebinding_stale_epoch_and_revoked_finish() -> anyhow::Result<()> {
    let (_directory, original, lease) = fixture()?;
    let material = Digest32::of_bytes(b"qualified-original-material").to_string();
    let (bound, reply) = transition(
        &original,
        lease.clone(),
        Command::Bind {
            expected: lease.clone(),
            material,
        },
        /*now*/ 50,
    )?;
    assert!(
        transition(
            &bound,
            reply.lease.clone(),
            Command::Bind {
                expected: reply.lease.clone(),
                material: Digest32::of_bytes(b"different-result").to_string(),
            },
            /*now*/ 51
        )
        .is_err()
    );
    assert!(
        transition(
            &bound,
            reply.lease.clone(),
            Command::Confirm { expected: lease },
            /*now*/ 51
        )
        .is_err()
    );
    let mut revoked = reply.lease.clone();
    revoked.revocations = Digest32::of_bytes(b"changed-root-revocations").to_string();
    assert!(
        transition(
            &bound,
            revoked,
            Command::Confirm {
                expected: reply.lease
            },
            /*now*/ 51
        )
        .is_err()
    );
    Ok(())
}

#[test]
fn factory_unbound_observation_is_read_only_and_expired_bind_is_refused() -> anyhow::Result<()> {
    let (_directory, original, lease) = fixture()?;
    let (unchanged, reply) =
        transition(&original, lease.clone(), Command::Observe, /*now*/ 101)?;
    assert_eq!(unchanged, original);
    assert_eq!(reply.lease, lease);
    assert!(!reply.newly_bound);
    assert!(
        transition(
            &original,
            lease.clone(),
            Command::Bind {
                expected: lease,
                material: Digest32::of_bytes(b"late-material").to_string(),
            },
            /*now*/ 100
        )
        .is_err()
    );
    Ok(())
}
