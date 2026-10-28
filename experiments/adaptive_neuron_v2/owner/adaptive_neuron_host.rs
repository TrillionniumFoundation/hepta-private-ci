//! Scoped research driver of the unchanged Agentd owner and native runtime.
mod credit;
mod decision;
mod events;
mod measure;
mod neural;
#[allow(dead_code)]
mod original_credit;
mod original_owner;
mod port;
mod profile;
mod session;

use serde::Deserialize;
use serde_json::Value;
use serde_json::json;
use std::io::BufRead;
use std::io::Write;
use std::io::{self};
use std::path::PathBuf;
use std::time::Instant;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
const Q: i64 = 1 << 24;
#[global_allocator]
static ALLOCATOR: measure::ObservedAllocator = measure::ObservedAllocator;

#[derive(Deserialize)]
#[serde(tag = "command", deny_unknown_fields)]
enum Request {
    Open { request: session::OpenRequest },
    Resume { request: session::OpenRequest },
    Observe { observation: events::Observation },
    Settle { reward: f64, outcome_digest: String },
    Status,
    Close,
}

fn main() -> Result<()> {
    let root = PathBuf::from(
        std::env::args()
            .nth(1)
            .ok_or("Explicit research run root required")?,
    )
    .canonicalize()?;
    let permit: Value = serde_json::from_slice(&std::fs::read(root.join("RESEARCH_PERMIT.json"))?)?;
    if permit["schema"] != "hepta.adaptive-neuron.local-research-permit.v2"
        || permit["allowed_root"] != root.to_string_lossy().as_ref()
        || permit["external_effects"] != false
        || permit["production_authority"] != false
    {
        return Err("Research fixture scope mismatch".into());
    }
    let mut current: Option<session::Session> = None;
    let mut stdout = io::stdout().lock();
    for line in io::stdin().lock().lines() {
        let line = line?;
        let started = Instant::now();
        let response: Result<Value> = (|| {
            if line.len() > 65536 {
                return Err("Bounded request size exceeded".into());
            }
            match serde_json::from_str::<Request>(&line)? {
                Request::Open { request } => {
                    if current.is_some() {
                        return Err("Session already open".into());
                    }
                    let (owner, receipt) =
                        session::Session::open(&root, request, session::Mode::Fresh)?;
                    current = Some(owner);
                    Ok(receipt)
                }
                Request::Resume { request } => {
                    if current.is_some() {
                        return Err("Session already open".into());
                    }
                    let (owner, receipt) =
                        session::Session::open(&root, request, session::Mode::Restore)?;
                    current = Some(owner);
                    Ok(receipt)
                }
                Request::Observe { observation } => {
                    current.as_mut().ok_or("No session")?.observe(observation)
                }
                Request::Settle {
                    reward,
                    outcome_digest,
                } => current
                    .as_mut()
                    .ok_or("No session")?
                    .settle(reward, outcome_digest),
                Request::Status => current.as_ref().ok_or("No session")?.status(),
                Request::Close => {
                    let status = current.as_ref().ok_or("No session")?.status()?;
                    current = None;
                    Ok(status)
                }
            }
        })();
        let physical_rpc_micros = started.elapsed().as_micros() as u64;
        let envelope = match response {
            Ok(result) => {
                json!({"ok":true,"result":result,"physical_rpc_micros":physical_rpc_micros})
            }
            Err(error) => {
                json!({"ok":false,"error":error.to_string(),"physical_rpc_micros":physical_rpc_micros})
            }
        };
        writeln!(stdout, "{envelope}")?;
        stdout.flush()?;
    }
    Ok(())
}
