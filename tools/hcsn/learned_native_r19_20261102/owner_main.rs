//! Real trained model plus durable causal owner. No target or Python callback.
#![forbid(unsafe_code)]
#[allow(dead_code)]
#[path = "../native_owner_r18_20261101/common.rs"]
mod common;
mod learned_owner;
#[allow(dead_code)]
#[path = "../native_owner_r18_20261101/provider.rs"]
mod mailbox;
#[allow(dead_code)]
mod model;
#[allow(dead_code)]
#[path = "../native_numeric_r19_20261102/numeric.rs"]
mod numeric;
use common::{Result, ensure};
use std::path::Path;
fn execute() -> Result<()> {
    let a: Vec<_> = std::env::args().collect();
    ensure(
        a.len() == 8 && a[1] == "owner",
        "owner PROFILE STATE MAILBOX RUN FAULT MARKER",
    )?;
    learned_owner::run(
        Path::new(&a[2]),
        Path::new(&a[3]),
        Path::new(&a[4]),
        &a[5],
        &a[6],
        Path::new(&a[7]),
    )
}
fn main() {
    if let Err(error) = execute() {
        eprintln!("{error}");
        std::process::exit(2);
    }
}
