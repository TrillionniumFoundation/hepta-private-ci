use crate::cell::Family;
use crate::owner::Open;
use crate::owner::Owner;
use crate::policy;
use crate::policy::Controller;
use crate::store;
use crate::task::Action;
use crate::task::Public;
use crate::task::State;
use std::path::Path;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

fn public() -> Public {
    Public {
        id: "native-task-test".into(),
        deadline: 6,
        budget: 3,
        reliability: vec![vec![0.8; 6]; 2],
        price: vec![vec![0.02; 6]; 2],
        duration: vec![0.5, 1.0, 0.5, 1.0, 0.5, 1.0],
        packets: (0..2)
            .map(|j| (0..6).map(|t| format!("job{j}_tick{t}.json")).collect())
            .collect(),
        packet_sha256: vec![vec!["a".repeat(64); 6]; 2],
        multiplier: 1.5,
        latency_price: 0.01,
    }
}

#[test]
fn read_then_fire_uses_observed_posterior_and_regenerates_next_job() {
    let public = public();
    public.validate().unwrap();
    let confusion = [[0.9, 0.1], [0.1, 0.9]];
    let mut state = State::initial(&public);
    let mut event = state.event(&public, Action::Read).unwrap();
    event.observation = Some(1);
    event.payload_sha256 = Some("a".repeat(64));
    event.payload_bytes = 321;
    state.apply(&public, confusion, event).unwrap();
    assert!((state.posterior - 0.74).abs() < 1e-14);
    let event = state.event(&public, Action::Fire).unwrap();
    state.apply(&public, confusion, event).unwrap();
    assert_eq!(
        (
            state.job,
            state.tick,
            state.budget,
            state.posterior,
            state.reads_in_job
        ),
        (1, 3, 2, 0.5, 0)
    );
    assert_eq!(state.answers[0].prediction, 1);
    assert_eq!(state.elapsed_micros, 2_000_000);
    assert_eq!(state.counts.content_invocations, 1);
    state.validate(&public, confusion).unwrap();
}

#[test]
fn failed_read_keeps_paid_attempt_and_never_invents_content_completion() {
    let public = public();
    let confusion = [[0.9, 0.1], [0.1, 0.9]];
    let mut state = State::initial(&public);
    let mut event = state.event(&public, Action::Read).unwrap();
    event.error = Some("missing packet".into());
    state.apply(&public, confusion, event).unwrap();
    assert_eq!(
        (
            state.terminal,
            state.tick,
            state.budget,
            state.counts.content_invocations,
            state.counts.failed_read_attempts
        ),
        (true, 0, 3, 0, 1)
    );
    assert!((state.charged_cost - 0.035).abs() < 1e-15);
    assert_eq!(state.elapsed_micros, 500_000);
    state.validate(&public, confusion).unwrap();
}

#[test]
fn corrupted_checkpoint_cannot_supply_a_new_posterior_or_inflight_action() {
    let public = public();
    let confusion = [[0.9, 0.1], [0.1, 0.9]];
    let mut state = State::initial(&public);
    state.posterior = 0.9;
    assert!(state.validate(&public, confusion).is_err());
    state = State::initial(&public);
    state.in_flight = Some(Action::Read);
    assert!(state.validate(&public, confusion).is_err());
}

#[test]
fn fixed_boundary_and_value_controller_have_distinct_real_actions() {
    let public = public();
    let mut state = State::initial(&public);
    assert_eq!(policy::fixed(&state, state.legal(&public)), Action::Read);
    assert_eq!(
        policy::select([0.0, 0.7, 0.3, 0.2], state.legal(&public)),
        Action::Skip
    );
    state.posterior = 0.8;
    assert_eq!(policy::fixed(&state, state.legal(&public)), Action::Fire);
    state.posterior = 0.5;
    state.budget = 0;
    assert_eq!(policy::fixed(&state, state.legal(&public)), Action::Fire);
    assert_eq!(
        policy::select([0.0, 0.0, 0.0, 0.0], state.legal(&public)),
        Action::Stop
    );
}

#[test]
fn public_contract_rejects_label_paths_and_unrepresentable_microsecond_clocks() {
    let mut public = public();
    public.packets[0][0] = "evaluator_labels.json".into();
    assert!(public.validate().is_err());
    public.packets[0][0] = "job0_tick0.json".into();
    public.duration[0] = 0.0000001;
    assert!(public.validate().is_err());
}

struct OwnerFixture {
    folder: PathBuf,
    public: PathBuf,
    policy: PathBuf,
    content: PathBuf,
    snapshot: PathBuf,
}

