use super::*;

#[test]
fn runtime_codex_fence_and_abort_overflow_are_mutation_atomic() {
    for abort in [false, true] {
        let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).unwrap();
        coordinator.start_run(100, snapshot()).unwrap();
        coordinator.attach_context(200, 1, attachment()).unwrap();
        coordinator.runs.get_mut("run.1").unwrap().revision = u64::MAX;
        let before = coordinator.run("run.1").unwrap();
        let result = if abort {
            coordinator.abort_before_effect("run.1", u64::MAX, &digest('a'), "before send")
        } else {
            coordinator.mark_dispatched_exact(300, "run.1", u64::MAX, &digest('a'))
        };
        assert_eq!(result, Err(AgentRunError::ArithmeticOverflow));
        assert_eq!(coordinator.run("run.1").unwrap(), before);
        assert_eq!(coordinator.runs["run.1"].abort_origin_revision, None);
        assert_eq!(coordinator.runs["run.1"].dispatch_digest, None);
    }
}

#[test]
fn runtime_codex_concurrent_owner_fence_has_one_fresh_winner() {
    use std::sync::Arc;
    use std::sync::Barrier;
    use std::sync::Mutex;

    // The real owner serializes mutations with this mutex. This verifies its
    // CAS policy, not physical provider execution or durable restart.
    for _ in 0..8 {
        let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).unwrap();
        coordinator.start_run(100, snapshot()).unwrap();
        coordinator.attach_context(200, 1, attachment()).unwrap();
        let coordinator = Arc::new(Mutex::new(coordinator));
        let barrier = Arc::new(Barrier::new(16));
        let mut workers = Vec::new();
        for _ in 0..16 {
            let owner = Arc::clone(&coordinator);
            let barrier = Arc::clone(&barrier);
            workers.push(std::thread::spawn(move || {
                barrier.wait();
                owner.lock().unwrap().mark_dispatched_exact(300, "run.1", 2, &digest('a')).unwrap()
            }));
        }
        let receipts: Vec<_> = workers.into_iter().map(|worker| worker.join().unwrap()).collect();
        assert_eq!(receipts.iter().filter(|receipt| !receipt.idempotent).count(), 1);
        let mut owner = coordinator.lock().unwrap();
        assert_eq!(owner.active_run_count(), 1);
        assert_eq!(owner.run("run.1").unwrap().revision, 3);
        assert!(owner.abort_before_effect("run.1", 2, &digest('a'), "late abort").is_err());
        assert!(owner.mark_dispatched_exact(300, "run.1", 2, &digest('b')).is_err());
    }
}
