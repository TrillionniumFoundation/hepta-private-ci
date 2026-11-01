//! Real finite-Q jumps with fixed PRNG and pending-event process restoration.
mod core;
mod events;
mod sha256;

use events::Jump;
use events::PathState;
use std::fmt::Write as FmtWrite;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::{self};
use std::io::Read;
use std::io::Write;
use std::path::Path;

const SOURCE: &str = env!("HCSN_NATIVE_SOURCE_SHA256");
const MAGIC: &str = "HCSN_NATIVE_EVENTS_V1";

fn read(path: &Path) -> Result<String, String> {
    let file = File::open(path).map_err(|e| e.to_string())?;
    let mut text = String::new();
    file.take(300_000_001)
        .read_to_string(&mut text)
        .map_err(|e| e.to_string())?;
    if text.len() > 300_000_000 {
        return Err("File byte budget exceeded".into());
    }
    Ok(text)
}

fn initial(path: &Path, seed: u64) -> Result<PathState, String> {
    let text = read(path)?;
    let mut words = text.split_whitespace();
    let n: usize = words
        .next()
        .ok_or("Missing n")?
        .parse()
        .map_err(|_| "Invalid n")?;
    if !(6..=core::MAX_DIMENSION).contains(&n) || n % 2 != 0 {
        return Err("Invalid dimension".into());
    }
    let values: Result<Vec<f64>, _> = words.map(str::parse).collect();
    let values = values.map_err(|_| "Invalid initial numeric value")?;
    if values.len() != n * n + n {
        return Err("Invalid initial input shape".into());
    }
    PathState::new(values[..n * n].to_vec(), &values[n * n..], seed)
}

fn restored(path: &Path) -> Result<PathState, String> {
    let text = read(path)?;
    let (body, digest) = text.rsplit_once("CHECKSUM ").ok_or("Missing checksum")?;
    if digest.trim() != sha256::hex(body.as_bytes()) {
        return Err("Event checkpoint checksum mismatch".into());
    }
    let mut words = body.split_whitespace();
    if words.next() != Some(MAGIC) || words.next() != Some(SOURCE) {
        return Err("Event checkpoint version/source mismatch".into());
    }
    let mut field = || words.next().ok_or("Missing checkpoint field");
    let active: usize = field()?.parse().map_err(|_| "Invalid active count")?;
    if active == 0 || active > core::MAX_DIMENSION / 2 - 2 {
        return Err("Invalid active count".into());
    }
    let current = field()?.parse().map_err(|_| "Invalid current state")?;
    let time = f64::from_bits(u64::from_str_radix(field()?, 16).map_err(|_| "Invalid clock")?);
    let next_time =
        f64::from_bits(u64::from_str_radix(field()?, 16).map_err(|_| "Invalid pending clock")?);
    let next_state = field()?.parse().map_err(|_| "Invalid pending state")?;
    let rng = field()?.parse().map_err(|_| "Invalid PRNG state")?;
    let mut counts = [0u64; 5];
    for count in &mut counts {
        *count = field()?.parse().map_err(|_| "Invalid count")?;
    }
    let history = field()?.to_owned();
    if history.len() != 64 || !history.bytes().all(|c| c.is_ascii_hexdigit()) {
        return Err("Invalid history SHA".into());
    }
    let q: Result<Vec<f64>, _> = words
        .map(|x| u64::from_str_radix(x, 16).map(f64::from_bits))
        .collect();
    let state = PathState {
        q: q.map_err(|_| "Invalid Q bits")?,
        active,
        current,
        time,
        next_time,
        next_state,
        rng,
        counts,
        history,
    };
    state.validate()?;
    Ok(state)
}

fn persist(state: &PathState, path: &Path) -> Result<String, String> {
    let mut body = format!(
        "{MAGIC}\n{SOURCE}\n{} {} {:016x} {:016x} {} {} ",
        state.active,
        state.current,
        state.time.to_bits(),
        state.next_time.to_bits(),
        state.next_state,
        state.rng
    );
    for count in state.counts {
        write!(body, "{count} ").map_err(|e| e.to_string())?;
    }
    writeln!(body, "{}", state.history).map_err(|e| e.to_string())?;
    for value in &state.q {
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

fn run() -> Result<(), String> {
    let args: Vec<String> = std::env::args().collect();
    let mut state = match args.get(1).map(String::as_str) {
        Some("init") if args.len() == 6 => initial(Path::new(&args[2]), args[5].parse().map_err(|_| "Invalid seed")?)?,
        Some("resume") if args.len() == 5 => restored(Path::new(&args[2]))?,
        _ => return Err("Usage: hcsn-events init INITIAL SCRIPT NEW_CHECKPOINT SEED | resume CHECKPOINT SCRIPT NEW_CHECKPOINT".into()),
    };
    let initial_state = state.current;
    let initial_time = state.time;
    let mut jumps: Vec<Jump> = Vec::new();
    let script = read(Path::new(&args[3]))?;
    for (i, line) in script.lines().enumerate() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let words: Vec<&str> = line.split_whitespace().collect();
        if i >= 100_000 || words.len() != 2 || words[0] != "advance" {
            return Err("Expected a bounded sequence of advance dt commands".into());
        }
        jumps.extend(state.advance(words[1].parse().map_err(|_| "Invalid dt")?)?);
        if jumps.len() > 1_000_000 {
            return Err("Total trace budget exceeded".into());
        }
    }
    let digest = persist(&state, Path::new(&args[4]))?;
    let mut trace = String::from("[");
    for (i, jump) in jumps.iter().enumerate() {
        if i > 0 {
            trace.push(',');
        }
        write!(
            trace,
            "{{\"time\":{},\"from\":{},\"to\":{},\"kind\":\"{}\"}}",
            jump.time, jump.from, jump.to, jump.kind
        )
        .map_err(|e| e.to_string())?;
    }
    trace.push(']');
    let next_time = if state.next_time.is_finite() {
        state.next_time.to_string()
    } else {
        "null".into()
    };
    let pid = std::process::id();
    println!("{{\"schema\":\"hcsn-r12-gillespie-v1\",\"pid\":{pid},\"source_sha256\":\"{SOURCE}\",\"checkpoint_sha256\":\"{digest}\",\"initial_state\":{initial_state},\"initial_time\":{initial_time},\"current\":{},\"time\":{},\"next_time\":{next_time},\"next_state\":{},\"rng_state\":{},\"counts\":{:?},\"history_sha256\":\"{}\",\"jumps\":{trace}}}", state.current, state.time, state.next_state, state.rng, state.counts, state.history);
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("REFUSE: {error}");
        std::process::exit(2);
    }
}
