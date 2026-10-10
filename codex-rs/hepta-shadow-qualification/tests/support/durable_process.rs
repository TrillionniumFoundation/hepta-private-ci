//! Native process boundary for deterministic C1 engineering qualification.
//! The parent is a fixture selector/witness, never a product identity authority.

use std::fs::File;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;

use codex_hepta_learning_artifacts::ArtifactManifest;
use codex_hepta_learning_artifacts::RegistrySnapshotReceipt;
use codex_hepta_learning_artifacts::read_candidate_payload;
use codex_hepta_learning_artifacts::read_registry_snapshot;
use codex_hepta_learning_ledger::LearningLedger;
use codex_hepta_learning_ledger::LedgerAnchor;
use codex_hepta_learning_ledger::inspect_ledger;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

const REQUEST_ENV: &str = "HEPTA_C1_PROCESS_FIXTURE_REQUEST";
const RECEIPT_PREFIX: &str = "HEPTA_C1_PROCESS_RECEIPT=";

#[derive(Clone, Debug, Deserialize, Serialize)]
pub enum Request {
    Train {
        journal: PathBuf,
        binding: String,
        sequence: u64,
        head: String,
    },
    Load {
        generation: u64,
        selection: LoadRequest,
    },
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct LoadRequest {
    pub registry: PathBuf,
    pub payload: PathBuf,
    binding: String,
    registry_head: String,
    registry_file: String,
    registry_records: usize,
    registry_bytes: usize,
    artifact_id: String,
    artifact_generation: u64,
    content: String,
    pub objective: String,
    pub compatibility: String,
}

impl LoadRequest {
    pub fn new(
        registry: &Path,
        witness: RegistrySnapshotReceipt,
        payload: &Path,
        selected: &ArtifactManifest,
    ) -> Self {
        let mut request = Self {
            registry: registry.to_path_buf(),
            payload: payload.to_path_buf(),
            binding: String::new(),
            registry_head: String::new(),
            registry_file: String::new(),
            registry_records: 0,
            registry_bytes: 0,
            artifact_id: selected.artifact_id.to_string(),
            artifact_generation: selected.generation.get(),
            content: selected.content_digest.to_string(),
            objective: selected.objective_digest.to_string(),
            compatibility: selected.compatibility_digest.to_string(),
        };
        request.set_witness(witness);
        request
    }

    pub fn set_witness(&mut self, witness: RegistrySnapshotReceipt) {
        self.binding = witness.binding.to_string();
        self.registry_head = witness.head_digest.to_string();
        self.registry_file = witness.file_digest.to_string();
        self.registry_records = witness.records;
        self.registry_bytes = witness.encoded_bytes;
    }
}

#[derive(Debug, Deserialize, Serialize)]
pub struct Receipt {
    mode: String,
    process_id: u32,
    pub generation: u64,
    executable_digest: String,
    configuration_digest: String,
    pub result: ResultValue,
}

#[derive(Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum ResultValue {
    Trained {
        policy: String,
        ledger_head: String,
    },
    Loaded {
        artifact_id: String,
        artifact_generation: u64,
        content: String,
        objective: String,
        compatibility: String,
        registry_head: String,
        legal_candidates_digest: String,
        ordering: Vec<String>,
    },
    Rejected(String),
}

