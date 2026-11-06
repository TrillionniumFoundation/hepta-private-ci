use super::*;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use serde_json::Value;
use std::path::PathBuf;

const PLAN: &[u8] = include_bytes!("../fixtures/material-runtime-bridge-v1-plan.json");
const TARGET: &[u8] = include_bytes!("../fixtures/material-runtime-bridge-v1-target.json");

fn config() -> SmolLmNeuralReadConfigV1 {
    let names = [
        "contract_wire.py",
        "devnet-v1.json",
        "ledger-v1.json",
        "llm_adapter_contract.py",
        "llm_base_material.py",
        "llm_inherited_runtime.py",
        "llm_neural_read_worker.py",
        "llm_parent_material.py",
        "llm_python_runtime_contract.py",
        "llm_runtime_pilot.py",
        "model-family-smollm2-135m-v1.json",
        "model-family-v1.json",
        "work-profile-v1.json",
    ];
    let root = PathBuf::from("/unexecuted-material-bridge-component");
    let source_pins = names
        .into_iter()
        .map(|name| {
            (
                root.join(name),
                if name == "llm_runtime_pilot.py" {
                    EXECUTION_RUNTIME.parse().unwrap()
                } else {
                    Digest32::of_bytes(name.as_bytes())
                },
            )
        })
        .collect();
    SmolLmNeuralReadConfigV1 {
        python: root.join("python-not-executed"),
        script: root.join("llm_neural_read_worker.py"),
        materials: root.join("no-model"),
        run_directory: root.join("no-created-run"),
        source_pins,
        runtime_snapshot: b"explicit component snapshot bytes, not a qualified runtime".to_vec(),
        material_runtime_bridge: None,
        target_contract: TARGET.to_vec(),
        wrapped_adapter: b"unexecuted wrapper component".to_vec(),
        contract_digest: MATERIAL_CONTRACT.parse().unwrap(),
        adapter_digest: Digest32::of_bytes(b"adapter"),
        backbone_digest: Digest32::of_bytes(b"backbone"),
        tokenizer_digest: Digest32::of_bytes(b"tokenizer"),
        action_completions: BTreeMap::from([(StableId::new("action").unwrap(), "yes".to_owned())]),
    }
}

fn bridge() -> SmolLmMaterialRuntimeBridgeV1 {
    SmolLmMaterialRuntimeBridgeV1::new(PROFILE, PLAN.to_vec()).unwrap()
}

fn ready_value(config: &SmolLmNeuralReadConfigV1) -> Value {
    let mut sources = config.source_identities().unwrap();
    let worker_source = sources.remove("llm_neural_read_worker.py").unwrap();
    serde_json::json!({
        "schema": READY_SCHEMA, "actual_loaded_parent": config.adapter_digest.to_string(),
        "file_sha256": Digest32::of_bytes(b"unexecuted parameter component").to_string(),
        "contract": config.contract_digest.to_string(), "generation": 1,
        "backbone": config.backbone_digest.to_string(), "tokenizer": config.tokenizer_digest.to_string(),
        "source_pins": sources, "worker_source": worker_source,
        "runtime_snapshot_sha256": Digest32::of_bytes(&config.runtime_snapshot).to_string(),
        "actions": config.actions(), "observed_rss_bytes": 1,
        "authority": {"installation_authorized": false, "selection_authorized": false,
            "independent_accepted": false, "prospective_accepted": false,
            "public_reward_eligible": false, "hepta_final_use": false},
        "material_runtime_bridge": BridgeObservation::expected(),
        "runtime_source_set_sha256": Digest32::of_bytes(
            &serde_json::to_vec(&config.source_identities().unwrap()).unwrap()).to_string(),
    })
}

#[test]
fn fixed_pair_constructor_and_wire_keep_all_historical_bytes() {
    let value = bridge();
    assert_eq!(value.plan(), PLAN);
    let raw = serde_json::to_vec(&value).unwrap();
    let decoded: SmolLmMaterialRuntimeBridgeV1 = serde_json::from_slice(&raw).unwrap();
    assert_eq!(decoded.plan(), PLAN);
    for profile in ["legacy", "hepta-smollm-public-initial-v11", ""] {
        assert!(SmolLmMaterialRuntimeBridgeV1::new(profile, PLAN.to_vec()).is_err());
    }
    for plan in [Vec::new(), [PLAN, b" "].concat(), vec![0; 64 * 1024 + 1]] {
        assert!(SmolLmMaterialRuntimeBridgeV1::new(PROFILE, plan).is_err());
    }
    let mut object: Value = serde_json::from_slice(&raw).unwrap();
    object["extra"] = Value::Null;
    assert!(serde_json::from_value::<SmolLmMaterialRuntimeBridgeV1>(object).is_err());
}

#[test]
fn no_bridge_retains_the_exact_original_execution_tuple_and_entry() {
    let config = config();
    // Frozen original V2 tuple: adding bridge fields must not change its bytes.
    let raw = serde_json::to_vec(&(
        "hepta-smollm-runtime-bound-execution-v2",
        super::super::PROFILE,
        config.source_identities().unwrap(),
        config.actions(),
        Digest32::of_bytes(&config.runtime_snapshot).to_string(),
        config.contract_digest.to_string(),
        config.adapter_digest.to_string(),
        Digest32::of_bytes(&config.target_contract).to_string(),
        Digest32::of_bytes(&config.wrapped_adapter).to_string(),
        config.backbone_digest.to_string(),
        config.tokenizer_digest.to_string(),
        4_u32,
    ))
    .unwrap();
    assert_eq!(
        config.execution_profile_digest().unwrap(),
        Digest32::of_bytes(&raw)
    );
    assert_eq!(config.serve_command(), "serve");
    assert_eq!(config.ready_schema(), super::super::SCHEMA);
    assert!(config.bridge_material_plan().is_none());
}

