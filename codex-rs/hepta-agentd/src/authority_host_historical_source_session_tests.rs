//! Actual Root process checks around a controlled ACK channel. These tests do
//! not represent A execution, Initial enrollment or a historical source grant.

use pretty_assertions::assert_eq;

use super::*;

fn channel(
    lifetime: Duration,
) -> io::Result<(
    RootHistoricalSourceCaptureCapabilityV1,
    mpsc::Receiver<Submission>,
)> {
    let (sender, receiver) = mpsc::sync_channel(1);
    Ok((
        RootHistoricalSourceCaptureCapabilityV1 {
            sender,
            phase: Arc::new(AtomicU8::new(ACTIVE)),
            root: RootLifetime {
                pid: std::process::id(),
                boot: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?
                    .trim()
                    .into(),
                start: super::super::root_start()?,
            },
            end: Arc::new(OnceLock::from(Instant::now() + lifetime)),
        },
        receiver,
    ))
}

#[test]
#[ignore = "actual UID0 for original Root process-bound capability checks"]
fn root_source_capture_capability_rejects_replaced_lifetime_and_late_ack() -> anyhow::Result<()> {
    let (expired, receiver) = channel(Duration::ZERO)?;
    assert!(expired.capture().is_err());
    assert!(matches!(
        receiver.try_recv(),
        Err(mpsc::TryRecvError::Disconnected)
    ));

    let (mut changed, receiver) = channel(Duration::from_millis(50))?;
    changed.root.start = changed
        .root
        .start
        .checked_add(1)
        .ok_or_else(|| anyhow::anyhow!("component start overflow"))?;
    assert!(changed.capture().is_err());
    assert!(matches!(
        receiver.try_recv(),
        Err(mpsc::TryRecvError::Disconnected)
    ));

    let (capability, receiver) = channel(Duration::from_millis(50))?;
    let phase = Arc::clone(&capability.phase);
    let worker = std::thread::spawn(move || capability.capture());
    let submission = receiver.recv_timeout(Duration::from_secs(1))?;
    assert!(
        worker
            .join()
            .map_err(|_| anyhow::anyhow!("component capture worker"))?
            .is_err()
    );
    assert_eq!(phase.load(Ordering::Acquire), CLOSED);
    assert!(
        submission
            .acknowledgement
            .try_send(Ok(Digest32::of_bytes(b"late")))
            .is_err()
    );
    Ok(())
}

#[test]
#[ignore = "actual UID0 for original Root process-bound capability checks"]
fn root_source_capture_ack_is_data_and_keeps_the_one_shot_consumed() -> anyhow::Result<()> {
    let (capability, receiver) = channel(Duration::from_secs(1))?;
    let phase = Arc::clone(&capability.phase);
    let digest = Digest32::of_bytes(b"controlled-protected-record-component");
    let worker = std::thread::spawn(move || capability.capture());
    let submission = receiver.recv_timeout(Duration::from_secs(1))?;
    submission.acknowledgement.try_send(Ok(digest))?;
    let receipt = worker
        .join()
        .map_err(|_| anyhow::anyhow!("component capture worker"))??;
    assert_eq!(receipt.pin_digest(), digest);
    assert_eq!(phase.load(Ordering::Acquire), ACKNOWLEDGED);
    Ok(())
}