fn executable_digest(path: &Path) -> String {
    let Ok(mut file) = File::open(path) else {
        panic!("test executable must be readable");
    };
    let mut hasher = Sha256::new();
    let mut buffer = [0; 64 * 1024];
    loop {
        let Ok(read) = file.read(&mut buffer) else {
            panic!("test executable hash input must be readable");
        };
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    Digest32::from_array(hasher.finalize().into()).to_string()
}

pub fn run(request: Request) -> Receipt {
    let Ok(encoded) = serde_json::to_string(&request) else {
        panic!("fixture request must serialize");
    };
    assert!(encoded.len() <= 16 * 1024);
    let Ok(executable) = std::env::current_exe() else {
        panic!("native test executable must be available");
    };
    // Exec the native test target itself: no Cargo paths or runfile assumptions,
    // no inherited in-memory registry, and no mutation of the parent environment.
    let Ok(child) = Command::new(&executable)
        .args([
            "--exact",
            "process::worker",
            "--ignored",
            "--nocapture",
            "--test-threads=1",
        ])
        .env(REQUEST_ENV, &encoded)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
    else {
        panic!("native worker must start");
    };
    let process_id = child.id();
    let Ok(output) = child.wait_with_output() else {
        panic!("native worker must exit");
    };
    assert!(output.status.success(), "child failed: {output:?}");
    let Ok(stdout) = String::from_utf8(output.stdout) else {
        panic!("worker output must be UTF-8");
    };
    let receipts: Vec<_> = stdout
        .lines()
        .filter_map(|line| line.split_once(RECEIPT_PREFIX).map(|(_, receipt)| receipt))
        .collect();
    assert_eq!(receipts.len(), 1);
    let Ok(receipt): Result<Receipt, _> = serde_json::from_str(receipts[0]) else {
        panic!("worker must emit a structured receipt");
    };
    assert_eq!(receipt.mode, "reference");
    assert_eq!(receipt.process_id, process_id);
    assert_ne!(receipt.process_id, std::process::id());
    assert_eq!(receipt.executable_digest, executable_digest(&executable));
    assert_eq!(
        receipt.configuration_digest,
        Digest32::of_bytes(encoded.as_bytes()).to_string()
    );
    let Ok(encoded_receipt) = serde_json::to_string(&receipt) else {
        panic!("worker receipt must serialize");
    };
    println!("{RECEIPT_PREFIX}{encoded_receipt}");
    receipt
}

pub fn load(selection: &LoadRequest, generation: u64) -> Receipt {
    run(Request::Load {
        generation,
        selection: selection.clone(),
    })
}

pub fn assert_loaded(receipt: &Receipt, request: &LoadRequest, expected: &[&str]) -> Vec<String> {
    assert_eq!(
        receipt.result,
        ResultValue::Loaded {
            artifact_id: request.artifact_id.clone(),
            artifact_generation: request.artifact_generation,
            content: request.content.clone(),
            objective: request.objective.clone(),
            compatibility: request.compatibility.clone(),
            registry_head: request.registry_head.clone(),
            legal_candidates_digest: Digest32::of_bytes(b"supported-alpha:10|supported-beta:20")
                .to_string(),
            ordering: expected.iter().map(ToString::to_string).collect(),
        }
    );
    match &receipt.result {
        ResultValue::Loaded { ordering, .. } => ordering.clone(),
        other => panic!("expected loaded policy, got {other:?}"),
    }
}

pub fn assert_rejected(receipt: &Receipt, reason: &str) {
    assert_eq!(receipt.result, ResultValue::Rejected(reason.to_owned()));
}

fn load_selected(selection: LoadRequest) -> Result<ResultValue, String> {
    let registry = read_registry_snapshot(
        File::open(&selection.registry).map_err(|error| error.to_string())?,
        RegistrySnapshotReceipt {
            binding: selection.binding.parse().map_err(|_| "invalid_binding")?,
            head_digest: selection
                .registry_head
                .parse()
                .map_err(|_| "invalid_head")?,
            file_digest: selection
                .registry_file
                .parse()
                .map_err(|_| "invalid_file")?,
            records: selection.registry_records,
            encoded_bytes: selection.registry_bytes,
        },
    )
    .map_err(|error| error.to_string())?;
    let artifact = super::id(&selection.artifact_id);
    let manifest = registry.manifest(&artifact).ok_or("unknown_artifact")?;
    if manifest.generation.get() != selection.artifact_generation
        || manifest.content_digest.to_string() != selection.content
        || manifest.objective_digest.to_string() != selection.objective
        || manifest.compatibility_digest.to_string() != selection.compatibility
    {
        return Err("tuple_mismatch".to_owned());
    }
    let bytes = read_candidate_payload(
        File::open(&selection.payload).map_err(|error| error.to_string())?,
        &registry,
        &artifact,
    )
    .map_err(|error| error.to_string())?;
    // These are two fresh, authorized, supported fixture facts. The policy only
    // changes ordering; it cannot make stale, denied or revoked evidence legal.
    let mut candidates = [("supported-alpha", 10_u64), ("supported-beta", 20_u64)];
    let candidate_set = candidates
        .iter()
        .map(|(identifier, updated)| format!("{identifier}:{updated}"))
        .collect::<Vec<_>>()
        .join("|");
    match bytes.as_slice() {
        b"title-order" => candidates.sort_by_key(|(identifier, _)| *identifier),
        b"freshness-order" => {
            candidates.sort_by(|left, right| right.1.cmp(&left.1).then_with(|| left.0.cmp(right.0)))
        }
        _ => return Err("unsupported_policy".to_owned()),
    }
    Ok(ResultValue::Loaded {
        artifact_id: selection.artifact_id,
        artifact_generation: selection.artifact_generation,
        content: Digest32::of_bytes(&bytes).to_string(),
        objective: selection.objective,
        compatibility: selection.compatibility,
        registry_head: selection.registry_head,
        legal_candidates_digest: Digest32::of_bytes(candidate_set.as_bytes()).to_string(),
        ordering: candidates
            .iter()
            .map(|(identifier, _)| (*identifier).to_owned())
            .collect(),
    })
}

#[test]
#[ignore = "worker is executed only by the parent cross-process fixture"]
fn worker() {
    let encoded = std::env::var(REQUEST_ENV).expect("parent request is required");
    assert!(encoded.len() <= 16 * 1024);
    let request: Request = serde_json::from_str(&encoded).unwrap();
    let (generation, result) = match request {
        Request::Train {
            journal,
            binding,
            sequence,
            head,
        } => {
            let inspected = inspect_ledger(
                File::open(journal).unwrap(),
                binding.parse().unwrap(),
                /*max_records*/ 32,
                LedgerAnchor {
                    sequence,
                    chain_digest: head.parse().unwrap(),
                },
            );
            let result = match inspected {
                Ok(snapshot) => {
                    let ledger = LearningLedger::from_snapshot(snapshot).unwrap();
                    let policy = String::from_utf8(super::fit_binary_fixture(&ledger)).unwrap();
                    ResultValue::Trained {
                        policy,
                        ledger_head: head,
                    }
                }
                Err(error) => ResultValue::Rejected(error.to_string()),
            };
            (0, result)
        }
        Request::Load {
            generation,
            selection,
        } => {
            assert!(generation > 0);
            (
                generation,
                load_selected(selection).unwrap_or_else(ResultValue::Rejected),
            )
        }
    };
    let receipt = Receipt {
        mode: "reference".to_owned(),
        process_id: std::process::id(),
        generation,
        executable_digest: executable_digest(
            &std::env::current_exe().expect("native test executable is available"),
        ),
        configuration_digest: Digest32::of_bytes(encoded.as_bytes()).to_string(),
        result,
    };
    println!(
        "{RECEIPT_PREFIX}{}",
        serde_json::to_string(&receipt).expect("worker receipt serializes")
    );
}
