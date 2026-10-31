use crate::contract::*;
use crate::model::*;
use crate::owner::Owner;
use codex_hepta_types::Digest32;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

static NEXT: AtomicU64 = AtomicU64::new(0);
struct Fixture(PathBuf);
impl Fixture {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "hepta-task-native-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir(&path).unwrap();
        Self(path)
    }
    fn files(&self) -> (Vec<u8>, Vec<u8>) {
        (
            std::fs::read(self.0.join("journal.bin")).unwrap(),
            std::fs::read(self.0.join("witness.bin")).unwrap(),
        )
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}
fn checkpoint() -> Vec<u8> {
    serde_json::to_vec(&Checkpoint {
        norm: Normalization {
            mean: vec![0.2, 0.0],
            scale: vec![0.5, 1.0],
        },
        weights: Weights {
            w: vec![vec![0.3, -0.5], vec![0.1, 0.25]],
            b: vec![0.1, -0.2],
            v: vec![vec![0.0, 0.15, -0.1, 0.2], vec![0.0, -0.1, 0.3, 0.1]],
            c: vec![0.0, -0.2, 0.1, 0.2],
        },
    })
    .unwrap()
}
fn request(bytes: &[u8]) -> Request {
    Request {
        numeric_contract: NUMERIC_CONTRACT.into(),
        sequence: 1,
        monotonic_time_micros: 100,
        checkpoint_before: Digest32::ZERO.to_string(),
        model_sha256: Digest32::of_bytes(bytes).to_string(),
        cell_snapshot_sha256: marker("cell").to_string(),
        public_state_sha256: marker("public").to_string(),
        features: vec![0.5, 0.1],
        prior: [0.0, -0.1, 0.2, 0.4],
        feasible: [true; 4],
    }
}
fn open(root: &Fixture, bytes: &[u8], sequence: u64, anchor: &str) -> Result<Owner, String> {
    Owner::open(
        &root.0,
        bytes,
        "task.case",
        &marker("objective").to_string(),
        sequence,
        anchor,
    )
}

#[test]
fn executed_mlp_matches_independent_formula_and_masked_native_selection() {
    let root = Fixture::new();
    let bytes = checkpoint();
    let mut owner = open(&root, &bytes, 0, &Digest32::ZERO.to_string()).unwrap();
    let mut input = request(&bytes);
    input.feasible[3] = false;
    let packed = input.packed(2).unwrap();
    let (cp, _) = load(&bytes).unwrap();
    let x0 = (packed[0] as f64 / Q as f64 - 0.2) / 0.5;
    let x1 = packed[1] as f64 / Q as f64;
    let h0 = (0.3 * x0 + 0.1 * x1 + 0.1).tanh();
    let h1 = (-0.5 * x0 + 0.25 * x1 - 0.2).tanh();
    let expected = packed[4] as f64 / Q as f64 + (-0.1 * h0 + 0.3 * h1 + 0.1).max(0.0);
    let receipt = owner.tick(input).unwrap();
    assert!((receipt.q_values[2] - expected).abs() < 1e-14);
    assert_eq!(receipt.action, "READ");
    assert!(receipt.journal_bytes_written > 0);
    assert!(!receipt.native_physics_executed);
    assert_eq!(cp.norm.mean.len(), 2);
}

#[test]
fn restart_recovers_native_anchor_and_does_not_reset_sequence() {
    let root = Fixture::new();
    let bytes = checkpoint();
    let first = {
        let mut owner = open(&root, &bytes, 0, &Digest32::ZERO.to_string()).unwrap();
        owner.tick(request(&bytes)).unwrap()
    };
    assert!(open(&root, &bytes, 0, &Digest32::ZERO.to_string()).is_err());
    let mut owner = open(&root, &bytes, 1, &first.checkpoint_after).unwrap();
    let mut next = request(&bytes);
    next.sequence = 2;
    next.monotonic_time_micros = 200;
    next.checkpoint_before = first.checkpoint_after.clone();
    let receipt = owner.tick(next).unwrap();
    assert_eq!(receipt.checkpoint_before, first.checkpoint_after);
    assert_ne!(receipt.checkpoint_after, first.checkpoint_after);
}

#[test]
fn sequence_model_and_invalid_feature_rejections_leave_durable_bytes_unchanged() {
    let root = Fixture::new();
    let bytes = checkpoint();
    let mut owner = open(&root, &bytes, 0, &Digest32::ZERO.to_string()).unwrap();
    let initial = root.files();
    let mut bad = request(&bytes);
    bad.sequence = 2;
    assert!(owner.tick(bad).is_err());
    let mut bad = request(&bytes);
    bad.model_sha256 = marker("another model").to_string();
    assert!(owner.tick(bad).is_err());
    let mut bad = request(&bytes);
    bad.features[0] = f64::NAN;
    assert!(owner.tick(bad).is_err());
    let mut bad = request(&bytes);
    bad.feasible[0] = false;
    assert!(owner.tick(bad).is_err());
    assert_eq!(root.files(), initial);
    assert!(owner.tick(request(&bytes)).is_ok());
}

