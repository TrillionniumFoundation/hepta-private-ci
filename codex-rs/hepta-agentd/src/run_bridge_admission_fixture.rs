use super::*;
use crate::lane_b_runtime::{ContextAttachment, DurableAgentRunCoordinator, RunSnapshot};
use codex_hepta_contracts::RunBridgeIdentityV1;
use codex_hepta_infer_core::control_contracts::*;
use codex_hepta_infer_core::durable_control::native::{NativeBoundSourceRecordV2, NativeRequest};
use ed25519_dalek::{Signer, SigningKey};
use sha2::{Digest, Sha256};
use std::sync::Mutex;

pub(super) const AGENT: &str = "00000000-0000-4000-8000-000000000001";
pub(super) struct HostState {
    pub keys: Vec<TrustKey>,
    pub now: u64,
    pub generation: u64,
    pub epoch: u64,
    pub revision: u64,
    pub checks: usize,
    pub move_during_check: bool,
    pub rollback_during_check: bool,
    pub available: bool,
    pub configuration: Sha256Digest,
    pub ports: Sha256Digest,
}
pub(super) struct Host(pub Mutex<HostState>);
impl RunBridgeHostCurrentness for Host {
    fn observe(&self) -> Result<RunBridgeHostObservation, RunBridgeAdmissionError> {
        let mut s = self
            .0
            .lock()
            .map_err(|_| RunBridgeAdmissionError::HostUnavailable)?;
        if !s.available {
            return Err(RunBridgeAdmissionError::HostUnavailable);
        }
        s.checks += 1;
        Ok(RunBridgeHostObservation {
            trust: ControlTrustStore::new(s.keys.clone())
                .map_err(|_| RunBridgeAdmissionError::HostUnavailable)?,
            trust_revision: s.revision,
            now_unix_ms: s.now - u64::from(s.rollback_during_check && s.checks >= 2),
            agent_id: AgentId::parse(AGENT)
                .map_err(|_| RunBridgeAdmissionError::HostUnavailable)?,
            spawn_generation: 7,
            current_generation: s.generation + u64::from(s.move_during_check && s.checks >= 2),
            authority_epoch: s.epoch,
            configuration_sha256: s.configuration.clone(),
            ports_sha256: s.ports.clone(),
        })
    }
}

pub(super) struct Fixture {
    pub dir: tempfile::TempDir,
    pub owner: DurableAgentRunCoordinator,
    pub current: Arc<Host>,
    pub host: RunBridgeAdmissionHost,
    pub signed: SignedExecutionAuthorityBundle,
    pub proof: NativeBoundSourceProof,
    pub binding: RunBridgeBindingV1,
}