impl OwnerFixture {
    fn new() -> Self {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let pid = std::process::id();
        let folder = std::env::temp_dir().join(format!("hepta-task-owner-test-{pid}-{nonce}"));
        std::fs::create_dir(&folder).unwrap();
        let public = public();
        let mut feature_names = [
            "job",
            "tick",
            "budget",
            "posterior",
            "deadline",
            "initial_budget",
            "multiplier",
            "latency_price",
        ]
        .into_iter()
        .map(str::to_owned)
        .collect::<Vec<_>>();
        for schedule in ["reliability", "price"] {
            for job in 0..2 {
                for tick in 0..10 {
                    feature_names.push(format!("{schedule}_{job}_{tick}"));
                }
            }
        }
        for tick in 0..10 {
            feature_names.push(format!("duration_{tick}"));
        }
        for row in 0..2 {
            for column in 0..2 {
                feature_names.push(format!("confusion_{row}_{column}"));
            }
        }
        for i in 0..4 {
            feature_names.push(format!("cell_{i}"));
        }
        feature_names.push("next_observation_probability".into());
        let policy = policy::Policy {
            schema: "hcsn.task.native.policy.v1".into(),
            family: Family::Ordinary,
            controller: Controller::Value,
            input_width: 67,
            hidden_width: 24,
            norm: policy::Norm {
                mean: vec![0.0; 67],
                scale: vec![1.0; 67],
            },
            parameters: [0.0; 11],
            weights: policy::Weights {
                w: vec![vec![0.0; 24]; 67],
                b: vec![0.0; 24],
                v: vec![vec![0.0; 4]; 24],
                c: vec![0.0; 4],
            },
            confusion: [[0.9, 0.1], [0.1, 0.9]],
            fixed_boundary: 0.8,
            multiplier: public.multiplier,
            latency_price: public.latency_price,
            seed: 1,
            feature_names,
        };
        let fixture = Self {
            public: folder.join("public.json"),
            policy: folder.join("policy.json"),
            content: Path::new(file!())
                .parent()
                .unwrap()
                .join("../../round9_20261031/native/fixtures/fullhx.json"),
            snapshot: folder.join("checkpoint.json"),
            folder,
        };
        std::fs::write(&fixture.public, serde_json::to_vec(&public).unwrap()).unwrap();
        std::fs::write(&fixture.policy, serde_json::to_vec(&policy).unwrap()).unwrap();
        fixture
    }

    fn open(&self, ack: Option<&str>) -> Result<Owner, String> {
        Owner::open(Open {
            public: &self.public,
            content: &self.content,
            policy: &self.policy,
            family: Family::Ordinary,
            controller: Controller::Value,
            snapshot: &self.snapshot,
            ack,
        })
    }
}

impl Drop for OwnerFixture {
    fn drop(&mut self) {
        std::fs::remove_dir_all(&self.folder).unwrap();
    }
}

#[test]
fn inspect_genesis_reopens_and_real_native_tick_remains_recoverable() {
    let fixture = OwnerFixture::new();
    let first = fixture.open(/*ack*/ None).unwrap();
    let genesis = first.pair.clone();
    let initial_ack = first.acknowledged_sha256.clone();
    assert_eq!(
        std::fs::metadata(store::sibling(&fixture.snapshot, ".journal"))
            .unwrap()
            .len(),
        0
    );
    drop(first);
    let mut resumed = fixture.open(Some(&initial_ack)).unwrap();
    assert_eq!(resumed.pair, genesis);
    let receipt = resumed.step().unwrap();
    assert_eq!(receipt.action, Action::Stop);
    assert_eq!(receipt.signals_q24, vec![crate::native::Q, 0, 0, 0, 0]);
    let final_pair = resumed.pair.clone();
    let final_ack = resumed.acknowledged_sha256.clone();
    drop(resumed);
    let restored = fixture.open(Some(&final_ack)).unwrap();
    assert_eq!(restored.pair, final_pair);
    assert_eq!(restored.acknowledged_sha256, final_ack);
}

#[test]
fn unacknowledged_genesis_journal_is_refused_without_erasure() {
    let fixture = OwnerFixture::new();
    let first = fixture.open(/*ack*/ None).unwrap();
    let ack = first.acknowledged_sha256.clone();
    drop(first);
    let journal = store::sibling(&fixture.snapshot, ".journal");
    let unknown = b"unknown-unacknowledged-journal";
    std::fs::write(&journal, unknown).unwrap();
    let error = fixture
        .open(Some(&ack))
        .err()
        .expect("must refuse partial journal");
    assert_eq!(error, "unacknowledged genesis journal; refuse bootstrap");
    assert_eq!(std::fs::read(journal).unwrap(), unknown);
}
