#[cfg(test)]
mod tests {
    use codex_hepta_infer_core::durable_control::DurableInferenceControl;
    use codex_hepta_infer_core::durable_control::native::NativeRequest;
    fn request(id: &str) -> NativeRequest {
        NativeRequest { request_id: id.into(), principal_id: "principal".into(), worker_generation: 1, model: "model".into(), payload_digest: "1".repeat(64) }
    }
    fn path(name: &str) -> std::path::PathBuf {
        let path = std::env::temp_dir().join(format!("inference-audit-{}-{name}", std::process::id()));
        std::fs::create_dir_all(&path).unwrap();
        path.join("journal")
    }
    #[test]
    fn truncated_retained_journal_must_not_acknowledge_cached_retry() {
        let path = path("truncate");
        let mut owner = DurableInferenceControl::open(&path, 8).unwrap();
        owner.reserve_native(request("request-1"), 2).unwrap();
        std::fs::OpenOptions::new().write(true).open(&path).unwrap().set_len(0).unwrap();
        assert!(owner.reserve_native(request("request-1"), 2).is_err(), "cached reservation was acknowledged after all its retained evidence was deleted");
    }
    #[test]
    fn same_length_replaced_history_must_not_accept_new_mutation() {
        let path = path("tamper");
        let mut owner = DurableInferenceControl::open(&path, 8).unwrap();
        owner.reserve_native(request("request-1"), 2).unwrap();
        owner.stop_native_before_dispatch("request-1", "done".into()).unwrap();
        let original = std::fs::read_to_string(&path).unwrap();
        let replaced = original.replace("request-1", "request-2");
        assert_eq!(original.len(), replaced.len());
        std::fs::write(&path, replaced).unwrap();
        let accepted = owner.reserve_native(request("request-3"), 2);
        drop(owner);
        let reopened = DurableInferenceControl::open(&path, 8).unwrap();
        assert!(reopened.native_record("request-1").is_none());
        assert!(reopened.native_record("request-2").is_some());
        assert!(accepted.is_err(), "new reservation was acknowledged over valid but substituted history; restart forgot the original identity");
    }
}
