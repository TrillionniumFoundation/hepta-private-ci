//! Real concurrent admission and socket side effects. These component tests
//! do not construct a Root client, session, publication or authority receipt.

use super::InitialLaneAdmission;
use pretty_assertions::assert_eq;
use std::io::Read;
use std::io::Write;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::Barrier;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::time::Duration;
use std::time::Instant;

const WATCHDOG: Duration = Duration::from_secs(2);
fn end() -> Instant {
    Instant::now() + Duration::from_millis(500)
}

struct Data {
    sequence: u64,
    stream: UnixStream,
}
struct Fixture {
    gate: InitialLaneAdmission,
    data: Mutex<Option<Data>>,
    fenced: AtomicBool,
}
fn fixture() -> anyhow::Result<(Arc<Fixture>, UnixStream)> {
    let (stream, peer) = UnixStream::pair()?;
    Ok((
        Arc::new(Fixture {
            gate: InitialLaneAdmission::new()?,
            data: Mutex::new(Some(Data {
                sequence: 0,
                stream,
            })),
            fenced: AtomicBool::new(false),
        }),
        peer,
    ))
}

#[test]
fn initial_lane_serializes_concurrent_original_access_without_fencing() -> anyhow::Result<()> {
    let (fixture, mut peer) = fixture()?;
    let barrier = Arc::new(Barrier::new(/*n*/ 5));
    let (entered, observations) = mpsc::channel();
    let mut workers = Vec::new();
    let mut releases = Vec::new();
    for id in 0..4 {
        let fixture = fixture.clone();
        let barrier = barrier.clone();
        let entered = entered.clone();
        let (release, proceed) = mpsc::channel();
        releases.push(release);
        workers.push(std::thread::spawn(move || -> anyhow::Result<()> {
            let deadline = end();
            barrier.wait();
            let mut held = fixture
                .gate
                .acquire(&fixture.data, &fixture.fenced, deadline)?;
            let mut original = held
                .data
                .take()
                .ok_or_else(|| anyhow::anyhow!("missing original"))?;
            original.stream.write_all(&[original.sequence as u8])?;
            original.sequence += 1;
            entered.send(id)?;
            proceed.recv_timeout(WATCHDOG)?;
            held.require_open()?;
            *held.data = Some(original);
            held.release()?;
            Ok(())
        }));
    }
    barrier.wait();
    for _ in 0..4 {
        let id = observations.recv_timeout(WATCHDOG)?;
        assert!(matches!(
            observations.try_recv(),
            Err(mpsc::TryRecvError::Empty)
        ));
        releases[id].send(())?;
    }
    for worker in workers {
        worker.join().expect("admission worker")?;
    }
    peer.set_read_timeout(Some(WATCHDOG))?;
    let mut bytes = [0; 4];
    peer.read_exact(&mut bytes)?;
    assert_eq!(bytes, [0, 1, 2, 3]);
    assert!(!fixture.fenced.load(Ordering::Acquire));
    assert_eq!(
        fixture
            .data
            .lock()
            .expect("original data")
            .as_ref()
            .expect("restored data")
            .sequence,
        4
    );
    Ok(())
}

#[test]
fn initial_lane_queue_expiry_sends_nothing_and_consumes_no_sequence() -> anyhow::Result<()> {
    let (fixture, mut peer) = fixture()?;
    let held = fixture
        .gate
        .acquire(&fixture.data, &fixture.fenced, end())?;
    let deadline = Instant::now() + Duration::from_millis(30);
    let worker_fixture = fixture.clone();
    let (done, result) = mpsc::channel();
    let worker = std::thread::spawn(move || {
        let rejected = worker_fixture
            .gate
            .acquire(&worker_fixture.data, &worker_fixture.fenced, deadline)
            .is_err();
        done.send(rejected).expect("queue result");
    });
    assert!(result.recv_timeout(WATCHDOG)?);
    assert!(
        Instant::now() >= deadline,
        "contention must wait for the original queue end"
    );
    worker.join().expect("queue worker");
    assert_eq!(held.data.as_ref().expect("original data").sequence, 0);
    peer.set_nonblocking(true)?;
    assert_eq!(
        peer.read(&mut [0; 1]).expect_err("no request bytes").kind(),
        std::io::ErrorKind::WouldBlock
    );
    assert!(held.require_open().is_err());
    held.release()?;
    assert!(
        fixture
            .gate
            .acquire(&fixture.data, &fixture.fenced, end())
            .is_err()
    );
    Ok(())
}

