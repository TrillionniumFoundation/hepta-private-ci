//! Standalone research executable; all probability operations are integers.

mod q24_checkpoint;
mod q24_core;
mod q24_sha256;

use q24_core::{Emission, Kernel, Memory, Outcome, SCALE, apportion};
use q24_sha256::{digest, hexadecimal};
use std::fs;
use std::path::Path;
use std::str::SplitWhitespace;

struct Model {
    identity: [u8; 32],
    source_identity: String,
    classes: usize,
    states: usize,
    initial: Memory,
    kernels: Vec<Kernel>,
    emissions: Vec<Emission>,
}

fn number<T: std::str::FromStr>(tokens: &mut SplitWhitespace<'_>) -> Outcome<T> {
    tokens
        .next()
        .ok_or("missing number")?
        .parse()
        .map_err(|_| "invalid number")
}

impl Model {
    fn parse(bytes: &[u8]) -> Outcome<Self> {
        let text = std::str::from_utf8(bytes).map_err(|_| "model must be UTF-8")?;
        let mut tokens = text.split_whitespace();
        if tokens.next() != Some("HCSN_Q24_MODEL_V1") {
            return Err("unsupported model schema");
        }
        let source_identity = tokens.next().ok_or("missing source identity")?.to_string();
        if source_identity.len() != 64
            || !source_identity.bytes().all(|byte| byte.is_ascii_hexdigit())
        {
            return Err("invalid source model identity");
        }
        let states: usize = number(&mut tokens)?;
        let addresses: usize = number(&mut tokens)?;
        let classes: usize = number(&mut tokens)?;
        let transitions: usize = number(&mut tokens)?;
        let emissions_count: usize = number(&mut tokens)?;
        if states == 0
            || states > 512
            || addresses == 0
            || addresses > 64
            || classes == 0
            || states % classes != 0
            || transitions > 256
            || emissions_count > 64
        {
            return Err("unsupported model dimensions");
        }
        let mut initial = Vec::with_capacity(addresses);
        for _ in 0..addresses {
            let row = (0..states)
                .map(|_| number(&mut tokens))
                .collect::<Outcome<Vec<u128>>>()?;
            initial.push(apportion(&row)?);
        }
        let mut kernels = Vec::with_capacity(transitions);
        for _ in 0..transitions {
            let ticks = number(&mut tokens)?;
            let mut weights = Vec::with_capacity(states);
            for _ in 0..states {
                weights.push(
                    (0..states)
                        .map(|_| number(&mut tokens))
                        .collect::<Outcome<Vec<u128>>>()?,
                );
            }
            kernels.push(Kernel::new(&weights, ticks)?);
        }
        let mut emissions = Vec::with_capacity(emissions_count);
        for _ in 0..emissions_count {
            let columns: usize = number(&mut tokens)?;
            if columns == 0 || columns > 512 {
                return Err("unsupported emission alphabet");
            }
            let mut weights = Vec::with_capacity(states);
            for _ in 0..states {
                weights.push(
                    (0..columns)
                        .map(|_| number(&mut tokens))
                        .collect::<Outcome<Vec<u128>>>()?,
                );
            }
            emissions.push(Emission::new(&weights)?);
        }
        if tokens.next().is_some() {
            return Err("trailing model data");
        }
        Ok(Self {
            identity: digest(bytes),
            source_identity,
            classes,
            states,
            initial: Memory {
                addresses: initial,
                completed: 0,
                clock_ticks: 0,
            },
            kernels,
            emissions,
        })
    }
}

fn print_state(memory: &Memory, event: &str) {
    let counts = memory
        .addresses
        .iter()
        .map(|address| &address.counts)
        .collect::<Vec<_>>();
    let support = memory
        .addresses
        .iter()
        .map(|address| &address.support)
        .collect::<Vec<_>>();
    let bounds = memory
        .addresses
        .iter()
        .map(|address| address.error_units)
        .collect::<Vec<_>>();
    println!(
        "{{\"event\":\"{event}\",\"completed\":{},\"clock_ticks\":{},\"counts\":{counts:?},\"support\":{support:?},\"l1_bound_units\":{bounds:?}}}",
        memory.completed, memory.clock_ticks
    );
}

