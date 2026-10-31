use crate::cell::Cell;
use crate::cell::Family;
use crate::owner::Owner;
use crate::owner::Request;
use std::path::PathBuf;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
static SERIAL: AtomicUsize = AtomicUsize::new(0);
fn temporary() -> PathBuf {
    let p = std::env::temp_dir().join(format!(
        "native-r8-test-{}-{}",
        std::process::id(),
        SERIAL.fetch_add(1, Ordering::SeqCst)
    ));
    std::fs::create_dir(&p).unwrap();
    p
}
fn cell(family: Family) -> Cell {
    Cell::new([0.2, -0.3, 0.4, -0.1, 0.5, 0.2, 0.4, -0.2, 0.3, 0.5, -0.1], family, 173).unwrap()
}
fn request(sequence: u64, pair: &str) -> Request {
    Request {
        sequence,
        pair_before: pair.into(),
        driver: 0.3,
        duration_micros: 2_000_000,
        horizon_micros: 500_000,
        reset: sequence % 3 == 0,
    }
}
fn zero() -> String {
    "0".repeat(64)
}

#[test]
fn first_hit_rare_tail_is_positive_and_accurate() {
    let mut c = cell(Family::Distribution);
    c.probability = [1.0, 0.0, 0.0, 0.0, 0.0];
    // Independently evaluated six-term integral Taylor series for K^n r.
    for (micros, reference) in [(1, 1.5136615433021308e-19), (10, 1.51365041249785e-16)] {
        let hit = c.query(0.3, micros).unwrap()[3];
        assert!(hit > 0.0);
        assert!((hit / reference - 1.0).abs() < 1e-12);
    }
}

#[test]
fn sampled_split_keeps_path_and_hazard() {
    let mut coarse = cell(Family::Sampled);
    let mut dense = coarse.clone();
    let a = coarse.advance(1, 0.4, 64_000_000, false).unwrap();
    let mut b = Vec::new();
    for s in 1..=512 {
        b.extend(dense.advance(s, 0.4, 125_000, false).unwrap());
    }
    assert_eq!(a.len(), b.len());
    for (x, y) in a.iter().zip(b) {
        assert_eq!((x.before, x.after, x.fired), (y.before, y.after, y.fired));
        assert!((x.elapsed_seconds - y.elapsed_seconds).abs() < 2e-12);
    }
    assert_eq!((coarse.index, coarse.events), (dense.index, dense.events));
    let sa = coarse.snapshot();
    let sb = dense.snapshot();
    assert_eq!((&sa.rng_state_hex, sa.rng_draws), (&sb.rng_state_hex, sb.rng_draws));
}

#[test]
fn snapshot_exact_resume_and_read_only_query() {
    let mut a = cell(Family::Sampled);
    a.advance(1, -0.5, 9_000_000, true).unwrap();
    let bytes = serde_json::to_vec(&a.snapshot()).unwrap();
    let mut b = cell(Family::Sampled);
    b.restore(&serde_json::from_slice(&bytes).unwrap()).unwrap();
    let before = b.snapshot();
    b.query(0.9, 2_000_000).unwrap();
    assert_eq!(before, b.snapshot());
    let ja = a.advance(2, 0.7, 11_000_000, false).unwrap();
    let jb = b.advance(2, 0.7, 11_000_000, false).unwrap();
    assert_eq!(ja, jb);
    assert_eq!(a.snapshot(), b.snapshot());
    let before = b.snapshot();
    let mut corrupt = before.clone();
    corrupt.hazard_bits = "0000000000000000".into();
    assert!(b.restore(&corrupt).is_err());
    assert_eq!(before, b.snapshot());
}

#[test]
fn distribution_and_ordinary_semigroup() {
    for family in [Family::Distribution, Family::Ordinary] {
        let mut a = cell(family);
        let mut b = a.clone();
        a.advance(1, -0.2, 12_000_000, false).unwrap();
        for s in 1..=96 {
            b.advance(s, -0.2, 125_000, false).unwrap();
        }
        for (x, y) in a
            .query(0.3, 2_000_000)
            .unwrap()
            .iter()
            .zip(b.query(0.3, 2_000_000).unwrap())
        {
            assert!((x - y).abs() < 2e-10);
        }
        assert!((a.events - b.events).abs() < 2e-10);
    }
}

