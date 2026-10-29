//! Bounded research host over original native neuron and NDU crates.
mod decision;
mod measure;
mod model;
mod original_owner;
mod port;
mod pure;
mod replay;
mod session;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::SparseCheckpoint;
use codex_hepta_neuron::sparse_tick;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde_json::Value;
use serde_json::json;
use std::collections::BTreeMap;
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
    Identity,
    LoadProfile {
        path: PathBuf,
        sha256: String,
    },
    KernelBatch {
        profile_sha256: String,
        sequences: Vec<Vec<model::Features>>,
    },
    KernelReset {
        profile_sha256: String,
        case_ids: Vec<String>,
    },
    KernelAdvance {
        profile_sha256: String,
        observations: Vec<pure::Row>,
    },
    Open {
        request: session::OpenRequest,
    },
    Resume {
        request: session::OpenRequest,
    },
    Tick {
        observation: replay::Observation,
    },
    Status,
    Close,
}
fn batch(
    profile: &model::Profile,
    bundle: Digest32,
    binary: Digest32,
    sequences: Vec<Vec<model::Features>>,
) -> Result<Value> {
    if sequences.is_empty()
        || sequences.len() > 512
        || sequences.iter().map(Vec::len).sum::<usize>() > 8192
    {
        return Err("Kernel batch size limit".into());
    }
    let config = profile.runtime(bundle, binary)?;
    let native = profile.native(bundle)?;
    let mut result = Vec::new();
    let mut kernels = 0;
    for (number, sequence) in sequences.iter().enumerate() {
        if sequence.is_empty() || sequence.len() > profile.maximum_ticks as usize {
            return Err("Sequence length limit".into());
        }
        let subject = StableId::new(format!("batch.{number}"))?;
        let scope = JournalScope {
            scope_digest: Digest32::of_bytes(subject.as_str().as_bytes()),
            objective_digest: profile.objective_digest.parse()?,
        };
        let mut state: Option<SparseCheckpoint> = None;
        let mut rows = Vec::new();
        for (t, features) in sequence.iter().enumerate() {
            let prior = state.as_ref().map(|p| JournalAnchor {
                sequence: p.sequence(),
                checkpoint_digest: p.digest(),
            });
            let observation = replay::Observation {
                event_id: format!("batch.{number}.{t}"),
                step: t as u64 + 1,
                checkpoint: prior
                    .map_or(Digest32::ZERO, |a| a.checkpoint_digest)
                    .to_string(),
                features: features.clone(),
                evidence_digest: Digest32::of_bytes(&serde_json::to_vec(features)?).to_string(),
            };
            let request = replay::input(profile, &subject, scope, prior, &observation)?;
            let drive = profile.encode(&request.feature_vector_q24)?;
            let tick = replay::kernel_input(&config, scope, &request, drive)?;
            let (next, signal) = sparse_tick(&native, &tick, state.as_ref())?;
            rows.push(json!({"activation_q24":signal.activation_q24,"threshold_q24":next.thresholds_q24(),
                "eligibility_q24":next.eligibility_q24(),"temporal_digest":next.temporal_state_digest().to_string(),
                "checkpoint":next.digest().to_string(),"projection_count":signal.projection_count}));
            state = Some(next);
            kernels += 1;
        }
        result.push(rows);
    }
    Ok(
        json!({"schema":"hepta.continuous-boundary.kernel-batch.v1","sequences":result,
        "actual_kernel_calls":kernels,"profile_sha256":bundle.to_string(),"owner_authority":"DENY_ALL",
        "durable_owner_execution":false}),
    )
}
fn main() -> Result<()> {
    let root = PathBuf::from(
        std::env::args()
            .nth(1)
            .ok_or("Explicit research root required")?,
    )
    .canonicalize()?;
    let permit: Value = serde_json::from_slice(&std::fs::read(root.join("RESEARCH_PERMIT.json"))?)?;
    if permit["schema"] != "hepta.continuous-boundary.local-research-permit.v1"
        || permit["allowed_root"] != root.to_string_lossy().as_ref()
        || permit["external_effects"] != false
        || permit["production_authority"] != false
    {
        return Err("Research root permit mismatch".into());
    }
    let binary = Digest32::of_bytes(&std::fs::read(std::env::current_exe()?)?);
    let mut profiles: BTreeMap<String, model::Profile> = BTreeMap::new();
    let mut current: Option<session::Session> = None;
    let mut states = pure::States::new();
    let mut stdout = io::stdout().lock();
    for line in io::stdin().lock().lines() {
        let line = line?;
        let start = Instant::now();
        let result: Result<Value> = (|| {
            if line.len() > 16 * 1024 * 1024 {
                return Err("Native request byte limit".into());
            }
            match serde_json::from_str::<Request>(&line)? {
                Request::Identity => Ok(
                    json!({"schema":"hepta.continuous-boundary.native-identity.v1",
                    "binary_sha256":binary.to_string(),"source_commit":env!("CONTINUOUS_NATIVE_SOURCE_COMMIT"),
                    "source_manifest_digest":env!("CONTINUOUS_NATIVE_SOURCE_DIGEST"),"owner_authority":"DENY_ALL"}),
                ),
                Request::LoadProfile { path, sha256 } => {
                    if profiles.len() >= 2048 && !profiles.contains_key(&sha256) {
                        return Err("Profile cache limit".into());
                    }
                    let bytes = std::fs::read(path)?;
                    if bytes.len() > 1 << 20 || Digest32::of_bytes(&bytes).to_string() != sha256 {
                        return Err("Profile byte identity mismatch".into());
                    }
                    let profile: model::Profile = serde_json::from_slice(&bytes)?;
                    profile.validate()?;
                    profiles.insert(sha256.clone(), profile);
                    Ok(json!({"profile_sha256":sha256}))
                }
                Request::KernelBatch {
                    profile_sha256,
                    sequences,
                } => {
                    let p = profiles
                        .get(&profile_sha256)
                        .ok_or("Unknown frozen profile")?;
                    batch(p, profile_sha256.parse()?, binary, sequences)
                }
                Request::KernelReset {
                    profile_sha256,
                    case_ids,
                } => {
                    let profile = profiles
                        .get(&profile_sha256)
                        .ok_or("Unknown frozen profile")?;
                    pure::reset(&mut states, profile, profile_sha256.parse()?, case_ids)
                }
                Request::KernelAdvance {
                    profile_sha256,
                    observations,
                } => {
                    let profile = profiles
                        .get(&profile_sha256)
                        .ok_or("Unknown frozen profile")?;
                    pure::advance(
                        &mut states,
                        profile,
                        profile_sha256.parse()?,
                        binary,
                        observations,
                    )
                }
                Request::Open { request } => {
                    if current.is_some() {
                        return Err("Owner already open".into());
                    }
                    let profile = profiles
                        .get(&request.profile_sha256)
                        .ok_or("Unknown frozen profile")?
                        .clone();
                    let digest = request.profile_sha256.parse()?;
                    let (session, receipt) = session::Session::open(
                        &root,
                        request,
                        profile,
                        digest,
                        binary,
                        session::Mode::Fresh,
                    )?;
                    current = Some(session);
                    Ok(receipt)
                }
                Request::Resume { request } => {
                    if current.is_some() {
                        return Err("Owner already open".into());
                    }
                    let profile = profiles
                        .get(&request.profile_sha256)
                        .ok_or("Unknown frozen profile")?
                        .clone();
                    let digest = request.profile_sha256.parse()?;
                    let (session, receipt) = session::Session::open(
                        &root,
                        request,
                        profile,
                        digest,
                        binary,
                        session::Mode::Restore,
                    )?;
                    current = Some(session);
                    Ok(receipt)
                }
                Request::Tick { observation } => {
                    current.as_mut().ok_or("No native owner")?.tick(observation)
                }
                Request::Status => current.as_ref().ok_or("No native owner")?.status(),
                Request::Close => {
                    let status = current.as_ref().ok_or("No native owner")?.status()?;
                    current = None;
                    Ok(status)
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
        writeln!(stdout, "{response}")?;
        stdout.flush()?;
    }
    Ok(())
}
