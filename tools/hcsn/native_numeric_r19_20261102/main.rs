//! Public-generator native numerical qualification; all ownership is opt-in.
#![forbid(unsafe_code)]
#[allow(dead_code)]
#[path = "../native_owner_r18_20261101/common.rs"]
mod common;
#[allow(dead_code)]
#[path = "../native_owner_r18_20261101/provider.rs"]
mod mailbox;
mod numeric;
mod owner;
use common::{Result, ensure};
use std::path::Path;
fn execute() -> Result<()> {
    let a: Vec<_> = std::env::args().collect();
    ensure(a.len() >= 2, "mode")?;
    if a[1] == "operator" {
        ensure(a.len() == 5, "operator MODEL TIME OUTPUT")?;
        let model = numeric::Model::open(Path::new(&a[2]))?;
        let t = a[3].parse()?;
        let mut rate = [0.; 40];
        let mut killed = model.q;
        for i in 0..4 {
            rate[i] = model.q[i][32 + i];
            killed[i][32 + i] = 0.;
        }
        let f = numeric::propagate(&model.q, t, &rate)?;
        let k = numeric::propagate(&killed, t, &rate)?;
        let mut s = String::new();
        for (name, m) in [("P", f.p), ("KILLED", k.p)] {
            s.push_str(name);
            for row in m {
                for x in row {
                    s.push_str(&format!("\t{x:.17e}"));
                }
            }
            s.push('\n');
        }
        for (name, g) in [("COUNT", f.g), ("HIT", k.g)] {
            s.push_str(name);
            for x in g {
                s.push_str(&format!("\t{x:.17e}"));
            }
            s.push('\n');
        }
        s.push_str(&format!(
            "\nBOUND\t{:.17e}\t{:.17e}\t{:.17e}\t{:.17e}\t{}\n",
            f.tail, f.roundoff, f.reward_tail, f.reward_roundoff, f.order
        ));
        std::fs::write(&a[4], s)?;
        return Ok(());
    }
    ensure(
        a.len() == 9 && a[1] == "owner",
        "owner MODEL STATE MAILBOX RUN REPRESENTATION FAULT MARKER",
    )?;
    owner::run(
        Path::new(&a[2]),
        Path::new(&a[3]),
        Path::new(&a[4]),
        &a[5],
        &a[6],
        &a[7],
        Path::new(&a[8]),
    )
}
fn main() {
    if let Err(e) = execute() {
        eprintln!("{e}");
        std::process::exit(2);
    }
}