fn read_bounded(path: &Path, maximum_bytes: u64) -> Result<Vec<u8>, String> {
    if fs::metadata(path).map_err(|error| error.to_string())?.len() > maximum_bytes {
        return Err("input exceeds research executable bound".to_string());
    }
    fs::read(path).map_err(|error| error.to_string())
}

fn run() -> Result<(), String> {
    let arguments = std::env::args().skip(1).collect::<Vec<_>>();
    if arguments.len() != 4 && arguments.len() != 5 {
        return Err("usage: q24 MODEL OPS CHECKPOINT MAX_L1_UNITS [RESTORE]".to_string());
    }
    let maximum_error: u32 = arguments[3].parse().map_err(|_| "invalid error limit")?;
    if maximum_error > 2 * SCALE {
        return Err("L1 error limit exceeds two".to_string());
    }
    let model = Model::parse(&read_bounded(Path::new(&arguments[0]), 16 * 1024 * 1024)?)?;
    let mut memory = if arguments.len() == 5 {
        q24_checkpoint::decode(
            &read_bounded(Path::new(&arguments[4]), 256 * 1024)?,
            &model.identity,
            model.initial.addresses.len(),
            model.states,
        )?
    } else {
        model.initial.clone()
    };
    if memory
        .addresses
        .iter()
        .any(|address| address.error_units > maximum_error)
    {
        return Err("precision required: restored or initial error budget".to_string());
    }
    let operations_bytes = read_bounded(Path::new(&arguments[1]), 2 * 1024 * 1024)?;
    let operations =
        std::str::from_utf8(&operations_bytes).map_err(|_| "operations must be UTF-8")?;
    print_state(&memory, "initial");
    for (index, line) in operations.lines().enumerate() {
        let mut tokens = line.split_whitespace();
        let Some(operation) = tokens.next() else {
            continue;
        };
        let outcome = (|| -> Outcome<()> {
            match operation {
                "T" => {
                    let kernel = model
                        .kernels
                        .get(number::<usize>(&mut tokens)?)
                        .ok_or("unknown transition")?;
                    memory.advance(kernel, maximum_error)?;
                }
                "O" => {
                    let address = number(&mut tokens)?;
                    let emission = model
                        .emissions
                        .get(number::<usize>(&mut tokens)?)
                        .ok_or("unknown emission")?;
                    let token = number(&mut tokens)?;
                    memory.observe(address, emission, token, maximum_error)?;
                }
                "W" => {
                    memory.write(number(&mut tokens)?, number(&mut tokens)?, model.classes)?;
                }
                _ => return Err("unknown operation"),
            }
            if tokens.next().is_some() {
                return Err("trailing operation data");
            }
            Ok(())
        })();
        outcome.map_err(|error| format!("operation line {}: {error}", index + 1))?;
        print_state(&memory, operation);
    }
    let checkpoint = q24_checkpoint::encode(&memory, &model.identity)?;
    q24_checkpoint::save(Path::new(&arguments[2]), &checkpoint)
        .map_err(|error| error.to_string())?;
    println!(
        "{{\"event\":\"checkpoint\",\"model_sha256\":\"{}\",\"source_identity\":\"{}\",\"checkpoint_sha256\":\"{}\"}}",
        hexadecimal(&model.identity),
        model.source_identity,
        hexadecimal(&digest(&checkpoint))
    );
    Ok(())
}

fn main() {
    if let Err(message) = run() {
        eprintln!("{message}");
        std::process::exit(2);
    }
}

#[cfg(test)]
#[path = "q24_tests.rs"]
mod tests;
