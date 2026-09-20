use std::cell::Cell;
use std::io::Cursor;
use std::rc::Rc;

use pretty_assertions::assert_eq;

use super::super::catalog_test_support::TestDirectory;

use super::*;

#[test]
fn absent_rows_remain_absent() {
    let root = TestDirectory::new().expect("temporary directory");
    assert_eq!(
        read_catalog_file(&root.path().join("absent"), 32).expect("missing row"),
        None
    );
}

#[test]
fn exact_regular_rows_round_trip() {
    let root = TestDirectory::new().expect("temporary directory");
    let path = root.path().join("row");
    std::fs::write(&path, b"catalog").expect("write row");
    assert_eq!(
        read_catalog_file(&path, 7).expect("read row"),
        Some(b"catalog".to_vec())
    );
}

#[test]
fn truncated_and_extended_rows_are_rejected() {
    let root = TestDirectory::new().expect("temporary directory");
    let path = root.path().join("row");
    for bytes in [b"ab".as_slice(), b"abcd".as_slice()] {
        std::fs::write(&path, bytes).expect("write malformed row");
        assert!(matches!(
            read_catalog_file(&path, 3),
            Err(LongHorizonLedgerErrorV1::CatalogCorrupt)
        ));
    }
}

#[test]
fn oversized_sparse_rows_are_rejected_before_payload_read() {
    let root = TestDirectory::new().expect("temporary directory");
    let path = root.path().join("sparse");
    let file = File::create(&path).expect("create sparse row");
    file.set_len(1_u64 << 30).expect("extend sparse row");
    assert!(matches!(
        read_catalog_file(&path, 120),
        Err(LongHorizonLedgerErrorV1::CatalogCorrupt)
    ));
    assert_eq!(file.metadata().expect("metadata").len(), 1_u64 << 30);
}

struct GrowingReader(Rc<Cell<usize>>);

impl Read for GrowingReader {
    fn read(&mut self, buffer: &mut [u8]) -> std::io::Result<usize> {
        buffer.fill(0);
        self.0.set(self.0.get() + buffer.len());
        Ok(buffer.len())
    }
}

#[test]
fn growth_after_metadata_reads_only_one_extra_byte() {
    let consumed = Rc::new(Cell::new(0));
    let reader = GrowingReader(Rc::clone(&consumed));
    assert!(matches!(
        bounded_contents(reader, 120),
        Err(LongHorizonLedgerErrorV1::CatalogCorrupt)
    ));
    assert_eq!(consumed.get(), 121);
}

#[test]
fn shrink_after_metadata_is_rejected() {
    assert!(matches!(
        bounded_contents(Cursor::new(b"short"), 120),
        Err(LongHorizonLedgerErrorV1::CatalogCorrupt)
    ));
}

#[test]
fn directories_are_not_catalog_rows() {
    let root = TestDirectory::new().expect("temporary directory");
    assert!(read_catalog_file(root.path(), 120).is_err());
}

#[test]
fn empty_regular_file_is_read_without_an_extra_payload() {
    let root = TestDirectory::new().expect("temporary directory");
    let path = root.path().join("empty");
    std::fs::write(&path, b"").expect("write empty file");
    assert_eq!(
        read_catalog_file(&path, 0).expect("empty read"),
        Some(Vec::new())
    );
}
