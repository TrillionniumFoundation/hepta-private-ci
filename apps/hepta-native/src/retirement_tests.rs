use super::Checkpoint;
use super::RetirementStore;
use super::directory;
use crate::model::sha256_hex;

fn identities(start: usize, end: usize) -> Vec<String> {
    (start..end)
        .map(|index| sha256_hex(format!("retired.{index}")))
        .collect()
}

#[test]
fn segmented_frontier_survives_restart_beyond_legacy_lifetime_limit() {
    let temp = tempfile::tempdir().unwrap();
    let journal = temp.path().join("operations.json");
    let mut store = RetirementStore::create(&journal).unwrap();
    let values = identities(0, 33_000);
    store.append(&values).unwrap();
    let checkpoint = store.checkpoint();
    assert_eq!(checkpoint.count, 33_000);
    assert_eq!(store.segments(), 33);
    drop(store);
    let mut reopened = RetirementStore::open(&journal, Some(&checkpoint))
        .unwrap()
        .unwrap();
    assert!(values.iter().all(|value| reopened.contains(value)));
    reopened.append(&values).unwrap();
    assert_eq!(reopened.checkpoint(), checkpoint);
    reopened.append(&identities(33_000, 34_000)).unwrap();
    assert_eq!(reopened.len(), 34_000);
}

#[test]
fn an_ahead_head_is_accepted_but_a_regressed_or_missing_head_is_not() {
    let temp = tempfile::tempdir().unwrap();
    let journal = temp.path().join("operations.json");
    let mut store = RetirementStore::create(&journal).unwrap();
    store.append(&identities(0, 2)).unwrap();
    let checkpoint = store.checkpoint();
    let path = directory(&journal).join("head.json");
    let before = std::fs::read(&path).unwrap();
    store.append(&identities(2, 4)).unwrap();
    let latest = store.checkpoint();
    assert_eq!(
        RetirementStore::open(&journal, Some(&checkpoint))
            .unwrap()
            .unwrap()
            .len(),
        4
    );
    std::fs::write(&path, before).unwrap();
    assert!(RetirementStore::open(&journal, Some(&latest)).is_err());
    std::fs::remove_file(&path).unwrap();
    assert!(RetirementStore::open(&journal, Some(&checkpoint)).is_err());
}

#[test]
fn corrupt_or_missing_segments_are_never_treated_as_empty_history() {
    let temp = tempfile::tempdir().unwrap();
    let journal = temp.path().join("operations.json");
    let mut store = RetirementStore::create(&journal).unwrap();
    store.append(&identities(0, 2)).unwrap();
    let checkpoint = store.checkpoint();
    let path = directory(&journal).join(format!("{}.json", checkpoint.head.as_ref().unwrap()));
    std::fs::write(&path, b"{}").unwrap();
    assert!(RetirementStore::open(&journal, Some(&checkpoint)).is_err());
    std::fs::remove_file(&path).unwrap();
    assert!(RetirementStore::open(&journal, Some(&checkpoint)).is_err());
}

#[test]
fn orphan_segment_does_not_hide_new_active_work_or_fabricate_a_head() {
    let temp = tempfile::tempdir().unwrap();
    let journal = temp.path().join("operations.json");
    let mut store = RetirementStore::create(&journal).unwrap();
    let head_path = directory(&journal).join("head.json");
    let before = std::fs::read(&head_path).unwrap();
    store.append(&identities(0, 4)).unwrap();
    // Crash equivalent: immutable segment exists but head was not published.
    std::fs::write(&head_path, before).unwrap();
    let reopened = RetirementStore::open(&journal, Some(&Checkpoint::default()))
        .unwrap()
        .unwrap();
    assert_eq!(reopened.len(), 0);
    assert!(!reopened.contains(&identities(0, 1)[0]));
}
