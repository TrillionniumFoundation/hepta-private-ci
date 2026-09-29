use super::*;

#[test]
fn terminal_reserve_preserves_fifo_and_shutdown_when_every_quota_is_full() {
    let (sender, mut receiver) = channel_with_terminal_capacity(2, 2).unwrap();
    sender.send(1).unwrap();
    sender.send(2).unwrap();
    assert_eq!(sender.send(3), Err(SendError::Full));
    sender.send_terminal(4).unwrap();
    sender.send_terminal(5).unwrap();
    assert_eq!(sender.send_terminal(6), Err(SendError::Full));
    sender.seal_and_send(9).unwrap();
    assert_eq!(sender.send(10), Err(SendError::Closed));
    assert_eq!(sender.send_terminal(11), Err(SendError::Closed));
    for value in [1, 2, 4, 5, 9] {
        assert_eq!(receiver.blocking_recv(), Some(value));
        receiver.finish_command(/*successful_reply_lost*/ false);
    }
    let metrics = sender.metrics().unwrap();
    assert_eq!(
        (metrics.capacity, metrics.depth, metrics.high_water),
        (4, 0, 4)
    );
    assert_eq!((metrics.ordinary_depth, metrics.terminal_depth), (0, 0));
    assert_eq!(
        (metrics.rejected_full, metrics.rejected_terminal_full),
        (2, 1)
    );
    assert_eq!(
        (
            metrics.ordinary_queue_wait.observed,
            metrics.terminal_queue_wait.observed
        ),
        (2, 2)
    );
    assert_eq!(
        (
            metrics.ordinary_apply.observed,
            metrics.terminal_apply.observed
        ),
        (2, 2)
    );
}

#[test]
fn terminal_traffic_cannot_steal_ordinary_quota_or_overtake_it() {
    let (sender, mut receiver) = channel_with_terminal_capacity(1, 1).unwrap();
    sender.send_terminal(1).unwrap();
    sender.send(2).unwrap();
    assert_eq!(sender.send_terminal(3), Err(SendError::Full));
    assert_eq!(receiver.blocking_recv(), Some(1));
    receiver.finish_command(/*successful_reply_lost*/ true);
    sender.send_terminal(4).unwrap();
    assert_eq!(receiver.blocking_recv(), Some(2));
    receiver.finish_command(/*successful_reply_lost*/ false);
    assert_eq!(receiver.blocking_recv(), Some(4));
    receiver.finish_command(/*successful_reply_lost*/ false);
    assert_eq!(sender.metrics().unwrap().successful_replies_lost, 1);
    assert!(channel_with_terminal_capacity::<u8>(usize::MAX, 1).is_none());
    assert!(channel_with_terminal_capacity::<u8>(1, 0).is_none());
}

#[test]
fn concurrent_producers_are_bounded_and_all_accepted_commands_precede_shutdown() {
    let (sender, mut receiver) = channel_with_terminal_capacity(8, 8).unwrap();
    let producers: Vec<_> = (0..32)
        .map(|id| {
            let sender = sender.clone();
            std::thread::spawn(move || {
                let result = if id % 2 == 0 {
                    sender.send(id)
                } else {
                    sender.send_terminal(id)
                };
                result.is_ok().then_some(id)
            })
        })
        .collect();
    let mut accepted: Vec<_> = producers
        .into_iter()
        .filter_map(|join| join.join().unwrap())
        .collect();
    assert_eq!(accepted.len(), 16);
    sender.seal_and_send(99).unwrap();
    let mut observed = Vec::new();
    for _ in 0..accepted.len() {
        observed.push(receiver.blocking_recv().unwrap());
        receiver.finish_command(/*successful_reply_lost*/ false);
    }
    assert_eq!(receiver.blocking_recv(), Some(99));
    accepted.sort_unstable();
    observed.sort_unstable();
    assert_eq!(accepted, observed);
}

#[test]
#[ignore = "pilot scheduling measurement, not filesystem or target-host qualification"]
fn mixed_fifo_contention_curve() {
    for ordinary in [8, 64, 256] {
        let (sender, mut receiver) = channel_with_terminal_capacity(ordinary, 8).unwrap();
        for id in 0..ordinary {
            sender.send(id).unwrap();
        }
        for id in ordinary..ordinary + 8 {
            sender.send_terminal(id).unwrap();
        }
        sender.seal_and_send(usize::MAX).unwrap();
        let started = Instant::now();
        while let Some(value) = receiver.blocking_recv() {
            if value == usize::MAX {
                break;
            }
            // A named synthetic service delay on the real FIFO. Not a disk-fault test.
            std::thread::sleep(std::time::Duration::from_micros(100));
            receiver.finish_command(/*successful_reply_lost*/ false);
        }
        let metrics = sender.metrics().unwrap();
        assert_eq!(metrics.terminal_apply.observed, 8);
        assert_eq!(metrics.ordinary_apply.observed, ordinary as u64);
        println!(
            "{{\"scope\":\"pilot_fifo_synthetic_service_delay\",\"drain_micros\":{},\"metrics\":{}}}",
            started.elapsed().as_micros(),
            serde_json::to_string(&metrics).unwrap()
        );
    }
}
