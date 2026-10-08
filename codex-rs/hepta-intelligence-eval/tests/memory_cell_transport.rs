#[path = "../examples/memory_cell_lab/data.rs"]
mod data;
#[path = "../examples/memory_cell_lab/model.rs"]
mod model;
#[path = "../examples/memory_cell_lab/transfer.rs"]
mod transfer;
use std::fs;

#[test]
fn transfer_contains_no_replay_labels_and_new_revocation_blocks_old_artifact() {
    let rows = data::parse(&data::smoke_corpus()).unwrap();
    let mut bundle = model::Bundle::new("lab-public".into(), &[4, 4]).unwrap();
    bundle.train(&rows, &mut model::Meter::default(), 500_000).unwrap();
    let root = std::env::temp_dir().join(format!("mcell-transport-{}", std::process::id()));
    fs::create_dir(&root).unwrap();
    let input = root.join("transfer");
    transfer::export(&bundle, &rows, &input, &root.join("expected.tsv")).unwrap();
    assert_eq!(fs::read_dir(&input).unwrap().count(), 2);
    let queries = fs::read_to_string(input.join("queries.tsv")).unwrap();
    assert!(queries.lines().skip(1).all(|line| line.split('\t').count() == 4));
    transfer::infer(&input, &root.join("observed.tsv"), None).unwrap();
    assert_eq!(fs::read(root.join("expected.tsv")).unwrap(), fs::read(root.join("observed.tsv")).unwrap());
    let revoked = root.join("current-revocations.txt");
    fs::write(&revoked, format!("MCELL-REVOCATIONS-LAB-1\n{}\n", bundle.roots.first().unwrap())).unwrap();
    assert_eq!(transfer::infer(&input, &root.join("after.tsv"), Some(&revoked)), Err("revoked training root".into()));
    assert!(!root.join("after.tsv").exists());
    fs::remove_dir_all(root).unwrap();
}
