//! Real channel-lock and Unix socket custody components only. These tests do
//! not construct RootIntent, close a privileged purpose, or qualify C/Root
//! retirement. They exercise the exact private admission used after Intent.

use super::*;
use pretty_assertions::assert_eq;
use std::io::ErrorKind;
use std::sync::TryLockError;

#[test]
fn original_retirement_idle_admission_keeps_exact_transport_and_sequence() -> anyhow::Result<()> {
    let history = snapshots(Decision::Update)?;
    let (client, mut peer) = client(&history[0]);
    peer.set_nonblocking(true)?;
    {
        let held = AgentdLearningCheckpointClientV1::lock_original_retirement_channel(&client)?;
        assert_eq!(held.as_ref().unwrap().next_request_id, 1);
        assert!(matches!(
            client.channel.try_lock(),
            Err(TryLockError::WouldBlock)
        ));
        assert!(matches!(
            peer.read(&mut [0]),
            Err(error) if error.kind() == ErrorKind::WouldBlock
        ));
    }
    assert_eq!(
        client.channel.lock().unwrap().as_ref().unwrap().next_request_id,
        1
    );
    assert!(matches!(
        peer.read(&mut [0]),
        Err(error) if error.kind() == ErrorKind::WouldBlock
    ));
    drop(client);
    assert_eq!(peer.read(&mut [0])?, 0);
    Ok(())
}

#[test]
fn original_retirement_admission_refuses_busy_and_unfinished_slots() -> anyhow::Result<()> {
    let history = snapshots(Decision::Update)?;
    let (client, mut peer) = client(&history[0]);
    peer.set_nonblocking(true)?;
    let mut held = client.channel.lock().unwrap();
    assert!(
        AgentdLearningCheckpointClientV1::lock_original_retirement_channel(&client).is_err()
    );
    let actual_in_flight = held.take().unwrap();
    drop(held);
    assert!(
        AgentdLearningCheckpointClientV1::lock_original_retirement_channel(&client).is_err()
    );
    assert!(client.channel.lock().unwrap().is_none());
    // The unfinished exchange still owns its real transport. Refusal neither
    // puts it back nor claims that a missing slot was a successful close.
    assert!(matches!(
        peer.read(&mut [0]),
        Err(error) if error.kind() == ErrorKind::WouldBlock
    ));
    drop(actual_in_flight);
    assert_eq!(peer.read(&mut [0])?, 0);
    assert!(client.channel.lock().unwrap().is_none());
    Ok(())
}

#[test]
fn original_retirement_admission_refuses_poison_without_releasing_owner() -> anyhow::Result<()> {
    let history = snapshots(Decision::Update)?;
    let (client, mut peer) = client(&history[0]);
    let client = Arc::new(client);
    peer.set_nonblocking(true)?;
    let owned = Arc::clone(&client);
    let worker = std::thread::spawn(move || {
        let _held = owned.channel.lock().unwrap();
        panic!("poison the actual original channel mutex");
    });
    assert!(worker.join().is_err());
    assert!(
        AgentdLearningCheckpointClientV1::lock_original_retirement_channel(client.as_ref())
            .is_err()
    );
    let poisoned = match client.channel.lock() {
        Err(poisoned) => poisoned.into_inner(),
        Ok(_) => panic!("actual channel mutex was not poisoned"),
    };
    assert_eq!(poisoned.as_ref().unwrap().next_request_id, 1);
    drop(poisoned);
    assert!(matches!(
        peer.read(&mut [0]),
        Err(error) if error.kind() == ErrorKind::WouldBlock
    ));
    drop(client);
    assert_eq!(peer.read(&mut [0])?, 0);
    Ok(())
}