#[test]
fn real_runtime_restart_restores_physics_and_signal() {
    let p = temporary();
    let mut o = Owner::open(&p, cell(Family::Sampled), &zero()).unwrap();
    let first = o.step(request(1, &zero())).unwrap();
    drop(o);
    let mut o = Owner::open(&p, cell(Family::Sampled), &first.pair_after).unwrap();
    let second = o.step(request(2, &first.pair_after)).unwrap();
    assert!(second.native_physics_executed);
    assert_eq!(second.signals_q24.len(), 5);
    let p2 = temporary();
    let mut other = Owner::open(&p2, cell(Family::Sampled), &zero()).unwrap();
    let first2 = other.step(request(1, &zero())).unwrap();
    let second2 = other.step(request(2, &first2.pair_after)).unwrap();
    assert_eq!(
        (second.cell, second.signals_q24, second.pair_after),
        (second2.cell, second2.signals_q24, second2.pair_after)
    );
    drop(o);
    drop(other);
    std::fs::remove_dir_all(p).unwrap();
    std::fs::remove_dir_all(p2).unwrap();
}

#[test]
fn rejection_consumes_neither_physics_rng_nor_journal() {
    let p = temporary();
    let mut o = Owner::open(&p, cell(Family::Sampled), &zero()).unwrap();
    let first = o.step(request(1, &zero())).unwrap();
    let before = o.cell.snapshot();
    let journal = std::fs::read(p.join("journal.bin")).unwrap();
    assert!(o.step(request(1, &first.pair_after)).is_err());
    let mut invalid = request(2, &first.pair_after);
    invalid.driver = f64::NAN;
    assert!(o.step(invalid).is_err());
    assert_eq!(before, o.cell.snapshot());
    assert_eq!(journal, std::fs::read(p.join("journal.bin")).unwrap());
    drop(o);
    std::fs::remove_dir_all(p).unwrap();
}

#[test]
fn acknowledged_physics_tamper_and_native_loss_rejected() {
    let p = temporary();
    let mut o = Owner::open(&p, cell(Family::Distribution), &zero()).unwrap();
    let first = o.step(request(1, &zero())).unwrap();
    drop(o);
    let path = p.join("cell-checkpoint.json");
    let good = std::fs::read(&path).unwrap();
    let mut corrupt: serde_json::Value = serde_json::from_slice(&good).unwrap();
    corrupt["cell"]["elapsed_micros"] = serde_json::json!(999);
    std::fs::write(&path, serde_json::to_vec(&corrupt).unwrap()).unwrap();
    assert!(Owner::open(&p, cell(Family::Distribution), &first.pair_after).is_err());
    std::fs::write(&path, good).unwrap();
    std::fs::write(p.join("journal.bin"), []).unwrap();
    assert!(Owner::open(&p, cell(Family::Distribution), &first.pair_after).is_err());
    std::fs::remove_dir_all(p).unwrap();
}

#[test]
fn interrupted_pair_publication_fails_closed() {
    let p = temporary();
    let mut o = Owner::open(&p, cell(Family::Sampled), &zero()).unwrap();
    let first = o.step(request(1, &zero())).unwrap();
    std::fs::write(p.join("cell-checkpoint.pending"), b"interrupted publication").unwrap();
    assert!(o.step(request(2, &first.pair_after)).is_err());
    assert!(o.step(request(2, &first.pair_after)).is_err());
    drop(o);
    assert!(Owner::open(&p, cell(Family::Sampled), &first.pair_after).is_err());
    std::fs::remove_dir_all(p).unwrap();
}

#[test]
fn native_model_and_exclusive_owner_are_bound() {
    let p = temporary();
    let mut o = Owner::open(&p, cell(Family::Sampled), &zero()).unwrap();
    assert!(Owner::open(&p, cell(Family::Sampled), &zero()).is_err());
    let first = o.step(request(1, &zero())).unwrap();
    drop(o);
    assert!(Owner::open(&p, cell(Family::Ordinary), &first.pair_after).is_err());
    std::fs::remove_dir_all(p).unwrap();
}
