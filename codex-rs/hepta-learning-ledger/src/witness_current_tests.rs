use super::*;
use pretty_assertions::assert_eq;
use std::fs;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

static NEXT: AtomicU64 = AtomicU64::new(0);

struct Fixture(PathBuf);
impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "hepta-witness-current-{}-{serial}",
            std::process::id()
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }

    fn file(&self) -> File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(self.0.join("witness"))
            .unwrap()
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn binding() -> Digest32 {
    Digest32::of_bytes(b"current-witness-original-binding")
}

fn frontier(sequence: u64) -> LedgerWitnessFrontier {
    LedgerWitnessFrontier {
        anchor: LedgerAnchor {
            sequence,
            chain_digest: Digest32::of_bytes(&sequence.to_le_bytes()),
        },
        segment: None,
        sealed: false,
    }
}

fn populated(fixture: &Fixture) -> LedgerWitnessStore {
    let mut store = LedgerWitnessStore::create(fixture.file(), binding()).unwrap();
    store
        .advance(LedgerWitnessFrontier::empty(), frontier(1))
        .unwrap();
    store.advance(frontier(1), frontier(2)).unwrap();
    store
}

fn bytes(store: &mut LedgerWitnessStore) -> Vec<u8> {
    store.file.qualification_bytes(8 * 1024 * 1024).unwrap()
}

#[test]
fn current_reread_preserves_original_cursor_bytes_and_append_owner() {
    let fixture = Fixture::new();
    let mut store = populated(&fixture);
    let original = bytes(&mut store);
    store.file.seek(SeekFrom::Start(7)).unwrap();
    assert_eq!(store.read_current_frontier().unwrap(), frontier(2));
    assert_eq!(store.file.stream_position().unwrap(), 7);
    assert_eq!(bytes(&mut store), original);
    store.advance(frontier(2), frontier(3)).unwrap();
    drop(store);
    let mut recovered = LedgerWitnessStore::recover(fixture.file(), binding()).unwrap();
    assert_eq!(recovered.read_current_frontier().unwrap(), frontier(3));
}

#[test]
fn current_refuses_physical_length_changes_without_repair_or_rearm() {
    for mutation in 0..3 {
        let fixture = Fixture::new();
        let mut store = populated(&fixture);
        let original = bytes(&mut store);
        match mutation {
            0 => store.file.set_len((HEADER + FRAME) as u64).unwrap(),
            1 => store.file.set_len((original.len() - 1) as u64).unwrap(),
            2 => {
                store.file.seek(SeekFrom::End(0)).unwrap();
                store.file.write_all(&[0]).unwrap();
            }
            _ => unreachable!(),
        }
        let changed = bytes(&mut store);
        store.file.seek(SeekFrom::Start(9)).unwrap();
        assert!(store.read_current_frontier().is_err());
        assert_eq!(store.file.stream_position().unwrap(), 9);
        assert_eq!(bytes(&mut store), changed);
        store.file.seek(SeekFrom::Start(0)).unwrap();
        store.file.write_all(&original).unwrap();
        store.file.set_len(original.len() as u64).unwrap();
        assert_eq!(
            store.read_current_frontier(),
            Err(DurableLedgerError::Poisoned)
        );
    }
}

#[test]
fn current_detects_rehashed_history_even_with_unchanged_latest_frontier() {
    let fixture = Fixture::new();
    let mut store = populated(&fixture);
    let mut historical = frontier(1);
    historical.anchor.chain_digest = Digest32::of_bytes(b"other-valid-history");
    let frame = encode_frontier(historical).unwrap();
    store.file.seek(SeekFrom::Start(HEADER as u64)).unwrap();
    store.file.write_all(&frame).unwrap();
    let changed = bytes(&mut store);
    // Both frames remain well-formed, monotone and independently checksummed;
    // the latest frontier is still the retained frontier(2).
    assert_eq!(store.frontier().unwrap(), frontier(2));
    assert_eq!(
        store.read_current_frontier(),
        Err(DurableLedgerError::AnchorMismatch)
    );
    assert_eq!(bytes(&mut store), changed);
}

#[test]
fn recovered_current_detects_same_length_corruption_and_valid_frontier_substitution() {
    for rehash in [false, true] {
        let fixture = Fixture::new();
        drop(populated(&fixture));
        let mut store = LedgerWitnessStore::recover(fixture.file(), binding()).unwrap();
        let mut changed = bytes(&mut store);
        let offset = HEADER + FRAME;
        changed[offset + 24] ^= 1;
        if rehash {
            let checksum = Digest32::of_bytes(&changed[offset..offset + FRAME - 32]);
            changed[offset + FRAME - 32..].copy_from_slice(checksum.as_array());
        }
        store.file.seek(SeekFrom::Start(0)).unwrap();
        store.file.write_all(&changed).unwrap();
        assert!(store.read_current_frontier().is_err());
        assert_eq!(bytes(&mut store), changed);
    }
}
