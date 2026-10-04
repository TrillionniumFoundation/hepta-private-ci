use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::time::Duration;
use std::time::Instant;

use super::*;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Kind {
    Mutation,
    History,
    Picker,
    Close,
}

fn drain<T: Send + 'static>(
    controller: &mut TaskController<Kind, T>,
) -> Vec<(Kind, JoinedTask<T>)> {
    let deadline = Instant::now() + Duration::from_secs(5);
    let mut outcomes = Vec::new();
    while controller.any_active() {
        for (index, outcome) in controller.poll().into_iter().enumerate() {
            if let Some((kind, joined)) = outcome {
                assert_eq!(
                    index,
                    match kind {
                        Kind::Mutation | Kind::Close => 0,
                        Kind::History => 1,
                        Kind::Picker => 2,
                    }
                );
                outcomes.push((kind, joined));
            }
        }
        assert!(Instant::now() < deadline, "owned workers did not finish");
        std::thread::yield_now();
    }
    assert!(
        controller
            .poll()
            .into_iter()
            .all(|outcome| outcome.is_none())
    );
    outcomes
}

#[test]
fn mutation_and_history_are_serialized_while_picker_is_independent() {
    for (lane, kind) in [
        (TaskLane::Runtime, Kind::Mutation),
        (TaskLane::History, Kind::History),
    ] {
        let shutdown = Shutdown::default();
        let mut controller = TaskController::default();
        let (release, wait) = mpsc::channel();
        controller
            .start(lane, &shutdown, || {
                PendingTask::spawn(
                    kind,
                    "lane-owner",
                    || {},
                    move |admission| {
                        admission.begin().unwrap();
                        wait.recv().unwrap();
                        7
                    },
                )
            })
            .unwrap();
        assert!(controller.runtime_busy(&shutdown));
        assert!(!controller.picker_busy(&shutdown));
        for blocked in [TaskLane::Runtime, TaskLane::History] {
            let error = controller
                .start(blocked, &shutdown, || panic!("busy lane started a worker"))
                .unwrap_err();
            assert_eq!(error.kind(), std::io::ErrorKind::WouldBlock);
        }
        controller
            .start(TaskLane::Picker, &shutdown, || {
                PendingTask::spawn(Kind::Picker, "independent-picker", || {}, |_| 9)
            })
            .unwrap();
        assert!(controller.picker_busy(&shutdown));
        assert!(
            controller
                .start(TaskLane::Picker, &shutdown, || panic!(
                    "picker replaced its worker"
                ))
                .is_err()
        );
        release.send(()).unwrap();
        let outcomes = drain(&mut controller);
        assert_eq!(outcomes.len(), 2);
        assert!(outcomes.contains(&(kind, Ok(7))));
        assert!(outcomes.contains(&(Kind::Picker, Ok(9))));
        assert!(!controller.runtime_busy(&shutdown));
        assert!(!controller.picker_busy(&shutdown));
    }
}

#[test]
fn completion_wake_does_not_release_the_lane_before_join() {
    let mut controller = TaskController::default();
    let shutdown = Shutdown::default();
    let (wake, awakened) = mpsc::channel();
    controller
        .start(TaskLane::Runtime, &shutdown, || {
            PendingTask::spawn(
                Kind::Mutation,
                "completed-owner",
                move || wake.send(()).unwrap(),
                |admission| {
                    admission.begin().unwrap();
                    "completed"
                },
            )
        })
        .unwrap();
    awakened.recv_timeout(Duration::from_secs(5)).unwrap();
    assert_eq!(
        controller.pending(TaskLane::Runtime).unwrap().kind,
        Kind::Mutation
    );
    assert!(
        controller
            .start(TaskLane::History, &shutdown, || panic!(
                "completion was not joined"
            ))
            .is_err()
    );
    assert_eq!(
        drain(&mut controller),
        vec![(Kind::Mutation, Ok("completed"))]
    );
    controller
        .start(TaskLane::History, &shutdown, || {
            PendingTask::spawn(Kind::History, "after-join", || {}, |_| "read")
        })
        .unwrap();
    assert_eq!(drain(&mut controller), vec![(Kind::History, Ok("read"))]);
}

