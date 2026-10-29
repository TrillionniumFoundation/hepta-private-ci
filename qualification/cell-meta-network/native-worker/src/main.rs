//! Isolated Linux measurement worker for the original native residual Cell.
//!
//! The worker binds loopback only and is launched/stopped by Hepta Runtime's
//! process owner. Its instance and generation checks protect experiment routing;
//! they do not replace Agentd source or publication authority.

use std::error::Error;
use std::fs;
use std::io::BufRead;
use std::io::BufReader;
use std::io::Read;
use std::io::Write;
use std::net::TcpListener;
use std::net::TcpStream;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_neuron::MemoryResidualCellV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde_json::Value;
use serde_json::json;

const MESSAGE_CAP: usize = 2 * 1024 * 1024;
const BATCH_CAP: usize = 64;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    request_id: String,
    instance: String,
    generation: u64,
    artifact_sha256: String,
    action: Action,
}

#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum Action {
    Read { features: Vec<Vec<f32>> },
    Stats,
}

struct Worker {
    model: MemoryResidualCellV1,
    instance: String,
    generation: u64,
    rows: u64,
    requests: u64,
    compute_ns: u128,
}

impl Worker {
    fn respond(&mut self, request: Request) -> Value {
        if request.instance != self.instance
            || request.generation != self.generation
            || request.artifact_sha256 != self.model.artifact_digest().to_string()
        {
            return json!({"ok": false, "error": "binding_mismatch", "request_id": request.request_id});
        }
        if request.request_id.is_empty() || request.request_id.len() > 128 {
            return json!({"ok": false, "error": "invalid_request_id"});
        }
        match request.action {
            Action::Stats => json!({
                "ok": true,
                "request_id": request.request_id,
                "instance": self.instance,
                "generation": self.generation,
                "artifact_sha256": self.model.artifact_digest().to_string(),
                "parameter_sha256": self.model.parameters_digest().to_string(),
                "encoder_sha256": self.model.encoder_digest().to_string(),
                "model_serialized_bytes": self.model.serialized_bytes(),
                "parameter_bytes": self.model.parameter_bytes(),
                "requests": self.requests,
                "rows": self.rows,
                "compute_ns": self.compute_ns,
                "process": process_usage(),
            }),
            Action::Read { features } => {
                if features.is_empty() || features.len() > BATCH_CAP {
                    return json!({"ok": false, "error": "invalid_batch", "request_id": request.request_id});
                }
                let started = Instant::now();
                let mut predictions = Vec::with_capacity(features.len());
                for row in &features {
                    match self.model.predict(row, self.model.encoder_digest()) {
                        Ok(prediction) => predictions.push(prediction.value),
                        Err(error) => {
                            return json!({"ok": false, "error": format!("{error:?}"), "request_id": request.request_id});
                        }
                    }
                }
                let elapsed = started.elapsed().as_nanos();
                self.rows += features.len() as u64;
                self.requests += 1;
                self.compute_ns += elapsed;
                json!({"ok": true, "request_id": request.request_id,
                       "instance": self.instance, "generation": self.generation,
                       "parameter_sha256": self.model.parameters_digest().to_string(),
                       "values": predictions, "compute_ns": elapsed})
            }
        }
    }

    fn serve_connection(&mut self, stream: TcpStream) -> Result<(), Box<dyn Error>> {
        stream.set_read_timeout(Some(Duration::from_secs(30)))?;
        stream.set_write_timeout(Some(Duration::from_secs(30)))?;
        stream.set_nodelay(true)?;
        let mut reader = BufReader::new(stream);
        loop {
            let mut line = Vec::new();
            let count = reader.by_ref().take((MESSAGE_CAP + 1) as u64).read_until(b'\n', &mut line)?;
            if count == 0 {
                return Ok(());
            }
            if count > MESSAGE_CAP || line.last() != Some(&b'\n') {
                return Err("request exceeds the bounded JSONL frame".into());
            }
            let response = match serde_json::from_slice::<Request>(&line) {
                Ok(request) => self.respond(request),
                Err(_) => json!({"ok": false, "error": "invalid_request"}),
            };
            let mut encoded = serde_json::to_vec(&response)?;
            encoded.push(b'\n');
            reader.get_mut().write_all(&encoded)?;
            reader.get_mut().flush()?;
        }
    }
}

fn process_usage() -> Value {
    // /proc counters include JSON parsing, sockets and model work. CLK_TCK is
    // recorded by the launcher; integer ticks are retained without false precision.
    let ticks = fs::read_to_string("/proc/self/stat")
        .ok()
        .and_then(|text| text.rsplit_once(')').map(|(_, tail)| tail.to_owned()))
        .and_then(|tail| {
            let fields: Vec<_> = tail.split_whitespace().collect();
            Some((fields.get(11)?.parse::<u64>().ok()?, fields.get(12)?.parse::<u64>().ok()?))
        });
    let status = fs::read_to_string("/proc/self/status").unwrap_or_default();
    let memory = |name: &str| {
        status.lines().find_map(|line| {
            line.strip_prefix(name)?.split_whitespace().next()?.parse::<u64>().ok()
        })
    };
    json!({"user_ticks": ticks.map(|value| value.0),
           "system_ticks": ticks.map(|value| value.1),
           "rss_kib": memory("VmRSS:"), "peak_rss_kib": memory("VmHWM:")})
}

fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 6 {
        return Err("usage: worker MODEL ARTIFACT_SHA256 INSTANCE GENERATION PORT".into());
    }
    let started = Instant::now();
    let expected = args[2].parse::<Digest32>()?;
    if fs::metadata(&args[1])?.len() > 4 * 1024 * 1024 {
        return Err("model artifact exceeds the native profile bound".into());
    }
    let bytes = fs::read(&args[1])?;
    let model = MemoryResidualCellV1::from_bytes(&bytes, expected)
        .map_err(|error| format!("invalid residual model: {error:?}"))?;
    let generation = args[4].parse::<u64>()?;
    if args[3].is_empty() || args[3].len() > 128 || generation == 0 {
        return Err("nonempty bounded instance and positive generation required".into());
    }
    let port = args[5].parse::<u16>()?;
    let listener = TcpListener::bind(("127.0.0.1", port))?;
    println!("{}", json!({"ready": true, "address": listener.local_addr()?.to_string(),
                         "instance": args[3], "generation": generation,
                         "artifact_sha256": model.artifact_digest().to_string(),
                         "parameter_sha256": model.parameters_digest().to_string(),
                         "encoder_sha256": model.encoder_digest().to_string(),
                         "startup_ns": started.elapsed().as_nanos(), "process": process_usage()}));
    std::io::stdout().flush()?;
    let mut worker = Worker { model, instance: args[3].clone(), generation,
                              rows: 0, requests: 0, compute_ns: 0 };
    for connection in listener.incoming() {
        let stream = connection?;
        if let Err(error) = worker.serve_connection(stream) {
            eprintln!("connection ended: {error}");
        }
    }
    Ok(())
}
