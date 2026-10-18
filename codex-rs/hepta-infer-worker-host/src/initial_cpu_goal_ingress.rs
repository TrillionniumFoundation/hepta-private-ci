//! Fixed Root signing and ordinary workload delivery of a conservative CPU Goal.
//! The original compiler, current E/S/CURRENT readers, seven owners, resource
//! owner and AuthBus remain the authorities. These routes create no RunStart.
use super::*;
use codex_hepta_agentd::AgentdDurableCpuAbstainInvocationProviderV2;
use codex_hepta_agentd::AuthBusObjectiveBody;
use codex_hepta_agentd::AuthBusObjectiveIngress;
use codex_hepta_agentd::ConservativeCpuStateV1;
use codex_hepta_agentd::IntelligenceAuthorityVerifierV1;
use ed25519_dalek::Signer;
use serde::Serialize;
use std::path::PathBuf;

#[path = "initial_cpu_goal_transport.rs"]
mod transport;

const ADAPTER: &str = "root.readonly-public-facts";
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Configuration {
    schema: String,
    program: Source,
    signer: Role,
    fleet_root: PathBuf,
    local_host_policy: Source,
    fleetctl: Source,
    worker_program: Source,
    installed_composition: Source,
    goal: Source,
    agent_id: String,
    spawn_generation: u64,
    process_id: u32,
    run_id: String,
    message_id: String,
    sequence: u64,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Packet {
    schema: String,
    configuration: Source,
    agent_id: String,
    process_id: u32,
    goal_preview: Value,
    state_mode: codex_hepta_agentd::ConservativeCpuStateModeV1,
    ingress: AuthBusObjectiveIngress,
}

pub(super) fn sign(path: &Path, pin: Digest32) -> HostResult<Value> {
    let source = Source {
        path: path.to_owned(),
        digest: pin.to_string(),
    };
    let bytes = source.read(32 * 1024)?;
    let cfg: Configuration = serde_json::from_slice(&bytes)?;
    if cfg.schema != "hepta.cpu-neuron.root-objective-ingress-config.v1"
        || cfg.signer.id != ADAPTER
        || cfg.signer.uid != 0
        || cfg.signer.gid != 0
        || cfg.sequence == 0
        || cfg.spawn_generation == 0
        || cfg.process_id == 0
    {
        return Err("closed conservative objective signer configuration".into());
    }
    let key = role::actual_role_for_program(&cfg.program, &cfg.signer)?;
    // Neither the selected PID nor the program hash is evidence on its own.
    // The original read-only owner verifies its current row and native tuple.
    let before = transport::observe(&cfg)?;
    let installed_bytes = cfg.installed_composition.read(32 * 1024)?;
    let installed: installed_plan::Installed = serde_json::from_slice(&installed_bytes)?;
    if installed.agent_id != cfg.agent_id {
        return Err("objective subject differs from installed composition".into());
    }
    let pointer = installed
        .model_use_pointer
        .as_ref()
        .ok_or("stable model-use pointer required")?;
    let current = model_use_current::inspect_current(pointer)?;
    if cfg.worker_program != current.worker_program()? {
        return Err("running program differs from the opaque installed E/S body closure".into());
    }
    let body: Value = serde_json::from_slice(&installed.compiled_body.read(32 * 1024)?)?;
    if body["runtime_body_digest"].as_str()
        != Some(current.runtime_body_digest().to_string().as_str())
    {
        return Err("composition body differs from the opaque installed model use".into());
    }
    let state = ConservativeCpuStateV1::from_current_payloads(
        id(&cfg.agent_id)?,
        current.current_payload_digests()?,
    )?;
    let provider = AgentdDurableCpuAbstainInvocationProviderV2::new(
        installed.authority_file.clone(),
        IntelligenceAuthorityVerifierV1 {
            signer_id: installed.authority_signer_id.clone(),
            verifying_key: public(&installed.authority_verifying_key_hex)?,
        },
        current.native_configuration().clone(),
        current.runtime_configuration().semantic_digest()?,
        current.runtime_body_digest(),
    )?
    .with_inactive_state(state);
    let binding = provider.current_goal_bindings(current.current_authority_epoch()?)?;
    let preview = goal::preview(&cfg.goal.path, digest(&cfg.goal.digest)?)?;
    if preview["adapter_identity"] != ADAPTER {
        return Err("conservative objective adapter differs from registered signer".into());
    }
    let envelope: Source = serde_json::from_value(preview["source_envelope"].clone())?;
    let envelope_bytes = envelope.read(32 * 1024)?;
    let expires = preview["deadline_unix_micros"]
        .as_u64()
        .ok_or("objective deadline")?
        .div_ceil(1_000)
        .min(current.expires_at())
        .min(now_ms()?.saturating_add(300_000));
    let body = AuthBusObjectiveBody {
        spawn_generation: cfg.spawn_generation,
        run_id: id(&cfg.run_id)?.to_string(),
        objective_revision: preview["objective_revision"]
            .as_u64()
            .ok_or("objective revision")?,
        source_envelope_json: std::str::from_utf8(&envelope_bytes)?.to_owned(),
        runtime_body_digest: binding.runtime_body_digest.to_string(),
        preference_state_digest: binding.state.preference_state_digest().to_string(),
        model_tuple_digest: binding.model_tuple_digest.to_string(),
        prompt_registry_digest: binding.state.prompt_registry_digest().to_string(),
        artifact_set_digest: binding.state.artifact_set_digest().to_string(),
        authority_epoch: binding.authority_epoch,
    };
    let mut ingress = AuthBusObjectiveIngress {
        issuer_id: ADAPTER.into(),
        key_epoch: 1,
        message_id: cfg.message_id.clone(),
        sequence: cfg.sequence,
        expires_at_ms: expires,
        signature_hex: String::new(),
        body,
    };
    let claims =
        codex_hepta_agentd::objective_ingress_signing_claims_v1(&cfg.agent_id.parse()?, &ingress)?;
    current.revalidate_current()?;
    if cfg.installed_composition.read(32 * 1024)? != installed_bytes
        || source.read(32 * 1024)? != bytes
        || envelope.read(32 * 1024)? != envelope_bytes
        || transport::observe(&cfg)? != before
        || expires <= now_ms()?
    {
        return Err("current objective inputs changed or expired during signing".into());
    }
    ingress.signature_hex = key
        .sign(&claims.signing_bytes())
        .to_bytes()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    let packet = Packet {
        schema: "hepta.cpu-neuron.root-signed-objective-packet.v1".into(),
        configuration: source,
        agent_id: cfg.agent_id,
        process_id: cfg.process_id,
        goal_preview: preview,
        state_mode: binding.state.mode(),
        ingress,
    };
    Ok(serde_json::to_value(packet)?)
}

pub(super) async fn deliver(path: &Path, pin: Digest32) -> HostResult<Value> {
    transport::deliver(path, pin).await
}

pub(super) async fn inspect(path: &Path, pin: Digest32) -> HostResult<Value> {
    transport::inspect(path, pin).await
}
