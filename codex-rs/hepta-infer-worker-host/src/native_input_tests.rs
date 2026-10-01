use super::*;

#[test]
fn intelligence_handoff_is_committed_to_native_admission_identity() {
    let socket = std::path::Path::new("/tmp/native-owner.sock");
    let none = native_source_payload_digest("prompt", &None, socket, 5000, None).unwrap();
    let original = NativeIntelligenceRunBinding {
        run_id: "intelligence-run".to_string(),
        expected_revision: 2,
        context_digest: "a".repeat(64),
        envelope_digest: "b".repeat(64),
    };
    let bound =
        native_source_payload_digest("prompt", &None, socket, 5000, Some(&original)).unwrap();
    assert_ne!(none, bound);
    for field in 0..4 {
        let mut changed = original.clone();
        match field {
            0 => changed.run_id.push_str("-other"),
            1 => changed.expected_revision += 1,
            2 => changed.context_digest = "c".repeat(64),
            _ => changed.envelope_digest = "d".repeat(64),
        }
        assert_ne!(
            bound,
            native_source_payload_digest("prompt", &None, socket, 5000, Some(&changed)).unwrap()
        );
    }
    assert_eq!(
        none,
        digest(
            &serde_json::to_vec(&(
                "hepta.native-request.v1",
                "prompt",
                Option::<String>::None,
                socket,
                5000_u128,
            ))
            .unwrap()
        )
    );
}

#[test]
fn streamed_native_payload_preserves_legacy_unicode_and_escape_digest() {
    let prompt = "line one\n你好 \"quoted\" \\x";
    let query = Some("résumé".to_string());
    let socket = std::path::Path::new("/tmp/owner-测试.sock");
    assert_eq!(
        native_source_payload_digest(prompt, &query, socket, 5000, None).unwrap(),
        "97d8be701db799d69440403c5e4834d55af96894ff56ce5dcf4a2660e7e25502"
    );
    let binding = NativeIntelligenceRunBinding {
        run_id: "RUN:Mixed_Case-1.0".to_string(),
        expected_revision: 2,
        context_digest: "a".repeat(64),
        envelope_digest: "b".repeat(64),
    };
    let old_payload = serde_json::to_vec(&(
        "hepta.native-intelligence-request.v2",
        prompt,
        &query,
        socket,
        5000_u128,
        &binding.run_id,
        binding.expected_revision,
        &binding.context_digest,
        &binding.envelope_digest,
    ))
    .unwrap();
    assert_eq!(
        native_source_payload_digest(prompt, &query, socket, 5000, Some(&binding)).unwrap(),
        digest(&old_payload)
    );
}

#[test]
fn structural_handoff_validation_preserves_the_existing_stable_id_profile() {
    for run_id in ["RUN:Mixed_Case-1.0".to_string(), "r".repeat(128)] {
        let binding = NativeIntelligenceRunBinding {
            run_id,
            expected_revision: 2,
            context_digest: "b".repeat(64),
            envelope_digest: "c".repeat(64),
        };
        validate_intelligence_binding(&binding).unwrap();
    }
    let zero_context = NativeIntelligenceRunBinding {
        run_id: "run-a".to_string(),
        expected_revision: 2,
        context_digest: "0".repeat(64),
        envelope_digest: "c".repeat(64),
    };
    assert!(validate_intelligence_binding(&zero_context).is_err());
}

#[test]
fn initialize_version_preserves_existing_printable_unicode_and_size_profile() {
    for accepted in [
        "release 1.2+build/abc".to_string(),
        "版本 1.2".to_string(),
        "v".repeat(128),
    ] {
        assert!(app_server_version_valid(&accepted));
    }
    for rejected in [
        String::new(),
        "v".repeat(129),
        "version\nother".to_string(),
        "version\0other".to_string(),
    ] {
        assert!(!app_server_version_valid(&rejected));
    }
}

#[test]
fn bounded_diagnostic_preserves_short_multichunk_display_exactly() {
    assert_eq!(
        bounded_diagnostic(format_args!("owner {} failed: {}", 7, "说明")),
        "owner 7 failed: 说明"
    );
    assert_eq!(bounded_diagnostic(format_args!("")), "");
}

#[test]
fn bounded_diagnostic_caps_unicode_across_display_chunks_without_suffix() {
    let oversized = "😀".repeat(2048);
    let diagnostic = bounded_diagnostic(format_args!("owner: {oversized}; omitted suffix"));
    assert_eq!(diagnostic, format!("owner: {}", "😀".repeat(1017)));
    assert_eq!(diagnostic.chars().count(), 1024);
    assert!(diagnostic.len() <= 4096);
    assert_eq!(
        bounded_diagnostic(format_args!("{oversized}")),
        "😀".repeat(1024)
    );
}
