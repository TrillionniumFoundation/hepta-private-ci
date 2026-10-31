//! Bounded, sequential reuse of the original evaluator in one native process.
//!
//! Only transport is amortized. Each request still calls the original typed
//! decoder, feasibility checks and recursive utility evaluation independently.

use std::io::BufRead;
use std::io::Read;
use std::io::Write;

use serde_json::json;

const MAX_REQUESTS: usize = 256;

pub(crate) fn run(mut input: impl BufRead, mut output: impl Write) -> Result<(), String> {
    writeln!(
        output,
        "{}",
        json!({"schema": "hepta.hia.ndu.stream.v1", "identity": super::identity(),
            "max_requests": MAX_REQUESTS, "authority": "DENY_ALL", "safety_certificate": false})
    )
    .map_err(|error| error.to_string())?;
    output.flush().map_err(|error| error.to_string())?;
    for sequence in 1..=MAX_REQUESTS {
        let mut line = Vec::new();
        input
            .by_ref()
            .take(super::MAX_INPUT + 2)
            .read_until(b'\n', &mut line)
            .map_err(|error| error.to_string())?;
        if line.is_empty() {
            return Ok(());
        }
        if line.pop() != Some(b'\n') || line.len() as u64 > super::MAX_INPUT {
            return Err("stream requires one newline-terminated request of at most 1 MiB".into());
        }
        let response = super::evaluate(&line)?;
        writeln!(
            output,
            "{}",
            json!({"schema": "hepta.hia.ndu.stream-response.v1", "sequence": sequence,
                "response": response, "authority": "DENY_ALL", "safety_certificate": false})
        )
        .map_err(|error| error.to_string())?;
        output.flush().map_err(|error| error.to_string())?;
    }
    let mut extra = [0_u8; 1];
    if input.read(&mut extra).map_err(|error| error.to_string())? != 0 {
        return Err("stream request budget of 256 exhausted".into());
    }
    Ok(())
}
