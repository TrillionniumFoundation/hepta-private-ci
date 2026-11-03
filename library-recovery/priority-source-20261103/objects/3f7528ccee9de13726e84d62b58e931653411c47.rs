fn main() {
    let error = diagnostic::preserve(std::io::Error::from_raw_os_error(13)).unwrap_err();
    assert_eq!(error.raw_os_error(), Some(13));
    assert_eq!(error.kind(), std::io::ErrorKind::PermissionDenied);
}
