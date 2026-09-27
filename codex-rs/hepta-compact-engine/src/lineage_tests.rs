use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::Error;
use crate::compact;

fn first() -> MemoryRecord {
    MemoryRecord {
        record_id: StableId::new("record:lineage").unwrap_or_else(|error| panic!("id: {error}")),
        revision: Revision::new(1).unwrap_or_else(|error| panic!("revision: {error}")),
        kind: MemoryKind::Episode,
        content_digest: Digest32::of_bytes(b"first"),
        predecessor_digest: None,
        citations: Vec::new(),
        state: RecordState::Live,
    }
}

#[test]
fn compaction_rejects_tombstone_resurrection_with_otherwise_correct_lineage() {
    let first = first();
    let mut tombstone = first.clone();
    tombstone.revision = Revision::new(2).expect("revision");
    tombstone.predecessor_digest = Some(first.record_digest());
    tombstone.state = RecordState::Tombstone;
    tombstone.content_digest = Digest32::of_bytes(b"withdrawn");
    let mut resurrected = tombstone.clone();
    resurrected.revision = Revision::new(3).expect("revision");
    resurrected.predecessor_digest = Some(tombstone.record_digest());
    resurrected.state = RecordState::Live;
    assert_eq!(
        compact(Generation::new(1).expect("generation"), Digest32::of_bytes(b"source"), vec![first, tombstone, resurrected]),
        Err(Error::BrokenLineage("record:lineage".to_string())),
    );
}

#[test]
fn compaction_preserves_legitimate_revisioned_kind_change() {
    let first = first();
    let mut next = first.clone();
    next.revision = Revision::new(2).expect("revision");
    next.predecessor_digest = Some(first.record_digest());
    next.kind = MemoryKind::Fact;
    next.content_digest = Digest32::of_bytes(b"corrected");
    let checkpoint = compact(Generation::new(1).expect("generation"), Digest32::of_bytes(b"source"), vec![first, next.clone()]).expect("valid revision");
    assert_eq!(checkpoint.records, vec![next]);
}
