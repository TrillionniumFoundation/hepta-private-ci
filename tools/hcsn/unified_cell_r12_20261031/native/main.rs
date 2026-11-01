//! Standalone finite-state runner with actual process-to-process restoration.
//! This is a research CLI, not Hepta's production NeuronRuntime admission path.
mod core;
mod sha256;

use std::fmt::Write as FmtWrite;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::{self};
use std::io::Read;
use std::io::Write;
use std::path::Path;

const SOURCE: &str = env!("HCSN_NATIVE_SOURCE_SHA256");
const MAGIC: &str = "HCSN_NATIVE_CHECKPOINT_V1";
const MAX_FILE_BYTES: u64 = 300_000_000;

struct State {
    n: usize,
    q: Vec<f64>,
    p: Vec<f64>,
    elapsed: f64,
    advances: u64,
    observations: u64,
    history: String,
}

fn read_limited(path: &Path) -> Result<String, String> {
    let file = File::open(path).map_err(|e| e.to_string())?;
    if file.metadata().map_err(|e| e.to_string())?.len() > MAX_FILE_BYTES {
        return Err("Input exceeds the explicit byte limit".into());
    }
    let mut text = String::new();
    file.take(MAX_FILE_BYTES + 1)
        .read_to_string(&mut text)
        .map_err(|e| e.to_string())?;
    if text.len() as u64 > MAX_FILE_BYTES {
        return Err("Growing input exceeds byte limit".into());
    }
    Ok(text)
}

fn parse_initial(path: &Path) -> Result<State, String> {
    let text = read_limited(path)?;
    let mut words = text.split_whitespace();
    let n: usize = words
        .next()
        .ok_or("Missing n")?
        .parse()
        .map_err(|_| "Invalid n")?;
    if n == 0 || n > core::MAX_DIMENSION {
        return Err("Invalid dimension".into());
    }
    let values: Result<Vec<f64>, _> = words.map(str::parse).collect();
    let values = values.map_err(|_| "Invalid decimal number")?;
    if values.len() != n * n + n {
        return Err("Expected n*n generator and n prior values".into());
    }
    let q = values[..n * n].to_vec();
    let p = values[n * n..].to_vec();
    core::propagate_row(n, &q, 0.0, &p).map_err(|e| format!("Invalid initial state: {e:?}"))?;
    let mut bytes = Vec::new();
    for value in &values {
        bytes.extend_from_slice(&value.to_bits().to_be_bytes());
    }
    Ok(State {
        n,
        q,
        p,
        elapsed: 0.0,
        advances: 0,
        observations: 0,
        history: sha256::hex(&bytes),
    })
}

fn restore(path: &Path) -> Result<State, String> {
    let text = read_limited(path)?;
    let (body, checksum) = text
        .rsplit_once("CHECKSUM ")
        .ok_or("Missing checkpoint checksum")?;
    if checksum.trim() != sha256::hex(body.as_bytes()) {
        return Err("Checkpoint checksum mismatch".into());
    }
    let mut words = body.split_whitespace();
    if words.next() != Some(MAGIC) || words.next() != Some(SOURCE) {
        return Err("Checkpoint contract/source mismatch".into());
    }
    let n: usize = words
        .next()
        .ok_or("Missing n")?
        .parse()
        .map_err(|_| "Invalid n")?;
    if n == 0 || n > core::MAX_DIMENSION {
        return Err("Invalid dimension".into());
    }
    let elapsed = f64::from_bits(
        u64::from_str_radix(words.next().ok_or("Missing clock")?, 16)
            .map_err(|_| "Invalid clock")?,
    );
    let advances = words
        .next()
        .ok_or("Missing advances")?
        .parse()
        .map_err(|_| "Invalid advances")?;
    let observations = words
        .next()
        .ok_or("Missing observations")?
        .parse()
        .map_err(|_| "Invalid observations")?;
    let history = words.next().ok_or("Missing history")?.to_owned();
    if history.len() != 64 || !history.bytes().all(|c| c.is_ascii_hexdigit()) {
        return Err("Invalid history digest".into());
    }
    let values: Result<Vec<f64>, _> = words
        .map(|s| u64::from_str_radix(s, 16).map(f64::from_bits))
        .collect();
    let values = values.map_err(|_| "Invalid float bits")?;
    if values.len() != n * n + n || !elapsed.is_finite() || elapsed < 0.0 {
        return Err("Invalid checkpoint shape/clock".into());
    }
    let q = values[..n * n].to_vec();
    let p = values[n * n..].to_vec();
    core::propagate_row(n, &q, 0.0, &p).map_err(|e| format!("Invalid restored state: {e:?}"))?;
    Ok(State {
        n,
        q,
        p,
        elapsed,
        advances,
        observations,
        history,
    })
}

