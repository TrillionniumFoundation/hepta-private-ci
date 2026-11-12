//! Same-UID framing and shared-close components. The private client fixture
//! exercises actual UDS/pidfd and FileCas custody; it does not qualify the
//! Root-only constructor, a business snapshot, or a complete phase deployment.

use super::*;
use crate::same_actor_q24_phase_gate::RequiredSameActorPhaseChannel;
use crate::same_actor_q24_phase_gate::SameActorPhaseDeadline;
use crate::same_actor_q24_phase_gate::SameActorPhaseGate;
use codex_hepta_learning_artifacts::LearningUpdateScopeV2;
use pretty_assertions::assert_eq;

fn current_uid() -> u32 {
    // SAFETY: reads this test process's kernel credential without changing it.
    unsafe { libc::geteuid() }
}

struct PhaseClient {
    client: Arc<AgentdLearningCheckpointClientV1>,
    server: Option<UnixStream>,
    gate: Arc<SameActorPhaseGate>,
    _other: RequiredSameActorPhaseChannel,
    other_peer: UnixStream,
}

fn phase_client(
    initial: &LearningIterationSnapshotV1,
    scope: FrozenLearningScopeV2,
) -> PhaseClient {
    let gate = SameActorPhaseGate::from_original_deadline(
        SameActorPhaseDeadline::at_original_service_start(Duration::from_secs(10)).unwrap(),
    )
    .unwrap();
    let (stream, server) = UnixStream::pair().unwrap();
    let phase = gate.retain_required_original_stream(&stream).unwrap();
    // This same-UID transport is only the framing fixture. Until construction
    // remains the separate Root-only production entry and its own tests.
    let transport = RootObservationStream::from_stream_for_uid(
        stream,
        peer(),
        pidfd(),
        Duration::from_millis(500),
        Duration::from_secs(5),
        current_uid(),
    )
    .unwrap();
    let (other, other_peer) = UnixStream::pair().unwrap();
    let other = gate.retain_required_original_stream(&other).unwrap();
    other_peer
        .set_read_timeout(Some(Duration::from_secs(2)))
        .unwrap();
    PhaseClient {
        client: Arc::new(AgentdLearningCheckpointClientV1 {
            channel: Mutex::new(Some(Channel {
                transport,
                next_request_id: 1,
            })),
            initial: initial.clone(),
            scope: Some(scope),
            phase: Some(phase),
        }),
        server: Some(server),
        gate,
        _other: other,
        other_peer,
    }
}

fn scoped(initial: &LearningIterationSnapshotV1) -> FrozenLearningScopeV2 {
    FrozenLearningScopeV2::freeze(
        &initial.request,
        &initial.owners,
        LearningUpdateScopeV2::Cell,
        Digest32::of_bytes(b"same-actor-framing-component-rule"),
    )
    .unwrap()
}

fn backend(
    store: Arc<FileCas>,
    initial: &LearningIterationSnapshotV1,
    scope: FrozenLearningScopeV2,
) -> LearningIterationCheckpointOwnerV1 {
    LearningIterationCheckpointOwnerV1::from_research_store_scoped_v2(
        store,
        support::OWNER.into(),
        initial.request.clone(),
        initial.owners.clone(),
        scope,
    )
    .unwrap()
}

fn vacant(
    path: &std::path::Path,
    initial: &LearningIterationSnapshotV1,
    scope: &FrozenLearningScopeV2,
) -> Arc<FileCas> {
    Arc::new(
        FileCas::create(
            path,
            &LearningIterationCheckpointRecordV1::vacant_scoped_v2(
                initial.request.clone(),
                initial.owners.clone(),
                scope,
            )
            .unwrap(),
        )
        .unwrap(),
    )
}

fn closed(fixture: &mut PhaseClient) {
    assert!(fixture.gate.require_open().is_err());
    assert_eq!(fixture.other_peer.read(&mut [0]).unwrap(), 0);
}

#[tokio::test]
async fn phase_learning_success_keeps_lane_but_wrong_scope_closes_all_lanes() -> anyhow::Result<()>
{
    let history = snapshots(Decision::EvaluatedNoUpdate)?;
    let initial = &history[0];
    let scope = scoped(initial);
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("original");
    let store = vacant(&path, initial, &scope);
    let original = std::fs::read(&path)?;
    let mut fixture = phase_client(initial, scope.clone());
    let worker = serve(
        fixture.server.take().unwrap(),
        backend(store.clone(), initial, scope),
    );
    assert_eq!(fixture.client.restore(&initial.request).await?, None);
    assert!(fixture.gate.require_open().is_ok());
    let mut wrong = initial.request.clone();
    wrong.operation_id = codex_hepta_types::StableId::new("foreign-phase-request")?;
    assert_eq!(fixture.client.restore(&wrong).await, Err(Error::WrongScope));
    closed(&mut fixture);
    assert_eq!(
        fixture.client.restore(&initial.request).await,
        Err(Error::Store(AuthorityTrustError::Unavailable))
    );
    worker.join().unwrap()?;
    assert_eq!(store.commits.load(Ordering::SeqCst), 0);
    assert_eq!(std::fs::read(&path)?, original);
    Ok(())
}

