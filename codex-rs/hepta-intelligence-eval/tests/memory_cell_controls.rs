#[path = "../examples/memory_cell_lab/controls.rs"]
mod controls;
#[path = "../examples/memory_cell_lab/data.rs"]
mod data;
#[path = "../examples/memory_cell_lab/model.rs"]
mod model;
#[path = "../examples/memory_cell_lab/retrieval.rs"]
mod retrieval;

#[test]
fn all_controls_use_bounded_compute_and_future_labels_cannot_select_topology() {
    let rows = data::parse(&data::smoke_corpus()).unwrap();
    let first = controls::train_arms(&rows).unwrap();
    let mut poisoned = rows.clone();
    for r in &mut poisoned {
        if matches!(
            r.split,
            data::Split::FutureA | data::Split::FutureB | data::Split::Retention
        ) {
            r.targets = [3, 3];
        }
    }
    let second = controls::train_arms(&poisoned).unwrap();
    for (a, b) in first.iter().zip(&second) {
        assert_eq!(a.bundle, b.bundle);
        assert_eq!(a.name, b.name);
        assert_eq!(a.training_micros > 0, a.bundle.is_some());
        if let Some(bundle) = &a.bundle {
            assert_eq!(model::Bundle::decode(&bundle.encode()).unwrap(), *bundle);
        }
        assert!(
            controls::predict(a, &rows, &rows[128].query)
                .unwrap()
                .ops_estimate
                > 0
        );
        assert_eq!(a.decisions, b.decisions);
        assert_eq!(a.meter, b.meter);
        assert!(a.meter.train_ops <= controls::TRAIN_CEILING);
        let prediction = controls::predict(a, &rows, &rows[128].query).unwrap();
        assert!(
            prediction
                .probabilities
                .iter()
                .flatten()
                .all(|p| p.is_finite())
        );
    }
    assert_eq!(
        first[0].bundle.as_ref().unwrap().parameters(),
        first[1].bundle.as_ref().unwrap().parameters()
    );
    assert_eq!(
        first[0].bundle.as_ref().unwrap().parameters(),
        first[4].bundle.as_ref().unwrap().parameters()
    );
    assert_eq!(
        first[2].bundle.as_ref().unwrap().parameters(),
        first[3].bundle.as_ref().unwrap().parameters()
    );
}

#[test]
fn split_and_merge_preserve_budget_lineage_and_reject_wrong_generation() {
    let rows = data::parse(&data::smoke_corpus()).unwrap();
    let mut parent = model::Bundle::new("lab-public".into(), &[8]).unwrap();
    parent
        .train(&rows, &mut model::Meter::default(), 500_000)
        .unwrap();
    let children = controls::split(&parent).unwrap();
    assert_eq!(children.parameters(), parent.parameters());
    assert_eq!(children.roots, parent.roots);
    let mut merged = controls::merge(&children).unwrap();
    assert_eq!(merged.parameters(), parent.parameters());
    merged.generation = children.generation;
    assert!(controls::admit_topology(&children, &merged, &rows).is_err());
    assert!(controls::merge(&parent).is_err());
    assert!(controls::split(&children).is_err());
}

#[test]
fn retrieval_excludes_future_and_cross_scope_and_reports_actual_scans() {
    let rows = data::parse(&data::smoke_corpus()).unwrap();
    let q = &rows[128].query;
    let p = retrieval::recall(&rows, q, 16).unwrap();
    assert_eq!(p.scanned, 16);
    assert!(p.evidence.iter().all(|e| e.starts_with("fixture:0:")));
    let mut denied = q.clone();
    denied.scope = "unrelated-private-scope".into();
    assert!(retrieval::recall(&rows, &denied, 16).is_err());
    assert!(retrieval::recall(&rows, q, 0).is_err());
}