fn execute(state: &mut State, script: &Path) -> Result<(), String> {
    let text = read_limited(script)?;
    for (index, line) in text.lines().enumerate() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        if index > 100_000 {
            return Err("Script exceeds explicit command limit".into());
        }
        let mut words = line.split_whitespace();
        let command = words.next().ok_or("Missing command")?;
        let values: Result<Vec<f64>, _> = words.map(str::parse).collect();
        let values = values.map_err(|_| "Invalid command value")?;
        match command {
            "advance" if values.len() == 1 => {
                state.p = core::propagate_row(state.n, &state.q, values[0], &state.p)
                    .map_err(|e| format!("advance refused: {e:?}"))?;
                state.elapsed += values[0];
                if !state.elapsed.is_finite() {
                    return Err("Clock overflow".into());
                }
                state.advances = state
                    .advances
                    .checked_add(1)
                    .ok_or("Advance counter overflow")?;
            }
            "observe" if values.len() == state.n => {
                state.p = core::observe_row(&state.p, &values)
                    .map_err(|e| format!("observe refused: {e:?}"))?;
                state.observations = state
                    .observations
                    .checked_add(1)
                    .ok_or("Observation counter overflow")?;
            }
            _ => return Err(format!("Unknown command or shape at line {}", index + 1)),
        }
        let mut binding = state.history.as_bytes().to_vec();
        binding.extend_from_slice(command.as_bytes());
        for value in values.iter().chain(&state.p) {
            binding.extend_from_slice(&value.to_bits().to_be_bytes());
        }
        state.history = sha256::hex(&binding);
    }
    Ok(())
}

fn persist(state: &State, path: &Path) -> Result<String, String> {
    let mut body = format!(
        "{MAGIC}\n{SOURCE}\n{} {:016x} {} {} {}\n",
        state.n,
        state.elapsed.to_bits(),
        state.advances,
        state.observations,
        state.history
    );
    for value in state.q.iter().chain(&state.p) {
        writeln!(body, "{:016x}", value.to_bits()).map_err(|e| e.to_string())?;
    }
    let digest = sha256::hex(body.as_bytes());
    let content = format!("{body}CHECKSUM {digest}\n");
    let temporary = path.with_extension(format!("tmp.{}", std::process::id()));
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temporary)
        .map_err(|e| e.to_string())?;
    let publish = (|| -> Result<(), String> {
        file.write_all(content.as_bytes())
            .map_err(|e| e.to_string())?;
        file.sync_all().map_err(|e| e.to_string())?;
        // Same-directory hard-link is atomic create-only: it never overwrites
        // an existing checkpoint, including concurrent publishers.
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
    publish?;
    Ok(digest)
}

fn run() -> Result<(), String> {
    let arguments: Vec<String> = std::env::args().collect();
    if arguments.len() != 5 {
        return Err("Usage: hcsn-native init INITIAL SCRIPT NEW_CHECKPOINT | resume CHECKPOINT SCRIPT NEW_CHECKPOINT".into());
    }
    let mut state = match arguments[1].as_str() {
        "init" => parse_initial(Path::new(&arguments[2]))?,
        "resume" => restore(Path::new(&arguments[2]))?,
        _ => return Err("Expected init or resume".into()),
    };
    execute(&mut state, Path::new(&arguments[3]))?;
    let checkpoint_digest = persist(&state, Path::new(&arguments[4]))?;
    let pid = std::process::id();
    println!("{{\"schema\":\"hcsn-r12-native-state-v1\",\"pid\":{pid},\"source_sha256\":\"{SOURCE}\",\"checkpoint_sha256\":\"{checkpoint_digest}\",\"n\":{},\"elapsed\":{},\"advances\":{},\"observations\":{},\"history_sha256\":\"{}\",\"probability\":{:?}}}", state.n, state.elapsed, state.advances, state.observations, state.history, state.p);
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("REFUSE: {error}");
        std::process::exit(2);
    }
}
