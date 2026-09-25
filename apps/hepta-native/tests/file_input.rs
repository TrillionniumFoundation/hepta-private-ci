mod common;
use common::private_tempdir;
use hepta_native::file_input::read_json_file;

#[test]
fn bounded_json_rejects_oversize_unknown_type_and_truncation() {
    let root = private_tempdir();
    let path = root.path().join("config.json");
    std::fs::write(&path, b"{\"x\":1}").unwrap();
    let value: serde_json::Value = read_json_file(&path, 7).unwrap();
    assert_eq!(value["x"], 1);
    assert!(read_json_file::<serde_json::Value>(&path, 6).is_err());
    assert!(read_json_file::<serde_json::Value>(root.path(), 1024).is_err());
    std::fs::write(&path, b"{\"x\":").unwrap();
    assert!(read_json_file::<serde_json::Value>(&path, 1024).is_err());
}
#[cfg(unix)]
#[test]
fn symlinks_and_fifos_do_not_cross_the_input_boundary() {
    let root = private_tempdir();
    let path = root.path().join("config.json");
    std::fs::write(&path, b"{}").unwrap();
    let link = root.path().join("link.json");
    std::os::unix::fs::symlink(&path, &link).unwrap();
    assert!(read_json_file::<serde_json::Value>(&link, 1024).is_err());
    let fifo = root.path().join("fifo");
    rustix::fs::mknodat(
        rustix::fs::CWD,
        &fifo,
        rustix::fs::FileType::Fifo,
        rustix::fs::Mode::RUSR | rustix::fs::Mode::WUSR,
        0,
    )
    .unwrap();
    assert!(read_json_file::<serde_json::Value>(&fifo, 1024).is_err());
}
