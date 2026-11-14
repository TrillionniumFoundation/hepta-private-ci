use super::SandboxAccountLease;
use anyhow::Context;
use anyhow::Result;
use pretty_assertions::assert_eq;
use std::sync::mpsc;
use std::thread;

#[test]
fn account_lease_excludes_other_launches_and_survives_thread_handoff() -> Result<()> {
    let first = SandboxAccountLease::acquire()?;
    let (entered_tx, entered_rx) = mpsc::channel();
    let (acquired_tx, acquired_rx) = mpsc::channel();
    let contender = thread::spawn(move || -> Result<()> {
        entered_tx.send(())?;
        let second = SandboxAccountLease::acquire()?;
        acquired_tx.send(())?;
        drop(second);
        Ok(())
    });
    entered_rx.recv()?;
    assert_eq!(acquired_rx.try_recv(), Err(mpsc::TryRecvError::Empty));
    // The caller can move to a blocking worker before completing runner logon.
    thread::spawn(move || drop(first))
        .join()
        .map_err(|_| anyhow::anyhow!("account lease handoff thread panicked"))?;
    acquired_rx.recv()?;
    contender
        .join()
        .map_err(|_| anyhow::anyhow!("account lease contender panicked"))??;
    let third = SandboxAccountLease::acquire().context("reacquire after both launches")?;
    drop(third);
    Ok(())
}