#[tokio::test]
async fn phase_learning_original_owner_conflict_preserves_error_and_closes_connection()
-> anyhow::Result<()> {
    let history = snapshots(Decision::EvaluatedNoUpdate)?;
    let initial = &history[0];
    let scope = scoped(initial);
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("original");
    let store = vacant(&path, initial, &scope);
    let original = std::fs::read(&path)?;
    let mut fixture = phase_client(initial, scope.clone());
    let worker = serve(
        fixture.server.take().unwrap(),
        backend(store.clone(), initial, scope),
    );
    // The real store is vacant. This locally valid next snapshot has a
    // different predecessor, so the original owner returns Conflict.
    assert_eq!(
        fixture
            .client
            .checkpoint(initial.head_digest, &history[1])
            .await,
        Err(Error::Conflict)
    );
    assert!(fixture.client.channel.lock().unwrap().is_none());
    closed(&mut fixture);
    assert_eq!(
        fixture.client.checkpoint(Digest32::ZERO, initial).await,
        Err(Error::CommitUncertain(AuthorityTrustError::Unavailable))
    );
    worker.join().unwrap()?;
    assert_eq!(store.commits.load(Ordering::SeqCst), 0);
    assert_eq!(std::fs::read(&path)?, original);
    Ok(())
}

#[tokio::test]
async fn phase_learning_original_commit_lost_ack_is_kept_and_never_rearmed() -> anyhow::Result<()> {
    let history = snapshots(Decision::EvaluatedNoUpdate)?;
    let initial = &history[0];
    let scope = scoped(initial);
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("original");
    let store = vacant(&path, initial, &scope);
    store.failure.store(2, Ordering::SeqCst);
    let mut fixture = phase_client(initial, scope.clone());
    let worker = serve(
        fixture.server.take().unwrap(),
        backend(store.clone(), initial, scope),
    );
    assert_eq!(
        fixture.client.checkpoint(Digest32::ZERO, initial).await,
        Err(Error::CommitUncertain(AuthorityTrustError::Unavailable))
    );
    closed(&mut fixture);
    assert!(worker.join().unwrap().is_err());
    let committed = std::fs::read(&path)?;
    assert_eq!(store.commits.load(Ordering::SeqCst), 1);
    assert_eq!(
        fixture.client.checkpoint(Digest32::ZERO, initial).await,
        Err(Error::CommitUncertain(AuthorityTrustError::Unavailable))
    );
    assert_eq!(
        fixture.client.restore(&initial.request).await,
        Err(Error::Store(AuthorityTrustError::Unavailable))
    );
    assert_eq!(store.commits.load(Ordering::SeqCst), 1);
    assert_eq!(std::fs::read(&path)?, committed);
    Ok(())
}

#[tokio::test]
async fn phase_learning_cancelled_ack_closes_other_lane_while_client_is_retained()
-> anyhow::Result<()> {
    let history = snapshots(Decision::EvaluatedNoUpdate)?;
    let initial = &history[0];
    let scope = scoped(initial);
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("original");
    let store = vacant(&path, initial, &scope);
    let mut fixture = phase_client(initial, scope.clone());
    let backend = backend(store.clone(), initial, scope);
    let server = fixture.server.take().unwrap();
    let (committed, observed) = tokio::sync::oneshot::channel();
    let (release, released) = std::sync::mpsc::channel();
    let worker = std::thread::spawn(move || {
        let policy = HostAuthorityPeerPolicy {
            peer: HostIssuerPeer {
                uid: current_uid(),
                pid: std::process::id(),
            },
            timeout: Duration::from_millis(500),
            lifetime: Duration::from_secs(10),
            request_bound: FRAME_BOUND,
            response_bound: FRAME_BOUND,
        };
        let mut channel = HostAuthorityPeerChannel::from_stream(server, policy, pidfd()).unwrap();
        let mut committed = Some(committed);
        let result = channel.exchange(|bytes| {
            let response = backend.exchange_learning_checkpoint(bytes, &mut 1)?;
            committed.take().unwrap().send(()).unwrap();
            released.recv_timeout(Duration::from_secs(2)).unwrap();
            Ok(response)
        });
        assert!(result.is_err());
    });
    let client = Arc::clone(&fixture.client);
    let snapshot = initial.clone();
    let pending = tokio::spawn(async move { client.checkpoint(Digest32::ZERO, &snapshot).await });
    observed.await?;
    pending.abort();
    assert!(pending.await.unwrap_err().is_cancelled());
    // The original client still exists here. The cancelled exchange guard,
    // not dropping that owner, must close its separately retained sibling.
    closed(&mut fixture);
    assert_eq!(store.commits.load(Ordering::SeqCst), 1);
    let committed = std::fs::read(&path)?;
    release.send(())?;
    worker.join().unwrap();
    assert_eq!(
        fixture.client.restore(&initial.request).await,
        Err(Error::Store(AuthorityTrustError::Unavailable))
    );
    assert_eq!(std::fs::read(&path)?, committed);
    Ok(())
}

#[tokio::test]
async fn phase_learning_constructor_rejects_nonempty_initial_and_closes_before_peer_use()
-> anyhow::Result<()> {
    let history = snapshots(Decision::EvaluatedNoUpdate)?;
    let scope = scoped(&history[0]);
    let gate = SameActorPhaseGate::from_original_deadline(
        SameActorPhaseDeadline::at_original_service_start(Duration::from_secs(10))?,
    )?;
    let (stream, mut remote) = UnixStream::pair()?;
    remote.set_read_timeout(Some(Duration::from_secs(2)))?;
    let result = AgentdLearningCheckpointClientV1::from_original_same_actor_stream_until(
        stream,
        peer(),
        pidfd(),
        history[1].clone(),
        Duration::from_millis(500),
        scope,
        &gate,
    );
    assert!(matches!(result, Err(Error::WrongScope)));
    assert!(gate.require_open().is_err());
    assert_eq!(remote.read(&mut [0])?, 0);
    Ok(())
}
