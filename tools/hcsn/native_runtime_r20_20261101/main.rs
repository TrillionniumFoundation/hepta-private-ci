//! Experimental finite numeric owner; trusted-loopback operation only.
#![forbid(unsafe_code)]
// Reuse immutable R18 bounded IO helpers; its old replay types are unused here.
#[allow(dead_code)]
#[path = "../native_owner_r18_20261101/common.rs"]
mod common;
#[path = "../native_financial_r20_20261101/financial.rs"]
mod financial;
mod model;
mod numeric;
mod runtime;
mod wire;
use common::{Result, ensure};
use std::path::Path;

fn execute() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();
    ensure(args.len() >= 2, "missing role")?;
    let role = &args[1];
    if role == "identify" {
        ensure(args.len() == 3, "usage identify MODEL")?;
        let model = model::Model::open(Path::new(&args[2]))?;
        println!("{:016x}", model.id);
        return Ok(());
    }
    ensure(
        (role == "owner" && args.len() == 8) || (role == "provider" && args.len() == 9),
        "usage owner MODEL PLAN STATE ENDPOINT FAULT MARKER | provider MODEL PLAN CATALOG STATE ENDPOINT FAULT MARKER",
    )?;
    let model = model::Model::open(Path::new(&args[2]))?;
    let plan = model::Plan::open(Path::new(&args[3]), &model)?;
    match role.as_str() {
        "owner" => runtime::owner(
            &model,
            &plan,
            Path::new(&args[4]),
            Path::new(&args[5]),
            &args[6],
            Path::new(&args[7]),
        ),
        "provider" => runtime::provider(
            &model,
            &plan,
            Path::new(&args[4]),
            Path::new(&args[5]),
            Path::new(&args[6]),
            &args[7],
            Path::new(&args[8]),
        ),
        _ => Err("unknown role".into()),
    }
}
fn main() {
    if let Err(error) = execute() {
        eprintln!("{error}");
        std::process::exit(2);
    }
}
