//! Opt-in local stateful-provider recovery qualification, not a neural kernel.
#![forbid(unsafe_code)]

mod common;
mod owner;
mod provider;

use common::{Job, Result, ensure};
use std::path::Path;

fn main() {
    if let Err(error) = execute() {
        eprintln!("{error}");
        std::process::exit(2);
    }
}

fn execute() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();
    ensure(
        args.len() == 7,
        "usage: native-owner owner|provider JOB STATE SOCKET STOP MARKER",
    )?;
    let job = Job::open(Path::new(&args[2]))?;
    match args[1].as_str() {
        "owner" => owner::run(
            &job,
            Path::new(&args[3]),
            Path::new(&args[4]),
            &args[5],
            Path::new(&args[6]),
        ),
        "provider" => provider::serve(
            &job,
            Path::new(&args[3]),
            Path::new(&args[4]),
            &args[5],
            Path::new(&args[6]),
        ),
        _ => Err("unknown role".into()),
    }
}
