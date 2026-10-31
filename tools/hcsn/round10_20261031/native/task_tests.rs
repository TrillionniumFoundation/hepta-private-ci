use crate::cell::Cell;
use crate::cell::Family;
use crate::content;
use crate::contract::Action;
use crate::contract::Config;
use crate::contract::Packet;
use crate::policy::Policy;
use crate::task_owner::Setup;
use crate::task_owner::TaskOwner;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use std::collections::BTreeMap;
use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

static NEXT: AtomicU64 = AtomicU64::new(0);

struct Directory(PathBuf);
impl Directory {
    fn new() -> Self {
        let ordinal = NEXT.fetch_add(/*val*/ 1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!("hcsn-r10-{}-{ordinal}", std::process::id()));
        std::fs::create_dir(&path).unwrap();
        Self(path)
    }
}
impl Drop for Directory {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn task() -> Config {
    Config {
        deadline: 5,
        budget: 2,
        prior: 0.5,
        read_cost: 0.03,
        latency_cost: 0.01,
        stop_cost: 0.002,
        failure_cost: 0.02,
        invalid_cost: 0.07,
        refractory_ticks: 1,
        packets: vec![
            Packet { arrival: 0, reliability: 0.8, failure_probability: 0.1 },
            Packet { arrival: 0, reliability: 0.7, failure_probability: 0.1 },
        ],
    }
}

fn packet(root: &Path) -> content::Request {
    let bytes = br#"{"schema":"hcsn.memory.packet.v1","symbols":[0,1,2,3,-1],"dt":[1,1,1,1,1]}"#;
    let path = root.join("payload.json");
    std::fs::write(&path, bytes).unwrap();
    content::Request { path: path.to_string_lossy().into_owned(), sha256: Digest32::of_bytes(bytes).to_string() }
}

fn setup(task: Config, payload: content::Request, policy: Policy) -> Setup {
    let fixture = Path::new(file!()).parent().unwrap().join("../../round9_20261031/native/fixtures/fullhx.json");
    let digest = Digest32::of_bytes(&std::fs::read(&fixture).expect("real frozen FullHX fixture is required")).to_string();
    Setup {
        cell: Cell::new([0.2, -0.3, 0.4, -0.1, 0.5, 0.2, 0.4, -0.2, 0.3, 0.5, -0.1], Family::Distribution, /*seed*/ 173).unwrap(),
        content_model: content::Model::load(&fixture, &digest).unwrap(),
        payloads: vec![payload; task.packets.len()],
        task,
        policy,
        tick_micros: 50_000,
    }
}

#[test]
fn policy_wait_and_stop_do_not_read_missing_payloads() {
    let root = Directory::new();
    let payload = content::Request { path: root.0.join("never-created").to_string_lossy().into_owned(), sha256: Digest32::ZERO.to_string() };
    let task = task();
    let mut entries = BTreeMap::new();
    entries.insert(task.initial().key(), [0.0, 1.0, 0.0]);
    let (after_wait, _, _) = task.successor(&task.initial(), Action::Wait, /*observation*/ None).unwrap();
    entries.insert(after_wait.key(), [0.0, 0.0, 1.0]);
    let mut owner = TaskOwner::open(&root.0, &Digest32::ZERO.to_string(), setup(task, payload, Policy::QTable { entries })).unwrap();
    let first = owner.step(&owner.acknowledged.clone(), /*forced*/ None).unwrap();
    assert_eq!((first.actual, first.read_attempted, first.observation, first.read_error), (Action::Wait, false, None, None));
    assert_eq!(first.inner.as_ref().unwrap().content.as_ref().unwrap().completed_reads, 0);
    let second = owner.step(&owner.acknowledged.clone(), /*forced*/ None).unwrap();
    assert_eq!((second.actual, second.state.clock, second.state.answer, second.inner.is_none()), (Action::Stop, 1, Some(1), true));
}

#[test]
fn real_decode_and_native_checkpoint_survive_task_restart() {
    let root = Directory::new();
    let payload = packet(&root.0);
    let mut owner = TaskOwner::open(&root.0, &Digest32::ZERO.to_string(), setup(task(), payload.clone(), Policy::OneRead)).unwrap();
    let first = owner.step(&owner.acknowledged.clone(), Some(Action::Read)).unwrap();
    let inner = first.inner.as_ref().unwrap();
    let output = inner.content.as_ref().unwrap().last.as_ref().unwrap();
    assert_eq!((first.read_attempted, first.ledger.read_failed, inner.native_physics_executed), (true, false, true));
    assert_eq!(first.state.history, output.observation.to_string());
    assert_eq!(first.state.clock, inner.cell.sequence);
    let state = first.state.clone();
    let ack = first.task_after;
    drop(owner);
    let mut resumed = TaskOwner::open(&root.0, &ack, setup(task(), payload, Policy::OneRead)).unwrap();
    assert_eq!(resumed.state, state);
    let wait = resumed.step(&ack, Some(Action::Wait)).unwrap();
    assert_eq!((wait.actual, wait.state.clock, wait.state.recovery_until), (Action::Wait, 2, 2));
    let second = resumed.step(&wait.task_after, Some(Action::Read)).unwrap();
    assert_eq!((second.state.next_packet, second.state.budget_left, second.inner.unwrap().content.unwrap().completed_reads), (2, 0, 2));
}

#[test]
fn failed_read_consumes_real_attempt_budget_time_and_failure_cost() {
    let root = Directory::new();
    let missing = content::Request { path: root.0.join("missing").to_string_lossy().into_owned(), sha256: Digest32::ZERO.to_string() };
    let mut owner = TaskOwner::open(&root.0, &Digest32::ZERO.to_string(), setup(task(), missing, Policy::OneRead)).unwrap();
    let first = owner.step(&owner.acknowledged.clone(), Some(Action::Read)).unwrap();
    assert_eq!((first.actual, first.observation, first.read_attempted, first.ledger.read_failed), (Action::Read, Some('x'), true, true));
    assert!(first.read_error.is_some());
    assert_eq!((first.state.clock, first.state.budget_left, first.state.recovery_until, first.state.history.as_str()), (1, 1, 2, "x"));
    assert_eq!(first.cost, 0.05);
    assert_eq!(first.inner.unwrap().content.unwrap().completed_reads, 0);
    let stop = owner.step(&first.task_after, Some(Action::Read)).unwrap();
    assert_eq!((stop.actual, stop.read_attempted, stop.state.clock, stop.state.answer), (Action::Stop, false, 1, Some(1)));
    assert_eq!(stop.cost, task().invalid_cost + task().stop_cost);
}

#[test]
fn stale_ack_changed_binding_and_interrupted_intent_fail_closed() {
    let root = Directory::new();
    let payload = packet(&root.0);
    let zero = Digest32::ZERO.to_string();
    let mut owner = TaskOwner::open(&root.0, &zero, setup(task(), payload.clone(), Policy::OneRead)).unwrap();
    let first = owner.step(&zero, Some(Action::Wait)).unwrap();
    let saved = owner.state.clone();
    assert!(owner.step(&zero, Some(Action::Read)).is_err());
    assert_eq!(owner.state, saved);
    drop(owner);
    let mut altered = task();
    altered.read_cost = 0.04;
    assert!(TaskOwner::open(&root.0, &first.task_after, setup(altered, payload.clone(), Policy::OneRead)).is_err());
    std::fs::write(root.0.join("task-intent.json"), b"interrupted read intent").unwrap();
    let error = TaskOwner::open(&root.0, &first.task_after, setup(task(), payload, Policy::OneRead)).err().unwrap();
    assert!(error.contains("reconciliation required"));
}

#[test]
fn deadline_mask_is_applied_before_q_table_selection() {
    let mut task = task();
    task.deadline = 1;
    let initial = task.initial();
    let (state, _, _) = task.successor(&initial, Action::Wait, /*observation*/ None).unwrap();
    let mut entries = BTreeMap::new();
    entries.insert(state.key(), [100.0, 50.0, -1.0]);
    let policy = Policy::QTable { entries };
    assert_eq!(policy.decision(&task, &state).unwrap(), Action::Stop);
    let (terminated, cost, actual) = task.successor(&state, Action::Read, /*observation*/ None).unwrap();
    assert_eq!((terminated.clock, terminated.answer, actual, cost), (1, Some(1), Action::Stop, task.invalid_cost + task.stop_cost));
}
