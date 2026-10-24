//! Real-model native test composition, using the original inference control
//! and FinalUseAuthority with an explicitly controlled, non-product issuer.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fs;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_agentd::NeuralCognitivePinV1;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_worker_host::model_worker::ResourceGrant;
use codex_hepta_infer_worker_host::native_app_server::TurnStartAuthorityFuture;
use codex_hepta_infer_worker_host::native_app_server::TurnStartAuthorizer;
use codex_hepta_infer_worker_host::smollm_neural_read::SmolLmNeuralReadConfigV1;
use codex_hepta_infer_worker_host::smollm_neural_read::SmolLmNeuralReadPortV1;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde::Deserialize;

use super::ledger_fixture::actions;
use super::ledger_fixture::hash;
use super::ledger_fixture::micros;
use super::ledger_fixture::owner;

pub type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Input {
    pub schema: String,
    pub python: PathBuf,
    pub chain: PathBuf,
    pub materials: PathBuf,
    pub baseline_parent: PathBuf,
    pub baseline_parent_sha256: String,
    pub candidate_parent: PathBuf,
    pub candidate_parent_sha256: String,
    pub output: PathBuf,
}

pub struct Model {
    pub config: SmolLmNeuralReadConfigV1,
    pub pin: NeuralCognitivePinV1,
    pub parameters: Vec<u8>,
    pub parent_sha256: Digest32,
}

pub fn model(
    input: &Input,
    parent_path: &Path,
    expected: &str,
    name: &str,
    dataset: &DatasetSnapshotReceiptV3,
) -> Result<Model> {
    let parent_raw = fs::read(parent_path)?;
    let parent_sha256 = expected.parse()?;
    if parent_raw.len() > 65_536 || Digest32::of_bytes(&parent_raw) != parent_sha256 {
        return Err("retained parent descriptor mismatch".into());
    }
    let parent: serde_json::Value = serde_json::from_slice(&parent_raw)?;
    let directory = PathBuf::from(parent["directory"].as_str().ok_or("parent directory")?);
    if parent["schema"] != "hepta-smollm-parent-material-v1" || !directory.is_absolute() {
        return Err("parent schema/absolute path".into());
    }
    let parameters = fs::read(directory.join("artifact.safetensors"))?;
    let target_contract = fs::read(directory.join("target-contract.json"))?;
    let contract: serde_json::Value = serde_json::from_slice(&target_contract)?;
    let wrapped_adapter = fs::read(directory.join("wrapped-adapter.json"))?;
    let mut source_pins = BTreeMap::new();
    for relative in [
        "formal/pon-nakamoto-v1/llm_adapter_contract.py",
        "scripts/llm_inherited_runtime.py",
        "scripts/llm_neural_read_worker.py",
        "scripts/llm_parent_material.py",
        "scripts/llm_runtime_pilot.py",
        "config/pon/model-family-smollm2-135m-v1.json",
    ] {
        let path = input.chain.join(relative);
        source_pins.insert(path.clone(), Digest32::of_bytes(&fs::read(path)?));
    }
    let family_digest = source_pins[&input
        .chain
        .join("config/pon/model-family-smollm2-135m-v1.json")];
    let config = SmolLmNeuralReadConfigV1 {
        python: input.python.clone(),
        script: input.chain.join("scripts/llm_neural_read_worker.py"),
        materials: input.materials.clone(),
        run_directory: input.output.join(format!("original-{name}-model-session")),
        source_pins,
        target_contract,
        wrapped_adapter,
        contract_digest: parent["contract"]
            .as_str()
            .ok_or("contract digest")?
            .parse()?,
        adapter_digest: parent["adapter"]
            .as_str()
            .ok_or("adapter digest")?
            .parse()?,
        backbone_digest: contract["backbone"]["index_root"]
            .as_str()
            .ok_or("backbone digest")?
            .parse()?,
        tokenizer_digest: contract["tokenizer"]["files_root"]
            .as_str()
            .ok_or("tokenizer digest")?
            .parse()?,
        action_completions: BTreeMap::from([
            (actions()[0].clone(), "no".to_owned()),
            (actions()[1].clone(), "yes".to_owned()),
        ]),
    };
    let pin = NeuralCognitivePinV1 {
        payload_digest: parent["file_sha256"]
            .as_str()
            .ok_or("payload digest")?
            .parse()?,
        // This is the frozen comparison dataset context, not a declaration
        // that these weights trained on this nuisance-estimator calibration.
        objective_digest: dataset.snapshot.objective_digest,
        dataset_digest: dataset.snapshot.dataset_digest,
        generation: Generation::new(parent["generation"].as_u64().ok_or("generation")?)?,
        family_digest,
        execution_profile_digest: config.execution_profile_digest()?,
    };
    if parameters.is_empty()
        || parameters.len() > 2 * 1024 * 1024
        || Digest32::of_bytes(&parameters) != pin.payload_digest
    {
        return Err("actual parameter bytes differ from retained parent".into());
    }
    Ok(Model {
        config,
        pin,
        parameters,
        parent_sha256,
    })
}