#[test]
fn shutdown_drains_admitted_owner_and_cancelled_picker_before_close() {
    let mut controller = TaskController::default();
    let mut shutdown = Shutdown::default();
    shutdown.update_requested = true;
    let calls = Arc::new(AtomicUsize::new(0));
    let effects = Arc::clone(&calls);
    let (entered, admitted) = mpsc::channel();
    let (release, wait) = mpsc::channel();
    controller
        .start(TaskLane::Runtime, &shutdown, || {
            PendingTask::spawn(
                Kind::Mutation,
                "admitted-owner",
                || {},
                move |admission| {
                    admission.begin()?;
                    entered.send(()).unwrap();
                    wait.recv().unwrap();
                    effects.fetch_add(1, Ordering::SeqCst);
                    Ok(())
                },
            )
        })
        .unwrap();
    admitted.recv_timeout(Duration::from_secs(5)).unwrap();
    let (picker_release, picker_wait) = mpsc::channel();
    controller
        .start(TaskLane::Picker, &shutdown, || {
            PendingTask::spawn(
                Kind::Picker,
                "waiting-picker",
                || {},
                move |admission| {
                    picker_wait.recv().unwrap();
                    admission.begin()
                },
            )
        })
        .unwrap();
    shutdown.request(Instant::now());
    controller.cancel_waiting();
    for lane in [TaskLane::Runtime, TaskLane::History, TaskLane::Picker] {
        assert!(
            controller
                .start(lane, &shutdown, || panic!(
                    "shutdown admitted ordinary work"
                ))
                .is_err()
        );
    }
    assert!(
        controller
            .start_close(&shutdown, || panic!("close overtook an owned worker"))
            .is_err()
    );
    assert!(!shutdown.activation_allowed());
    release.send(()).unwrap();
    picker_release.send(()).unwrap();
    let outcomes = drain(&mut controller);
    assert_eq!(outcomes.len(), 2);
    assert!(outcomes.contains(&(Kind::Mutation, Ok(Ok(())))));
    assert!(outcomes.contains(&(
        Kind::Picker,
        Ok(Err("native task cancelled before runtime admission"))
    )));
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert!(!shutdown.activation_allowed());
    controller
        .start_close(&shutdown, || {
            PendingTask::spawn(
                Kind::Close,
                "runtime-close",
                || {},
                |admission| admission.begin(),
            )
        })
        .unwrap();
    shutdown.close_started = true;
    assert_eq!(drain(&mut controller), vec![(Kind::Close, Ok(Ok(())))]);
    // A joined result is applied by the retained owner adapter, never guessed
    // from an empty queue or a worker wake.
    assert!(!shutdown.activation_allowed());
    shutdown.runtime_closed = true;
    assert!(shutdown.activation_allowed());
    assert!(
        controller
            .start_close(&shutdown, || panic!("close started twice"))
            .is_err()
    );
    shutdown.close_started = false;
    assert!(
        controller
            .start_close(&shutdown, || panic!("closed owner was restarted"))
            .is_err()
    );
}

#[test]
fn failed_spawn_preserves_empty_slots_and_close_retry() {
    let mut controller = TaskController::<Kind, ()>::default();
    let mut shutdown = Shutdown::default();
    for lane in [TaskLane::Runtime, TaskLane::History, TaskLane::Picker] {
        assert!(
            controller
                .start(lane, &shutdown, || Err(std::io::Error::other(
                    "spawn failed"
                )))
                .is_err()
        );
        assert!(controller.pending(lane).is_none());
    }
    assert!(
        controller
            .start_close(&shutdown, || panic!("close without request"))
            .is_err()
    );
    shutdown.request(Instant::now());
    assert!(
        controller
            .start_close(&shutdown, || Err(std::io::Error::other(
                "close spawn failed"
            )))
            .is_err()
    );
    assert!(!controller.any_active());
    shutdown.close_started = true;
    shutdown.failure = Some("close spawn failed".into());
    assert!(
        controller
            .start_close(&shutdown, || panic!("retry was not requested"))
            .is_err()
    );
    shutdown.close_started = false;
    controller
        .start_close(&shutdown, || {
            PendingTask::spawn(Kind::Close, "close-retry", || {}, |_| ())
        })
        .unwrap();
    assert_eq!(drain(&mut controller), vec![(Kind::Close, Ok(()))]);
    shutdown.runtime_closed = true;
    shutdown.update_requested = true;
    assert!(!shutdown.activation_allowed());
}

#[test]
fn panic_completion_is_joined_once_and_retains_failure() {
    let mut controller = TaskController::default();
    let shutdown = Shutdown::default();
    let (wake, awakened) = mpsc::channel();
    controller
        .start(TaskLane::Runtime, &shutdown, || {
            PendingTask::spawn(
                Kind::Mutation,
                "panic-owner",
                move || wake.send(()).unwrap(),
                |admission| {
                    admission.begin().unwrap();
                    panic!("owner failure");
                },
            )
        })
        .unwrap();
    awakened.recv_timeout(Duration::from_secs(5)).unwrap();
    assert_eq!(
        drain(&mut controller),
        vec![(
            Kind::Mutation,
            Err("native worker panicked; completion is not established")
        )]
    );
    assert!(!shutdown.runtime_closed);
    assert!(!shutdown.activation_allowed());
}
