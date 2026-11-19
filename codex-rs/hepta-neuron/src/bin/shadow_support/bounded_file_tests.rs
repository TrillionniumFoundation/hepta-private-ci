use super::read_capped;
use super::read_file;
use std::fs;
use std::io;
use std::io::Read;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;

static NEXT: AtomicU64 = AtomicU64::new(0);

struct Fixture {
    root: PathBuf,
}

impl Fixture {
    fn new() -> io::Result<Self> {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-shadow-bounded-file-{}-{serial}",
            std::process::id()
        ));
        fs::create_dir(&root)?;
        Ok(Self { root })
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

struct UnendingInput {
    bytes_read: usize,
}

impl Read for UnendingInput {
    fn read(&mut self, output: &mut [u8]) -> io::Result<usize> {
        output.fill(b'x');
        self.bytes_read += output.len();
        Ok(output.len())
    }
}

#[test]
fn growing_input_stops_after_the_single_overflow_byte() {
    let mut reader = UnendingInput { bytes_read: 0 };
    assert_eq!(
        read_capped(&mut reader, 64).err(),
        Some("research file exceeds byte limit".to_owned())
    );
    assert_eq!(reader.bytes_read, 65);
}

#[test]
fn exact_limit_input_is_not_truncated() -> Result<(), Box<dyn std::error::Error>> {
    let original = b"bounded input";
    assert_eq!(read_capped(&original[..], original.len())?, original);
    let fixture = Fixture::new()?;
    let path = fixture.root.join("input");
    fs::write(&path, original)?;
    assert_eq!(read_file(&path, original.len())?, original);
    assert!(read_file(&path, original.len() - 1).is_err());
    Ok(())
}

#[test]
fn empty_files_and_directories_are_not_research_artifacts() -> Result<(), Box<dyn std::error::Error>>
{
    let fixture = Fixture::new()?;
    let path = fixture.root.join("empty");
    fs::write(&path, [])?;
    assert!(read_file(&path, 64).is_err());
    assert!(read_file(&fixture.root, 64).is_err());
    Ok(())
}
