use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_evidence::EvidenceCheckpoint;
use codex_hepta_evidence::EvidenceIssuerProof;
use codex_hepta_evidence::EvidenceTrustPolicy;
use codex_hepta_evidence::HeptaEvidenceStore;
use codex_hepta_evidence::IndependentDecisionInput;
use codex_hepta_evidence::PreparedIndependentDecision;
use codex_hepta_evidence::QualificationEvidenceEnvelope;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use serde::de::DeserializeOwned;
use serde::Serialize;

const USAGE: &str = "usage:
  hepta-evidence-writer bootstrap-checkpoint <sqlite-home> <checkpoint-out>
  hepta-evidence-writer signing-bytes <envelope-json> <signing-bytes-out>
  hepta-evidence-writer admit <sqlite-home> <trust-policy-json> <envelope-json> <issuer-proof-json> <previous-checkpoint-json> <next-checkpoint-out>
  hepta-evidence-writer prepare-independent <sqlite-home> <trust-policy-json> <input-json> <checkpoint-json> <prepared-out> <signing-bytes-out>
  hepta-evidence-writer append-independent <sqlite-home> <trust-policy-json> <prepared-json> <issuer-proof-json> <previous-checkpoint-json> <next-checkpoint-out>
  hepta-evidence-writer verify-checkpoint <sqlite-home> <checkpoint-json>";

#[tokio::main]
async fn main() {
    if let Err(error) = run().await {
        eprintln!("{error}");
        std::process::exit(1);
    }
}

