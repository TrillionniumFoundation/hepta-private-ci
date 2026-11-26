//! Parse cache only. Every cache hit still requires signature, current frontier
//! and monotonic lease verification by the publication provider.

use codex_hepta_agent_components::types::Digest32;
use std::sync::Mutex;

pub(super) struct PublicationCache<T> {
    value: Mutex<Option<(Digest32, T)>>,
}
impl<T: Clone> PublicationCache<T> {
    pub(super) fn new() -> Self {
        Self {
            value: Mutex::new(None),
        }
    }
    pub(super) fn decode<F>(&self, bytes: &[u8], maximum: usize, decode: F) -> Result<T, String>
    where
        F: FnOnce(&[u8]) -> Result<T, String>,
    {
        if bytes.is_empty() || bytes.len() > maximum {
            return Err("publication cache byte limit".to_string());
        }
        let digest = Digest32::of_bytes(bytes);
        let mut cached = self
            .value
            .lock()
            .map_err(|_| "publication parse cache poisoned".to_string())?;
        if let Some((expected, value)) = cached.as_ref()
            && *expected == digest
        {
            return Ok(value.clone());
        }
        let value = decode(bytes)?;
        *cached = Some((digest, value.clone()));
        Ok(value)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::AtomicUsize;
    use std::sync::atomic::Ordering;

    #[test]
    fn equal_bytes_skip_parsing_but_changed_bytes_do_not() {
        let cache = PublicationCache::new();
        let calls = AtomicUsize::new(0);
        let decode = |bytes: &[u8]| {
            calls.fetch_add(1, Ordering::SeqCst);
            String::from_utf8(bytes.to_vec()).map_err(|error| error.to_string())
        };
        assert_eq!(cache.decode(b"first", 10, decode).expect("first"), "first");
        assert_eq!(cache.decode(b"first", 10, decode).expect("hit"), "first");
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert_eq!(
            cache.decode(b"second", 10, decode).expect("changed"),
            "second"
        );
        assert_eq!(calls.load(Ordering::SeqCst), 2);
    }

    #[test]
    fn errors_and_oversize_never_return_a_previous_value() {
        let cache = PublicationCache::new();
        cache.decode(b"valid", 5, |_| Ok(7)).expect("initial");
        assert!(
            cache
                .decode(b"bad", 5, |_| Err("invalid".to_string()))
                .is_err()
        );
        assert!(cache.decode(b"valid", 4, |_| Ok(9)).is_err());
        assert!(cache.decode(b"", 5, |_| Ok(9)).is_err());
        assert_eq!(
            cache
                .decode(b"valid", 5, |_| Err("should be hit".to_string()))
                .expect("same original bytes"),
            7
        );
    }
}
