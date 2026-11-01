//! Bounded local test protocol and crash-safe file replacement; no release authority.

use std::error::Error;
use std::fs::{File, OpenOptions};
use std::io::{Read, Write};
use std::path::Path;

pub type Result<T> = std::result::Result<T, Box<dyn Error>>;
pub const MAX_FILE: usize = 4_000_000;

pub fn ensure(value: bool, message: &str) -> Result<()> {
    if value { Ok(()) } else { Err(message.into()) }
}

pub fn checksum(bytes: &[u8]) -> u64 {
    bytes.iter().fold(0xcbf29ce484222325, |hash, byte| {
        (hash ^ u64::from(*byte)).wrapping_mul(0x100000001b3)
    })
}

pub fn read(path: &Path) -> Result<String> {
    let mut text = String::new();
    File::open(path)?
        .take((MAX_FILE + 1) as u64)
        .read_to_string(&mut text)?;
    ensure(text.len() <= MAX_FILE, "file capacity")?;
    Ok(text)
}

pub fn atomic(path: &Path, body: &str) -> Result<()> {
    ensure(body.len() <= MAX_FILE, "file capacity")?;
    let temporary = path.with_extension(format!("tmp-{}", std::process::id()));
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temporary)?;
    file.write_all(body.as_bytes())?;
    file.sync_all()?;
    std::fs::rename(&temporary, path)?;
    File::open(path.parent().ok_or("no parent")?)?.sync_all()?;
    Ok(())
}

pub fn seal(body: &str) -> String {
    format!("{body}CHECK\t{:016x}\n", checksum(body.as_bytes()))
}

pub fn unseal(text: &str) -> Result<&str> {
    let index = text.rfind("CHECK\t").ok_or("missing checksum")?;
    let body = &text[..index];
    let expected = format!("CHECK\t{:016x}\n", checksum(body.as_bytes()));
    ensure(text[index..] == expected, "checksum mismatch")?;
    Ok(body)
}

pub fn lock(path: &Path) -> Result<File> {
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(path)?;
    file.lock()?;
    Ok(file)
}

pub fn fault(stage: &str, requested: &str, marker: &Path) -> Result<()> {
    if requested != "none" && stage == requested {
        atomic(marker, &format!("{stage}\t{}\n", std::process::id()))?;
        while !marker.with_extension("release").exists() {
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
    }
    Ok(())
}

#[derive(Clone)]
pub struct Frame {
    pub sequence: usize,
    pub event: String,
    pub opid: String,
    pub token: i32,
    pub elapsed_ns: u64,
    pub charged_micros: u64,
    pub provider_micros: u64,
    pub before_checksum: u64,
    pub after_state: String,
}

pub struct Job {
    pub run: String,
    pub initial: String,
    pub frames: Vec<Frame>,
    pub checksum: u64,
}

impl Job {
    pub fn open(path: &Path) -> Result<Self> {
        let text = read(path)?;
        let mut lines = unseal(&text)?.lines();
        let header: Vec<_> = lines.next().ok_or("missing run")?.split('\t').collect();
        ensure(
            header.len() == 3 && header[0] == "RUN" && header[1].len() == 64,
            "invalid run",
        )?;
        let mut frames = Vec::new();
        for line in lines {
            let fields: Vec<_> = line.split('\t').collect();
            ensure(fields.len() == 10 && fields[0] == "FRAME", "invalid frame")?;
            let sequence = fields[1].parse()?;
            ensure(sequence == frames.len(), "unordered frame")?;
            ensure(frames.len() < 256, "frame capacity")?;
            frames.push(Frame {
                sequence,
                event: fields[2].into(),
                opid: fields[3].into(),
                token: fields[4].parse()?,
                elapsed_ns: fields[5].parse()?,
                charged_micros: fields[6].parse()?,
                provider_micros: fields[7].parse()?,
                before_checksum: u64::from_str_radix(fields[8], 16)?,
                after_state: fields[9].into(),
            });
        }
        ensure(!frames.is_empty(), "empty job")?;
        Ok(Self {
            run: header[1].into(),
            initial: header[2].into(),
            frames,
            checksum: checksum(text.as_bytes()),
        })
    }
}
