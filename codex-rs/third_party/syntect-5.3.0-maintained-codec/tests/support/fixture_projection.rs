//! Restore sealed upstream test fixtures into a private output directory.

use std::fs;
use std::io;
use std::io::Read;
use std::io::Write;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;

use flate2::bufread::GzDecoder;
use sha2::Digest;
use sha2::Sha256;

const CRATE_PREFIX: &str = "codex-rs/third_party/syntect-5.3.0-maintained-codec";
const ARCHIVE_INDEX: &str = include_str!("../../fixture-custody/raw-evidence-storage.json");
const MAX_FIXTURE_BYTES: u64 = 256 * 1024;

#[derive(serde_derive::Deserialize)]
struct Index {
    schema: String,
    files: Vec<Entry>,
}

#[derive(serde_derive::Deserialize)]
pub(crate) struct Entry {
    original_path: String,
    original_bytes: u64,
    original_sha256: String,
    stored_path: String,
    stored_bytes: u64,
    stored_sha256: String,
}

pub(crate) fn source_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("testdata")
}

pub(crate) fn entries() -> io::Result<Vec<Entry>> {
    let index: Index = serde_json::from_str(ARCHIVE_INDEX)?;
    if index.schema != "hepta.raw-evidence.storage.v1" {
        return Err(invalid("unsupported fixture custody schema"));
    }
    Ok(index.files)
}

impl Entry {
    pub(crate) fn original(&self) -> io::Result<&Path> {
        let relative = Path::new(&self.original_path)
            .strip_prefix(Path::new(CRATE_PREFIX).join("testdata"))
            .map_err(|_| invalid("fixture is outside the original testdata tree"))?;
        if relative.as_os_str().is_empty()
            || !relative
                .components()
                .all(|part| matches!(part, Component::Normal(_)))
        {
            return Err(invalid("invalid fixture custody path"));
        }
        Ok(relative)
    }

    pub(crate) fn restore(&self, root: &Path) -> io::Result<()> {
        let relative = self.original()?;
        if self.stored_path != format!("{}.evidence.gz", self.original_path)
            || self.original_bytes > MAX_FIXTURE_BYTES
            || self.stored_bytes > MAX_FIXTURE_BYTES
        {
            return Err(invalid("invalid fixture archive path or size"));
        }
        let archived = Path::new(&self.stored_path)
            .strip_prefix(CRATE_PREFIX)
            .map_err(|_| invalid("fixture archive is outside the crate"))?;
        let mut compressed = Vec::new();
        fs::File::open(Path::new(env!("CARGO_MANIFEST_DIR")).join(archived))?
            .take(self.stored_bytes + 1)
            .read_to_end(&mut compressed)?;
        verify(&compressed, self.stored_bytes, &self.stored_sha256)?;

        let mut decoded = Vec::new();
        let mut reader = GzDecoder::new(compressed.as_slice());
        (&mut reader)
            .take(self.original_bytes + 1)
            .read_to_end(&mut decoded)?;
        if !reader.into_inner().is_empty() {
            return Err(invalid("unexpected trailing data in fixture archive"));
        }
        verify(&decoded, self.original_bytes, &self.original_sha256)?;

        let destination = root.join(relative);
        fs::create_dir_all(destination.parent().unwrap())?;
        fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(destination)?
            .write_all(&decoded)
    }
}

fn verify(bytes: &[u8], expected_size: u64, expected_sha256: &str) -> io::Result<()> {
    if bytes.len() as u64 != expected_size
        || format!("{:x}", Sha256::digest(bytes)) != expected_sha256
    {
        return Err(invalid("fixture byte length or digest changed"));
    }
    Ok(())
}

fn invalid(message: &str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message)
}
