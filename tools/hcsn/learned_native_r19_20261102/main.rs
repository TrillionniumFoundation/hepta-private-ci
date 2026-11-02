//! Text-only pure forward parity executable; no Python callbacks or weights fitting.
#![forbid(unsafe_code)]
#[allow(dead_code)]
#[path = "../native_owner_r18_20261101/common.rs"]
mod common;
#[allow(dead_code)]
mod model;
#[allow(dead_code)]
#[path = "../native_numeric_r19_20261102/numeric.rs"]
mod numeric;
use common::{Result, ensure};
use model::Model;
use std::io::Write;
use std::path::Path;
fn execute() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    ensure(args.len() == 4, "forward MODEL TAPE OUTPUT")?;
    let mut model = Model::open(Path::new(&args[1]))?;
    let tape = std::fs::read_to_string(&args[2])?;
    let mut output = std::fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&args[3])?;
    let mut state = [[0.; 40]; 4];
    for line in tape.lines() {
        let p: Vec<_> = line.split_whitespace().collect();
        if p[0] == "WORLD" {
            ensure(p.len() == 5, "world shape")?;
            state = model.initial([p[1].parse()?, p[2].parse()?, p[3].parse()?, p[4].parse()?])?;
            continue;
        }
        ensure(p.len() == 7 && p[0] == "QUERY", "query shape")?;
        let write: i32 = p[1].parse()?;
        if write >= 0 {
            model.write(&mut state, write as usize, p[2].parse()?)?;
        }
        model.advance(&mut state, p[3].parse()?)?;
        let key: usize = p[4].parse()?;
        let decision = model.choose(&state, key, p[5].parse()?)?;
        if decision.read {
            model.apply_read(&mut state, key, p[6].parse()?)?;
        }
        let (answer, _) = model.answer(&state, key)?;
        write!(output, "{}\t{}", u8::from(decision.read), answer)?;
        for row in state {
            for value in row {
                write!(output, "\t{value:.17e}")?;
            }
        }
        for values in [decision.pre_logits, decision.pre_prob] {
            for value in values {
                write!(output, "\t{value:.9e}")?;
            }
        }
        for values in decision.post_logits.into_iter().chain(decision.post_prob) {
            for value in values {
                write!(output, "\t{value:.9e}")?;
            }
        }
        writeln!(
            output,
            "\t{:.9e}\t{:.9e}\t{:.9e}",
            decision.read_value, decision.action_gap, decision.min_head_gap
        )?;
    }
    Ok(())
}
fn main() {
    if let Err(error) = execute() {
        eprintln!("{error}");
        std::process::exit(2);
    }
}