pub(super) fn fixture() -> Result<Fixture, Box<dyn std::error::Error>> {
    let dir = tempfile::tempdir()?;
    let composition = RuntimeComposition {
        agent_id: AGENT.into(),
        supervisor_generation: 7,
        agentd_generation: 7,
        configuration_digest: "1".repeat(64),
        ports_digest: "2".repeat(64),
        max_active_runs: 4,
    };
    let mut owner = DurableAgentRunCoordinator::open(composition, dir.path().join("runs.json"))
        .map_err(|e| format!("{e:?}"))?;
    let mut material = b"hepta:agentd:objective-fence:v1\0".to_vec();
    material.extend_from_slice(AGENT.as_bytes());
    material.extend_from_slice(&7_u64.to_be_bytes());
    material.extend_from_slice(&8_u64.to_be_bytes());
    let fence = Sha256Digest::for_bytes(&material);
    let snapshot = RunSnapshot {
        run_id: "bridge-run".into(),
        request_digest: "3".repeat(64),
        objective_digest: "4".repeat(64),
        body_digest: "5".repeat(64),
        artifact_set_digest: "6".repeat(64),
        authority_epoch: 3,
        generation: 8,
        fence_digest: fence.as_str().into(),
        deadline_ms: 60_000,
    };
    owner
        .start_run(10, snapshot.clone())
        .map_err(|e| format!("{e:?}"))?;
    owner
        .attach_context(
            20,
            1,
            ContextAttachment {
                run_id: snapshot.run_id.clone(),
                request_digest: snapshot.request_digest,
                objective_digest: snapshot.objective_digest,
                body_digest: snapshot.body_digest,
                artifact_set_digest: snapshot.artifact_set_digest,
                authority_epoch: 3,
                generation: 8,
                fence_digest: snapshot.fence_digest,
                deadline_ms: 60_000,
                context_digest: "8".repeat(64),
                compilation_receipt_digest: "9".repeat(64),
            },
        )
        .map_err(|e| format!("{e:?}"))?;
    let socket = dir.path().join("agent.sock");
    let payload = format!(
        "{:x}",
        Sha256::digest(serde_json::to_vec(&(
            "hepta.native-intelligence-request.v2",
            "prompt",
            None::<String>,
            &socket,
            1000_u128,
            "bridge-run",
            2_u64,
            "8".repeat(64),
            "9".repeat(64)
        ))?)
    );
    let request = NativeRequest {
        request_id: "source-request".into(),
        principal_id: AGENT.into(),
        worker_generation: 7,
        model: "model".into(),
        payload_digest: payload.clone(),
    };
    let proof = NativeBoundSourceProof::verify(
        &request,
        "prompt",
        &None,
        &socket,
        1000,
        NativeBoundSourceRecordV2 {
            schema_version: 2,
            request_id: request.request_id.clone(),
            request_payload_sha256: payload.clone(),
            run_id: "bridge-run".into(),
            owner_pre_dispatch_revision: 2,
            context_sha256: "8".repeat(64),
            envelope_sha256: "9".repeat(64),
        },
    )?;
    let manifest: ExecutionManifest = serde_json::from_value(serde_json::json!({
        "schema_version":1,"manifest_id":"manifest","issuer_id":"manifest-authority","authority_epoch":3,
        "provider_id":"provider","model_id":"model","model_revision":"revision","model_digest":"1".repeat(64),
        "tokenizer_id":"tokenizer","tokenizer_version":"v1","tokenizer_digest":"2".repeat(64),
        "template_id":"template","template_digest":"3".repeat(64),"runtime_abi":"runtime.v1","runtime_digest":"4".repeat(64),
        "adapter_abi":"adapter.v1","adapter_digest":"5".repeat(64),"payload_digest":payload,"policy_digest":"7".repeat(64)
    }))?;
    let bytes = serde_json::to_vec(&manifest)?;
    let mut hash = Sha256::new();
    hash.update(b"hepta.inference-control.manifest.v1\0");
    hash.update((bytes.len() as u64).to_be_bytes());
    hash.update(bytes);
    let manifest_digest = format!("{:x}", hash.finalize());
    let bundle = ExecutionAuthorityBundle {
        schema_version: 1,
        request_id: request.request_id.clone(),
        principal_id: AGENT.into(),
        manifest,
        quota_lease: QuotaLease {
            schema_version: 1,
            lease_id: "quota".into(),
            authority_id: "quota-authority".into(),
            authority_epoch: 3,
            request_id: request.request_id.clone(),
            principal_id: AGENT.into(),
            manifest_digest: manifest_digest.clone(),
            maximum_input_tokens: 100,
            maximum_output_tokens: 200,
            maximum_cost_microunits: 50_000,
            valid_from_unix_ms: 50,
            valid_until_unix_ms: 50_000,
        },
        resource_lease: ResourceLease {
            schema_version: 1,
            lease_id: "resource".into(),
            authority_id: "resource-authority".into(),
            authority_epoch: 3,
            request_id: request.request_id,
            worker_id: "worker".into(),
            worker_generation: 7,
            manifest_digest,
            cpu_millis: 1000,
            memory_bytes: 1024 * 1024,
            accelerator_count: 0,
            accelerator_profile_digest: "a".repeat(64),
            valid_from_unix_ms: 50,
            valid_until_unix_ms: 50_000,
        },
        output_policy: OutputDataPolicy {
            schema_version: 1,
            policy_id: "policy".into(),
            authority_id: "data-authority".into(),
            authority_epoch: 3,
            classification: OutputClassification::Internal,
            storage_mode: OutputStorageMode::DigestOnly,
            maximum_retention_ms: 50_000,
            delete_after_unix_ms: 50_000,
            encryption_key_id: None,
            encrypted_store_namespace: None,
        },
    };
    let message = bundle.signing_bytes()?;
    let mut keys = Vec::new();
    let mut signatures = Vec::new();
    for (index, (signer, role)) in [
        ("manifest-authority", TrustRole::ManifestAuthority),
        ("quota-authority", TrustRole::QuotaAuthority),
        ("resource-authority", TrustRole::ResourceAuthority),
        ("data-authority", TrustRole::DataAuthority),
    ]
    .into_iter()
    .enumerate()
    {
        let key = SigningKey::from_bytes(&[(index + 1) as u8; 32]);
        let key_id = format!("key-{index}");
        keys.push(TrustKey {
            key_id: key_id.clone(),
            signer_id: signer.into(),
            role,
            verifying_key: key.verifying_key().to_bytes(),
            not_before_authority_epoch: 1,
            not_after_authority_epoch: 9,
            revoked_at_authority_epoch: None,
        });
        signatures.push(ControlSignature {
            key_id,
            signer_id: signer.into(),
            signature: key.sign(&message).to_bytes().to_vec(),
        });
    }
    let signed = SignedExecutionAuthorityBundle { bundle, signatures };
    let plan = verify_execution_plan(100, &ControlTrustStore::new(keys.clone())?, &signed)?;
    let identity = RunBridgeIdentityV1 {
        schema_version: 1,
        agent_id: AgentId::parse(AGENT)?,
        run_id: "bridge-run".into(),
        request_id: "source-request".into(),
        owner_generation: 8,
        owner_dispatch_revision: 3,
        source_dispatch_revision: 2,
        fence_sha256: fence,
        context_sha256: Sha256Digest::parse("8".repeat(64))?,
        envelope_sha256: Sha256Digest::parse("9".repeat(64))?,
        execution_binding_sha256: Sha256Digest::parse(plan.execution_binding_digest())?,
        dispatch_sha256: Sha256Digest::for_bytes(b"pending dispatch observation"),
    };
    let binding = RunBridgeBindingV1 {
        abort_commitment_sha256: RunBridgeBindingV1::abort_commitment(&identity, &[7; 32])?,
        identity,
    };
    let current = Arc::new(Host(Mutex::new(HostState {
        keys,
        now: 100,
        generation: 8,
        epoch: 3,
        revision: 1,
        checks: 0,
        move_during_check: false,
        rollback_during_check: false,
        available: true,
        configuration: Sha256Digest::parse("1".repeat(64))?,
        ports: Sha256Digest::parse("2".repeat(64))?,
    })));
    let host = RunBridgeAdmissionHost::new(current.clone());
    Ok(Fixture {
        dir,
        owner,
        current,
        host,
        signed,
        proof,
        binding,
    })
}
