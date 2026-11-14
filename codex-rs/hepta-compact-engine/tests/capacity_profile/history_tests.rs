use super::*;

#[test]
fn history_rows_form_distinct_linked_heads() {
    let key = SigningKey::from_bytes(&[13; 32]);
    let tokenizer = TrustedTokenizerV1 {
        enrollment: enrollment(
            CompactionTrustRoleV1::Tokenizer,
            "tokenizer:key:capacity",
            &key,
        ),
        tokenizer_digest: digest("tokenizer:capacity"),
    };
    let rows = history_inputs(2, 4, &tokenizer, &key);
    assert_eq!(rows.len(), 8);
    for revisions in rows.chunks_exact(4) {
        assert_eq!(revisions[0].record.revision.get(), 1);
        assert_eq!(revisions[0].record.predecessor_digest, None);
        for pair in revisions.windows(2) {
            assert_eq!(pair[0].record.record_id, pair[1].record.record_id);
            assert_eq!(
                pair[1].record.revision.get(),
                pair[0].record.revision.get() + 1
            );
            assert_eq!(
                pair[1].record.predecessor_digest,
                Some(pair[0].record.record_digest())
            );
        }
    }
    let snapshot = memory_snapshot(&rows);
    assert_eq!(snapshot.records.len(), 2);
    assert!(
        snapshot
            .records
            .iter()
            .all(|record| record.revision.get() == 4)
    );
    assert_eq!(snapshot.records[0], rows[3].record);
    assert_eq!(snapshot.records[1], rows[7].record);
}
