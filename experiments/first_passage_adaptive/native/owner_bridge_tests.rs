use super::*;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

static IDS: AtomicU64 = AtomicU64::new(0);

struct Fixture(PathBuf);
impl Fixture {
    fn new() -> Self {
        let value = std::env::temp_dir().join(format!(
            "hepta-fpt-native-{}-{}",
            std::process::id(),
            IDS.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir_all(value.join("data")).expect("fixture directory");
        std::fs::write(value.join("data/one.txt"), "needle=verified answer\n")
            .expect("fixture data");
        Self(value)
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn request() -> Request {
    let checkpoint=json!({"profile":"hepta-first-passage-cell-v1","parameters":{"drift":-0.4,"weights":[0.0,0.0],"sigma":0.3,"barrier":0.0,"reset_gap":1.0,"refractory":0.00002,"interaction":0.0},
        "model_digest":marker("physical.model").to_string(),"time":0.0,"refractory_remaining":0.0,"event_count":0,"level":1.0,"seed":1,"random_counter":0}).to_string();
    Request {
        schema: PROFILE.to_owned(),
        subject: "research.cell.1".into(),
        sequence: 1,
        owner_monotonic_us: 100,
        checkpoint_digest: Digest32::ZERO.to_string(),
        objective_digest: marker("objective").to_string(),
        ndu_receipt_digest: marker("ndu.receipt").to_string(),
        features_q24: [Q / 2, Q / 8, Q / 4, Q, Q],
        fpt_checkpoint_digest: marker(&checkpoint).to_string(),
        fpt_predecessor_digest: Digest32::ZERO.to_string(),
        fpt_checkpoint_json: checkpoint,
        state: ExecutionState {
            clock_us: 0,
            refractory_until_us: 0,
            refractory_period_us: 20,
            events: 0,
            read_units_spent: 0,
            read_units_budget: 2,
            terminal: None,
        },
        window: EventWindow {
            end_us: 0,
            hit_times_us: vec![],
        },
        deadline_us: 1000,
        command: Command::Read {
            relative_path: "one.txt".into(),
            query: "needle".into(),
        },
    }
}

#[test]
fn original_owner_commits_then_reopens_and_stop_performs_no_source_read() {
    let f = Fixture::new();
    let input = request();
    let first = execute(&f.0.join("owner"), &f.0.join("data"), input.clone()).expect("read");
    assert_eq!(first["read"]["answer"], json!("verified answer"));
    assert_eq!(first["owner"]["recovered"], json!(false));
    let mut stop = input;
    stop.sequence = 2;
    stop.owner_monotonic_us = 200;
    stop.checkpoint_digest = first["owner"]["checkpoint_after"].as_str().unwrap().into();
    stop.state = serde_json::from_value(first["state"].clone()).unwrap();
    stop.command = Command::Stop;
    stop.fpt_predecessor_digest = first["fpt_checkpoint_digest"].as_str().unwrap().into();
    std::fs::remove_dir_all(f.0.join("data")).expect("remove all task sources");
    let second =
        execute(&f.0.join("owner"), &f.0.join("data"), stop).expect("stop without touching data");
    assert_eq!(second["owner"]["recovered"], json!(true));
    assert_eq!(second["read"], Value::Null);
    assert_eq!(second["state"]["terminal"], json!("Stopped"));
    assert_eq!(second["state"]["read_units_spent"], json!(1));
}

#[test]
fn cancellation_and_exhausted_budget_never_open_nonexistent_sources() {
    for command in [
        Command::Cancel,
        Command::Read {
            relative_path: "absent.txt".into(),
            query: "needle".into(),
        },
    ] {
        let f = Fixture::new();
        let mut input = request();
        input.command = command.clone();
        input.state.read_units_budget = 0;
        let out =
            execute(&f.0.join("owner"), &f.0.join("absent"), input).expect("guarded operation");
        let terminal = if command == Command::Cancel {
            "Cancelled"
        } else {
            "BudgetExhausted"
        };
        assert_eq!(out["state"]["terminal"], json!(terminal));
        assert_eq!(out["state"]["read_units_spent"], json!(0));
        assert_eq!(out["read"], Value::Null);
    }
}

#[test]
fn refractory_events_and_clock_are_checked_before_owner_or_io() {
    let f = Fixture::new();
    let mut input = request();
    input.window = EventWindow {
        end_us: 10,
        hit_times_us: vec![5],
    };
    assert!(execute(&f.0.join("owner"), &f.0.join("data"), input.clone()).is_err());
    assert!(!f.0.join("owner").exists());
    input.command = Command::Wait;
    let mut checkpoint: Value = serde_json::from_str(&input.fpt_checkpoint_json).unwrap();
    checkpoint["time"] = json!(0.00001);
    checkpoint["refractory_remaining"] = json!(0.000015);
    checkpoint["event_count"] = json!(1);
    input.fpt_checkpoint_json = checkpoint.to_string();
    input.fpt_checkpoint_digest = marker(&input.fpt_checkpoint_json).to_string();
    let waited =
        execute(&f.0.join("owner"), &f.0.join("data"), input.clone()).expect("refractory wait");
    assert_eq!(waited["state"]["refractory_until_us"], json!(25));
    assert_eq!(waited["state"]["events"], json!(1));
    let state: ExecutionState = serde_json::from_value(waited["state"].clone()).unwrap();
    assert!(
        state
            .advance(
                &EventWindow {
                    end_us: 30,
                    hit_times_us: vec![20]
                },
                1000
            )
            .is_err()
    );
    assert!(
        state
            .advance(
                &EventWindow {
                    end_us: 9,
                    hit_times_us: vec![]
                },
                1000
            )
            .is_err()
    );
    assert_eq!(
        state
            .advance(
                &EventWindow {
                    end_us: 30,
                    hit_times_us: vec![25]
                },
                1000
            )
            .unwrap()
            .events,
        2
    );
}

#[test]
fn stale_owner_predecessor_rejects_without_second_read() {
    let f = Fixture::new();
    let input = request();
    execute(&f.0.join("owner"), &f.0.join("data"), input.clone()).expect("first commit");
    let before = std::fs::read(f.0.join("owner/journal.bin")).unwrap();
    let mut stale = input;
    stale.command = Command::Stop;
    assert!(execute(&f.0.join("owner"), &f.0.join("data"), stale).is_err());
    assert_eq!(
        std::fs::read(f.0.join("owner/journal.bin")).unwrap(),
        before
    );
}

#[test]
fn repeated_request_returns_recorded_result_and_forged_budget_state_rejects() {
    let f = Fixture::new();
    let input = request();
    let out = execute(&f.0.join("owner"), &f.0.join("data"), input.clone()).unwrap();
    std::fs::remove_dir_all(f.0.join("data")).unwrap();
    let replay = execute(&f.0.join("owner"), &f.0.join("data"), input.clone()).unwrap();
    assert_eq!(replay["replayed"], json!(true));
    assert_eq!(replay["source_reads_this_call"], json!(0));
    let mut forged = input;
    forged.sequence = 2;
    forged.owner_monotonic_us = 200;
    forged.checkpoint_digest = out["owner"]["checkpoint_after"].as_str().unwrap().into();
    forged.fpt_predecessor_digest = out["fpt_checkpoint_digest"].as_str().unwrap().into();
    assert!(execute(&f.0.join("owner"), &f.0.join("data"), forged).is_err());
}

#[test]
fn changing_physical_parameters_with_an_old_model_digest_is_rejected() {
    let f = Fixture::new();
    let input = request();
    let first = execute(&f.0.join("owner"), &f.0.join("data"), input.clone()).unwrap();
    let mut forged = input;
    forged.sequence = 2;
    forged.owner_monotonic_us = 200;
    forged.checkpoint_digest = first["owner"]["checkpoint_after"].as_str().unwrap().into();
    forged.fpt_predecessor_digest = first["fpt_checkpoint_digest"].as_str().unwrap().into();
    forged.state = serde_json::from_value(first["state"].clone()).unwrap();
    let mut checkpoint: Value = serde_json::from_str(&forged.fpt_checkpoint_json).unwrap();
    checkpoint["parameters"]["sigma"] = json!(0.31);
    // Deliberately retain model_digest and provide a correct hash for the new
    // full payload, so only the physical-parameter continuity guard catches it.
    forged.fpt_checkpoint_json = checkpoint.to_string();
    forged.fpt_checkpoint_digest = marker(&forged.fpt_checkpoint_json).to_string();
    let before = std::fs::read(f.0.join("owner/journal.bin")).unwrap();
    let error = execute(&f.0.join("owner"), &f.0.join("data"), forged).unwrap_err();
    assert_eq!(error, "selected FPT model changed within a run");
    assert_eq!(
        std::fs::read(f.0.join("owner/journal.bin")).unwrap(),
        before
    );
    assert!(!f.0.join("owner/task-sidecars/request-0002.json").exists());
}

#[test]
fn lost_reply_inspection_returns_committed_anchor_without_repeating_read() {
    let f = Fixture::new();
    let input = request();
    let out = execute(&f.0.join("owner"), &f.0.join("data"), input.clone()).unwrap();
    std::fs::remove_dir_all(f.0.join("data")).unwrap();
    let observed = inspect(&f.0.join("owner"), &input).expect("inspect without source access");
    assert_eq!(observed["sequence"], json!(1));
    assert_eq!(
        observed["checkpoint_digest"],
        out["owner"]["checkpoint_after"]
    );
    assert_eq!(observed["source_reads"], json!(0));
}

#[test]
fn missing_outcome_after_owner_commit_is_indeterminate_and_not_reexecuted() {
    let f = Fixture::new();
    let input = request();
    execute(&f.0.join("owner"), &f.0.join("data"), input.clone()).unwrap();
    std::fs::remove_file(f.0.join("owner/task-sidecars/response-0001.json")).unwrap();
    std::fs::remove_dir_all(f.0.join("data")).unwrap();
    let before = std::fs::read(f.0.join("owner/journal.bin")).unwrap();
    assert!(execute(&f.0.join("owner"), &f.0.join("data"), input.clone()).is_err());
    assert_eq!(
        std::fs::read(f.0.join("owner/journal.bin")).unwrap(),
        before
    );
    assert_eq!(
        inspect(&f.0.join("owner"), &input).unwrap()["sequence"],
        json!(1)
    );
}

#[test]
fn actual_read_attempts_are_charged_once_but_path_guard_rejections_are_not() {
    for (name, bytes, expected) in [
        ("../escape", vec![], 0_u64),
        ("one.txt", vec![0xff], 1),
        ("one.txt", vec![b'x'; 65_537], 1),
    ] {
        let f = Fixture::new();
        std::fs::write(f.0.join("data/one.txt"), bytes).unwrap();
        let mut input = request();
        input.command = Command::Read {
            relative_path: name.into(),
            query: "needle".into(),
        };
        let response = execute(&f.0.join("owner"), &f.0.join("data"), input.clone()).unwrap();
        assert_eq!(response["source_read_attempts_this_call"], json!(expected));
        assert_eq!(response["state"]["read_units_spent"], json!(expected));
        let replay = execute(&f.0.join("owner"), &f.0.join("data"), input).unwrap();
        assert_eq!(replay["source_read_attempts_this_call"], json!(0));
    }
}
