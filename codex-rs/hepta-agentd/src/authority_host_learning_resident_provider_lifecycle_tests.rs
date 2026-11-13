//! Actual registered Root, original Candidate admission and unmodified runtime
//! supervision before any Admit. Dedicated-UID peers fail on role dispatch.
//! These cases prove idle lifetime boundaries, not completed NoUpdate or B.

use super::*;
use crate::AgentdError;
use crate::RootResidentCandidateServiceV1;
use pretty_assertions::assert_eq;
use tokio_util::sync::CancellationToken;

struct Idle {
    root: ResidentRootFixture,
    material: MaterialCommandFixture,
    before: Vec<Vec<u8>>,
    peer: process::PeerProcess,
    service: RootResidentCandidateServiceV1,
    latest_original_end: Instant,
}

async fn idle(recovered: bool, lifetime: Duration, delay: Duration) -> anyhow::Result<Idle> {
    let (material, protocol) = material().await?;
    let before = material.bytes()?;
    let mut root = root(&material)?;
    if recovered {
        root.recover()?;
    }
    assert_eq!(
        root.registration
            .as_ref()
            .expect("actual Root registration")
            .owner
            .authority
            .readonly(),
        recovered
    );
    let mut peer = process::PeerProcess::start()?;
    let (streams, a) = peer.take_streams()?;
    let streams = role_streams(&peer, streams, &root.profile, lifetime)?;
    let (handoff, after_send) = transfer(&root.profile, streams)?;
    tokio::time::sleep(delay).await;
    let registration = root
        .registration
        .take()
        .ok_or_else(|| anyhow::anyhow!("once-consumed original registration"))?;
    let service = registration.into_candidate_service(
        input(&material, protocol),
        handoff,
        consumer(&peer, a, Duration::from_secs(3))?,
    )?;
    Ok(Idle {
        root,
        material,
        before,
        peer,
        service,
        latest_original_end: after_send + lifetime,
    })
}

async fn unchanged_and_joined(mut idle: IdleRemainder) -> anyhow::Result<()> {
    // A new explicitly authorized read-only opening observes the real protected
    // record only after the consumed service and all its role channels ended.
    idle.root.recover()?;
    let observed = idle
        .root
        .registration
        .as_ref()
        .expect("actual recovered Root")
        .owner
        .read(&CancellationToken::new())
        .await?
        .0;
    assert!(observed.snapshot.is_none());
    assert!(!observed.dispatch_pending);
    assert_eq!(idle.material.bytes()?, idle.before);
    idle.peer.finish()?;
    Ok(())
}

struct IdleRemainder {
    root: ResidentRootFixture,
    material: MaterialCommandFixture,
    before: Vec<Vec<u8>>,
    peer: process::PeerProcess,
}

impl Idle {
    fn split(self) -> (RootResidentCandidateServiceV1, IdleRemainder, Instant) {
        (
            self.service,
            IdleRemainder {
                root: self.root,
                material: self.material,
                before: self.before,
                peer: self.peer,
            },
            self.latest_original_end,
        )
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "explicit actual Root and pre-existing protected bind qualification"]
async fn resident_idle_original_a_eof_does_not_cancel_fresh_or_readonly_root() -> anyhow::Result<()>
{
    for recovered in [false, true] {
        let (service, remainder, _) =
            Box::pin(idle(recovered, Duration::from_secs(3), Duration::ZERO))
                .await?
                .split();
        let cancellation = CancellationToken::new();
        let _cancel_on_drop = cancellation.clone().drop_guard();
        let mut running = tokio::spawn(RootResidentCandidateServiceV1::run(
            service,
            cancellation.clone(),
        ));
        remainder.peer.close_a()?;
        assert!(
            tokio::time::timeout(Duration::from_millis(150), &mut running)
                .await
                .is_err(),
            "actual A EOF cannot end the resident runtime"
        );
        assert!(!cancellation.is_cancelled());
        cancellation.cancel();
        tokio::time::timeout(Duration::from_secs(2), running).await???;
        unchanged_and_joined(remainder).await?;
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "explicit actual Root and pre-existing protected bind qualification"]
async fn resident_idle_root_cancel_closes_live_a_and_joins_original_work() -> anyhow::Result<()> {
    let (service, remainder, _) = Box::pin(idle(false, Duration::from_secs(3), Duration::ZERO))
        .await?
        .split();
    let cancellation = CancellationToken::new();
    let _cancel_on_drop = cancellation.clone().drop_guard();
    let mut running = tokio::spawn(RootResidentCandidateServiceV1::run(
        service,
        cancellation.clone(),
    ));
    // A is still actually connected. No role command or substituted reply is
    // issued to drive the loop; Root alone requests termination.
    assert!(
        tokio::time::timeout(Duration::from_millis(50), &mut running)
            .await
            .is_err()
    );
    cancellation.cancel();
    let terminal = tokio::time::timeout(Duration::from_secs(2), running).await??;
    // Shutdown may be observed as EOF or the original server transport error.
    // Neither represents a completed learning result. Preserve that distinction.
    assert!(
        matches!(&terminal, Ok(()) | Err(AgentdError::Protocol(_))),
        "{terminal:?}"
    );
    println!("RESIDENT_IDLE_ROOT_CANCEL original_terminal={terminal:?}");
    unchanged_and_joined(remainder).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "explicit actual Root and pre-existing protected bind qualification"]
async fn resident_idle_delivery_delay_keeps_original_service_expiry_and_joins() -> anyhow::Result<()>
{
    let (service, remainder, latest_original_end) = Box::pin(idle(
        false,
        Duration::from_secs(1),
        Duration::from_millis(400),
    ))
    .await?
    .split();
    let cancellation = CancellationToken::new();
    let _cancel_on_drop = cancellation.clone().drop_guard();
    let running = tokio::spawn(RootResidentCandidateServiceV1::run(
        service,
        cancellation.clone(),
    ));
    // The extra observation window is only a scheduling/join bound. It is not
    // supplied to any production channel, handoff, service or test gate.
    let observation_end = latest_original_end + Duration::from_millis(200);
    let terminal = tokio::time::timeout_at(observation_end.into(), running).await??;
    assert!(
        matches!(&terminal, Err(AgentdError::GenerationFenced(_))),
        "{terminal:?}"
    );
    assert!(
        !cancellation.is_cancelled(),
        "the service expires without mutating its parent's token"
    );
    unchanged_and_joined(remainder).await
}