#[test]
fn explicit_bridge_execution_digest_binds_snapshot_and_every_source() {
    let mut config = config();
    let original = config.execution_profile_digest().unwrap();
    config.material_runtime_bridge = Some(bridge());
    let current = config.execution_profile_digest().unwrap();
    assert_ne!(original, current);
    assert_eq!(config.serve_command(), "serve-bridge-v1");
    assert_eq!(config.ready_schema(), READY_SCHEMA);
    let old_snapshot = config.runtime_snapshot.clone();
    config.runtime_snapshot.push(0);
    assert_ne!(config.execution_profile_digest().unwrap(), current);
    config.runtime_snapshot = old_snapshot;
    for (path, old) in config.source_pins.clone() {
        config
            .source_pins
            .insert(path.clone(), Digest32::of_bytes(b"changed-source"));
        if path.file_name().unwrap() == "llm_runtime_pilot.py" {
            assert!(config.execution_profile_digest().is_err());
        } else {
            assert_ne!(config.execution_profile_digest().unwrap(), current);
        }
        config.source_pins.insert(path, old);
    }
    assert_eq!(config.execution_profile_digest().unwrap(), current);
}

#[test]
fn bridge_refuses_any_other_target_contract_or_execution_source() {
    let mut config = config();
    config.material_runtime_bridge = Some(bridge());
    config.target_contract.push(b'\n');
    assert!(config.execution_profile_digest().is_err());
    config.target_contract = TARGET.to_vec();
    config.contract_digest = Digest32::of_bytes(b"other-contract");
    assert!(config.execution_profile_digest().is_err());
    config.contract_digest = MATERIAL_CONTRACT.parse().unwrap();
    let path = config
        .source_pins
        .keys()
        .find(|p| p.file_name().unwrap() == "llm_runtime_pilot.py")
        .unwrap()
        .clone();
    config
        .source_pins
        .insert(path, MATERIAL_RUNTIME.parse().unwrap());
    assert!(config.execution_profile_digest().is_err());
}

#[test]
fn bridge_ready_requires_both_complete_identities_and_all_source_commitments() {
    let mut config = config();
    config.material_runtime_bridge = Some(bridge());
    let original = ready_value(&config);
    assert!(
        config
            .decode_ready(&serde_json::to_vec(&original).unwrap())
            .is_ok()
    );
    for key in original["material_runtime_bridge"]
        .as_object()
        .unwrap()
        .keys()
    {
        let mut changed = original.clone();
        changed["material_runtime_bridge"][key] = Value::String("wrong".to_owned());
        assert!(
            config
                .decode_ready(&serde_json::to_vec(&changed).unwrap())
                .is_err(),
            "{key}"
        );
    }
    for value in [Value::Null, Value::String("00".repeat(32))] {
        let mut changed = original.clone();
        changed["runtime_source_set_sha256"] = value;
        assert!(
            config
                .decode_ready(&serde_json::to_vec(&changed).unwrap())
                .is_err()
        );
    }
}

#[test]
fn old_ready_refuses_bridge_fields_including_null_and_new_ready_refuses_old_schema() {
    let mut config = config();
    let bridged = ready_value(&config);
    let mut original = bridged.clone();
    original["schema"] = Value::String(super::super::SCHEMA.to_owned());
    original
        .as_object_mut()
        .unwrap()
        .remove("material_runtime_bridge");
    original
        .as_object_mut()
        .unwrap()
        .remove("runtime_source_set_sha256");
    assert!(
        config
            .decode_ready(&serde_json::to_vec(&original).unwrap())
            .is_ok()
    );
    for key in ["material_runtime_bridge", "runtime_source_set_sha256"] {
        let mut mixed = original.clone();
        mixed[key] = Value::Null;
        assert!(
            config
                .decode_ready(&serde_json::to_vec(&mixed).unwrap())
                .is_err()
        );
    }
    config.material_runtime_bridge = Some(bridge());
    assert!(
        config
            .decode_ready(&serde_json::to_vec(&original).unwrap())
            .is_err()
    );
    let mut mixed = bridged;
    mixed["schema"] = Value::String(super::super::SCHEMA.to_owned());
    assert!(
        config
            .decode_ready(&serde_json::to_vec(&mixed).unwrap())
            .is_err()
    );
}

#[test]
fn successful_bridge_decode_does_not_cache_later_material_or_source_admission() {
    let mut config = config();
    config.material_runtime_bridge = Some(bridge());
    let raw = serde_json::to_vec(&ready_value(&config)).unwrap();
    assert!(config.decode_ready(&raw).is_ok());
    config.target_contract[0] ^= 1;
    assert!(config.decode_ready(&raw).is_err());
    config.target_contract = TARGET.to_vec();
    config.source_pins.pop_first();
    assert!(config.decode_ready(&raw).is_err());
}

#[test]
fn ready_snapshot_actions_and_parent_facts_are_retained_for_original_driver_checks() {
    let mut config = config();
    config.material_runtime_bridge = Some(bridge());
    let value = ready_value(&config);
    let ready = config
        .decode_ready(&serde_json::to_vec(&value).unwrap())
        .unwrap();
    assert_eq!(
        ready.runtime_snapshot_sha256,
        Digest32::of_bytes(&config.runtime_snapshot).to_string()
    );
    assert_eq!(
        ready.actual_loaded_parent,
        config.adapter_digest.to_string()
    );
    assert_eq!(ready.contract, config.contract_digest.to_string());
    assert_eq!(ready.actions, config.actions());
    assert!(ready.authority.denied());
}
