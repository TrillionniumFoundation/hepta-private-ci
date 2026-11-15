use super::Index;
use super::Insert;
use pretty_assertions::assert_eq;
use std::collections::BTreeMap;
use std::collections::btree_map::Entry;

#[test]
fn ordered_pages_and_stable_duplicate_ids_match_the_original_map() {
    let names: Vec<_> = (0..2051)
        .rev()
        .map(|index| format!("key{index:06}"))
        .collect();
    let mut keys = Vec::new();
    let ranges: Vec<_> = names
        .iter()
        .map(|name| {
            let begin = keys.len();
            keys.extend_from_slice(name.as_bytes());
            begin..keys.len()
        })
        .collect();
    let mut index = Index::new();
    let mut original = BTreeMap::new();
    for position in (0..names.len()).chain(0..names.len()) {
        let next_id = original.len();
        let expected = match original.entry(names[position].clone()) {
            Entry::Vacant(entry) => {
                entry.insert(next_id);
                Insert::New { id: next_id }
            }
            Entry::Occupied(entry) => Insert::Existing { id: *entry.get() },
        };
        assert_eq!(
            index.insert_range(&keys, ranges[position].start, ranges[position].end),
            expected
        );
    }
    let expected: Vec<_> = original.values().copied().collect();
    assert_eq!(index.ordered_ids(), expected);
    assert_eq!(index.ordered_ids(), expected);
    for (name, id) in &original {
        assert_eq!(index.find(&keys, name), Some(*id));
        assert_eq!(index.find_and_mark(&keys, name), Some(*id));
    }
    assert_eq!(index.first_unused(), None);
    assert_eq!(index.find(&keys, "absent"), None);
}

#[test]
fn borrowed_ranges_and_query_windows_preserve_prefixes_and_usage_marks() {
    let prefix = "x".repeat(3 * super::QUERY_WINDOW + 1);
    let names = [
        format!("{prefix}😀"),
        format!("{prefix}é"),
        prefix,
        String::new(),
    ];
    let mut keys = vec![b'p'; 2 * 1024 * 1024 + 1];
    let mut index = Index::new();
    let mut original = BTreeMap::new();
    for (id, name) in names.iter().enumerate() {
        let begin = keys.len();
        keys.extend_from_slice(name.as_bytes());
        assert_eq!(
            index.insert_range(&keys, begin, keys.len()),
            Insert::New { id }
        );
        original.insert(name, id);
    }
    assert_eq!(
        index.ordered_ids(),
        original.values().copied().collect::<Vec<_>>()
    );
    for (name, id) in original {
        assert_eq!(index.first_unused(), Some(id));
        assert_eq!(index.find(&keys, name), Some(id));
        assert_eq!(index.first_unused(), Some(id));
        assert_eq!(index.find_and_mark(&keys, name), Some(id));
    }
    assert_eq!(index.first_unused(), None);
    assert_eq!(index.find(&keys, &(names[2].clone() + "not-present")), None);
}

#[test]
fn an_empty_index_and_insertions_after_marking_keep_native_order() {
    let mut index = Index::new();
    assert_eq!(index.ordered_ids(), Vec::<usize>::new());
    assert_eq!(index.find(&[], ""), None);
    assert_eq!(index.find_and_mark(&[], "longer"), None);
    assert_eq!(index.first_unused(), None);
    let keys = b"za";
    assert_eq!(
        index.insert_range(keys, /*begin*/ 0, /*end*/ 1),
        Insert::New { id: 0 }
    );
    assert_eq!(index.find_and_mark(keys, "z"), Some(0));
    assert_eq!(index.first_unused(), None);
    assert_eq!(
        index.insert_range(keys, /*begin*/ 1, /*end*/ 2),
        Insert::New { id: 1 }
    );
    assert_eq!(index.first_unused(), Some(1));
    assert_eq!(index.ordered_ids(), vec![1, 0]);
    assert_eq!(index.find_and_mark(keys, "a"), Some(1));
    assert_eq!(index.first_unused(), None);
}
