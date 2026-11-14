use super::to_ascii_json_string;
use pretty_assertions::assert_eq;
use serde_json::json;

#[test]
fn ascii_json_preserves_scalar_and_surrogate_pair_boundaries() -> serde_json::Result<()> {
    let input = "\u{80}\u{7ff}\u{800}\u{d7ff}\u{e000}\u{ffff}\u{10000}\u{10ffff}";
    assert_eq!(
        to_ascii_json_string(input)?,
        r#""\u0080\u07ff\u0800\ud7ff\ue000\uffff\ud800\udc00\udbff\udfff""#
    );
    Ok(())
}

#[test]
fn ascii_json_keeps_serde_structure_and_control_escaping() -> serde_json::Result<()> {
    let input = json!({"東京": ["\"\\\n", "🚀"], "a": [null, true, 1.5]});
    let output = to_ascii_json_string(&input)?;
    assert!(output.is_ascii());
    assert!(output.contains(r#""\u6771\u4eac":["\"\\\n","\ud83d\ude80"]"#));
    assert_eq!(serde_json::from_str::<serde_json::Value>(&output)?, input);
    Ok(())
}

#[test]
fn ascii_json_borrowed_windows_preserve_unicode_boundaries() -> serde_json::Result<()> {
    for padding in 4091..=4098 {
        let prefix = "A".repeat(padding);
        assert_eq!(
            to_ascii_json_string(&format!("{prefix}🚀é汉"))?,
            format!("\"{prefix}\\ud83d\\ude80\\u00e9\\u6c49\"")
        );
    }
    Ok(())
}

#[test]
fn ascii_json_has_no_total_frame_limit() -> serde_json::Result<()> {
    let text = "A".repeat(2_097_155);
    assert_eq!(
        to_ascii_json_string(&format!("{text}😀"))?,
        format!("\"{text}\\ud83d\\ude00\"")
    );
    assert_eq!(to_ascii_json_string("")?, "\"\"");
    Ok(())
}

#[cfg(feature = "hia-native")]
#[test]
fn ascii_json_native_transport_propagates_writer_errors() {
    struct Reject;
    impl std::io::Write for Reject {
        fn write(&mut self, _: &[u8]) -> std::io::Result<usize> {
            Err(std::io::Error::from(std::io::ErrorKind::PermissionDenied))
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Ok(())
        }
    }
    let result = super::hia_native_ascii_json::write_string_fragment(&mut Reject, "東京");
    assert_eq!(
        result.err().map(|error| error.kind()),
        Some(std::io::ErrorKind::PermissionDenied)
    );
}
