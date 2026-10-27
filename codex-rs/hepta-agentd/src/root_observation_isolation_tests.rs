//! Real held observation channel while both application runtime workers stop.
use super::*;
use std::sync::mpsc;
use std::time::Instant;

struct ApplicationWorkers {
    releases: Vec<mpsc::Sender<()>>,
    tasks: Vec<tokio::task::JoinHandle<()>>,
}

impl ApplicationWorkers {
    fn block_both() -> Self {
        let (entered, arrivals) = mpsc::channel();
        let mut workers = Self {
            releases: Vec::new(),
            tasks: Vec::new(),
        };
        for _ in 0..2 {
            let (release, wait) = mpsc::channel();
            workers.releases.push(release);
            let entered = entered.clone();
            workers.tasks.push(tokio::spawn(async move {
                entered.send(()).unwrap();
                // A finite escape keeps a failed test from stranding a worker.
                let _ = wait.recv_timeout(Duration::from_secs(3));
            }));
        }
        drop(entered);
        for _ in 0..2 {
            arrivals.recv_timeout(Duration::from_secs(2)).unwrap();
        }
        workers
    }

    async fn release(&mut self) {
        self.releases.clear();
        for task in self.tasks.drain(..) {
            task.await.unwrap();
        }
    }
}

impl Drop for ApplicationWorkers {
    fn drop(&mut self) {
        self.releases.clear();
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn feed_is_independent_of_blocked_application_runtime_workers() {
    let (session, _, peer, _) = connected().await;
    let mut blocked = ApplicationWorkers::block_both();
    // The original 500ms freshness limit stays fixed. The original Root peer
    // continues serving on its independent thread through the held channel.
    std::thread::sleep(Duration::from_millis(700));
    let current = session.clock().now_unix_ms();
    let diagnostic = session.live.cache.diagnostics.first();
    blocked.release().await;
    drop(session);
    peer.join().unwrap();
    assert!(
        current.is_ok(),
        "application workers starved the Root feed: {diagnostic:?}"
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn session_drop_closes_held_channel_without_application_worker_progress() {
    let (session, _, peer, _) = connected().await;
    let clock = session.clock();
    let mut blocked = ApplicationWorkers::block_both();
    drop(session);
    let fenced_immediately = clock.now_unix_ms().is_err();
    let until = Instant::now() + Duration::from_millis(400);
    while !peer.is_finished() && Instant::now() < until {
        std::thread::sleep(Duration::from_millis(1));
    }
    let channel_closed = peer.is_finished();
    blocked.release().await;
    peer.join().unwrap();
    assert!(
        fenced_immediately,
        "dropping the original owner kept authority live"
    );
    assert!(
        channel_closed,
        "held observation channel waited for application workers"
    );
}