async fn run() -> Result<(), String> {
    let args = std::env::args().collect::<Vec<_>>();
    let command = args.get(1).map(String::as_str).ok_or_else(|| USAGE.to_string())?;
    match command {
        "bootstrap-checkpoint" if args.len() == 4 => {
            let sqlite = sqlite_config(&args[2])?;
            let store = HeptaEvidenceStore::open(&sqlite)
                .await
                .map_err(|error| error.to_string())?;
            let checkpoint = store
                .qualification()
                .export_checkpoint()
                .await
                .map_err(|error| error.to_string())?;
            if checkpoint.receipt_count != 0 {
                return Err(
                    "refusing to bootstrap an external checkpoint after qualification evidence already exists"
                        .to_string(),
                );
            }
            write_new(
                Path::new(&args[3]),
                &checkpoint
                    .canonical_bytes()
                    .map_err(|error| error.to_string())?,
            )?;
            print_json(&checkpoint)
        }
        "signing-bytes" if args.len() == 4 => {
            let envelope: QualificationEvidenceEnvelope = read_json(Path::new(&args[2]))?;
            let bytes = envelope.signing_bytes().map_err(|error| error.to_string())?;
            write_new(Path::new(&args[3]), &bytes)?;
            Ok(())
        }
        "admit" if args.len() == 8 => {
            let sqlite = sqlite_config(&args[2])?;
            let policy: EvidenceTrustPolicy = read_json(Path::new(&args[3]))?;
            let envelope: QualificationEvidenceEnvelope = read_json(Path::new(&args[4]))?;
            let proof: EvidenceIssuerProof = read_json(Path::new(&args[5]))?;
            let previous: EvidenceCheckpoint = read_json(Path::new(&args[6]))?;
            let store = HeptaEvidenceStore::open_with_checkpoint(&sqlite, &previous)
                .await
                .map_err(|error| error.to_string())?;
            let issuer = store
                .qualification()
                .authenticate_issuer(&policy, &envelope, &proof)
                .map_err(|error| error.to_string())?;
            let disposition = store
                .qualification()
                .append_receipt(&envelope, &issuer)
                .await
                .map_err(|error| error.to_string())?;
            let next = store
                .qualification()
                .export_checkpoint()
                .await
                .map_err(|error| error.to_string())?;
            write_new(
                Path::new(&args[7]),
                &next.canonical_bytes().map_err(|error| error.to_string())?,
            )?;
            print_json(&WriterResult {
                disposition: match disposition {
                    codex_hepta_evidence::AppendDisposition::Inserted => "inserted",
                    codex_hepta_evidence::AppendDisposition::AlreadyPresent => "already_present",
                },
                checkpoint: next,
            })
        }
        "prepare-independent" if args.len() == 8 => {
            let sqlite = sqlite_config(&args[2])?;
            let policy: EvidenceTrustPolicy = read_json(Path::new(&args[3]))?;
            let input: IndependentDecisionInput = read_json(Path::new(&args[4]))?;
            let checkpoint: EvidenceCheckpoint = read_json(Path::new(&args[5]))?;
            let store = HeptaEvidenceStore::open_existing_read_only_with_checkpoint(
                &sqlite,
                &checkpoint,
            )
            .await
            .map_err(|error| error.to_string())?;
            let prepared = store
                .qualification()
                .prepare_independent_decision(input, &policy)
                .map_err(|error| error.to_string())?;
            write_new(
                Path::new(&args[6]),
                &prepared
                    .canonical_bytes()
                    .map_err(|error| error.to_string())?,
            )?;
            write_new(
                Path::new(&args[7]),
                &prepared.signing_bytes().map_err(|error| error.to_string())?,
            )?;
            print_json(&prepared)
        }
        "append-independent" if args.len() == 9 => {
            let sqlite = sqlite_config(&args[2])?;
            let policy: EvidenceTrustPolicy = read_json(Path::new(&args[3]))?;
            let prepared: PreparedIndependentDecision = read_json(Path::new(&args[4]))?;
            let proof: EvidenceIssuerProof = read_json(Path::new(&args[5]))?;
            let previous: EvidenceCheckpoint = read_json(Path::new(&args[6]))?;
            let store = HeptaEvidenceStore::open_with_checkpoint(&sqlite, &previous)
                .await
                .map_err(|error| error.to_string())?;
            let disposition = store
                .qualification()
                .append_prepared_independent_decision(&prepared, &policy, &proof)
                .await
                .map_err(|error| error.to_string())?;
            let next = store
                .qualification()
                .export_checkpoint()
                .await
                .map_err(|error| error.to_string())?;
            write_new(
                Path::new(&args[7]),
                &next.canonical_bytes().map_err(|error| error.to_string())?,
            )?;
            if Path::new(&args[8]).exists() {
                return Err("terminal receipt output already exists".to_string());
            }
            write_new(
                Path::new(&args[8]),
                &canonical_json(&IndependentWriterResult {
                    disposition: match disposition {
                        codex_hepta_evidence::AppendDisposition::Inserted => "inserted",
                        codex_hepta_evidence::AppendDisposition::AlreadyPresent => {
                            "already_present"
                        }
                    },
                    decision_id: prepared.receipt.decision_id.clone(),
                    checkpoint: next.clone(),
                })?,
            )?;
            print_json(&IndependentWriterResult {
                disposition: match disposition {
                    codex_hepta_evidence::AppendDisposition::Inserted => "inserted",
                    codex_hepta_evidence::AppendDisposition::AlreadyPresent => "already_present",
                },
                decision_id: prepared.receipt.decision_id,
                checkpoint: next,
            })
        }
        "verify-checkpoint" if args.len() == 4 => {
            let sqlite = sqlite_config(&args[2])?;
            let checkpoint: EvidenceCheckpoint = read_json(Path::new(&args[3]))?;
            let store =
                HeptaEvidenceStore::open_existing_read_only_with_checkpoint(&sqlite, &checkpoint)
                    .await
                    .map_err(|error| error.to_string())?;
            let current = store
                .qualification()
                .export_checkpoint()
                .await
                .map_err(|error| error.to_string())?;
            print_json(&current)
        }
        _ => Err(USAGE.to_string()),
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct WriterResult {
    disposition: &'static str,
    checkpoint: EvidenceCheckpoint,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct IndependentWriterResult {
    disposition: &'static str,
    decision_id: String,
    checkpoint: EvidenceCheckpoint,
}

fn sqlite_config(value: &str) -> Result<SqliteConfig, String> {
    let path = PathBuf::from(value);
    let absolute = if path.is_absolute() {
        path
    } else {
        std::env::current_dir()
            .map_err(|error| error.to_string())?
            .join(path)
    };
    let home = AbsolutePathBuf::try_from(absolute)
        .map_err(|_| "sqlite home must be an absolute path".to_string())?;
    Ok(SqliteConfig::from_sqlite_home(home))
}

fn read_json<T: DeserializeOwned>(path: &Path) -> Result<T, String> {
    let bytes = std::fs::read(path).map_err(|error| format!("{}: {error}", path.display()))?;
    serde_json::from_slice(&bytes)
        .map_err(|error| format!("invalid JSON {}: {error}", path.display()))
}

fn write_new(path: &Path, bytes: &[u8]) -> Result<(), String> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|error| format!("{}: {error}", path.display()))?;
    file.write_all(bytes)
        .map_err(|error| format!("{}: {error}", path.display()))?;
    file.sync_all()
        .map_err(|error| format!("{}: {error}", path.display()))
}

fn print_json<T: Serialize>(value: &T) -> Result<(), String> {
    println!("{}", String::from_utf8(canonical_json(value)?) .map_err(|error| error.to_string())?);
    Ok(())
}

fn canonical_json<T: Serialize>(value: &T) -> Result<Vec<u8>, String> {
    let mut value = serde_json::to_value(value).map_err(|error| error.to_string())?;
    sort_value(&mut value);
    serde_json::to_vec(&value).map_err(|error| error.to_string())
}

fn sort_value(value: &mut serde_json::Value) {
    match value {
        serde_json::Value::Array(items) => {
            for item in items {
                sort_value(item);
            }
        }
        serde_json::Value::Object(map) => {
            let mut entries = std::mem::take(map).into_iter().collect::<Vec<_>>();
            entries.sort_by(|(left, _), (right, _)| left.cmp(right));
            for (_, item) in &mut entries {
                sort_value(item);
            }
            map.extend(entries);
        }
        _ => {}
    }
}
