use super::tests::authority_verifier;
use super::tests::digest;
use super::tests::fixture;
use super::tests::id;
use super::tests::write_authority_file;
use super::*;

#[test]
fn complete_owner_snapshot_preserves_order_and_reopens_after_atomic_replacement() {
    let mut value = fixture();
    let directory = tempfile::tempdir().expect("directory");
    let path = directory.path().join("authority.json");
    let frontier = value.request.snapshot.revocation_frontier_digest();
    write_authority_file(&path, &value.owners, frontier);
    let requested: Vec<_> = value
        .owners
        .iter()
        .rev()
        .map(|owner| owner.owner_id.clone())
        .collect();
    let mut oracle = FileBackedFreshnessOracleV1::new(path.clone(), authority_verifier());
    let before = oracle.current_owners(&requested).expect("first snapshot");
    let expected: Vec<_> = requested
        .iter()
        .map(|owner| oracle.current(owner).expect("single owner"))
        .collect();
    assert_eq!(before, expected);
    for owner in &mut value.owners {
        owner.generation = Generation::new(owner.generation.get() + 1).expect("next generation");
    }
    let replacement = directory.path().join("replacement.json");
    let next_frontier = digest("updated revocation frontier");
    write_authority_file(&replacement, &value.owners, next_frontier);
    std::fs::rename(replacement, path).expect("atomic replacement");
    let after = oracle.current_owners(&requested).expect("new snapshot");
    let expected: Vec<_> = before
        .iter()
        .cloned()
        .map(|mut state| {
            state.generation = Generation::new(state.generation.get() + 1).expect("generation");
            state.revocation_frontier_digest = next_frontier;
            state
        })
        .collect();
    assert_eq!(after, expected);
    assert_eq!(
        oracle
            .current(&requested[0])
            .expect("fresh final-use lookup"),
        after[0]
    );
}

#[test]
fn owner_snapshot_rejects_missing_duplicate_tampered_and_oversized_inputs() {
    let value = fixture();
    let directory = tempfile::tempdir().expect("directory");
    let path = directory.path().join("authority.json");
    let frontier = value.request.snapshot.revocation_frontier_digest();
    write_authority_file(&path, &value.owners, frontier);
    let oracle = FileBackedFreshnessOracleV1::new(path.clone(), authority_verifier());
    let requested: Vec<_> = value
        .owners
        .iter()
        .map(|owner| owner.owner_id.clone())
        .collect();
    assert!(
        oracle
            .current_owners(&[requested[0].clone(), id("unknown.owner")])
            .is_err()
    );
    assert!(
        oracle
            .current_owners(&[requested[0].clone(), requested[0].clone()])
            .is_err()
    );
    let mut owners = value.owners.clone();
    owners.push(owners[0].clone());
    write_authority_file(&path, &owners, frontier);
    assert!(oracle.current_owners(&requested).is_err());
    write_authority_file(&path, &value.owners, frontier);
    let mut file: IntelligenceAuthorityFileV1 =
        serde_json::from_slice(&std::fs::read(&path).expect("read")).expect("file");
    file.owners[0].key_epoch += 1;
    std::fs::write(&path, serde_json::to_vec(&file).expect("serialize")).expect("tamper");
    assert!(oracle.current_owners(&requested).is_err());
    std::fs::write(
        &path,
        vec![b' '; MAX_INTELLIGENCE_AUTHORITY_FILE_BYTES as usize + 1],
    )
    .expect("oversized");
    assert!(oracle.current_owners(&requested).is_err());
}
