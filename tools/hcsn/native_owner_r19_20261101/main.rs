//! Bounded trusted-loopback recovery experiment; no release authority.
#![forbid(unsafe_code)]

#[path = "../native_owner_r18_20261101/common.rs"]
mod common;
#[path = "../native_owner_r18_20261101/owner.rs"]
mod owner;
// The immutable backend also contains its old client, retained for regression.
#[allow(dead_code)]
#[path = "../native_owner_r18_20261101/provider.rs"]
mod backend;
mod transport;
mod provider {
    pub use crate::transport::rpc;
}

use common::{Job, Result, ensure};
use std::path::Path;

fn main() {
    if let Err(error) = execute() {
        eprintln!("{error}");
        std::process::exit(2);
    }
}

fn execute() -> Result<()> {
    let a: Vec<String> = std::env::args().collect();
    ensure(
        a.len() == 7,
        "usage: owner|provider|relay JOB STATE ENDPOINT STOP MARKER",
    )?;
    let job = Job::open(Path::new(&a[2]))?;
    match a[1].as_str() {
        "owner" => owner::run(
            &job,
            Path::new(&a[3]),
            Path::new(&a[4]),
            &a[5],
            Path::new(&a[6]),
        ),
        "provider" => backend::serve(
            &job,
            Path::new(&a[3]),
            Path::new(&a[4]),
            &a[5],
            Path::new(&a[6]),
        ),
        "relay" => transport::serve(Path::new(&a[3]), Path::new(&a[4]), &a[5], Path::new(&a[6])),
        _ => Err("unknown role".into()),
    }
}
