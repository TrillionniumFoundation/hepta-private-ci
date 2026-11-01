//! Compatibility names used by Matrix SDK 0.18, with storage and downcasts
//! implemented exclusively by the maintained `anymap3` crate.

pub use anymap3::Map;

pub mod any {
    pub use anymap3::CloneAny;
    pub use anymap3::CloneAny as CloneAnySend;
    pub use anymap3::CloneAny as CloneAnySync;
    pub use anymap3::CloneAny as CloneAnySendSync;
    pub use core::any::Any;
}

pub mod raw {
    pub use anymap3::RawMap;
}

pub type AnyMap = anymap3::AnyMap;

#[cfg(test)]
mod tests {
    use super::any::CloneAnySendSync;
    use super::Map;

    #[test]
    fn cloned_event_contexts_are_isolated_and_remain_send_sync() {
        fn assert_send_sync<T: Send + Sync>(_: &T) {}
        let mut original = Map::<dyn CloneAnySendSync + Send + Sync>::new();
        original.insert(String::from("before"));
        original.insert(7_u64);
        let mut cloned = original.clone();
        cloned.get_mut::<String>().unwrap().push_str(" changed");
        assert_eq!(original.get::<String>().map(String::as_str), Some("before"));
        assert_eq!(cloned.remove::<u64>(), Some(7));
        assert_eq!(original.get::<u64>(), Some(&7));
        assert_send_sync(&cloned);
    }

    #[test]
    fn ordinary_any_does_not_gain_a_clone_requirement() {
        struct NotClone(u64);
        let mut values = Map::<dyn super::any::Any>::new();
        values.insert(NotClone(11));
        assert_eq!(values.remove::<NotClone>().unwrap().0, 11);
    }
}

