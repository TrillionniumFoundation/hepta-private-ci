use super::*;

#[test]
fn renewal_cannot_restore_an_old_or_forked_artifact_frontier() {
    let a = Digest32::of_bytes(b"original current head");
    let b = Digest32::of_bytes(b"next current head");
    assert!(frontier_extends((3, a, 4), (3, a, 5)));
    assert!(frontier_extends((3, a, 4), (4, b, 4)));
    assert!(!frontier_extends((3, a, 4), (2, a, 5)));
    assert!(!frontier_extends((3, a, 4), (3, b, 5)));
    assert!(!frontier_extends((3, a, 4), (4, b, 3)));
}
