//! Exercise the real one-worker scheduler and original Root read feed. These
//! are component checks, not an ordinary-main or external Root qualification.

use super::InitialLaneAdmission;
use super::run_original_blocking;
use crate::AgentdError;
use pretty_assertions::assert_eq;
use std::cell::Cell;
use std::rc::Rc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::time::Duration;
use std::time::Instant;

#[tokio::test(flavor = "multi_thread", worker_threads = 1)]
async fn initial_blocking_scope_keeps_original_root_feed_current_on_one_worker()
-> anyhow::Result<()> {
    // The test's block_on thread is not the sole worker. The entire workload
    // must be a spawned task, or synchronous blocking could falsely pass.
    tokio::spawn(async {
        let (session, _, peer, _) = crate::root_authority_session::tests::connected().await;
        let refresh = crate::root_authority_session::tests::observation_worker(&session);
        let clock = session.clock();
        let outcome = (|| -> anyhow::Result<()> {
            let admission = InitialLaneAdmission::for_artifact()?;
            let data = Mutex::new(());
            let fenced = AtomicBool::new(false);
            let local = Rc::new(Cell::new(0));
            let mut borrowed = 0;
            let original_thread = std::thread::current().id();
            let started = Instant::now();
            for _ in 0..3 {
                // Shorter than the unchanged 500 ms product frame/freshness
                // limits; handoff must not restart this already chosen end.
                let end = Instant::now() + Duration::from_millis(400);
                run_original_blocking(|| {
                    assert_eq!(std::thread::current().id(), original_thread);
                    InitialLaneAdmission::with_original_action(
                        &admission,
                        &data,
                        &fenced,
                        end,
                        |_| {
                            clock.now_unix_ms().map(|_| ()).map_err(|error| {
                                AgentdError::Invalid(format!("original clock: {error:?}"))
                            })
                        },
                        |_| {
                            // Nested Initial wire scopes preserve these
                            // non-Send borrows on this same original thread.
                            run_original_blocking(|| {
                                assert_eq!(std::thread::current().id(), original_thread);
                                local.set(local.get() + 1);
                                borrowed += 1;
                                std::thread::sleep(Duration::from_millis(200));
                            });
                            Ok(())
                        },
                    )
                })?;
                assert!(Instant::now() < end);
            }
            // Without the handoff, the independently spawned 100 ms feed
            // cannot run and its original 500 ms freshness fence rejects.
            assert!(started.elapsed() >= Duration::from_millis(600));
            assert_eq!(local.get(), 3);
            assert_eq!(borrowed, 3);
            assert!(!fenced.load(Ordering::Acquire));
            Ok(())
        })();
        drop(session);
        tokio::time::timeout(Duration::from_secs(2), async {
            while !refresh.is_finished() {
                tokio::task::yield_now().await;
            }
        })
        .await?;
        run_original_blocking(|| peer.join().expect("original Root peer"));
        outcome
    })
    .await?
}

#[tokio::test(flavor = "multi_thread", worker_threads = 1)]
async fn initial_blocking_scope_preserves_the_original_admission_deadline() -> anyhow::Result<()> {
    tokio::spawn(async {
        let (sent, received) = mpsc::channel();
        let timer = tokio::spawn(async move {
            tokio::time::sleep(Duration::from_millis(20)).await;
            sent.send(()).expect("independent timer");
        });
        let outcome = (|| -> anyhow::Result<()> {
            let admission = InitialLaneAdmission::for_artifact()?;
            let data = Mutex::new(0_u64);
            let fenced = AtomicBool::new(false);
            let held =
                admission.acquire(&data, &fenced, Instant::now() + Duration::from_millis(500))?;
            let end = Instant::now() + Duration::from_millis(60);
            let entered = Cell::new(false);
            let result = run_original_blocking(|| {
                InitialLaneAdmission::with_original_action(
                    &admission,
                    &data,
                    &fenced,
                    end,
                    |_| Ok(()),
                    |_| {
                        entered.set(true);
                        Ok(())
                    },
                )
            });
            assert!(result.is_err());
            assert!(Instant::now() >= end);
            assert!(
                Instant::now() < end + Duration::from_millis(250),
                "the queue must not receive a fresh 500 ms end"
            );
            assert!(!entered.get());
            assert_eq!(*held.data, 0);
            assert!(fenced.load(Ordering::Acquire));
            assert_eq!(received.try_recv(), Ok(()));
            held.release()?;
            Ok(())
        })();
        timer.await?;
        outcome
    })
    .await?
}

#[tokio::test(flavor = "current_thread")]
async fn initial_blocking_scope_retains_current_thread_borrows() {
    let original_thread = std::thread::current().id();
    let local = Rc::new(Cell::new(1));
    let mut borrowed = 2;
    let result = run_original_blocking(|| {
        assert_eq!(std::thread::current().id(), original_thread);
        local.set(3);
        borrowed = 4;
        Rc::clone(&local)
    });
    assert!(Rc::ptr_eq(&result, &local));
    assert_eq!(borrowed, 4);
    assert_eq!(local.get(), 3);
}

#[test]
fn initial_blocking_scope_retains_standalone_borrows() {
    assert!(tokio::runtime::Handle::try_current().is_err());
    let original_thread = std::thread::current().id();
    let local = Rc::new(Cell::new(1));
    let mut borrowed = 2;
    let result = run_original_blocking(|| {
        assert_eq!(std::thread::current().id(), original_thread);
        local.set(3);
        borrowed = 4;
        Rc::clone(&local)
    });
    assert!(Rc::ptr_eq(&result, &local));
    assert_eq!(borrowed, 4);
    assert_eq!(local.get(), 3);
}