#[test]
fn stale_predecessor_is_rejected_without_a_second_commit() {
    let root = Fixture::new();
    let bytes = checkpoint();
    let mut owner = open(&root, &bytes, 0, &Digest32::ZERO.to_string()).unwrap();
    let first = owner.tick(request(&bytes)).unwrap();
    let settled = root.files();
    let mut next = request(&bytes);
    next.sequence = 2;
    next.monotonic_time_micros = 200;
    assert!(owner.tick(next.clone()).is_err());
    assert_eq!(root.files(), settled);
    next.checkpoint_before = first.checkpoint_after;
    assert!(owner.tick(next).is_ok());
}

#[test]
fn independent_witness_detects_acknowledged_journal_loss() {
    let root = Fixture::new();
    let bytes = checkpoint();
    let (first, header) = {
        let mut owner = open(&root, &bytes, 0, &Digest32::ZERO.to_string()).unwrap();
        let header = std::fs::metadata(root.0.join("journal.bin")).unwrap().len();
        (owner.tick(request(&bytes)).unwrap(), header)
    };
    std::fs::OpenOptions::new()
        .write(true)
        .open(root.0.join("journal.bin"))
        .unwrap()
        .set_len(header)
        .unwrap();
    let corrupted = root.files();
    assert!(open(&root, &bytes, 1, &first.checkpoint_after).is_err());
    assert_eq!(root.files(), corrupted);
}

#[test]
fn changed_checkpoint_is_refused_on_same_durable_owner() {
    let root = Fixture::new();
    let bytes = checkpoint();
    let first = {
        let mut owner = open(&root, &bytes, 0, &Digest32::ZERO.to_string()).unwrap();
        owner.tick(request(&bytes)).unwrap()
    };
    let settled = root.files();
    let mut modified: Checkpoint = serde_json::from_slice(&bytes).unwrap();
    modified.weights.c[1] += 0.01;
    let bytes = serde_json::to_vec(&modified).unwrap();
    assert!(open(&root, &bytes, 1, &first.checkpoint_after).is_err());
    assert_eq!(root.files(), settled);
}

#[test]
fn concurrent_owner_cannot_acquire_witness() {
    let root = Fixture::new();
    let bytes = checkpoint();
    let _first = open(&root, &bytes, 0, &Digest32::ZERO.to_string()).unwrap();
    assert!(open(&root, &bytes, 0, &Digest32::ZERO.to_string()).is_err());
}

#[test]
fn invalid_checkpoint_shape_and_nonpositive_scale_are_rejected() {
    let mut cp: Checkpoint = serde_json::from_slice(&checkpoint()).unwrap();
    cp.weights.v[0].pop();
    assert!(cp.validate().is_err());
    let mut cp: Checkpoint = serde_json::from_slice(&checkpoint()).unwrap();
    cp.norm.scale[0] = 0.0;
    assert!(cp.validate().is_err());
}

#[test]
fn model_masks_sentinel_and_uses_stable_stop_tie_order() {
    let root = Fixture::new();
    let mut cp: Checkpoint = serde_json::from_slice(&checkpoint()).unwrap();
    cp.weights.c.fill(-4.0);
    let bytes = serde_json::to_vec(&cp).unwrap();
    let mut input = request(&bytes);
    input.prior = [0.0; 4];
    let mut owner = open(&root, &bytes, 0, &Digest32::ZERO.to_string()).unwrap();
    assert_eq!(owner.tick(input).unwrap().action, "STOP");
}

#[test]
fn numeric_contract_mismatch_and_score_saturation_do_not_commit() {
    let root = Fixture::new();
    let bytes = checkpoint();
    let mut owner = open(&root, &bytes, 0, &Digest32::ZERO.to_string()).unwrap();
    let initial = root.files();
    let mut bad = request(&bytes);
    bad.numeric_contract = "another.numeric.profile".into();
    assert!(owner.tick(bad).is_err());
    assert_eq!(root.files(), initial);
    drop(owner);
    let root = Fixture::new();
    let mut cp: Checkpoint = serde_json::from_slice(&checkpoint()).unwrap();
    cp.weights.c[2] = 10.0;
    let bytes = serde_json::to_vec(&cp).unwrap();
    let mut owner = open(&root, &bytes, 0, &Digest32::ZERO.to_string()).unwrap();
    let initial = root.files();
    assert!(owner.tick(request(&bytes)).is_err());
    assert_eq!(root.files(), initial);
}
