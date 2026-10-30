// SPDX-License-Identifier: Apache-2.0
// Exercise the actual event-handler context adapter after anymap migration.
use super::*;
use pretty_assertions::assert_eq;
use std::sync::atomic::{AtomicUsize, Ordering};

#[test]
fn event_context_clone_preserves_type_isolation_and_send_sync() {
    let store = EventHandlerStore::default();
    let shared = Arc::new(AtomicUsize::new(7));
    store.add_context(String::from("first"));
    store.add_context(Arc::clone(&shared));
    let cloned = store.context.read().unwrap().clone();
    store.add_context(String::from("replacement"));
    assert_eq!(
        store.context.read().unwrap().get::<String>().map(String::as_str),
        Some("replacement")
    );
    let observed = std::thread::spawn(move || {
        assert!(cloned.get::<u64>().is_none());
        cloned.get::<Arc<AtomicUsize>>().unwrap().fetch_add(1, Ordering::SeqCst);
        cloned.get::<String>().unwrap().clone()
    })
    .join()
    .unwrap();
    assert_eq!(observed, "first");
    assert_eq!(shared.load(Ordering::SeqCst), 8);
}
