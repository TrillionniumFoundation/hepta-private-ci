//! Bit-preserving process checkpoint with no-overwrite publication.
use crate::events::PathState;
use crate::prepared::Model;
use crate::prepared::MAX_PREPARED_DIMENSION;
use crate::sha256;
use std::fmt::Write as FmtWrite;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::{self};
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::sync::Arc;

pub const SOURCE: &str = env!("HCSN_NATIVE_SOURCE_SHA256");
const MAGIC: &str = "HCSN_R13_EXPOSURE_CHECKPOINT_V1";

pub fn read(path: &Path) -> Result<String, String> {
    let file = File::open(path).map_err(|e| e.to_string())?;
    let mut text = String::new();
    file.take(40_000_001)
        .read_to_string(&mut text)
        .map_err(|e| e.to_string())?;
    if text.len() > 40_000_000 {
        return Err("Input byte budget exceeded".into());
    }
    Ok(text)
}

pub fn model_file(path: &Path) -> Result<(Arc<Model>, Vec<f64>), String> {
    let text = read(path)?;
    let mut words = text.split_whitespace();
    let n: usize = words
        .next()
        .ok_or("Missing n")?
        .parse()
        .map_err(|_| "Invalid n")?;
    let version: u64 = words
        .next()
        .ok_or("Missing model version")?
        .parse()
        .map_err(|_| "Invalid version")?;
    if !(6..=MAX_PREPARED_DIMENSION).contains(&n) || n % 2 != 0 {
        return Err("Invalid layout dimension".into());
    }
    let values: Result<Vec<f64>, _> = words.map(str::parse).collect();
    let values = values.map_err(|_| "Invalid model number")?;
    if values.len() != n * n + n {
        return Err("Expected n*n Q entries followed by n prior entries".into());
    }
    let model =
        Model::new(n, &values[..n * n], version).map_err(|e| format!("Invalid Q: {e:?}"))?;
    crate::core::probability_mass(&values[n * n..]).map_err(|e| format!("Invalid prior: {e:?}"))?;
    PathState::validate_layout(&model)?;
    Ok((Arc::new(model), values[n * n..].to_vec()))
}

pub fn restore(path: &Path, expected_version: u64) -> Result<PathState, String> {
    let text = read(path)?;
    let (body, digest) = text.rsplit_once("CHECKSUM ").ok_or("Missing checksum")?;
    if digest.trim() != sha256::hex(body.as_bytes()) {
        return Err("Checkpoint checksum mismatch".into());
    }
    let mut words = body.split_whitespace();
    if words.next() != Some(MAGIC) || words.next() != Some(SOURCE) {
        return Err("Checkpoint source/schema mismatch".into());
    }
    let mut field = || words.next().ok_or("Missing checkpoint field");
    let n: usize = field()?.parse().map_err(|_| "Invalid n")?;
    let version = field()?.parse().map_err(|_| "Invalid model version")?;
    if version != expected_version {
        return Err("Expected model version mismatch".into());
    }
    if !(6..=MAX_PREPARED_DIMENSION).contains(&n) || n % 2 != 0 {
        return Err("Invalid n".into());
    }
    let identity = field()?.to_owned();
    let current = field()?.parse().map_err(|_| "Invalid state")?;
    let clock = |x| {
        u64::from_str_radix(x, 16)
            .map(f64::from_bits)
            .map_err(|_| "Invalid float bits")
    };
    let time = clock(field()?)?;
    let hazard_anchor = clock(field()?)?;
    let threshold = clock(field()?)?;
    let rng = field()?.parse().map_err(|_| "Invalid PRNG")?;
    let migrations = field()?.parse().map_err(|_| "Invalid migrations")?;
    let mut counts = [0u64; 5];
    for count in &mut counts {
        *count = field()?.parse().map_err(|_| "Invalid count")?;
    }
    let history = field()?.to_owned();
    let q: Result<Vec<f64>, _> = words.map(clock).collect();
    let q = q?;
    let model = Model::new(n, &q, version).map_err(|e| format!("Invalid checkpoint Q: {e:?}"))?;
    if model.identity != identity {
        return Err("Exact model identity mismatch".into());
    }
    let state = PathState {
        model: Arc::new(model),
        current,
        time,
        hazard_anchor,
        threshold,
        rng,
        counts,
        migrations,
        history,
    };
    state.validate()?;
    Ok(state)
}

pub fn persist(state: &PathState, path: &Path) -> Result<String, String> {
    state.validate()?;
    let mut body = format!(
        "{MAGIC}\n{SOURCE}\n{} {} {}\n{} {:016x} {:016x} {:016x} {} {}\n",
        state.model.n,
        state.model.version,
        state.model.identity,
        state.current,
        state.time.to_bits(),
        state.hazard_anchor.to_bits(),
        state.threshold.to_bits(),
        state.rng,
        state.migrations
    );
    for count in state.counts {
        write!(body, "{count} ").map_err(|e| e.to_string())?;
    }
    writeln!(body, "{}", state.history).map_err(|e| e.to_string())?;
    for value in &state.model.q {
        writeln!(body, "{:016x}", value.to_bits()).map_err(|e| e.to_string())?;
    }
    let checksum = sha256::hex(body.as_bytes());
    let content = format!("{body}CHECKSUM {checksum}\n");
    let temporary = path.with_extension(format!("tmp.{}", std::process::id()));
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temporary)
        .map_err(|e| e.to_string())?;
    let result = (|| -> Result<(), String> {
        file.write_all(content.as_bytes())
            .map_err(|e| e.to_string())?;
        file.sync_all().map_err(|e| e.to_string())?;
        fs::hard_link(&temporary, path).map_err(|e| e.to_string())?;
        let directory = path
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or(Path::new("."));
        File::open(directory)
            .and_then(|f| f.sync_all())
            .map_err(|e| e.to_string())?;
        Ok(())
    })();
    drop(file);
    let _ = fs::remove_file(&temporary);
    result?;
    Ok(checksum)
}
