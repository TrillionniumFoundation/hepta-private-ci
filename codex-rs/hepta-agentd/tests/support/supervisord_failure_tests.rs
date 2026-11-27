use super::MESSAGE_BYTES;
use super::child_log_tail;

#[test]
fn large_unicode_log_has_bounded_read_and_rendered_tail() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("owned-child.log");
    std::fs::write(&path, "λ\n".repeat(8192)).unwrap();
    let observed = child_log_tail(&path);
    assert!(observed.len() <= MESSAGE_BYTES);
    assert!(observed.starts_with("child_log_read=ok observed_extent=24576 start_offset=16384"));
    assert!(observed.contains("requested_bytes=8192 read_bytes=8192 range_complete=true"));
    assert!(observed.ends_with("child_log_format_complete=false"));
}

#[test]
fn missing_child_log_is_reported_without_a_replacement_error() {
    let directory = tempfile::tempdir().unwrap();
    let observed = child_log_tail(&directory.path().join("absent-child.log"));
    assert!(observed.len() <= MESSAGE_BYTES);
    assert!(observed.starts_with("child_log_read=error kind=NotFound"));
    assert!(observed.ends_with("child_log_format_complete=true"));
}
