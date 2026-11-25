//! Original-owner boundary tests. The private signing key below is a controlled
//! test issuer, never a product issuer or independent model qualification.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fs;
use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::AtomicBool;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::*;
use crate::native_app_server::TurnStartAuthorityFuture;

struct TestIssuer {
    authority: FinalUseAuthority,
    signer: SigningKey,
    denied: AtomicBool,
    bindings: Mutex<Vec<FinalUseBinding>>,
    sequence: AtomicU64,
}

impl TestIssuer {
    fn open(directory: &Path) -> Self {
        let signer = SigningKey::from_bytes(&[91; 32]);
        let authority = FinalUseAuthority::open_state_dir(
            directory,
            "controlled-neural-test-issuer".to_owned(),
            signer.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 9,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )
        .unwrap();
        Self {
            authority,
            signer,
            denied: AtomicBool::new(false),
            bindings: Mutex::new(Vec::new()),
            sequence: AtomicU64::new(1),
        }
    }
}

impl TurnStartAuthorizer for TestIssuer {
    fn claim<'a>(&'a self, binding: FinalUseBinding) -> TurnStartAuthorityFuture<'a> {
        Box::pin(async move {
            self.bindings
                .lock()
                .map_err(|_| "controlled issuer poisoned")?
                .push(binding.clone());
            if self.denied.load(Ordering::SeqCst) {
                return Err("controlled original-authority denial".into());
            }
            let sequence = self.sequence.fetch_add(1, Ordering::SeqCst);
            let now = now_ms()?;
            let grant = FinalUseGrant {
                schema_version: 1,
                signer_id: "controlled-neural-test-issuer".to_owned(),
                authority_epoch: 9,
                grant_id: format!("controlled-neural-use-{sequence}"),
                nonce: Digest32::of_parts(&[b"controlled-neural-nonce", &sequence.to_be_bytes()])
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

fn owner() -> AgentId {
    AgentId::parse("00000000-0000-4000-8000-000000000219").unwrap()
}

fn grant() -> ResourceGrant {
    ResourceGrant {
        grant_id: "controlled-neural-resource".to_owned(),
        authority_epoch: 9,
        generation: 1,
        expires_at_ms: now_ms().unwrap() + 900_000,
        revoked: false,
        maximum_models: 1,
        maximum_active_requests: 1,
        maximum_memory_bytes: 8 * 1024 * 1024 * 1024,
        semantic_digest: Digest32::of_bytes(b"controlled-neural-resource-semantics").to_string(),
    }
}

fn runtime() -> tokio::runtime::Runtime {
    tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()
        .unwrap()
}

#[test]
fn original_control_and_final_use_bind_resource_epoch_owner_and_body_on_reopen() {
    let directory = tempfile::tempdir().unwrap();
    let runtime = runtime();
    let issuer = Arc::new(TestIssuer::open(&directory.path().join("authority")));
    let path = directory.path().join("inference.control");
    let control = Arc::new(Mutex::new(DurableInferenceControl::open(&path, 8).unwrap()));
    let mut context = ControlContext {
        control: control.clone(),
        authorizer: issuer.clone(),
        runtime: runtime.handle().clone(),
        owner_id: owner(),
        body_generation: 1,
        worker_id: "controlled-neural-worker".to_owned(),
        grant: grant(),
        model_digest: Digest32::of_bytes(b"model").to_string(),
    };
    let payload = Digest32::of_bytes(b"actual-request-binding-fixture");
    let scope = Digest32::of_bytes(b"registered-execution-profile-fixture");
    let first = context.admit(payload, 2000).unwrap();
    let entered = context.enter(&first, scope).unwrap();
    assert!(entered.matches(&issuer.bindings.lock().unwrap()[0]));
    drop(entered);
    context
        .settle(
            &first,
            Some(Digest32::of_bytes(b"controlled-terminal-output")),
            true,
            1,
        )
        .unwrap();
    context.grant.authority_epoch += 1;
    let second = context.admit(payload, 2000).unwrap();
    let entered = context.enter(&second, scope).unwrap();
    drop(entered);
    {
        let bindings = issuer.bindings.lock().unwrap();
        assert_ne!(bindings[0].scope_sha256, bindings[1].scope_sha256);
    }
    context.settle(&second, None, true, 0).unwrap();
    context.body_generation += 1;
    let third = context.admit(payload, 2000).unwrap();
    drop(context.enter(&third, scope).unwrap());
    context.settle(&third, None, true, 0).unwrap();
    context.owner_id = AgentId::parse("00000000-0000-4000-8000-000000000220").unwrap();
    let fourth = context.admit(payload, 2000).unwrap();
    drop(context.enter(&fourth, scope).unwrap());
    context.settle(&fourth, None, true, 0).unwrap();
    {
        let bindings = issuer.bindings.lock().unwrap();
        assert_eq!(bindings.len(), 4);
        assert!(
            bindings
                .windows(2)
                .all(|pair| pair[0].scope_sha256 != pair[1].scope_sha256)
        );
        assert_eq!(bindings[0].subject_id, owner().as_str());
        assert_eq!(bindings[3].subject_id, context.owner_id.as_str());
    }
    let third_before = control
        .lock()
        .unwrap()
        .get(&third.request_id)
        .unwrap()
        .clone();
    let fourth_before = control
        .lock()
        .unwrap()
        .get(&fourth.request_id)
        .unwrap()
        .clone();
    let first_before = control
        .lock()
        .unwrap()
        .get(&first.request_id)
        .unwrap()
        .clone();
    let second_before = control
        .lock()
        .unwrap()
        .get(&second.request_id)
        .unwrap()
        .clone();
    assert_eq!(
        (first_before.state, second_before.state),
        (RequestState::Completed, RequestState::Failed)
    );
    drop(context);
    drop(control);
    let reopened = DurableInferenceControl::open(path, 8).unwrap();
    assert_eq!(reopened.get(&first.request_id), Some(&first_before));
    assert_eq!(reopened.get(&second.request_id), Some(&second_before));
    assert_eq!(reopened.get(&third.request_id), Some(&third_before));
    assert_eq!(reopened.get(&fourth.request_id), Some(&fourth_before));
}

#[test]
fn original_final_use_denial_prevents_even_starting_the_model_process() {
    let directory = tempfile::tempdir().unwrap();
    let root = directory.path();
    let runtime = runtime();
    let issuer = Arc::new(TestIssuer::open(&root.join("authority")));
    issuer.denied.store(true, Ordering::SeqCst);
    let source_pins = [
        "llm_adapter_contract.py",
        "llm_inherited_runtime.py",
        "llm_neural_read_worker.py",
        "llm_parent_material.py",
        "llm_runtime_pilot.py",
        "model-family-smollm2-135m-v1.json",
    ]
    .into_iter()
    .map(|name| {
        (
            root.join(name),
            Digest32::of_bytes(b"explicit nonexecutable source fixture"),
        )
    })
    .collect();
    let config = SmolLmNeuralReadConfigV1 {
        python: root.join("must-not-execute"),
        script: root.join("llm_neural_read_worker.py"),
        materials: root.join("absent-model"),
        run_directory: root.join("must-not-create-model-session"),
        source_pins,
        target_contract: b"controlled sidecar fixture".to_vec(),
        wrapped_adapter: b"controlled wrapper fixture".to_vec(),
        contract_digest: Digest32::of_bytes(b"contract"),
        adapter_digest: Digest32::of_bytes(b"adapter"),
        backbone_digest: Digest32::of_bytes(b"backbone"),
        tokenizer_digest: Digest32::of_bytes(b"tokenizer"),
        action_completions: BTreeMap::from([(StableId::new("action").unwrap(), "yes".to_owned())]),
    };
    let parameters = b"EXPLICIT CONTROLLED BOUNDARY FIXTURE, NOT MODEL WEIGHTS".to_vec();
    let pin = NeuralCognitivePinV1 {
        payload_digest: Digest32::of_bytes(&parameters),
        objective_digest: Digest32::of_bytes(b"objective"),
        dataset_digest: Digest32::of_bytes(b"dataset"),
        generation: Generation::new(1).unwrap(),
        family_digest: Digest32::of_bytes(b"family"),
        execution_profile_digest: config.execution_profile_digest().unwrap(),
    };
    let control = Arc::new(Mutex::new(
        DurableInferenceControl::open(root.join("inference.control"), 8).unwrap(),
    ));
    let result = SmolLmNeuralReadPortV1::start(
        config,
        pin,
        parameters,
        owner(),
        /*body_generation*/ 1,
        "controlled-neural-worker".to_owned(),
        grant(),
        control.clone(),
        issuer.clone(),
        runtime.handle().clone(),
    );
    assert!(
        matches!(result, Err(ref error) if error.contains("controlled original-authority denial"))
    );
    assert!(!root.join("must-not-create-model-session").exists());
    assert_eq!(issuer.bindings.lock().unwrap().len(), 1);
    let journal = fs::read_to_string(control.lock().unwrap().journal_path()).unwrap();
    let request_id = journal
        .lines()
        .find_map(|line| line.strip_prefix("submit|"))
        .unwrap()
        .split('|')
        .next()
        .unwrap();
    assert_eq!(
        control.lock().unwrap().get(request_id).unwrap().state,
        RequestState::Failed
    );
}

#[path = "smollm_neural_native_tests.rs"]
mod native;
