use super::*;

fn key(epoch: u64, local_id: u64) -> RoomKey {
    RoomKey { epoch, local_id }
}

#[test]
fn room_round_trip_keeps_independent_selection_for_exact_unicode_text() {
    let mut memory = EditorMemory::default();
    memory.bind(1);
    memory.remember(key(1, 0), "a中文🚀z", (1, 7));
    memory.remember(key(1, 1), "second", (6, 2));
    assert_eq!(memory.restore(key(1, 0), "a中文🚀z"), Some((1, 7)));
    assert_eq!(memory.restore(key(1, 1), "second"), Some((6, 2)));
    assert_eq!(memory.restore(key(1, 0), "a中文🚀z"), Some((1, 7)));
}

#[test]
fn changed_text_discards_selection_even_if_the_old_text_returns() {
    let mut memory = EditorMemory::default();
    memory.bind(1);
    memory.remember(key(1, 0), "old", (0, 3));
    assert_eq!(memory.restore(key(1, 0), "new"), None);
    assert_eq!(memory.restore(key(1, 0), "old"), None);
}

#[test]
fn account_change_and_late_old_widget_cannot_restore_private_state() {
    let mut memory = EditorMemory::default();
    memory.bind(1);
    memory.remember(key(1, 0), "private", (0, 7));
    memory.bind(2);
    memory.remember(key(1, 0), "private", (0, 7));
    assert_eq!(memory.restore(key(1, 0), "private"), None);
    assert_eq!(memory.restore(key(2, 0), "private"), None);
    memory.remember(key(2, 0), "other", (2, 2));
    memory.bind(3);
    assert_eq!(memory.restore(key(3, 0), "other"), None);
    assert!(memory.entries.is_empty());
}

#[test]
fn capacity_and_text_limits_do_not_evict_existing_rooms() {
    let mut memory = EditorMemory::default();
    memory.bind(1);
    for id in 0..MAX_LOCAL_DRAFTS as u64 {
        memory.remember(key(1, id), "draft", (1, 2));
    }
    memory.remember(key(1, MAX_LOCAL_DRAFTS as u64), "overflow", (0, 1));
    assert_eq!(memory.entries.len(), MAX_LOCAL_DRAFTS);
    memory.remember(key(1, 0), &"x".repeat(MAX_DRAFT_BYTES + 1), (0, 1));
    memory.remember(key(1, 0), "bad\0input", (0, 1));
    assert_eq!(memory.restore(key(1, 0), "draft"), Some((1, 2)));
    memory.remember(key(1, 0), "changed", (2, 3));
    assert_eq!(memory.restore(key(1, 0), "changed"), Some((2, 3)));
}
