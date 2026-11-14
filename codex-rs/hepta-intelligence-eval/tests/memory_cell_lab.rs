//! Same executable backend tested as a normal learning.eval integration target.
#[path = "../examples/memory_cell_lab/data.rs"]
mod data;
#[path = "../examples/memory_cell_lab/model.rs"]
mod model;
use data::Episode;
use data::Split;
use model::Bundle;
use model::Meter;

fn corpus() -> Vec<Episode> {
    data::parse(&data::smoke_corpus()).unwrap()
}

#[test]
fn real_gradient_updates_and_loss_falls_without_test_labels() {
    let rows = corpus();
    let mut bundle = Bundle::new("lab-public".into(), &[8]).unwrap();
    let original = bundle.clone();
    let loss = |b: &Bundle| {
        rows.iter()
            .filter(|r| r.split == Split::Train)
            .map(|r| {
                let p = b.infer(&r.query).unwrap();
                -p[0][r.targets[0]].ln() - p[1][r.targets[1]].ln()
            })
            .sum::<f64>()
    };
    let before = loss(&bundle);
    let mut meter = Meter::default();
    bundle.train(&rows, &mut meter, 8_000_000).unwrap();
    assert!(loss(&bundle) < before);
    assert_ne!(bundle, original);
    assert!(meter.train_ops <= 8_000_000 && meter.updates > 0);
    let mut poisoned = rows.clone();
    for row in &mut poisoned {
        if row.split != Split::Train {
            row.targets = [3, 3];
        }
    }
    let mut other = original;
    other
        .train(&poisoned, &mut Meter::default(), 8_000_000)
        .unwrap();
    assert_eq!(bundle, other);
}

#[test]
fn source_groups_and_chronology_cannot_cross_holdout() {
    let mut rows = corpus();
    rows[64].root = rows[0].root.clone();
    assert!(data::validate(&rows).is_err());
    rows = corpus();
    rows[64].time = 1;
    assert!(data::validate(&rows).is_err());
}

#[test]
fn clean_bundle_has_no_events_and_rejects_wrong_scope_or_encoder() {
    let rows = corpus();
    let mut bundle = Bundle::new("lab-public".into(), &[8]).unwrap();
    bundle.train(&rows, &mut Meter::default(), 100_000).unwrap();
    let encoded = bundle.encode();
    assert!(!encoded.contains("ownership moved value"));
    let clean = Bundle::decode(&encoded).unwrap();
    assert_eq!(clean, bundle);
    let mut query = rows[0].query.clone();
    query.scope = "private-other".into();
    assert!(clean.infer(&query).is_err());
    assert!(Bundle::decode(&encoded.replace(data::ENCODER, "different-encoder")).is_err());
    assert!(Bundle::decode(&(encoded + "unexpected\n")).is_err());
}

#[test]
fn static_and_shared_capacity_are_exactly_equal() {
    let shared = Bundle::new("lab-public".into(), &[8]).unwrap();
    let static_cells = Bundle::new("lab-public".into(), &[4, 4]).unwrap();
    assert_eq!(shared.parameters(), static_cells.parameters());
    assert!(model::Cell::new(0).is_err());
}

#[test]
fn duplicate_observations_do_not_hide_behind_new_root_names() {
    let mut rows = corpus();
    rows[64].query = rows[0].query.clone();
    assert!(data::validate(&rows).is_err());
}
