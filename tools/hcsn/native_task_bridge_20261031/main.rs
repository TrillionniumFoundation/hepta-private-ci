#![forbid(unsafe_code)]
mod config;
mod contract;
mod model;
mod owner;
#[cfg(test)]
mod tests;

use crate::contract::Request;
use crate::owner::Owner;
use serde_json::json;
use std::io::BufRead;
use std::io::Read;
use std::io::Write;
use std::path::Path;

fn run() -> Result<(), String> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 7 {
        return Err("usage: native-task MODEL OWNER_DIR RUN_ID OBJECTIVE_SHA PREVIOUS_SEQUENCE PREVIOUS_ANCHOR".into());
    }
    let bytes = std::fs::read(&args[1]).map_err(|error| error.to_string())?;
    let mut owner = Owner::open(
        Path::new(&args[2]),
        &bytes,
        &args[3],
        &args[4],
        args[5].parse::<u64>().map_err(|error| error.to_string())?,
        &args[6],
    )?;
    let stdin = std::io::stdin();
    let mut input = stdin.lock();
    let stdout = std::io::stdout();
    let mut output = stdout.lock();
    loop {
        let mut line = String::new();
        let n = input
            .by_ref()
            .take(1_048_577)
            .read_line(&mut line)
            .map_err(|error| error.to_string())?;
        if n == 0 {
            break;
        }
        if n > 1_048_576 || !line.ends_with('\n') {
            return Err("request exceeds bounded JSONL line".into());
        }
        let started = std::time::Instant::now();
        let response = match serde_json::from_str::<Request>(&line)
            .map_err(|error| error.to_string())
            .and_then(|request| owner.tick(request))
        {
            Ok(receipt) => json!({"ok": true, "receipt": receipt}),
            Err(error) => {
                json!({"ok": false, "error": error, "failure_wall_micros": started.elapsed().as_micros()})
            }
        };
        serde_json::to_writer(&mut output, &response).map_err(|error| error.to_string())?;
        output
            .write_all(b"\n")
            .and_then(|_| output.flush())
            .map_err(|error| error.to_string())?;
    }
    Ok(())
}
fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(1);
    }
}