pub struct ControlledIssuer {
    authority: FinalUseAuthority,
    signer: SigningKey,
    sequence: AtomicU64,
}

impl ControlledIssuer {
    pub fn open(path: &Path) -> Result<Self> {
        let signer = SigningKey::from_bytes(&[91; 32]);
        let authority = FinalUseAuthority::open_state_dir(
            path,
            "controlled-neural-test-issuer".to_owned(),
            signer.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 9,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )?;
        Ok(Self {
            authority,
            signer,
            sequence: AtomicU64::new(1),
        })
    }

    pub fn claims(&self) -> u64 {
        self.sequence.load(Ordering::SeqCst) - 1
    }
}

impl TurnStartAuthorizer for ControlledIssuer {
    fn claim<'a>(&'a self, binding: FinalUseBinding) -> TurnStartAuthorityFuture<'a> {
        Box::pin(async move {
            let sequence = self.sequence.fetch_add(1, Ordering::SeqCst);
            let now = micros() / 1000;
            let grant = FinalUseGrant {
                schema_version: 1,
                signer_id: "controlled-neural-test-issuer".to_owned(),
                authority_epoch: 9,
                grant_id: format!("controlled-comparison-use-{sequence}"),
                nonce: Digest32::of_parts(&[
                    b"controlled-comparison-nonce",
                    &sequence.to_be_bytes(),
                ])
                .into_array(),
                binding: binding.clone(),
                not_before_unix_ms: now.saturating_sub(1000),
                expires_at_unix_ms: now + 180_000,
            };
            let signature = self
                .signer
                .sign(&grant.signing_bytes()?)
                .to_bytes()
                .to_vec();
            Ok(self
                .authority
                .claim(&SignedFinalUseGrant { grant, signature }, &binding)?)
        })
    }
}

pub fn start(
    model: Model,
    name: &str,
    control: Arc<Mutex<DurableInferenceControl>>,
    issuer: Arc<ControlledIssuer>,
    runtime: &tokio::runtime::Runtime,
) -> Result<Arc<SmolLmNeuralReadPortV1>> {
    let grant = ResourceGrant {
        grant_id: format!("controlled-{name}-resource"),
        authority_epoch: 9,
        generation: 1,
        expires_at_ms: micros() / 1000 + 900_000,
        revoked: false,
        maximum_models: 1,
        maximum_active_requests: 1,
        maximum_memory_bytes: 8 * 1024 * 1024 * 1024,
        semantic_digest: hash("controlled-neural-resource-semantics").to_string(),
    };
    Ok(Arc::new(SmolLmNeuralReadPortV1::start(
        model.config,
        model.pin,
        model.parameters,
        owner(),
        /*body_generation*/ 1,
        format!("controlled-{name}-worker"),
        grant,
        control,
        issuer,
        runtime.handle().clone(),
    )?))
}
