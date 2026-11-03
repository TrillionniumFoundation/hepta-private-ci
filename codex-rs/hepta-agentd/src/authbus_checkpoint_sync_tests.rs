use super::*;
use std::future::Future;
use std::pin::Pin;
use std::task::Poll;

use codex_hepta_authbus::SignedMessage;

use crate::AuthBusTextState;
use crate::authbus_trust::hex_bytes;

#[tokio::test]
async fn concurrent_checkpoint_syncs_share_owner_lock_and_preserve_rollback_rejection() {
    for algorithm in [AuthBusAlgorithm::Ed25519V1, AuthBusAlgorithm::MlDsa65V2] {
        let fixture = Fixture::with_algorithm(algorithm).await;
        let host = attached(&fixture.state).unwrap();
        let trust = host.trust(&fixture.state).await.unwrap();
        let previous_witness = std::fs::read(&fixture.checkpoint_file).unwrap();
        let request = fixture.request(/*sequence*/ 1);
        let body = payload(&request.body).unwrap();
        let message = SignedMessage {
            claims: authbus_text_claims(&fixture.state.identity().agent_id, &request).unwrap(),
            signature: match algorithm {
                AuthBusAlgorithm::Ed25519V1 => {
                    hex_bytes::<64>(&request.signature_hex).unwrap().into()
                }
                AuthBusAlgorithm::MlDsa65V2 => {
                    hex_bytes::<3309>(&request.signature_hex).unwrap().into()
                }
            },
        };
        host.evidence
            .enqueue_authbus_message(
                &trust.issuer().unwrap(),
                &message,
                &host.subject,
                host.scope,
                &body,
            )
            .await
            .unwrap();
        let pending = host
            .evidence
            .pending_authbus_restore_checkpoint()
            .await
            .unwrap()
            .unwrap();

        // Stop the first real handshake immediately after its protected-file
        // read, before it starts SQLite reconciliation. No sleeps or retry
        // loops select the interleaving.
        let (first_read, resume_first) = host.pause_next_checkpoint_read();
        let first = host.sync_replay_checkpoint();
        tokio::pin!(first);
        tokio::select! {
            result = &mut first => panic!("sync completed before its read pause: {result:?}"),
            reached = first_read => reached.unwrap(),
        }

        let (mut second_read, resume_second) = host.pause_next_checkpoint_read();
        // Disable only the scheduler's cooperative early yield for this poll:
        // an unguarded implementation must reach the installed second read
        // pause, while the guarded implementation must wait for the owner.
        let second = tokio::task::unconstrained(host.sync_replay_checkpoint());
        tokio::pin!(second);
        poll_pending(second.as_mut()).await;
        assert!(
            matches!(
                second_read.try_recv(),
                Err(tokio::sync::oneshot::error::TryRecvError::Empty)
            ),
            "another sync read the predecessor while the first handshake owned it"
        );

        resume_first.send(()).unwrap();
        resume_second.send(()).unwrap();
        let (first, second) = tokio::join!(first, second);
        first.unwrap();
        second.unwrap();
        second_read.await.unwrap();
        assert_eq!(host.checkpoint.read().unwrap(), pending);
        assert_eq!(
            host.evidence.authbus_restore_checkpoint().await.unwrap(),
            Some(pending)
        );
        assert_eq!(
            host.evidence
                .pending_authbus_restore_checkpoint()
                .await
                .unwrap(),
            None
        );

        // Serialization must not reinterpret a genuine old witness as
        // concurrency. Restore only the exact newer witness actually produced
        // above, then require a fresh signed request to resume normal service.
        let current_witness = std::fs::read(&fixture.checkpoint_file).unwrap();
        std::fs::write(&fixture.checkpoint_file, previous_witness).unwrap();
        assert!(host.sync_replay_checkpoint().await.is_err());
        assert_eq!(
            host.evidence.authbus_restore_checkpoint().await.unwrap(),
            Some(pending)
        );
        std::fs::write(&fixture.checkpoint_file, current_witness).unwrap();
        host.sync_replay_checkpoint().await.unwrap();
        let resumed = submit(&fixture.state, fixture.request(/*sequence*/ 2))
            .await
            .unwrap();
        assert_eq!(resumed.state, AuthBusTextState::Queued);
    }
}

#[tokio::test]
async fn cancelled_checkpoint_sync_waiter_and_owner_release_exclusive_admission() {
    for algorithm in [AuthBusAlgorithm::Ed25519V1, AuthBusAlgorithm::MlDsa65V2] {
        let fixture = Fixture::with_algorithm(algorithm).await;
        let host = attached(&fixture.state).expect("attached ingress");
        let before = host.checkpoint.read().expect("initial checkpoint");
        let (first_read, resume_first) = host.pause_next_checkpoint_read();
        let mut first = Box::pin(tokio::task::unconstrained(host.sync_replay_checkpoint()));
        tokio::select! {
            result = &mut first => panic!("sync completed before its read pause: {result:?}"),
            reached = first_read => reached.expect("first checkpoint read"),
        }
        let (mut next_read, resume_next) = host.pause_next_checkpoint_read();
        {
            let mut waiting = Box::pin(tokio::task::unconstrained(host.sync_replay_checkpoint()));
            poll_pending(waiting.as_mut()).await;
            assert!(matches!(
                next_read.try_recv(),
                Err(tokio::sync::oneshot::error::TryRecvError::Empty)
            ));
            // Cancel a queued operation before it receives the sole permit.
        }
        let mut next = Box::pin(tokio::task::unconstrained(host.sync_replay_checkpoint()));
        poll_pending(next.as_mut()).await;
        assert!(matches!(
            next_read.try_recv(),
            Err(tokio::sync::oneshot::error::TryRecvError::Empty)
        ));
        // Cancel the holder after its real protected-file read. Dropping its
        // future must release admission without advancing either checkpoint.
        drop(first);
        assert!(resume_first.send(()).is_err());
        poll_pending(next.as_mut()).await;
        next_read.try_recv().expect("next owner acquired admission");
        resume_next.send(()).expect("resume next owner");
        next.await.expect("checkpoint synchronization resumes");
        assert_eq!(host.checkpoint.read().expect("current checkpoint"), before);
        assert_eq!(
            host.evidence
                .authbus_restore_checkpoint()
                .await
                .expect("local checkpoint"),
            Some(before)
        );
        assert_eq!(
            host.evidence
                .pending_authbus_restore_checkpoint()
                .await
                .expect("pending checkpoint"),
            None
        );
        let resumed = submit(&fixture.state, fixture.request(/*sequence*/ 1))
            .await
            .expect("fresh signed message after cancellation");
        assert_eq!(resumed.state, AuthBusTextState::Queued);
    }
}

async fn poll_pending<F: Future>(mut future: Pin<&mut F>) {
    std::future::poll_fn(|context| {
        assert!(future.as_mut().poll(context).is_pending());
        Poll::Ready(())
    })
    .await;
}