#[test]
fn initial_lane_original_mutex_poison_cannot_be_healed_by_returned_token() -> anyhow::Result<()> {
    let (fixture, _) = fixture()?;
    let worker_fixture = fixture.clone();
    assert!(
        std::thread::spawn(move || {
            let _held = worker_fixture
                .gate
                .acquire(&worker_fixture.data, &worker_fixture.fenced, end())
                .expect("original guard");
            panic!("actual unwind while holding original data mutex");
        })
        .join()
        .is_err()
    );
    assert!(fixture.data.is_poisoned());
    assert_eq!(fixture.gate.available.len(), 1);
    assert!(
        fixture
            .gate
            .acquire(&fixture.data, &fixture.fenced, end())
            .is_err()
    );
    assert!(fixture.fenced.load(Ordering::Acquire));
    assert!(
        fixture
            .gate
            .acquire(&fixture.data, &fixture.fenced, end())
            .is_err()
    );
    Ok(())
}

#[test]
fn initial_lane_fence_during_pending_admission_refuses_the_waiter() -> anyhow::Result<()> {
    let (fixture, _) = fixture()?;
    let held = fixture
        .gate
        .acquire(&fixture.data, &fixture.fenced, end())?;
    let waiter = fixture.clone();
    let (started, ready) = mpsc::channel();
    let worker = std::thread::spawn(move || {
        let deadline = end();
        started.send(()).expect("waiter entered");
        waiter
            .gate
            .acquire(&waiter.data, &waiter.fenced, deadline)
            .is_err()
    });
    ready.recv_timeout(WATCHDOG)?;
    fixture.fenced.store(true, Ordering::Release);
    assert!(held.require_open().is_err());
    held.release()?;
    assert!(worker.join().expect("fenced waiter"));
    assert_eq!(
        fixture
            .data
            .lock()
            .expect("original data")
            .as_ref()
            .expect("original data")
            .sequence,
        0
    );
    Ok(())
}

#[test]
fn initial_lane_terminal_consumption_never_restores_original_data() -> anyhow::Result<()> {
    let (fixture, _) = fixture()?;
    let mut held = fixture
        .gate
        .acquire(&fixture.data, &fixture.fenced, end())?;
    let original = held.data.take().expect("original data");
    fixture.fenced.store(true, Ordering::Release);
    held.require_deadline()?;
    drop(original);
    held.release()?;
    assert!(fixture.data.lock().expect("original data").is_none());
    assert!(
        fixture
            .gate
            .acquire(&fixture.data, &fixture.fenced, end())
            .is_err()
    );
    assert!(fixture.data.lock().expect("original data").is_none());
    Ok(())
}

#[test]
fn initial_lane_token_return_failure_cannot_report_success() -> anyhow::Result<()> {
    let (fixture, _) = fixture()?;
    let held = fixture
        .gate
        .acquire(&fixture.data, &fixture.fenced, end())?;
    fixture.gate.returned.try_send(())?;
    assert!(held.release().is_err());
    assert!(fixture.fenced.load(Ordering::Acquire));
    assert!(
        fixture.data.try_lock().is_ok(),
        "data must release before permit return"
    );
    assert!(
        fixture
            .gate
            .acquire(&fixture.data, &fixture.fenced, end())
            .is_err()
    );
    Ok(())
}
