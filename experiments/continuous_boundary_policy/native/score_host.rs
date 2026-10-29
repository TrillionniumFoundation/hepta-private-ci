//! Bounded, stateless, research-only original NDU score host.
#[path = "boundary_policy_score/decision.rs"]
mod decision;
#[path = "boundary_policy_score/protocol.rs"]
mod protocol;
use codex_hepta_types::Digest32;
use protocol::Request;
use serde::Deserialize;
use serde_json::Value;
use serde_json::json;
use std::io::BufRead;
use std::io::Read;
use std::io::Write;
use std::io::{self};
use std::path::PathBuf;
use std::time::Instant;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Permit {
    schema: String,
    allowed_root: String,
    external_effects: bool,
    production_authority: bool,
}

fn discard_line(reader: &mut impl BufRead) -> io::Result<()> {
    loop {
        let available = reader.fill_buf()?;
        if available.is_empty() {
            return Ok(());
        }
        let end = available.iter().position(|value| *value == b'\n');
        let count = end.map_or(available.len(), |position| position + 1);
        reader.consume(count);
        if end.is_some() {
            return Ok(());
        }
    }
}

fn main() -> Result<()> {
    let root = PathBuf::from(
        std::env::args()
            .nth(1)
            .ok_or("Explicit research root required")?,
    )
    .canonicalize()?;
    let permit_bytes = std::fs::read(root.join("RESEARCH_PERMIT.json"))?;
    if permit_bytes.len() > 4096 {
        return Err("Research permit byte limit".into());
    }
    let permit: Permit = serde_json::from_slice(&permit_bytes)?;
    if permit.schema != "hepta.boundary-policy.local-research-permit.v1"
        || permit.allowed_root != root.to_string_lossy()
        || permit.external_effects
        || permit.production_authority
    {
        return Err("Research permit mismatch".into());
    }
    let binary = Digest32::of_reader(
        std::fs::File::open(std::env::current_exe()?)?,
        /*maximum_bytes*/ 128 * 1024 * 1024,
    )?;
    let mut input = io::stdin().lock();
    let mut output = io::stdout().lock();
    loop {
        let mut bytes = Vec::new();
        let count = input
            .by_ref()
            .take((protocol::MAX_BYTES + 1) as u64)
            .read_until(b'\n', &mut bytes)?;
        if count == 0 {
            break;
        }
        let start = Instant::now();
        let mut shutdown = false;
        let result: Result<Value> = (|| {
            if count > protocol::MAX_BYTES {
                if bytes.last() != Some(&b'\n') {
                    discard_line(&mut input)?;
                }
                return Err("Native request byte limit".into());
            }
            match serde_json::from_slice::<Request>(&bytes)? {
                Request::Identity {} => Ok(json!({
                    "schema": "hepta.boundary-policy.native-score-identity.v1",
                    "binary_sha256": binary.to_string(),
                    "source_commit": env!("POLICY_NATIVE_SOURCE_COMMIT"),
                    "source_manifest_digest": env!("POLICY_NATIVE_SOURCE_DIGEST"),
                    "owner_authority": "DENY_ALL",
                    "durable_owner_execution": false,
                    "actual_kernel_calls": 0,
                    "actual_ndu_calls": 0,
                })),
                Request::DecideBatch { rows } => {
                    protocol::validate_batch(&rows)?;
                    let receipts: Vec<Value> = rows
                        .iter()
                        .map(|row| decision::decide(row, binary))
                        .collect::<Result<_>>()?;
                    Ok(json!({
                        "schema": "hepta.boundary-policy.score-batch.v1",
                        "rows": receipts,
                        "actual_ndu_calls": rows.len(),
                        "actual_kernel_calls": 0,
                        "owner_authority": "DENY_ALL",
                        "durable_owner_execution": false,
                        "model_inference_executed": false,
                    }))
                }
                Request::Shutdown {} => {
                    shutdown = true;
                    Ok(
                        json!({"shutdown":true,"actual_ndu_calls":0,"actual_kernel_calls":0,"owner_authority":"DENY_ALL"}),
                    )
                }
            }
        })();
        let elapsed = start.elapsed().as_micros() as u64;
        let response = match result {
            Ok(result) => json!({"ok":true,"result":result,"physical_rpc_micros":elapsed}),
            Err(error) => {
                json!({"ok":false,"error":error.to_string(),"physical_rpc_micros":elapsed})
            }
        };
        writeln!(output, "{response}")?;
        output.flush()?;
        if shutdown {
            break;
        }
    }
    Ok(())
}
